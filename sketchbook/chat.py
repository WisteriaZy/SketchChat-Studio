"""Opt-in Windows chat hooks, guarded focus and bounded clipboard waits."""
import copy
import io
import hashlib
import logging
import os
import threading
import time

from PySide6.QtCore import QObject, Signal
from .rendering import render
from .settings import chat_settings


def select_tag(character, expression_id, text):
    """Match one literal prefix only; longest wins. Never remove tags in the body."""
    matches = [e for e in character['expressions'] if e.get('tag') and text.startswith(e['tag'])]
    if matches:
        expression = max(matches, key=lambda e: len(e['tag']))
        return expression['id'], text[len(expression['tag']):].lstrip()
    return expression_id, text


class ChatService(QObject):
    message = Signal(str)
    selected = Signal(str, str)

    def __init__(self, library):
        super().__init__()
        self.library = library
        self.enabled = False
        self.handles = []
        self.lock = threading.Lock()
        self.busy = threading.Lock()
        self.snapshot = None
        self.settings = {}
        self.last_output_fingerprint = None
        self.generation = 0
        self.pending_expression = None

    def configure(self, settings, character=None, expression_id=None):
        with self.lock:
            self.settings = chat_settings(settings)
            if character and not self.settings['follow_expression']:
                expression_id = character['default_expression']
            self.pending_expression = None
            self.snapshot = (copy.deepcopy(character), expression_id) if character else None

    def stop(self):
        self.enabled = False
        self.generation += 1
        if self.handles:
            import keyboard
            for handle in self.handles:
                keyboard.remove_hotkey(handle)
            self.handles.clear()

    def start(self):
        if self.enabled:
            return
        if self.busy.locked():
            raise ValueError('上一次操作尚未结束，请稍后再启用')
        if not self.snapshot:
            raise ValueError('请先保存并设定当前角色')
        character, eid = self.snapshot
        self.library.validate_expression(character, self.library.expression(character, eid))
        import keyboard
        self.enabled = True
        try:
            hotkey = self.settings['hotkey']
            # Key release avoids generating while the user's Enter is still down.
            self.handles.append(keyboard.add_hotkey(hotkey, self.trigger, suppress=True, trigger_on_release=True))
            for key, tag in self.settings.get('emotion_switch_hotkeys', {}).items():
                if key != hotkey:
                    self.handles.append(keyboard.add_hotkey(key, lambda t=tag: self.switch(t), suppress=False))
        except Exception:
            self.stop()
            raise
        logging.info('聊天监听已启用：%s；操作间隔 %.2fs；粘贴等待 %.2fs；剪贴板配图 %s',
                     hotkey, self.settings['delay'], self.settings['paste_delay'], self.settings['include_clipboard_image'])

    def foreground(self, settings):
        import win32gui, win32process, psutil
        window = win32gui.GetForegroundWindow()
        _, pid = win32process.GetWindowThreadProcessId(window)
        allowed = settings.get('allowed_processes', [])
        if pid == os.getpid():
            return window, False
        try:
            name = psutil.Process(pid).name().lower()
        except psutil.Error:
            return window, False
        return window, not allowed or name in [p.lower() for p in allowed]

    def switch(self, tag):
        with self.lock:
            if not self.enabled or not self.snapshot or not self.foreground(self.settings)[1]:
                return
            character, eid = self.snapshot
            expression = next((e for e in character['expressions'] if e['tag'] == tag), None)
            if expression:
                if not self.settings['follow_expression']:
                    self.pending_expression = (character['id'], expression['id'])
                self.snapshot = character, expression['id']
                self.selected.emit(character['id'], expression['id'])

    def trigger(self):
        if not self.enabled:
            return
        with self.lock:
            settings = copy.deepcopy(self.settings)
        window, allowed = self.foreground(settings)
        if not allowed:
            # Supply the suppressed key press outside target applications.
            # keyboard.send marks its events as replayed and bypasses these hooks.
            import keyboard
            keyboard.send(settings['hotkey'])
            return
        if not self.busy.acquire(blocking=False):
            self.message.emit('上一条仍在处理中，本次按键已忽略，请等待完成后重试')
            return
        try:
            threading.Thread(target=self._generate, args=(window, self.generation), daemon=True).start()
        except Exception:
            self.busy.release()
            raise

    def _check_target(self, window, settings, generation):
        if not self.enabled or generation != self.generation:
            raise RuntimeError('监听已暂停，已取消后续操作')
        current, allowed = self.foreground(settings)
        if current != window or not allowed:
            raise RuntimeError('前台窗口已切换，已取消后续操作')

    @staticmethod
    def _retry_clipboard(operation, timeout):
        """Only retry clipboard API access, never cut/paste/send keystrokes."""
        deadline = time.monotonic() + timeout
        while True:
            try:
                return operation()
            except Exception:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.05)

    @staticmethod
    def _wait_cut(sequence, timeout):
        import win32clipboard, pyperclip
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if win32clipboard.GetClipboardSequenceNumber() != sequence:
                try:
                    text = pyperclip.paste()
                    if text:
                        return text
                    # Clipboard sequence can change while a chat app is still preparing text.
                except Exception:
                    pass  # The chat app may still have the clipboard locked.
            time.sleep(.05)
        raise TimeoutError('未检测到剪切完成；已停止，不会自动粘贴或发送。请检查输入框焦点')

    def _clipboard_matches_output(self, dib, timeout):
        """Sequence changes are hints, not proof that our image was replaced.

        Windows may synthesize image formats after CloseClipboard. Compare the
        original CF_DIB payload under a clipboard lock instead of rejecting it.
        Do not rewrite the clipboard or replay paste on a mismatch.
        """
        import win32clipboard
        self._retry_clipboard(win32clipboard.OpenClipboard, timeout)
        try:
            if not win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_DIB):
                return False
            actual = win32clipboard.GetClipboardData(win32clipboard.CF_DIB)
            return actual == dib
        finally:
            win32clipboard.CloseClipboard()

    def _generate(self, target_window=None, generation=None):
        import keyboard, pyperclip, win32clipboard
        from PIL import Image, ImageGrab
        cut_text = None
        output_ready = False
        stage = '准备'
        try:
            with self.lock:
                settings = copy.deepcopy(self.settings)
                snapshot = copy.deepcopy(self.snapshot)
                pending = self.pending_expression
            generation = self.generation if generation is None else generation
            window, allowed = self.foreground(settings)
            if target_window is not None:
                window = target_window
            if not allowed or not snapshot:
                return
            self._check_target(window, settings, generation)
            character, eid = snapshot
            self.library.validate_expression(character, self.library.expression(character, eid))
            clipboard_image = None
            if settings['include_clipboard_image']:
                clipboard_image = self._retry_clipboard(ImageGrab.grabclipboard, settings['clipboard_timeout'])
                if not isinstance(clipboard_image, Image.Image):
                    clipboard_image = None
                elif self.fingerprint(clipboard_image) == self.last_output_fingerprint:
                    clipboard_image = None
            # Separate selection from cutting, and confirm that cutting really updated the clipboard.
            stage = '全选'
            time.sleep(settings['delay'])
            self._check_target(window, settings, generation)
            keyboard.send(settings['select_all_hotkey'])
            time.sleep(settings['delay'])
            self._check_target(window, settings, generation)
            stage = '剪切'
            self._retry_clipboard(lambda: pyperclip.copy(''), settings['clipboard_timeout'])
            sequence = win32clipboard.GetClipboardSequenceNumber()
            self._check_target(window, settings, generation)
            keyboard.send(settings['cut_hotkey'])
            cut_text = self._wait_cut(sequence, settings['clipboard_timeout'])
            self._check_target(window, settings, generation)
            if not settings['follow_expression']:
                eid = pending[1] if pending and pending[0] == character['id'] else character['default_expression']
            eid, text = select_tag(character, eid, cut_text)
            if not text and clipboard_image is None:
                if cut_text:
                    if settings['follow_expression']:
                        self._remember(character, eid, snapshot)
                    else:
                        with self.lock:
                            if self.snapshot == snapshot:
                                self.pending_expression = (character['id'], eid)
                                self.snapshot = character, eid
                                self.selected.emit(character['id'], eid)
                self.message.emit('没有可生成的文字或配图；未粘贴、未发送')
                return
            stage = '渲染'
            png = render(self.library, character, self.library.expression(character, eid), text, clipboard_image)
            image = Image.open(io.BytesIO(png)).convert('RGB')
            buffer = io.BytesIO()
            image.save(buffer, 'BMP')
            dib = buffer.getvalue()[14:]
            stage = '写入图片'
            self._check_target(window, settings, generation)
            # Retry opening only: never repeat a partially completed clipboard write.
            self._retry_clipboard(win32clipboard.OpenClipboard, settings['clipboard_timeout'])
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib)
                output_sequence = win32clipboard.GetClipboardSequenceNumber()
            finally:
                win32clipboard.CloseClipboard()
            self.last_output_fingerprint = self.fingerprint(image)
            output_ready = True
            self._remember(character, eid, snapshot)
            result = '图片已保留在剪贴板，可手动粘贴'
            if settings['auto_paste_image']:
                stage = '粘贴'
                time.sleep(settings['delay'])
                self._check_target(window, settings, generation)
                current_sequence = win32clipboard.GetClipboardSequenceNumber()
                if current_sequence != output_sequence:
                    if not self._clipboard_matches_output(dib, settings['clipboard_timeout']):
                        raise RuntimeError('剪贴板图片已被替换或移除，已停止自动粘贴')
                    logging.info('剪贴板序列号变化 %s -> %s，但图片内容一致，继续粘贴',
                                 output_sequence, current_sequence)
                    # Clipboard lock retries may have taken time; recheck the target.
                    self._check_target(window, settings, generation)
                keyboard.send(settings['paste_hotkey'])
                result = '已请求粘贴，请在聊天窗口确认结果'
                if settings['auto_send_image']:
                    stage = '发送'
                    time.sleep(settings['paste_delay'])
                    self._check_target(window, settings, generation)
                    keyboard.send(settings['send_hotkey'])
                    result = '已请求粘贴和发送，请在聊天窗口确认结果'
            logging.info('聊天生成完成：%s', result)
            self.message.emit(result)
        except Exception as error:
            logging.exception('聊天操作失败，阶段=%s', stage)
            recovery = ''
            if cut_text and not output_ready:
                try:
                    self._retry_clipboard(lambda: pyperclip.copy(cut_text), settings['clipboard_timeout'])
                    recovery = ' 原始文字已保留在剪贴板，可 Ctrl+V 恢复。'
                except Exception:
                    logging.exception('恢复剪切文字到剪贴板失败')
                    recovery = ' 剪贴板被占用，文字恢复失败，请检查原输入框。'
            self.message.emit(f'{stage}失败：{error}。{recovery}')
        finally:
            time.sleep(.15)
            self.busy.release()

    @staticmethod
    def fingerprint(image):
        return (image.size, hashlib.sha256(image.convert('RGB').tobytes()).digest())

    def _remember(self, character, eid, initial):
        with self.lock:
            if self.snapshot == initial:
                if not self.settings['follow_expression']:
                    eid = character['default_expression']
                    self.pending_expression = None
                self.snapshot = character, eid
                self.selected.emit(character['id'], eid)
