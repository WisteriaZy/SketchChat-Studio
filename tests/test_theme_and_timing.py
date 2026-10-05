"""Regression coverage for dark Windows palettes and asynchronous chat operations."""
import copy
import io
import unittest
from contextlib import ExitStack
from unittest.mock import patch
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton, QLineEdit, QMenu
from test_studio import Fixture
from sketchbook.chat import ChatService
from sketchbook.settings import chat_settings
from sketchbook.theme import apply_light_theme
from sketchbook.gui import ManagerWindow


class ThemeTests(Fixture):
    def test_dark_system_palette_is_replaced_for_window_dialogs_and_menus(self):
        app = QApplication.instance() or QApplication([])
        dark = QPalette()
        for role in (QPalette.ColorRole.Window, QPalette.ColorRole.Base, QPalette.ColorRole.Button):
            dark.setColor(role,QColor('#202020'))
        for role in (QPalette.ColorRole.Text, QPalette.ColorRole.WindowText, QPalette.ColorRole.ButtonText):
            dark.setColor(role,QColor('white'))
        app.setPalette(dark)
        window = ManagerWindow(self.lib)
        dialog = QDialog(window)
        label = QLabel('文字',dialog)
        field = QLineEdit('输入',dialog)
        button = QPushButton('按钮',dialog)
        menu = QMenu(window)
        try:
            for widget, role in ((label,QPalette.ColorRole.WindowText),(field,QPalette.ColorRole.Text),
                                 (button,QPalette.ColorRole.ButtonText),(menu,QPalette.ColorRole.WindowText)):
                widget.ensurePolished()
                for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
                    self.assertLess(widget.palette().color(group,role).lightness(),100)
            self.assertGreater(dialog.palette().color(QPalette.ColorRole.Window).lightness(),230)
            self.assertGreater(field.palette().color(QPalette.ColorRole.Base).lightness(),230)
            self.assertLess(button.palette().color(QPalette.ColorGroup.Disabled,QPalette.ColorRole.ButtonText).lightness(),170)
            self.assertEqual(app.style().objectName().lower(),'fusion')
            if hasattr(app.styleHints(),'setColorScheme'):
                self.assertIn(app.styleHints().colorScheme(),(Qt.ColorScheme.Light, Qt.ColorScheme.Unknown))  # Offscreen has no OS scheme
        finally:
            window.timer.stop()
            window.pool.waitForDone()
            window.tray.hide()
            window.deleteLater()
            app.processEvents()


class TimingTests(Fixture):
    def simulate(self, settings=None, clipboard_image=None, render_error=None, target_error_at=None, output_changed=False, same_output=False):
        service = ChatService(self.lib)
        service.configure(settings or self.lib.state['settings'],self.character,self.expression['id'])
        service.enabled = True
        png = io.BytesIO()
        Image.new('RGB',(320,240),'white').save(png,'PNG')
        with ExitStack() as stack:
            mocks = {}
            values = {
                'keyboard.send': {}, 'pyperclip.copy': {},
                'PIL.ImageGrab.grabclipboard': {'return_value':clipboard_image},
                'win32clipboard.OpenClipboard': {}, 'win32clipboard.CloseClipboard': {},
                'win32clipboard.EmptyClipboard': {}, 'win32clipboard.SetClipboardData': {},
                'win32clipboard.GetClipboardSequenceNumber': {'side_effect':[1,2,3] if output_changed else [1,2,2]},
                'sketchbook.chat.time.sleep': {},
                'sketchbook.chat.render': {'side_effect':render_error} if render_error else {'return_value':png.getvalue()},
            }
            for name, kwargs in values.items():
                mocks[name] = stack.enter_context(patch(name,**kwargs))
            stack.enter_context(patch.object(service,'foreground',return_value=(10,True)))
            stack.enter_context(patch.object(service,'_clipboard_matches_output',return_value=same_output))
            stack.enter_context(patch.object(service,'_wait_cut',return_value='测试文字'))
            if target_error_at is not None:
                stack.enter_context(patch.object(service,'_check_target',side_effect=[None]*target_error_at+[RuntimeError('focus changed')]))
            stack.enter_context(patch('sketchbook.chat.logging.exception'))
            service.busy.acquire()
            service._generate()
            self.assertFalse(service.busy.locked())
        return service,mocks

    def test_existing_low_delay_gets_safe_defaults(self):
        before = {'delay':.1}
        settings = chat_settings(before)
        self.assertEqual(settings['delay'],.25)
        self.assertEqual(settings['paste_delay'],.8)
        self.assertEqual(settings['clipboard_timeout'],2)
        self.assertFalse(settings['include_clipboard_image'])
        self.assertEqual(before,{'delay':.1})

    def test_unrelated_clipboard_image_is_never_read_by_default(self):
        service,mocks = self.simulate(clipboard_image=Image.new('RGB',(10,10),'red'))
        mocks['PIL.ImageGrab.grabclipboard'].assert_not_called()
        self.assertIsNone(mocks['sketchbook.chat.render'].call_args.args[-1])

    def test_clipboard_image_can_be_explicitly_enabled(self):
        settings = dict(self.lib.state['settings'],include_clipboard_image=True)
        image = Image.new('RGB',(10,10),'red')
        service,mocks = self.simulate(settings,clipboard_image=image)
        mocks['PIL.ImageGrab.grabclipboard'].assert_called_once()
        self.assertIs(mocks['sketchbook.chat.render'].call_args.args[-1],image)

    def test_send_once_after_configured_paste_wait(self):
        settings = dict(self.lib.state['settings'],auto_paste_image=True,auto_send_image=True,paste_delay=1.4)
        service,mocks = self.simulate(settings)
        self.assertEqual([c.args[0] for c in mocks['keyboard.send'].call_args_list],['ctrl+a','ctrl+x','ctrl+v','enter'])
        waits = [c.args[0] for c in mocks['sketchbook.chat.time.sleep'].call_args_list]
        self.assertGreaterEqual(waits.count(.25),3)
        self.assertIn(1.4,waits)

    def test_changed_clipboard_never_pastes_or_sends(self):
        settings = dict(self.lib.state['settings'],auto_paste_image=True,auto_send_image=True)
        service,mocks = self.simulate(settings,output_changed=True)
        self.assertEqual([c.args[0] for c in mocks['keyboard.send'].call_args_list],['ctrl+a','ctrl+x'])

    def test_focus_change_before_cut_does_not_cut(self):
        service,mocks = self.simulate(target_error_at=2)
        self.assertEqual([c.args[0] for c in mocks['keyboard.send'].call_args_list],['ctrl+a'])
        mocks['pyperclip.copy'].assert_not_called()

    def test_focus_change_after_paste_does_not_send(self):
        settings = dict(self.lib.state['settings'],auto_paste_image=True,auto_send_image=True)
        service,mocks = self.simulate(settings,target_error_at=7)
        self.assertEqual([c.args[0] for c in mocks['keyboard.send'].call_args_list],['ctrl+a','ctrl+x','ctrl+v'])

    def test_wait_cut_waits_for_update_then_retries_locked_read(self):
        with patch('win32clipboard.GetClipboardSequenceNumber',side_effect=[7,7,8,8]), \
             patch('pyperclip.paste',side_effect=[OSError('locked'),'完成']) as read, patch('sketchbook.chat.time.sleep'):
            self.assertEqual(ChatService._wait_cut(7,2),'完成')
            self.assertEqual(read.call_count,2)

    def test_cut_timeout_is_bounded(self):
        with patch('win32clipboard.GetClipboardSequenceNumber',return_value=7), patch('pyperclip.paste') as read, \
             patch('sketchbook.chat.time.monotonic',side_effect=[0,.1,1,2.1]), patch('sketchbook.chat.time.sleep'):
            with self.assertRaises(TimeoutError): ChatService._wait_cut(7,2)
            read.assert_not_called()

    def test_clipboard_lock_retry_is_bounded_and_does_not_retry_keys(self):
        with patch('sketchbook.chat.time.sleep'), patch('sketchbook.chat.time.monotonic',side_effect=[0,.1,.2]):
            operation = unittest.mock.Mock(side_effect=[OSError('locked'),OSError('locked'),'ok'])
            self.assertEqual(ChatService._retry_clipboard(operation,1),'ok')
            self.assertEqual(operation.call_count,3)
        with patch('sketchbook.chat.time.monotonic',side_effect=[0,2]):
            operation = unittest.mock.Mock(side_effect=OSError('locked'))
            with self.assertRaises(OSError): ChatService._retry_clipboard(operation,1)
            self.assertEqual(operation.call_count,1)

    def test_pause_cancels_old_generation_even_after_reenable(self):
        service = ChatService(self.lib)
        service.configure(self.lib.state['settings'],self.character,self.expression['id'])
        service.enabled = True
        generation = service.generation
        service.stop()
        service.enabled = True
        with patch.object(service,'foreground',return_value=(10,True)):
            with self.assertRaises(RuntimeError): service._check_target(10,service.settings,generation)

    def test_hotkey_triggers_on_release_and_busy_trigger_does_not_queue(self):
        service = ChatService(self.lib)
        service.configure(self.lib.state['settings'],self.character,self.expression['id'])
        with patch('keyboard.add_hotkey',return_value='hook') as add, patch('keyboard.remove_hotkey'):
            service.start()
            self.assertTrue(add.call_args_list[0].kwargs['trigger_on_release'])
            service.busy.acquire()
            with patch.object(service,'foreground',return_value=(10,True)),patch('sketchbook.chat.threading.Thread') as thread:
                service.trigger()
                thread.assert_not_called()
            service.busy.release()
            service.stop()
    def test_clipboard_empty_intermediate_update_is_not_treated_as_finished(self):
        with patch('win32clipboard.GetClipboardSequenceNumber',return_value=8), \
             patch('pyperclip.paste',side_effect=['','完成']) as read, patch('sketchbook.chat.time.sleep'):
            self.assertEqual(ChatService._wait_cut(7,2),'完成')
            self.assertEqual(read.call_count,2)

    def test_cut_timeout_aborts_before_render_paste_or_send(self):
        service = ChatService(self.lib)
        settings = dict(self.lib.state['settings'],auto_paste_image=True,auto_send_image=True)
        service.configure(settings,self.character,self.expression['id'])
        service.enabled = True
        service.busy.acquire()
        with patch.object(service,'foreground',return_value=(10,True)), \
             patch.object(service,'_wait_cut',side_effect=TimeoutError('cut not acknowledged')), \
             patch('keyboard.send') as send, patch('pyperclip.copy'), \
             patch('win32clipboard.GetClipboardSequenceNumber',return_value=7), \
             patch('sketchbook.chat.time.sleep'), patch('sketchbook.chat.render') as rendering, \
             patch('win32clipboard.SetClipboardData') as write, patch('sketchbook.chat.logging.exception'):
            service._generate()
            self.assertEqual([call.args[0] for call in send.call_args_list],['ctrl+a','ctrl+x'])
            rendering.assert_not_called()
            write.assert_not_called()
            self.assertFalse(service.busy.locked())


    def test_sequence_change_with_identical_image_still_pastes_once(self):
        settings = dict(self.lib.state['settings'],auto_paste_image=True,auto_send_image=True)
        service,mocks = self.simulate(settings,output_changed=True,same_output=True)
        self.assertEqual([c.args[0] for c in mocks['keyboard.send'].call_args_list],
                         ['ctrl+a','ctrl+x','ctrl+v','enter'])
        mocks['win32clipboard.SetClipboardData'].assert_called_once()

    def test_output_comparison_checks_dib_and_always_closes_clipboard(self):
        service = ChatService(self.lib)
        for available, actual, expected in [(True,b'image',True),(True,b'other',False),(False,None,False)]:
            with self.subTest(available=available,actual=actual), patch('win32clipboard.OpenClipboard'), \
                 patch('win32clipboard.CloseClipboard') as close, \
                 patch('win32clipboard.IsClipboardFormatAvailable',return_value=available), \
                 patch('win32clipboard.GetClipboardData',return_value=actual) as read:
                self.assertEqual(service._clipboard_matches_output(b'image',.5),expected)
                close.assert_called_once()
                if not available:
                    read.assert_not_called()
        with patch('win32clipboard.OpenClipboard'), patch('win32clipboard.CloseClipboard') as close, \
             patch('win32clipboard.IsClipboardFormatAvailable',return_value=True), \
             patch('win32clipboard.GetClipboardData',side_effect=OSError('read error')):
            with self.assertRaises(OSError): service._clipboard_matches_output(b'image',.5)
            close.assert_called_once()
