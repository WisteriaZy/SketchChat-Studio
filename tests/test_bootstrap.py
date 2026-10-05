"""Offline bootstrap checks must detect missing/outdated packages without installing."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from importlib.metadata import PackageNotFoundError
from launcher.check_environment import check

class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root/'requirements.txt').write_text('PySide6>=6.8,<7\nPillow>=12\n',encoding='utf-8')
    def tearDown(self):
        self.temp.cleanup()
    def test_ready_imports_gui_without_launching_it(self):
        with patch('launcher.check_environment.metadata.version',side_effect=['6.11.2','12.0.0']), \
             patch('launcher.check_environment.importlib.import_module') as imports:
            check(self.root)
            self.assertIn('PySide6.QtWidgets',[call.args[0] for call in imports.call_args_list])
    def test_missing_package(self):
        with patch('launcher.check_environment.metadata.version',side_effect=PackageNotFoundError('PySide6')):
            with self.assertRaises(PackageNotFoundError): check(self.root)
    def test_version_mismatch(self):
        with patch('launcher.check_environment.metadata.version',return_value='6.0.0'):
            with self.assertRaises(RuntimeError): check(self.root)
    def test_broken_dll_detected(self):
        with patch('launcher.check_environment.metadata.version',side_effect=['6.11.2','12.0.0']), \
             patch('launcher.check_environment.importlib.import_module',side_effect=ImportError('DLL load failed')):
            with self.assertRaises(ImportError): check(self.root)
    def test_unsupported_python(self):
        with patch('launcher.check_environment.sys.version_info',(3,9)):
            with self.assertRaises(RuntimeError): check(self.root)
    def test_comments_and_markers(self):
        (self.root/'requirements.txt').write_text('# test\n\nignored; python_version < "2"\n',encoding='utf-8')
        with patch('launcher.check_environment.metadata.version') as version, \
             patch('launcher.check_environment.importlib.import_module'):
            check(self.root)
            version.assert_not_called()
