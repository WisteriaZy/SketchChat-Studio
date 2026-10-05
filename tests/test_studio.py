"""Unit + Qt widget integration tests; never register real keyboard hooks."""
import copy
import hashlib
import importlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PIL import Image
from PySide6.QtCore import Qt, QPointF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from sketchbook.library import Library, atomic_yaml
from sketchbook.rendering import render
from sketchbook.chat import ChatService, select_tag
from sketchbook.gui import ManagerWindow

ROOT = Path(__file__).resolve().parents[1]

class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.png'
        Image.new('RGBA', (320, 240), 'white').save(self.source)
        self.lib = Library(self.root / 'library')
        self.character = self.lib.new_character('角色 A')
        self.expression = self.lib.add_expression(self.character, self.source, '普通')
        self.character['layout']['region'] = [20, 20, 300, 220]
        self.character['layout']['font'] = self.lib.import_asset(self.character, ROOT/'font.ttf', 'font')
        self.lib.save_character(self.character)
        self.lib.state['settings'] = dict(hotkey='enter', send_hotkey='enter', select_all_hotkey='ctrl+a',
            cut_hotkey='ctrl+x', paste_hotkey='ctrl+v', allowed_processes=['qq.exe'], delay=.05,
            auto_paste_image=False, auto_send_image=False, emotion_switch_hotkeys={'alt+1':'#普通#'})
        self.lib.activate(self.character['id'], self.expression['id'])
    def tearDown(self):
        self.temp.cleanup()

class LibraryTests(Fixture):
    def test_roundtrip(self):
        again = Library(self.lib.root)
        self.assertTrue(again.load())
        self.assertEqual(again.characters[self.character['id']], self.character)
        self.assertEqual(again.state, self.lib.state)
    def test_import_is_managed_copy(self):
        self.source.unlink()
        self.assertTrue(self.lib.asset(self.character, self.expression['image']).is_file())
    def test_path_escape_rejected(self):
        with self.assertRaises(ValueError):
            self.lib.asset(self.character, '../../escape.png')
    def test_inherited_and_explicit_disabled_overlay(self):
        self.character['layout']['overlay'] = 'assets/example.png'
        self.assertEqual(self.lib.layout(self.character, self.expression)['overlay'], 'assets/example.png')
        self.expression['overrides'] = {'overlay': None, 'region': [1,2,30,40]}
        self.assertIsNone(self.lib.layout(self.character, self.expression)['overlay'])
        self.assertEqual(self.character['layout']['region'], [20,20,300,220])
    def test_invalid_bounds_do_not_overwrite_saved_role(self):
        file = self.lib.root/'characters'/self.character['id']/'character.yaml'
        before = file.read_bytes()
        self.character['layout']['region'] = [0,0,500,500]
        with self.assertRaises(ValueError): self.lib.save_character(self.character)
        self.assertEqual(file.read_bytes(), before)
    def test_invalid_overlay_size(self):
        overlay = self.root/'overlay.png'
        Image.new('RGBA',(4,4)).save(overlay)
        self.character['layout']['overlay'] = self.lib.import_asset(self.character,overlay)
        with self.assertRaisesRegex(ValueError, '尺寸一致'): self.lib.validate(self.character)
    def test_duplicate_tag_rejected(self):
        second = self.lib.add_expression(self.character,self.source,'开心')
        second['tag'] = self.expression['tag']
        with self.assertRaises(ValueError): self.lib.save_character(self.character)
    def test_duplicate_role_has_independent_ids_and_assets(self):
        duplicate = self.lib.duplicate(self.character,'角色 B')
        self.assertNotEqual(duplicate['id'],self.character['id'])
        self.assertNotEqual(duplicate['default_expression'],self.character['default_expression'])
        self.lib.archive(self.character['id'])
        self.lib.validate(duplicate)
        self.assertTrue(list((self.lib.root/'trash').iterdir()))
    def test_remembers_expression_per_role(self):
        second = self.lib.add_expression(self.character,self.source,'开心')
        self.lib.save_character(self.character)
        self.lib.activate(self.character['id'],second['id'])
        duplicate = self.lib.duplicate(self.character,'角色 B')
        self.lib.activate(duplicate['id'])
        self.assertEqual(self.lib.activate(self.character['id']), second['id'])
    def test_tag_resolution_is_local_and_preserves_unknown(self):
        second = self.lib.add_expression(self.character,self.source,'开心')
        self.assertEqual(select_tag(self.character,self.expression['id'],'#开心#你好'),(second['id'],'你好'))
        self.assertEqual(select_tag(self.character,self.expression['id'],'#未知#你好'),(self.expression['id'],'#未知#你好'))
    def test_render_modes(self):
        for text, content in [('',None),('你好【预览】',None),('',Image.new('RGB',(40,100),'red')),
                              ('你好',Image.new('RGB',(40,100),'red')),('你好',Image.new('RGB',(100,40),'red'))]:
            with self.subTest(text=text, content=content):
                png = render(self.lib,self.character,self.expression,text,content)
                self.assertEqual(Image.open(io.BytesIO(png)).size,(320,240))
    def test_overlay_is_last_layer(self):
        overlay = self.root/'overlay.png'
        Image.new('RGBA',(320,240),(255,0,0,255)).save(overlay)
        self.character['layout']['overlay'] = self.lib.import_asset(self.character,overlay)
        png = render(self.lib,self.character,self.expression,'Hello')
        self.assertEqual(Image.open(io.BytesIO(png)).getpixel((160,120)),(255,0,0,255))
    def test_legacy_import_does_not_mutate_sources(self):
        project = self.root/'legacy'
        project.mkdir()
        Image.new('RGB',(320,240),'white').save(project/'base.png')
        config = {'baseimage_mapping':{'#普通#':'base.png','#缺失#':'missing.png'}, 'baseimage_file':'base.png',
                  'text_box_topleft':[20,20], 'image_box_bottomright':[300,220],
                  'font_file':str(ROOT/'font.ttf'), 'use_base_overlay':True, 'base_overlay_file':''}
        atomic_yaml(project/'config.yaml',config)
        before = (project/'config.yaml').read_bytes()
        migrated = Library(self.root/'migrated')
        migrated.migrate(project)
        self.assertEqual((project/'config.yaml').read_bytes(),before)
        self.assertEqual(len(migrated.characters),1)
        self.assertEqual(len(migrated.warnings),1)
        migrated.validate(next(iter(migrated.characters.values())))
        self.assertTrue(list((migrated.root/'backups').glob('*.yaml')))
    def test_atomic_failure_preserves_previous_file(self):
        path = self.root/'state.yaml'
        atomic_yaml(path, {'a':1})
        with patch('sketchbook.library.os.replace',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError): atomic_yaml(path,{'a':2})
        self.assertIn('a: 1',path.read_text())
        self.assertFalse(list(self.root.glob('.save-*')))

class ServiceTests(Fixture):
    def test_explicit_start_stop_and_snapshot_isolation(self):
        service = ChatService(self.lib)
        settings = self.lib.state['settings']
        with patch('keyboard.add_hotkey',side_effect=['generate','emotion']) as add, patch('keyboard.remove_hotkey') as remove:
            service.configure(settings,self.character,self.expression['id'])
            self.character['name'] = '未保存'
            self.assertNotEqual(service.snapshot[0]['name'], '未保存')
            add.assert_not_called()
            service.start()
            self.assertEqual(add.call_count,2)
            service.start()
            self.assertEqual(add.call_count,2)
            service.stop()
            self.assertEqual(remove.call_count,2)
    def test_partial_registration_failure_cleans_up(self):
        service = ChatService(self.lib)
        service.configure(self.lib.state['settings'],self.character,self.expression['id'])
        with patch('keyboard.add_hotkey',side_effect=['first',RuntimeError('failed')]), patch('keyboard.remove_hotkey') as remove:
            with self.assertRaises(RuntimeError): service.start()
            self.assertFalse(service.enabled)
            remove.assert_called_once_with('first')
    def test_legacy_import_does_not_register_hooks(self):
        with patch('keyboard.add_hotkey') as add, patch('keyboard.wait') as wait:
            importlib.import_module('main')
            add.assert_not_called()
            wait.assert_not_called()
    def test_disabled_paste_retains_png_clipboard(self):
        service = ChatService(self.lib)
        service.configure(self.lib.state['settings'],self.character,self.expression['id'])
        service.enabled = True
        service.busy.acquire()
        with patch.object(service,'foreground',return_value=(10,True)), patch('PIL.ImageGrab.grabclipboard',return_value=None), \
             patch('pyperclip.paste',return_value='测试'), patch('pyperclip.copy') as copy_clip, \
             patch('keyboard.send') as send, patch('win32clipboard.OpenClipboard'), patch('win32clipboard.CloseClipboard'), \
             patch('win32clipboard.EmptyClipboard'), patch('win32clipboard.SetClipboardData') as put, patch('sketchbook.chat.time.sleep'), patch.object(ChatService, '_wait_cut', side_effect=lambda *args: __import__('pyperclip').paste()):
            service._generate()
            put.assert_called_once()
            self.assertEqual(copy_clip.call_args_list[-1].args, ('',))
            self.assertNotIn(('ctrl+v',),[call.args for call in send.call_args_list])
            self.assertFalse(service.busy.locked())
    def test_foreground_change_prevents_paste_and_send(self):
        settings = copy.deepcopy(self.lib.state['settings'])
        settings.update(auto_paste_image=True,auto_send_image=True)
        service = ChatService(self.lib)
        service.configure(settings,self.character,self.expression['id'])
        service.enabled = True
        service.busy.acquire()
        with patch.object(service,'foreground',side_effect=[(10,True)]*7+[(20,True)]), patch('PIL.ImageGrab.grabclipboard',return_value=None), \
             patch('pyperclip.paste',return_value='测试'), patch('pyperclip.copy'), patch('keyboard.send') as send, \
             patch('win32gui.GetForegroundWindow',return_value=20), patch('win32clipboard.OpenClipboard'), \
             patch('win32clipboard.CloseClipboard'), patch('win32clipboard.EmptyClipboard'), patch('win32clipboard.SetClipboardData'), \
             patch('sketchbook.chat.time.sleep'), patch.object(ChatService, '_wait_cut', side_effect=lambda *args: __import__('pyperclip').paste()):
            with self.assertLogs(level='ERROR'):
                service._generate()
            self.assertEqual([call.args for call in send.call_args_list],[('ctrl+a',),('ctrl+x',)])

class GuiTests(Fixture):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
    def setUp(self):
        super().setUp()
        self.hooks = patch('keyboard.add_hotkey')
        self.hook_mock = self.hooks.start()
        self.window = ManagerWindow(self.lib)
        self.window.tray.hide()
        self.window.show()
        QTest.qWait(30)
    def tearDown(self):
        self.window.timer.stop()
        self.window.pool.clear()
        self.window.pool.waitForDone()
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()
        self.hooks.stop()
        super().tearDown()
    def test_preview_does_not_enable_chat(self):
        self.window.timer.stop()
        self.window.preview()
        self.window.pool.waitForDone()
        self.app.processEvents()
        self.assertTrue(self.window.preview_bytes)
        self.assertFalse(self.window.chat.enabled)
        self.hook_mock.assert_not_called()
    def test_draft_inheritance_and_save(self):
        self.window.inherit.setChecked(False)
        self.window.coordinates[0].setValue(35)
        self.assertEqual(self.window.expression()['overrides']['region'][0],35)
        self.assertEqual(self.lib.characters[self.character['id']]['layout']['region'][0],20)
        self.assertEqual(self.window.chat.snapshot[0]['layout']['region'][0],20)
        self.assertTrue(self.window.save())
        self.assertEqual(self.lib.layout(*[self.window.chat.snapshot[0],self.lib.expression(self.window.chat.snapshot[0])])['region'][0],35)
        self.window.inherit.setChecked(True)
        self.assertEqual(self.window.effective_layout()['region'][0],20)
    def test_default_layout_edits_do_not_override_independent_expression(self):
        self.window.inherit.setChecked(False)
        self.window.coordinates[0].setValue(35)
        self.window.scope.setCurrentIndex(1)
        self.window.coordinates[0].setValue(50)
        self.assertEqual(self.window.draft['layout']['region'][0],50)
        self.assertEqual(self.window.expression()['overrides']['region'][0],35)
    def test_region_signal_edits_original_pixels(self):
        self.window.inherit.setChecked(False)
        self.window.canvas.regionChanged.emit([30,40,200,210])
        self.assertEqual([s.value() for s in self.window.coordinates],[30,40,200,210])
        self.assertTrue(self.window.dirty)
    def test_canvas_drag_creates_region(self):
        self.window.inherit.setChecked(False)
        self.window.canvas.fit()
        canvas = self.window.canvas
        start = canvas.mapFromScene(QPointF(4,4))
        end = canvas.mapFromScene(QPointF(100,100))
        QTest.mousePress(canvas.viewport(),Qt.MouseButton.LeftButton,pos=start)
        QTest.mouseMove(canvas.viewport(),end)
        QTest.mouseRelease(canvas.viewport(),Qt.MouseButton.LeftButton,pos=end)
        region = self.window.expression()['overrides']['region']
        self.assertAlmostEqual(region[0],4,delta=2)
        self.assertAlmostEqual(region[2],100,delta=2)
    def test_stale_preview_ignored(self):
        self.window.preview_finished(self.window.revision-1,b'invalid','')
        self.assertEqual(self.window.preview_bytes,b'')
    def test_cancel_role_switch_keeps_draft(self):
        second = self.lib.duplicate(self.character,'角色 B')
        self.window.reload_characters(self.character['id'])
        self.window.inherit.setChecked(False)
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Cancel):
            self.window.characters.setCurrentRow(1)
        self.assertEqual(self.window.draft['id'],self.character['id'])
        self.assertEqual(self.window.characters.currentItem().data(Qt.ItemDataRole.UserRole),self.character['id'])


class MoreGuiTests(Fixture):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setQuitOnLastWindowClosed(False)
    def setUp(self):
        super().setUp()
        self.window = ManagerWindow(self.lib)
        self.window.tray.hide()
        self.window.show()
        QTest.qWait(10)
    def tearDown(self):
        self.window.timer.stop()
        self.window.pool.clear()
        self.window.pool.waitForDone()
        self.window.hide()
        self.window.deleteLater()
        self.app.processEvents()
        super().tearDown()
    def test_save_while_switching_does_not_rename_other_role(self):
        second = self.lib.duplicate(self.character,'角色 B')
        self.window.reload_characters(self.character['id'])
        self.window.character_name.setText('角色 A 改名')
        self.window.form_changed()
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Save):
            self.window.characters.setCurrentRow(1)
        self.assertEqual(self.window.characters.item(0).text(),'角色 A 改名')
        self.assertEqual(self.window.characters.item(1).text(),'角色 B')
        self.assertEqual(self.window.draft['id'],second['id'])
    def test_new_role_is_persisted_but_not_activated(self):
        with patch('sketchbook.gui.QInputDialog.getText',return_value=('新角色',True)), \
             patch('sketchbook.gui.QFileDialog.getOpenFileNames',return_value=([str(self.source)],'')):
            self.window.new_character()
        cid = self.window.draft['id']
        self.assertNotEqual(cid,self.character['id'])
        self.assertTrue((self.lib.root/'characters'/cid/'character.yaml').exists())
        self.assertEqual(self.lib.state['active_character'],self.character['id'])
        self.assertFalse(self.window.dirty)
    def test_import_multiple_expressions_and_restore_inheritance(self):
        with patch('sketchbook.gui.QFileDialog.getOpenFileNames',return_value=([str(self.source),str(self.source)],'')):
            self.window.import_expressions()
        self.assertEqual(len(self.window.draft['expressions']),3)
        self.assertEqual(len(self.lib.characters[self.character['id']]['expressions']),1)
        self.assertTrue(self.window.save())
        self.assertEqual(len(self.lib.characters[self.character['id']]['expressions']),3)
    def test_delete_expression_preserves_asset(self):
        second = self.lib.add_expression(self.character,self.source,'开心')
        self.lib.save_character(self.character)
        self.window.reload_characters(self.character['id'])
        self.window.expressions.setCurrentRow(1)
        asset = self.lib.asset(self.character,second['image'])
        with patch.object(QMessageBox,'question',return_value=QMessageBox.StandardButton.Yes):
            self.window.delete_expression()
        self.assertTrue(asset.exists())
        self.assertEqual(len(self.window.draft['expressions']),1)
        self.assertTrue(self.window.save())
    def test_invalid_draft_cannot_save_or_activate(self):
        self.window.inherit.setChecked(False)
        self.window.coordinates[2].setValue(900)
        before = copy.deepcopy(self.window.chat.snapshot)
        with patch.object(self.window,'fail') as fail:
            self.assertFalse(self.window.save())
            self.window.activate()
            self.assertEqual(fail.call_count,2)
        self.assertEqual(self.window.chat.snapshot,before)
    def test_window_close_hides_when_tray_exists(self):
        with patch.object(self.window.tray,'isVisible',return_value=True), patch.object(self.window.tray,'showMessage'):
            self.window.close()
        self.assertFalse(self.window.isVisible())
    def test_replacing_missing_image_repairs_role(self):
        self.lib.asset(self.character,self.expression['image']).unlink()
        with patch('sketchbook.gui.QFileDialog.getOpenFileName',return_value=(str(self.source),'')):
            self.window.replace_image()
        self.assertTrue(self.window.save())
    def test_stale_chat_signal_cannot_override_new_selection(self):
        second = self.lib.add_expression(self.character,self.source,'开心')
        self.lib.save_character(self.character)
        self.lib.activate(self.character['id'],second['id'])
        self.window.configure_chat()
        self.window.chat_selected(self.character['id'],self.expression['id'])
        self.assertEqual(self.lib.state['last_expressions'][self.character['id']],second['id'])

class MoreServiceTests(Fixture):
    def test_previous_output_is_not_used_as_new_content(self):
        service = ChatService(self.lib)
        self.lib.state['settings']['include_clipboard_image'] = True
        service.configure(self.lib.state['settings'],self.character,self.expression['id'])
        service.enabled = True
        last = Image.new('RGB',(320,240),'red')
        service.last_output_fingerprint = service.fingerprint(last)
        expected = render(self.lib,self.character,self.expression,'测试')
        service.busy.acquire()
        with patch.object(service,'foreground',return_value=(10,True)), patch('PIL.ImageGrab.grabclipboard',return_value=last), \
             patch('pyperclip.paste',return_value='测试'), patch('pyperclip.copy'), patch('keyboard.send'), \
             patch('win32clipboard.OpenClipboard'), patch('win32clipboard.CloseClipboard'), \
             patch('win32clipboard.EmptyClipboard'), patch('win32clipboard.SetClipboardData'), \
             patch('sketchbook.chat.time.sleep'), patch.object(ChatService, '_wait_cut', side_effect=lambda *args: __import__('pyperclip').paste()), patch('sketchbook.chat.render',return_value=expected) as rendering:
            service._generate()
            self.assertIsNone(rendering.call_args.args[-1])
    def test_failure_recovers_cut_text_to_clipboard(self):
        service = ChatService(self.lib)
        service.configure(self.lib.state['settings'],self.character,self.expression['id'])
        service.enabled = True
        service.busy.acquire()
        with patch.object(service,'foreground',return_value=(10,True)), patch('PIL.ImageGrab.grabclipboard',return_value=None), \
             patch('pyperclip.paste',return_value='原始文字'), patch('pyperclip.copy') as clipboard, patch('keyboard.send'), \
             patch('sketchbook.chat.time.sleep'), patch.object(ChatService, '_wait_cut', side_effect=lambda *args: __import__('pyperclip').paste()), patch('sketchbook.chat.render',side_effect=ValueError('invalid image')):
            with self.assertLogs(level='ERROR'):
                service._generate()
            self.assertEqual(clipboard.call_args.args,('原始文字',))
            self.assertFalse(service.busy.locked())


if __name__ == '__main__':
    unittest.main()
