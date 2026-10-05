import copy
from unittest.mock import patch
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QSystemTrayIcon
from test_studio import Fixture
from sketchbook.chat import ChatService
from sketchbook.gui import ManagerWindow
from sketchbook.hotkeys import event_key

class FollowTests(Fixture):
    def test_follow_off_resets_after_success(self):
        happy = self.lib.add_expression(self.character,self.source,'开心')
        service = ChatService(self.lib)
        service.configure(dict(self.lib.state['settings'],follow_expression=False),self.character,happy['id'])
        self.assertEqual(service.snapshot[1],self.character['default_expression'])
        initial = copy.deepcopy(service.snapshot)
        service._remember(self.character,happy['id'],initial)
        self.assertEqual(service.snapshot[1],self.character['default_expression'])
    def test_shortcut_is_consumed_once(self):
        happy = self.lib.add_expression(self.character,self.source,'开心')
        service = ChatService(self.lib)
        service.configure(dict(self.lib.state['settings'],follow_expression=False),self.character,self.expression['id'])
        service.enabled = True
        with patch.object(service,'foreground',return_value=(10,True)):
            service.switch('#开心#')
        self.assertEqual(service.pending_expression,(self.character['id'],happy['id']))
        initial = copy.deepcopy(service.snapshot)
        service._remember(self.character,happy['id'],initial)
        self.assertIsNone(service.pending_expression)
        self.assertEqual(service.snapshot[1],self.character['default_expression'])
    def test_follow_on_preserves_expression(self):
        happy = self.lib.add_expression(self.character,self.source,'开心')
        service = ChatService(self.lib)
        service.configure(self.lib.state['settings'],self.character,self.expression['id'])
        service._remember(self.character,happy['id'],copy.deepcopy(service.snapshot))
        self.assertEqual(service.snapshot[1],happy['id'])
    def test_extended_native_modifier_bit(self):
        for key,vk,name in [(Qt.Key.Key_Control,0x11,'right ctrl'),(Qt.Key.Key_Alt,0x12,'right alt')]:
            event = QKeyEvent(QEvent.Type.KeyRelease,key,Qt.KeyboardModifier.NoModifier,0x1d,vk,0x01000000)
            self.assertEqual(event_key(event),name)
    def test_extended_e0_scan(self):
        event = QKeyEvent(QEvent.Type.KeyRelease,Qt.Key.Key_Control,Qt.KeyboardModifier.NoModifier,0xe01d,0x11,0)
        self.assertEqual(event_key(event),'right ctrl')

class TrayTests(Fixture):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
    def test_single_click_toggle_double_click_no_action(self):
        window = ManagerWindow(self.lib)
        try:
            with patch.object(window,'toggle_chat') as toggle,patch.object(window,'show_window') as show:
                window.tray_activated(QSystemTrayIcon.ActivationReason.Trigger)
                toggle.assert_called_once()
                window.tray_activated(QSystemTrayIcon.ActivationReason.DoubleClick)
                show.assert_not_called()
                self.assertEqual(toggle.call_count,1)
            window.chat.enabled=False
            window.update_tray_status()
            paused=window.tray.icon().cacheKey()
            self.assertIn('已暂停',window.tray.toolTip())
            window.chat.enabled=True
            window.update_tray_status()
            self.assertIn('监听中',window.tray.toolTip())
            self.assertNotEqual(paused,window.tray.icon().cacheKey())
        finally:
            window.chat.enabled=False
            window.timer.stop()
            window.pool.waitForDone()
            window.tray.hide()
            window.deleteLater()
            self.app.processEvents()
