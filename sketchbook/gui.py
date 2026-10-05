"""PySide6 manager. Editing drafts never changes the active chat snapshot."""
from __future__ import annotations
import copy
import logging
from pathlib import Path
import shutil
from PIL import Image
from PySide6.QtCore import Qt, QSize, QObject, QRunnable, QThreadPool, Signal, QTimer
from PySide6.QtGui import QAction, QIcon, QPixmap, QColor, QFontDatabase, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QSplitter, QListWidget, QListWidgetItem, QLineEdit, QPushButton, QLabel,
    QComboBox, QCheckBox, QSpinBox, QDoubleSpinBox, QFileDialog, QMessageBox,
    QInputDialog, QColorDialog, QGroupBox, QScrollArea, QSystemTrayIcon, QMenu,
    QStyle, QDialog, QDialogButtonBox, QPlainTextEdit)
from .library import Library, atomic_yaml
from .rendering import render
from .canvas import RegionCanvas
from .chat import ChatService
from .theme import apply_light_theme
from .settings import chat_settings
from .tags import validate_tag
from .hotkeys import HotkeyInput, ExpressionHotkeys, validate_hotkey, validate_mapping

class PreviewSignals(QObject):
    finished = Signal(int, bytes, str)

class PreviewJob(QRunnable):
    def __init__(self, revision, signals, library, character, expression, text, content):
        super().__init__()
        self.args = library, character, expression, text, content
        self.revision, self.signals = revision, signals
    def run(self):
        try:
            self.signals.finished.emit(self.revision, render(*self.args), '')
        except Exception as error:
            self.signals.finished.emit(self.revision, b'', str(error))

def button(text, callback, layout):
    widget = QPushButton(text)
    widget.clicked.connect(callback)
    layout.addWidget(widget)
    return widget

class ManagerWindow(QMainWindow):
    def __init__(self, library):
        super().__init__()
        # Explicit font registration also makes headless verification render CJK correctly.
        app = QApplication.instance()
        apply_light_theme(app)
        if not app.property('studio_font_registered'):
            import os
            font_path = Path(os.environ.get('WINDIR', 'C:/Windows')) / 'Fonts' / 'msyh.ttc'
            if font_path.exists():
                font_id = QFontDatabase.addApplicationFont(str(font_path))
                families = QFontDatabase.applicationFontFamilies(font_id)
                if families:
                    app.setFont(QFont(families[0], 10))
            app.setProperty('studio_font_registered', True)
        self.library = library
        self.draft = None
        self.expression_id = None
        self.loading = False
        self.dirty = False
        self.content = None
        self.preview_bytes = b''
        self.revision = 0
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)
        self.preview_signals = PreviewSignals(self)
        self.preview_signals.finished.connect(self.preview_finished)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.preview)
        self.chat = ChatService(library)
        self.chat.message.connect(self.statusBar().showMessage)
        self.chat.selected.connect(self.chat_selected)
        self.setWindowTitle('绘聊工坊 · SketchChat Studio')
        self.resize(1320, 880)
        self.setMinimumSize(1050, 730)
        self.setWindowIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
        self.build_ui()
        self.build_tray()
        self.reload_characters()
        self.configure_chat()
        self.statusBar().showMessage('聊天监听已暂停。先预览效果，再主动启用；预览不会读取剪贴板或发送消息。')
    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        column = QVBoxLayout(root)
        top = QHBoxLayout()
        title = QLabel('绘聊工坊')
        title.setStyleSheet('font-size:22px;font-weight:700;color:#17345c')
        top.addWidget(title)
        top.addStretch()
        self.active_label = QLabel()
        top.addWidget(self.active_label)
        self.listen_button = button('启用聊天监听', self.toggle_chat, top)
        button('聊天设置', self.settings_dialog, top)
        button('备份素材库', self.backup, top)
        column.addLayout(top)
        split = QSplitter()
        column.addWidget(split, 1)
        left = QWidget()
        left_column = QVBoxLayout(left)
        self.search = QLineEdit()
        self.search.setPlaceholderText('搜索角色…')
        self.search.textChanged.connect(self.filter_characters)
        left_column.addWidget(self.search)
        self.characters = QListWidget()
        self.characters.currentItemChanged.connect(self.change_character)
        left_column.addWidget(self.characters, 1)
        button('＋ 新建角色', self.new_character, left_column)
        row = QHBoxLayout()
        button('复制', self.duplicate_character, row)
        button('删除', self.delete_character, row)
        left_column.addLayout(row)
        left.setMinimumWidth(175)
        split.addWidget(left)
        center = QWidget()
        center_column = QVBoxLayout(center)
        tools = QHBoxLayout()
        tools.addWidget(QLabel('滚轮缩放 · 中键平移 · 四角调整区域'))
        tools.addStretch()
        button('适应窗口', lambda: self.canvas.fit(), tools)
        center_column.addLayout(tools)
        self.canvas = RegionCanvas()
        self.canvas.regionChanged.connect(self.region_changed)
        center_column.addWidget(self.canvas, 1)
        self.preview_status = QLabel('')
        self.preview_status.setWordWrap(True)
        center_column.addWidget(self.preview_status)
        self.expressions = QListWidget()
        self.expressions.setViewMode(QListWidget.ViewMode.IconMode)
        self.expressions.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.expressions.setIconSize(QSize(72, 88))
        self.expressions.setGridSize(QSize(112, 125))
        self.expressions.setMaximumHeight(165)
        self.expressions.setMinimumHeight(135)
        self.expressions.currentItemChanged.connect(self.change_expression)
        center_column.addWidget(self.expressions)
        row = QHBoxLayout()
        button('＋ 批量导入表情', self.import_expressions, row)
        button('删除表情', self.delete_expression, row)
        button('设为默认表情', self.set_default, row)
        center_column.addLayout(row)
        split.addWidget(center)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        panel = QWidget()
        side = QVBoxLayout(panel)
        basic = QFormLayout()
        self.character_name = QLineEdit()
        self.expression_name = QLineEdit()
        self.tag = QLineEdit()
        self.tag.setPlaceholderText("例如 /开心、[开心]、:)")
        self.tag.setToolTip("仅匹配消息最开头，按字面匹配而非正则；修改后保存角色。若有表情快捷键，请同步更新其目标标签。")
        basic.addRow('角色名称', self.character_name)
        basic.addRow('表情名称', self.expression_name)
        basic.addRow('聊天标签', self.tag)
        side.addLayout(basic)
        for field in (self.character_name, self.expression_name, self.tag):
            field.textEdited.connect(self.form_changed)
        button('替换当前底图…', self.replace_image, side)
        self.scope = QComboBox()
        self.scope.addItems(['当前表情布局', '角色默认布局'])
        self.scope.currentIndexChanged.connect(self.load_form)
        side.addWidget(self.scope)
        self.inherit = QCheckBox('继承角色布局（取消后独立设置）')
        self.inherit.setToolTip('继承当前角色自己的默认布局，不是默认表情。切到“角色默认布局”可修改共用设置。')
        self.inherit.toggled.connect(self.toggle_inherit)
        side.addWidget(self.inherit)
        self.layout_group = QGroupBox('写字区域 · 原始图片像素')
        form = QFormLayout(self.layout_group)
        self.coordinates = []
        for label in ('左上 X', '左上 Y', '右下 X', '右下 Y'):
            spin = QSpinBox()
            spin.setRange(0, 100000)
            spin.valueChanged.connect(self.form_changed)
            self.coordinates.append(spin)
            form.addRow(label, spin)
        self.font_label = QLabel('默认字体')
        self.font_label.setWordWrap(True)
        form.addRow('字体', self.font_label)
        self.font_button = QPushButton('选择字体文件…')
        self.font_button.clicked.connect(self.choose_font)
        form.addRow(self.font_button)
        self.color_button = QPushButton('文字颜色')
        self.color_button.clicked.connect(self.choose_color)
        form.addRow(self.color_button)
        self.font_size = QSpinBox()
        self.font_size.setRange(1, 2048)
        self.font_size.valueChanged.connect(self.form_changed)
        form.addRow('最大字号', self.font_size)
        self.align = QComboBox()
        for label, data in [('居左','left'),('居中','center'),('居右','right')]:
            self.align.addItem(label, data)
        self.align.currentIndexChanged.connect(self.form_changed)
        form.addRow('水平对齐', self.align)
        self.valign = QComboBox()
        for label, data in [('顶部','top'),('居中','middle'),('底部','bottom')]:
            self.valign.addItem(label, data)
        self.valign.currentIndexChanged.connect(self.form_changed)
        form.addRow('垂直对齐', self.valign)
        self.spacing = QDoubleSpinBox()
        self.spacing.setRange(0, 3)
        self.spacing.setSingleStep(.05)
        self.spacing.valueChanged.connect(self.form_changed)
        form.addRow('行距比例', self.spacing)
        self.overlay_label = QLabel('未启用')
        self.overlay_label.setWordWrap(True)
        form.addRow('遮挡层', self.overlay_label)
        row = QHBoxLayout()
        button('导入遮挡层', self.choose_overlay, row)
        button('关闭', self.clear_overlay, row)
        form.addRow(row)
        side.addWidget(self.layout_group)
        side.addStretch()
        scroll.setWidget(panel)
        scroll.setMinimumWidth(300)
        right = QWidget()
        right_column = QVBoxLayout(right)
        right_column.setContentsMargins(0,0,0,0)
        right_column.addWidget(scroll, 1)
        self.save_button = button('保存角色', self.save, right_column)
        button('设为聊天当前角色 / 表情', self.activate, right_column)
        split.addWidget(right)
        split.setSizes([185, 760, 325])
        bottom = QHBoxLayout()
        bottom.addWidget(QLabel('测试文字'))
        self.test_text = QLineEdit('你好呀！今天也要开心。')
        self.test_text.setMaxLength(2000)
        self.test_text.textChanged.connect(self.schedule_preview)
        bottom.addWidget(self.test_text, 1)
        self.content_button = button('测试图片…', self.choose_content, bottom)
        button('清除图片', self.clear_content, bottom)
        button('导出预览 PNG', self.export_preview, bottom)
        column.addLayout(bottom)
        self.setStyleSheet('''
            QMainWindow { background: #f5f7fb; }
            QWidget { font-family: "Microsoft YaHei"; font-size: 12px; }
            QPushButton { padding: 7px 10px; border: 1px solid #cbd5e1; border-radius: 5px; background: white; }
            QPushButton:hover { background: #e8f0ff; border-color: #769bdd; }
            QPushButton:disabled { color: #9ca3af; }
            QLineEdit,QSpinBox,QDoubleSpinBox,QComboBox { padding: 4px; }
            QListWidget { border: 1px solid #dce3ed; border-radius: 6px; background: white; }
            QListWidget::item:selected { background: #dbeafe; color: #17345c; }
            QGroupBox { margin-top: 12px; padding-top: 12px; }
        ''')
    def build_tray(self):
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip('绘聊工坊 · 聊天暂停')
        menu = QMenu(self)
        for title, callback in [('打开管理器', self.show_window), ('启用 / 暂停聊天监听', self.toggle_chat), ('退出', self.exit_app)]:
            action = QAction(title, self)
            action.triggered.connect(callback)
            menu.addAction(action)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self.tray_activated)
        self.update_tray_status()
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.tray.show()
    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.toggle_chat()

    def update_tray_status(self):
        enabled = self.chat.enabled
        pixmap = QPixmap(32, 32)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor('#16a34a' if enabled else '#64748b'))
        painter.drawEllipse(2, 2, 28, 28)
        painter.setPen(QPen(QColor('white'), 3))
        if enabled:
            painter.drawLine(9, 16, 14, 21)
            painter.drawLine(14, 21, 23, 11)
        else:
            painter.drawLine(12, 10, 12, 22)
            painter.drawLine(20, 10, 20, 22)
        painter.end()
        self.tray.setIcon(QIcon(pixmap))
        status = '监听中' if enabled else '已暂停'
        self.tray.setToolTip('绘聊工坊 · ' + status + '\n' + self.active_label.text() + '\n左键切换监听 · 右键打开菜单')
        self.listen_button.setText('暂停聊天监听' if enabled else '启用聊天监听')

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
    def fail(self, error):
        logging.warning('%s', error)
        QMessageBox.warning(self, '请检查', str(error))
    def mark_dirty(self):
        self.dirty = True
        self.save_button.setText('保存角色 *')
    def confirm_draft(self):
        if not self.dirty:
            return True
        result = QMessageBox.question(self, '未保存的修改', '是否保存当前角色的修改？',
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel)
        if result == QMessageBox.StandardButton.Save:
            return self.save()
        return result == QMessageBox.StandardButton.Discard
    def reload_characters(self, selected=None):
        self.characters.blockSignals(True)
        self.characters.clear()
        for character in self.library.characters.values():
            item = QListWidgetItem(character['name'])
            item.setData(Qt.ItemDataRole.UserRole, character['id'])
            self.characters.addItem(item)
        chosen = selected or self.library.state.get('active_character')
        index = next((i for i in range(self.characters.count()) if self.characters.item(i).data(Qt.ItemDataRole.UserRole) == chosen), 0)
        self.characters.setCurrentRow(index)
        self.characters.blockSignals(False)
        self.load_character(self.characters.currentItem())
        self.filter_characters(self.search.text())
    def filter_characters(self, text):
        for index in range(self.characters.count()):
            item = self.characters.item(index)
            item.setHidden(text.casefold() not in item.text().casefold())
    def change_character(self, item, previous):
        if self.loading:
            return
        if not self.confirm_draft():
            self.characters.blockSignals(True)
            self.characters.setCurrentItem(previous)
            self.characters.blockSignals(False)
            return
        self.load_character(item)
    def load_character(self, item):
        self.revision += 1
        self.preview_bytes = b''
        self.dirty = False
        self.save_button.setText('保存角色')
        self.draft = copy.deepcopy(self.library.characters[item.data(Qt.ItemDataRole.UserRole)]) if item else None
        self.refresh_expressions()
    def refresh_expressions(self, selected=None):
        self.expressions.blockSignals(True)
        self.expressions.clear()
        if self.draft:
            for expression in self.draft['expressions']:
                label = expression['name'] + (' ★' if expression['id'] == self.draft['default_expression'] else '')
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, expression['id'])
                item.setToolTip(expression['tag'])
                try:
                    item.setIcon(QIcon(str(self.library.asset(self.draft, expression['image']))))
                except ValueError:
                    pass
                self.expressions.addItem(item)
            selected = selected or self.library.state['last_expressions'].get(self.draft['id']) or self.draft['default_expression']
        index = next((i for i in range(self.expressions.count()) if self.expressions.item(i).data(Qt.ItemDataRole.UserRole) == selected), 0)
        self.expressions.setCurrentRow(index)
        self.expressions.blockSignals(False)
        self.change_expression(self.expressions.currentItem(), None)
    def expression(self):
        return self.library.expression(self.draft, self.expression_id)
    def change_expression(self, item, previous):
        self.expression_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        self.load_form()
        if self.draft and self.expression_id:
            try:
                self.canvas.set_image(QPixmap(str(self.library.asset(self.draft, self.expression()['image']))), reset=True)
            except ValueError as error:
                self.preview_status.setText(str(error))
        else:
            self.canvas.set_image(QPixmap())
            self.canvas.set_region([0,0,0,0])
        self.schedule_preview()
    def effective_layout(self):
        return self.draft['layout'] if self.scope.currentIndex() == 1 else self.library.layout(self.draft, self.expression())
    def editable_layout(self):
        return self.draft['layout'] if self.scope.currentIndex() == 1 else self.expression()['overrides']
    def load_form(self, *args):
        self.loading = True
        available = bool(self.draft and self.expression_id)
        for widget in (self.character_name, self.expression_name, self.tag, self.scope, self.inherit, self.save_button):
            widget.setEnabled(available)
        if available:
            expression = self.expression()
            layout = self.effective_layout()
            self.character_name.setText(self.draft['name'])
            self.expression_name.setText(expression['name'])
            self.tag.setText(expression['tag'])
            self.inherit.setChecked(not expression.get('overrides'))
            self.inherit.setVisible(self.scope.currentIndex() == 0)
            editable = self.scope.currentIndex() == 1 or bool(expression.get('overrides'))
            self.layout_group.setEnabled(editable)
            self.canvas.editable = editable
            for spin, value in zip(self.coordinates, layout['region']):
                spin.setValue(value)
            self.font_size.setValue(layout['max_font_size'])
            self.align.setCurrentIndex(self.align.findData(layout['align']))
            self.valign.setCurrentIndex(self.valign.findData(layout['valign']))
            self.spacing.setValue(layout['line_spacing'])
            self.font_label.setText('已导入字体' if layout.get('font') else '系统默认（建议导入中文字体）')
            self.font_label.setToolTip(layout.get('font') or '')
            self.overlay_label.setText('已启用遮挡层' if layout.get('overlay') else '未启用')
            self.color_button.setText('文字颜色：' + layout['color'])
            self.canvas.set_region(layout['region'])
        else:
            for widget in (self.character_name, self.expression_name, self.tag):
                widget.clear()
            self.layout_group.setEnabled(False)
            self.canvas.editable = False
        self.loading = False
        self.schedule_preview()
    def form_changed(self, *args):
        if self.loading or not self.draft or not self.expression_id:
            return
        self.draft['name'] = self.character_name.text()
        self.expression()['name'] = self.expression_name.text()
        self.expression()['tag'] = self.tag.text()
        if self.layout_group.isEnabled():
            self.editable_layout().update(region=[spin.value() for spin in self.coordinates],
                max_font_size=self.font_size.value(), align=self.align.currentData(),
                valign=self.valign.currentData(), line_spacing=self.spacing.value())
        self.canvas.set_region(self.effective_layout()['region'])
        self.mark_dirty()
        self.schedule_preview()
    def toggle_inherit(self, checked):
        if self.loading or not self.draft or not self.expression_id:
            return
        self.expression()['overrides'] = {} if checked else copy.deepcopy(self.draft['layout'])
        self.mark_dirty()
        self.load_form()
    def region_changed(self, values):
        if not self.draft or not self.canvas.editable:
            return
        self.editable_layout()['region'] = values
        self.mark_dirty()
        self.load_form()
    def schedule_preview(self, *args):
        if self.loading:
            return
        self.revision += 1
        self.preview_bytes = b''
        self.timer.start()
    def preview(self):
        if not self.draft or not self.expression_id:
            return
        character = copy.deepcopy(self.draft)
        expression = self.library.expression(character, self.expression_id)
        if self.scope.currentIndex() == 1:
            expression['overrides'] = {}
        self.pool.clear()
        self.preview_status.setText('正在渲染…')
        self.pool.start(PreviewJob(self.revision, self.preview_signals, self.library, character, expression,
                                  self.test_text.text(), self.content.copy() if self.content else None))
    def preview_finished(self, revision, data, error):
        if revision != self.revision:
            return
        self.preview_bytes = data
        self.preview_status.setText(error or ('预览角色默认布局（不改变当前表情的独立布局）' if self.scope.currentIndex() else '预览与聊天共用同一渲染器；蓝框不会导出'))
        self.preview_status.setStyleSheet('color:#b42318' if error else 'color:#607087')
        if data:
            pixmap = QPixmap()
            pixmap.loadFromData(data)
            self.canvas.set_image(pixmap)
        elif self.draft and self.expression_id:
            self.canvas.set_image(QPixmap(str(self.library.asset(self.draft, self.expression()['image']))))
    def save(self):
        if not self.draft:
            return False
        try:
            self.library.save_character(self.draft)
            self.dirty = False
            self.save_button.setText('保存角色')
            for index in range(self.characters.count()):
                item = self.characters.item(index)
                if item.data(Qt.ItemDataRole.UserRole) == self.draft['id']:
                    item.setText(self.draft['name'])
            self.configure_chat()
            self.refresh_expressions(self.expression_id)
            self.statusBar().showMessage('已保存；当前使用该角色时，下一次生成将使用新配置。')
            return True
        except Exception as error:
            self.fail(error)
            return False
    def activate(self):
        if not self.draft or not self.expression_id:
            return
        if self.dirty and not self.save():
            return
        try:
            self.library.activate(self.draft['id'], self.expression_id)
            self.configure_chat()
        except Exception as error:
            self.fail(error)
    def configure_chat(self):
        character = self.library.characters.get(self.library.state.get('active_character'))
        eid = None
        if character:
            eid = self.library.state['last_expressions'].get(character['id'])
            if eid not in {e['id'] for e in character['expressions']}:
                eid = character['default_expression']
            expression = self.library.expression(character, eid)
            self.active_label.setText(f"聊天当前：{character['name']} · {expression['name']}")
        else:
            self.active_label.setText('聊天当前：未选择')
        self.chat.configure(self.library.state['settings'], character, eid)
        if character and not self.chat.settings['follow_expression']:
            expression = self.library.expression(character, character['default_expression'])
            self.active_label.setText(f"聊天当前：{character['name']} · {expression['name']}（单次表情）")
        self.update_tray_status()
    def chat_selected(self, character_id, eid):
        with self.chat.lock:
            current = self.chat.snapshot
            if not current or current[0]['id'] != character_id or current[1] != eid:
                return
        if self.library.state.get('active_character') != character_id:
            return
        character = self.library.characters.get(character_id)
        if not character or eid not in {e['id'] for e in character['expressions']}:
            return
        self.library.state['last_expressions'][character_id] = eid
        try:
            self.library.save_state()
            expression = self.library.expression(character, eid)
            self.active_label.setText(f"聊天当前：{character['name']} · {expression['name']}")
            self.update_tray_status()
        except OSError as error:
            self.statusBar().showMessage(str(error))
    def toggle_chat(self):
        try:
            if self.chat.enabled:
                self.chat.stop()
            else:
                self.chat.start()
            self.listen_button.setText('暂停聊天监听' if self.chat.enabled else '启用聊天监听')
            self.tray.setToolTip('绘聊工坊 · ' + ('聊天监听中' if self.chat.enabled else '聊天暂停'))
        except Exception as error:
            self.fail(error)
        finally:
            self.update_tray_status()
    def new_character(self):
        if not self.confirm_draft():
            return
        name, ok = QInputDialog.getText(self, '新建角色', '角色名称')
        if not ok or not name.strip():
            return
        paths, _ = QFileDialog.getOpenFileNames(self, '导入角色底图', '', '图片 (*.png *.jpg *.jpeg *.webp *.bmp)')
        if not paths:
            return
        character = self.library.new_character(name)
        try:
            for path in paths:
                self.library.add_expression(character, path)
            font = Path(__file__).resolve().parent.parent / 'font.ttf'
            if font.exists():
                character['layout']['font'] = self.library.import_asset(character, font, 'font')
            # Creating a role persists a valid starter; subsequent edits are drafts.
            for expression in character['expressions']:
                with Image.open(self.library.asset(character, expression['image'])) as image:
                    w, h = image.size
                x1,y1,x2,y2 = character['layout']['region']
                if not (0 <= x1 < x2 <= w and 0 <= y1 < y2 <= h):
                    expression['overrides']['region'] = [int(w*.15), int(h*.65), int(w*.85), int(h*.95)]
            self.library.save_character(character)
            self.reload_characters(character['id'])
            self.scope.setCurrentIndex(1)
            self.statusBar().showMessage('请确认框选区域。不同尺寸的表情可取消继承并独立调整。')
        except Exception as error:
            self.fail(error)
    def import_expressions(self):
        if not self.draft:
            return self.new_character()
        paths, _ = QFileDialog.getOpenFileNames(self, '批量导入表情', '', '图片 (*.png *.jpg *.jpeg *.webp *.bmp)')
        if not paths:
            return
        errors = []
        selected = None
        reference = None
        if self.expression_id:
            with Image.open(self.library.asset(self.draft, self.library.expression(self.draft)['image'])) as image:
                reference = image.size
        for path in paths:
            try:
                expression = self.library.add_expression(self.draft, path)
                selected = expression['id']
                with Image.open(path) as image:
                    size = image.size
                if reference and size != reference:
                    self.scale_import(expression, reference, size)
            except Exception as error:
                errors.append(f'{Path(path).name}: {error}')
        self.mark_dirty()
        self.refresh_expressions(selected)
        if errors:
            self.fail('\n'.join(errors))
    def scale_import(self, expression, old, new):
        answer = QMessageBox.question(self, '底图尺寸不同',
            f"{expression['name']} 的尺寸为 {new[0]} × {new[1]}，参考图为 {old[0]} × {old[1]}。\n是否按比例换算写字区域并设置为独立布局？（遮挡层将关闭，请预览确认）")
        if answer == QMessageBox.StandardButton.Yes:
            layout = self.library.layout(self.draft, expression)
            layout['region'] = [round(value * new[i%2] / old[i%2]) for i,value in enumerate(layout['region'])]
            layout['overlay'] = None
            expression['overrides'] = layout
    def duplicate_character(self):
        if not self.draft or not self.confirm_draft():
            return
        name, ok = QInputDialog.getText(self, '复制角色', '新角色名称', text=self.draft['name']+' 副本')
        if ok and name.strip():
            try:
                duplicate = self.library.duplicate(self.library.characters[self.draft['id']], name.strip())
                self.reload_characters(duplicate['id'])
            except Exception as error:
                self.fail(error)
    def delete_character(self):
        if not self.draft:
            return
        if QMessageBox.question(self, '删除角色', '角色将移入素材库 trash 目录，可手动恢复。未保存修改将丢弃。确定删除？') != QMessageBox.StandardButton.Yes:
            return
        if self.chat.busy.locked():
            return self.fail('正在生成聊天图片，请稍后删除。')
        try:
            self.library.archive(self.draft['id'])
            if not self.library.state['active_character']:
                self.chat.stop()
                self.listen_button.setText('启用聊天监听')
            self.reload_characters()
            self.configure_chat()
        except Exception as error:
            self.fail(error)
    def delete_expression(self):
        if not self.draft or not self.expression_id:
            return
        if len(self.draft['expressions']) == 1:
            return self.fail('角色至少保留一个表情；可删除整个角色。')
        if QMessageBox.question(self, '删除表情', '从角色中移除此表情？图片文件仍保留，保存后生效。') != QMessageBox.StandardButton.Yes:
            return
        self.draft['expressions'] = [e for e in self.draft['expressions'] if e['id'] != self.expression_id]
        if self.draft['default_expression'] == self.expression_id:
            self.draft['default_expression'] = self.draft['expressions'][0]['id']
        self.mark_dirty()
        self.refresh_expressions()
    def set_default(self):
        if self.draft and self.expression_id:
            self.draft['default_expression'] = self.expression_id
            self.mark_dirty()
            self.refresh_expressions(self.expression_id)
    def replace_image(self):
        if not self.draft or not self.expression_id:
            return
        path, _ = QFileDialog.getOpenFileName(self, '替换底图', '', '图片 (*.png *.jpg *.jpeg *.webp *.bmp)')
        if not path:
            return
        try:
            expression = self.expression()
            try:
                with Image.open(self.library.asset(self.draft, expression['image'])) as image:
                    old = image.size
            except OSError:
                old = None
            relative = self.library.import_asset(self.draft, path)
            with Image.open(path) as image:
                new = image.size
            expression['image'] = relative
            if old and old != new:
                self.scale_import(expression, old, new)
            self.mark_dirty()
            self.refresh_expressions(self.expression_id)
        except Exception as error:
            self.fail(error)
    def choose_font(self):
        path, _ = QFileDialog.getOpenFileName(self, '导入字体', '', '字体 (*.ttf *.otf *.ttc)')
        if path:
            try:
                self.editable_layout()['font'] = self.library.import_asset(self.draft, path, 'font')
                self.mark_dirty()
                self.load_form()
            except Exception as error:
                self.fail(error)
    def choose_color(self):
        color = QColorDialog.getColor(QColor(self.effective_layout()['color']), self)
        if color.isValid():
            self.editable_layout()['color'] = color.name()
            self.mark_dirty()
            self.load_form()
    def choose_overlay(self):
        path, _ = QFileDialog.getOpenFileName(self, '导入透明遮挡层', '', 'PNG (*.png)')
        if path:
            try:
                self.editable_layout()['overlay'] = self.library.import_asset(self.draft, path)
                self.mark_dirty()
                self.load_form()
            except Exception as error:
                self.fail(error)
    def clear_overlay(self):
        self.editable_layout()['overlay'] = None
        self.mark_dirty()
        self.load_form()
    def choose_content(self):
        path, _ = QFileDialog.getOpenFileName(self, '选择测试图片（不会读取剪贴板）', '', '图片 (*.png *.jpg *.jpeg *.webp *.bmp)')
        if path:
            try:
                with Image.open(path) as image:
                    self.content = image.convert('RGBA')
                self.content_button.setText('测试图：' + Path(path).name[:12])
                self.schedule_preview()
            except Exception as error:
                self.fail(error)
    def clear_content(self):
        self.content = None
        self.content_button.setText('测试图片…')
        self.schedule_preview()
    def export_preview(self):
        if not self.preview_bytes:
            return self.fail('请等待有效预览生成，或先修正区域、字体与遮挡层。')
        path, _ = QFileDialog.getSaveFileName(self, '导出效果', 'preview.png', 'PNG (*.png)')
        if path:
            try:
                Path(path).write_bytes(self.preview_bytes)
                self.statusBar().showMessage('已导出：' + path)
            except OSError as error:
                self.fail(error)
    def backup(self):
        folder = QFileDialog.getExistingDirectory(self, '选择备份存放目录')
        if not folder:
            return
        from datetime import datetime
        destination = Path(folder) / ('sketchbook-backup-' + datetime.now().strftime('%Y%m%d-%H%M%S'))
        if destination.resolve().is_relative_to(self.library.root):
            return self.fail('请选素材库之外的目录，避免递归备份。')
        try:
            shutil.copytree(self.library.root, destination)
            self.statusBar().showMessage('已备份已保存的素材库：' + str(destination))
        except OSError as error:
            self.fail(error)
    def settings_dialog(self):
        if self.chat.busy.locked():
            return self.fail('正在生成图片，请稍后修改设置。')
        self.chat.stop()
        self.listen_button.setText('启用聊天监听')
        self.update_tray_status()
        dialog = QDialog(self)
        dialog.setWindowTitle('聊天设置 · 请勿同时运行旧版监听')
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        settings = chat_settings(self.library.state['settings'])
        fields = {}
        for key, label in [('hotkey','生成热键'),('send_hotkey','发送热键')]:
            field = HotkeyInput(settings.get(key, 'enter'))
            fields[key] = field
            form.addRow(label, field)
        allowed = QLineEdit(', '.join(settings.get('allowed_processes', [])))
        form.addRow('允许进程（逗号分隔；空=所有）', allowed)
        delay = QDoubleSpinBox()
        delay.setRange(.25, 5)
        delay.setSingleStep(.05)
        delay.setValue(settings.get('delay', .1))
        form.addRow('操作间隔（秒，至少 0.25）', delay)
        paste_delay = QDoubleSpinBox()
        paste_delay.setRange(.3, 10)
        paste_delay.setSingleStep(.1)
        paste_delay.setValue(settings['paste_delay'])
        form.addRow('粘贴后等待发送（秒）', paste_delay)
        clipboard_timeout = QDoubleSpinBox()
        clipboard_timeout.setRange(.5, 10)
        clipboard_timeout.setSingleStep(.5)
        clipboard_timeout.setValue(settings['clipboard_timeout'])
        form.addRow('剪贴板读取超时（秒）', clipboard_timeout)
        include_image = QCheckBox('使用剪贴板图片作为配图（默认关闭）')
        include_image.setChecked(settings['include_clipboard_image'])
        include_image.setToolTip('启用后会读取已有剪贴板图片；纯文字聊天请保持关闭。')
        form.addRow(include_image)
        follow = QCheckBox('跟随上一次表情（关闭后每条默认用角色默认表情）')
        follow.setChecked(settings['follow_expression'])
        follow.setToolTip('关闭后，正文标签只影响本条；表情快捷键或单独标签只影响下一条。')
        form.addRow(follow)
        paste = QCheckBox('生成后自动粘贴')
        paste.setChecked(settings.get('auto_paste_image', True))
        send = QCheckBox('粘贴后自动发送（建议先关闭测试）')
        send.setChecked(settings.get('auto_send_image', True))
        form.addRow(paste)
        form.addRow(send)
        suggestions = sorted({e['tag'] for c in self.library.characters.values() for e in c['expressions']})
        mappings = ExpressionHotkeys(settings.get('emotion_switch_hotkeys', {}), suggestions)
        form.addRow('表情快捷键 → 聊天标签', mappings)
        layout.addLayout(form)
        layout.addWidget(QLabel('打开设置已暂停监听；录制后松开全部按键完成，Esc 取消。\n表情快捷键按标签作用于当前角色；保存或取消后均需手动启用监听。'))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        layout.addWidget(buttons)
        buttons.rejected.connect(dialog.reject)
        def commit():
            try:
                if any(field.recording for field in fields.values()):
                    raise ValueError('请先完成快捷键录制')
                settings.update({key: validate_hotkey(field.text())[0] for key,field in fields.items()})
                mapping = validate_mapping(settings['hotkey'], mappings.values())
                settings.update(allowed_processes=[p.strip() for p in allowed.text().replace('，', ',').split(',') if p.strip()],
                    delay=delay.value(), paste_delay=paste_delay.value(), clipboard_timeout=clipboard_timeout.value(),
                    include_clipboard_image=include_image.isChecked(), follow_expression=follow.isChecked(), auto_paste_image=paste.isChecked(), auto_send_image=send.isChecked(), emotion_switch_hotkeys=mapping)
                state = copy.deepcopy(self.library.state)
                state['settings'] = settings
                atomic_yaml(self.library.root / 'library.yaml', state)
                self.library.state = state
                self.chat.stop()
                self.listen_button.setText('启用聊天监听')
                self.configure_chat()
                dialog.accept()
            except Exception as error:
                self.fail(error)
        buttons.accepted.connect(commit)
        dialog.resize(780, 780)
        dialog.exec()
    def exit_app(self):
        if self.chat.busy.locked():
            return self.fail('正在生成图片，请稍后退出，以免中断剪贴板操作。')
        if not self.confirm_draft():
            return
        self.chat.stop()
        self.timer.stop()
        self.pool.clear()
        self.pool.waitForDone()
        self.tray.hide()
        QApplication.instance().quit()
    def closeEvent(self, event):
        if self.tray.isVisible():
            self.hide()
            self.tray.showMessage('绘聊工坊', '已隐藏到托盘。右键托盘可暂停监听或退出。')
            event.ignore()
        else:
            event.ignore()
            self.exit_app()
