"""Render the real migrated library in an offscreen Qt widget, without chat hooks."""
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
import sys
import hashlib
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from sketchbook.library import Library
from sketchbook.gui import ManagerWindow
from sketchbook.rendering import render
root = Path(__file__).resolve().parents[1]
original = {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in ('config.yaml','font.ttf')}
lib = Library(root/'library')
if not lib.load():
    lib.migrate(root)
for character in lib.characters.values():
    lib.validate(character)
app = QApplication([])
window = ManagerWindow(lib)
window.tray.hide()
window.show()
QTest.qWait(300)
window.timer.stop()
window.preview()
window.pool.waitForDone()
app.processEvents()
window.canvas.fit()
app.processEvents()
assert window.preview_bytes, window.preview_status.text()
out = root/'.implementation-check'
out.mkdir(exist_ok=True)
window.grab().save(str(out/'studio-preview.png'))
(out/'render-preview.png').write_bytes(window.preview_bytes)
window.scope.setCurrentIndex(1)
window.timer.stop()
window.preview()
window.pool.waitForDone()
app.processEvents()
window.grab().save(str(out/'studio-editor.png'))
assert not window.chat.enabled
assert original == {name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in original}
print('Real library migration, render and offscreen UI: PASS. Original config/font unchanged.')
print('Characters:', len(lib.characters))
print('Screenshot:', out/'studio-preview.png')
window.timer.stop()
window.pool.waitForDone()
window.hide()
