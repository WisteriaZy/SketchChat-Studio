"""Run the desktop manager. Defaults to paused; legacy Start.cmd is unchanged."""
import argparse
import logging
from pathlib import Path
import sys
from PySide6.QtCore import QLockFile
from PySide6.QtWidgets import QApplication, QMessageBox
from sketchbook.library import Library
from sketchbook.gui import ManagerWindow
from sketchbook.theme import apply_light_theme


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--library', type=Path, help='Alternative portable library directory')
    args = parser.parse_args()
    project = Path(__file__).resolve().parent
    root = (args.library or project / 'library').resolve()
    app = QApplication(sys.argv[:1])
    apply_light_theme(app)
    app.setApplicationName('SketchChat Studio')
    app.setQuitOnLastWindowClosed(False)
    try:
        root.mkdir(parents=True, exist_ok=True)
        lock = QLockFile(str(root / '.studio.lock'))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            QMessageBox.information(None, '已在运行', '该素材库已有管理器运行，请从系统托盘打开。')
            return 1
        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
            handlers=[logging.FileHandler(root / 'studio.log', encoding='utf-8')], force=True)
        library = Library(root)
        if not library.load():
            library.migrate(project)
        window = ManagerWindow(library)
        window.show()
        if library.warnings:
            QMessageBox.warning(window, '迁移提示', '\n'.join(library.warnings))
        result = app.exec()
        window.chat.stop()
        lock.unlock()
        return result
    except Exception as error:
        logging.exception('启动管理器失败')
        QMessageBox.critical(None, '启动失败（原文件未修改）', str(error))
        return 1


if __name__ == '__main__':
    sys.exit(main())
