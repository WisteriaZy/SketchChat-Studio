import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from unittest.mock import patch
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QPushButton
from PySide6.QtTest import QTest
from sketchbook.hotkeys import HotkeyInput, ExpressionHotkeys, event_key, validate_mapping, validate_hotkey

class HotkeyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
    def setUp(self):
        self.widget = HotkeyInput('enter')
        self.widget.show()
        self.app.processEvents()
    def tearDown(self):
        self.widget.cancel_record()
        self.widget.hide()
        self.widget.deleteLater()
        self.app.processEvents()
    def event(self, kind, key, vk=0, scan=0):
        event = QKeyEvent(kind,key,Qt.KeyboardModifier.NoModifier,scan,vk,0)
        QApplication.sendEvent(self.widget.field,event)
    def test_right_alt_capture(self):
        with patch('keyboard.add_hotkey') as hook:
            self.widget.toggle_record()
            self.event(QEvent.Type.KeyPress,Qt.Key.Key_Alt,0xA5,0x138)
            self.event(QEvent.Type.KeyRelease,Qt.Key.Key_Alt,0xA5,0x138)
            self.assertEqual(self.widget.text(),'right alt')
            self.assertFalse(self.widget.recording)
            hook.assert_not_called()
    def test_combo_commits_only_after_all_keys_released(self):
        self.widget.toggle_record()
        self.event(QEvent.Type.KeyPress,Qt.Key.Key_Control,0xA2)
        self.event(QEvent.Type.KeyPress,Qt.Key.Key_F8,0x77)
        self.event(QEvent.Type.KeyRelease,Qt.Key.Key_F8,0x77)
        self.assertTrue(self.widget.recording)
        self.event(QEvent.Type.KeyRelease,Qt.Key.Key_Control,0xA2)
        self.assertEqual(self.widget.text(),'left ctrl+f8')
    def test_escape_cancel_and_timeout_keep_previous(self):
        self.widget.toggle_record()
        self.event(QEvent.Type.KeyPress,Qt.Key.Key_Escape)
        self.assertEqual(self.widget.text(),'enter')
        self.widget.toggle_record()
        self.widget.timeout.timeout.emit()
        self.assertEqual(self.widget.text(),'enter')
    def test_focus_loss_cancels(self):
        self.widget.toggle_record()
        QApplication.sendEvent(self.widget.field,QEvent(QEvent.Type.FocusOut))
        self.assertFalse(self.widget.recording)
        self.assertEqual(self.widget.text(),'enter')
    def test_enter_and_tab_can_be_recorded(self):
        for key,name in ((Qt.Key.Key_Return,'enter'),(Qt.Key.Key_Tab,'tab')):
            self.widget.toggle_record()
            QTest.keyClick(self.widget.field,key)
            self.assertEqual(self.widget.text(),name)
    def test_generic_and_sided_keys_conflict(self):
        with self.assertRaises(ValueError): validate_mapping('alt+1',[('right alt+1','/开心')])
        with self.assertRaises(ValueError): validate_mapping('f8',[('ctrl+a','a'),('left ctrl+a','b')])
        # keyboard on Windows exposes overlapping scan codes for left/right Alt.
        # Conservatively reject that pair rather than silently accepting a conflict.
        with self.assertRaises(ValueError): validate_mapping('right alt',[('left alt','/开心')])
    def test_reordered_keys_conflict(self):
        with self.assertRaises(ValueError): validate_mapping('f8',[('ctrl+shift+a','a'),('shift+ctrl+a','b')])
    def test_invalid_or_multistep_rejected(self):
        for key in ('','f8, f9','not a real key'):
            with self.subTest(key=key),self.assertRaises(ValueError): validate_hotkey(key)
    def test_expression_rows_preserve_custom_tags_and_delete(self):
        editor = ExpressionHotkeys({'alt+1':'a=b'},['/开心',':)'])
        self.assertEqual(editor.values(),[('alt+1','a=b')])
        row,hotkey,target = editor.add_row('f8','/开心')
        self.assertEqual(len(editor.values()),2)
        delete = next(b for b in row.findChildren(QPushButton) if b.text()=='删除')
        delete.click()
        self.assertEqual(editor.values(),[('alt+1','a=b')])
        editor.deleteLater()

if __name__ == '__main__':
    unittest.main()
