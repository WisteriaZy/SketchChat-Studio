"""Offscreen dark-palette reproduction and settings dialog visual verification."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
import sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QApplication, QDialog
from PySide6.QtTest import QTest
from sketchbook.library import Library
from sketchbook.gui import ManagerWindow
root = Path(__file__).resolve().parents[1]
app = QApplication([])
dark = QPalette()
for role in (QPalette.ColorRole.Window,QPalette.ColorRole.Base,QPalette.ColorRole.Button):
    dark.setColor(role,QColor('#202020'))
for role in (QPalette.ColorRole.WindowText,QPalette.ColorRole.Text,QPalette.ColorRole.ButtonText):
    dark.setColor(role,QColor('white'))
app.setPalette(dark)
lib = Library(root/'library')
assert lib.load()
window = ManagerWindow(lib)
window.tray.hide()
window.show()
QTest.qWait(350)
window.timer.stop()
window.pool.waitForDone()
app.processEvents()
window.canvas.fit()
app.processEvents()
out = root/'.implementation-check'
window.grab().save(str(out/'dark-system-fixed.png'))
def capture(dialog):
    dialog.show()
    app.processEvents()
    dialog.grab().save(str(out/'chat-settings-fixed.png'))
    dialog.reject()
    return 0
with patch.object(QDialog,'exec',capture):
    window.settings_dialog()
assert not window.chat.enabled
print('Dark palette reproduction and settings screenshots saved; chat hooks not enabled.')
window.timer.stop()
window.pool.waitForDone()
window.hide()
