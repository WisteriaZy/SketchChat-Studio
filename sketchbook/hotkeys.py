"""Local Qt key recording; no global hooks or clipboard access during capture."""
from itertools import product
from PySide6.QtCore import Qt, QEvent, QTimer
from PySide6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLineEdit, QComboBox, QScrollArea
from .tags import validate_tag


def event_key(event):
    vk = event.nativeVirtualKey()
    sided = {0xA0:'left shift',0xA1:'right shift',0xA2:'left ctrl',0xA3:'right ctrl',
             0xA4:'left alt',0xA5:'right alt',0x5B:'left windows',0x5C:'right windows'}
    if vk in sided:
        return sided[vk]
    key = event.key()
    scan = event.nativeScanCode()
    extended = bool(scan & 0x100 or scan & 0xE000 or event.nativeModifiers() & 0x01000000)
    # Some Windows/Qt combinations provide generic VK_CONTROL/VK_MENU and no
    # side bit in nativeScanCode. Query sided state only for native key-down.
    if vk in (0x10, 0x11, 0x12) and event.type() == QEvent.Type.KeyPress:
        import sys
        if sys.platform == 'win32':
            import ctypes
            left, right = {0x10:(0xA0,0xA1), 0x11:(0xA2,0xA3), 0x12:(0xA4,0xA5)}[vk]
            get_state = ctypes.windll.user32.GetKeyState
            if get_state(right) & 0x8000 and not get_state(left) & 0x8000:
                return sided[right]
    if key in (Qt.Key.Key_Alt, Qt.Key.Key_AltGr):
        return 'right alt' if key == Qt.Key.Key_AltGr or extended else 'left alt'
    if key == Qt.Key.Key_Control:
        return 'right ctrl' if extended else 'left ctrl'
    if key == Qt.Key.Key_Shift:
        return 'right shift' if event.nativeScanCode() == 0x36 else 'left shift'
    names = {Qt.Key.Key_Return:'enter',Qt.Key.Key_Enter:'enter',Qt.Key.Key_Space:'space',
             Qt.Key.Key_Tab:'tab',Qt.Key.Key_Backtab:'tab',Qt.Key.Key_Backspace:'backspace',
             Qt.Key.Key_Delete:'delete',Qt.Key.Key_Insert:'insert',Qt.Key.Key_Home:'home',
             Qt.Key.Key_End:'end',Qt.Key.Key_PageUp:'page up',Qt.Key.Key_PageDown:'page down',
             Qt.Key.Key_Left:'left',Qt.Key.Key_Right:'right',Qt.Key.Key_Up:'up',Qt.Key.Key_Down:'down',
             Qt.Key.Key_Escape:'esc',Qt.Key.Key_Comma:'comma',Qt.Key.Key_Plus:'plus',
             Qt.Key.Key_CapsLock:'caps lock',Qt.Key.Key_Menu:'menu',Qt.Key.Key_Meta:'windows'}
    if key in names:
        return names[key]
    if Qt.Key.Key_F1 <= key <= Qt.Key.Key_F24:
        return 'f' + str(key-Qt.Key.Key_F1+1)
    if 32 <= key <= 126:
        return chr(key).lower()
    return None


def validate_hotkey(value):
    import keyboard
    value = value.strip().lower()
    if not value:
        raise ValueError('请先录制或输入快捷键')
    steps = keyboard.parse_hotkey(value)
    if len(steps) != 1 or not steps[0] or any(not codes for codes in steps[0]):
        raise ValueError('只支持单键或同时按下的组合键，不支持多步骤快捷键')
    if len(steps[0]) > 8:
        raise ValueError('组合键过长')
    return value, {tuple(sorted(combo)) for combo in product(*steps[0])}


def validate_mapping(generate, rows):
    _, generation = validate_hotkey(generate)
    used = set(generation)
    mapping = {}
    for key, tag in rows:
        key, combos = validate_hotkey(key)
        validate_tag(tag)
        if used.intersection(combos):
            raise ValueError('表情快捷键重复或与生成热键冲突：' + key)
        used.update(combos)
        mapping[key] = tag
    return mapping


class HotkeyInput(QWidget):
    def __init__(self, value='', parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        self.field = QLineEdit(value)
        self.field.setPlaceholderText('点击录制，或手动输入')
        self.record = QPushButton('录制')
        self.record.setAutoDefault(False)
        self.record.clicked.connect(self.toggle_record)
        layout.addWidget(self.field,1)
        layout.addWidget(self.record)
        self.field.installEventFilter(self)
        self.recording = False
        self.held = set()
        self.ignore_release = None
        self.native_pressed = {}
        self.chord = []
        self.previous = value
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.setInterval(10000)
        self.timeout.timeout.connect(self.cancel_record)
        self.setToolTip('点击录制后按键，松开全部按键完成；支持左右 Alt/Ctrl/Shift。Esc 取消，10 秒超时取消。系统保留快捷键可能无法录制。')

    def text(self):
        return self.field.text()

    def toggle_record(self):
        if self.recording:
            self.cancel_record()
            return
        self.previous = self.text()
        self.held.clear()
        self.chord.clear()
        self.native_pressed.clear()
        self.recording = True
        self.field.setReadOnly(True)
        self.field.setText('请按快捷键…（Esc 取消）')
        self.record.setText('取消')
        self.field.setFocus(Qt.FocusReason.OtherFocusReason)
        self.timeout.start()

    def finish(self, value):
        self.timeout.stop()
        self.recording = False
        self.field.setReadOnly(False)
        self.field.setText(value)
        self.record.setText('录制')
        self.held.clear()
        self.chord.clear()

    def cancel_record(self):
        if self.recording:
            self.finish(self.previous)

    def eventFilter(self, watched, event):
        if not self.recording:
            if event.type() == QEvent.Type.KeyRelease and event_key(event) == self.ignore_release:
                self.ignore_release = None
                return True
            return super().eventFilter(watched,event)
        if event.type() == QEvent.Type.FocusOut:
            self.cancel_record()
            return False
        if event.type() == QEvent.Type.ShortcutOverride:
            event.accept()
            return True
        if event.type() not in (QEvent.Type.KeyPress,QEvent.Type.KeyRelease):
            return super().eventFilter(watched,event)
        if event.isAutoRepeat():
            return True
        identity = (event.key(), event.nativeVirtualKey(), event.nativeScanCode())
        if event.type() == QEvent.Type.KeyRelease:
            key = self.native_pressed.pop(identity, None) or event_key(event)
        else:
            key = event_key(event)
            if key:
                self.native_pressed[identity] = key
        if key == 'esc':
            self.ignore_release = 'esc'
            self.cancel_record()
            return True
        if not key:
            return True
        if event.type() == QEvent.Type.KeyPress:
            self.held.add(key)
            if key not in self.chord:
                self.chord.append(key)
            self.field.setText(' + '.join(self.chord))
        else:
            self.held.discard(key)
            if not self.held and self.chord:
                self.finish('+'.join(self.chord))
        return True

    def hideEvent(self, event):
        self.cancel_record()
        super().hideEvent(event)


class ExpressionHotkeys(QWidget):
    def __init__(self, mapping, suggestions, parent=None):
        super().__init__(parent)
        self.rows = []
        self.suggestions = suggestions
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(155)
        scroll.setMaximumHeight(250)
        body = QWidget()
        self.entries = QVBoxLayout(body)
        self.entries.setContentsMargins(2,2,2,2)
        self.entries.addStretch()
        scroll.setWidget(body)
        layout.addWidget(scroll)
        add = QPushButton('＋ 添加表情快捷键')
        add.setAutoDefault(False)
        add.clicked.connect(lambda: self.add_row())
        layout.addWidget(add)
        for key, tag in mapping.items():
            self.add_row(key,tag)

    def add_row(self, key='', tag=''):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0,0,0,0)
        hotkey = HotkeyInput(key)
        target = QComboBox()
        target.setEditable(True)
        target.addItems(self.suggestions)
        target.setCurrentText(tag)
        target.setMinimumWidth(125)
        target.setToolTip('选择或输入聊天标签，作用于当前角色中具有该标签的表情；不存在时不切换。')
        remove = QPushButton('删除')
        remove.setAutoDefault(False)
        layout.addWidget(hotkey,2)
        layout.addWidget(target,1)
        layout.addWidget(remove)
        entry = (row,hotkey,target)
        self.rows.append(entry)
        self.entries.insertWidget(self.entries.count()-1,row)
        def delete():
            hotkey.cancel_record()
            self.rows.remove(entry)
            self.entries.removeWidget(row)
            row.deleteLater()
        remove.clicked.connect(delete)
        return entry

    def values(self):
        if any(hotkey.recording for _,hotkey,_ in self.rows):
            raise ValueError('请先完成快捷键录制')
        return [(hotkey.text(),target.currentText()) for _,hotkey,target in self.rows]
