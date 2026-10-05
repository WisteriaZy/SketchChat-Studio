"""Versioned, portable character library. No GUI or keyboard dependencies."""
from __future__ import annotations

import copy
import os
from pathlib import Path
import shutil
import tempfile
import uuid
import yaml
from .tags import validate_tag
from PIL import Image, ImageFont, ImageColor


def uid():
    return uuid.uuid4().hex


def atomic_yaml(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.save-', suffix='.yaml', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            yaml.safe_dump(data, stream, allow_unicode=True, sort_keys=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Library:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.characters = {}
        self.state = {'version': 1, 'active_character': None, 'last_expressions': {}, 'settings': {}}
        self.warnings = []

    def asset(self, character, relative):
        if not relative:
            return None
        if uuid.UUID(character['id']).hex != character['id']:
            raise ValueError('Invalid character ID')
        base = (self.root / 'characters' / character['id']).resolve()
        path = (base / relative).resolve()
        if not path.is_relative_to(base):
            raise ValueError('素材路径必须位于角色目录内')
        return path

    def import_asset(self, character, source, kind='image'):
        source = Path(source)
        if kind == 'font':
            ImageFont.truetype(str(source), 16)
        else:
            with Image.open(source) as image:
                image.verify()
        relative = 'assets/' + uid() + source.suffix.lower()
        destination = self.asset(character, relative)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return relative

    def load(self):
        if not (self.root / 'library.yaml').exists():
            return False
        self.state = yaml.safe_load((self.root / 'library.yaml').read_text('utf-8'))
        if not isinstance(self.state, dict) or self.state.get('version') != 1:
            raise ValueError('不支持的素材库版本；不会覆盖现有数据')
        self.characters = {}
        for path in sorted((self.root / 'characters').glob('*/character.yaml')):
            character = yaml.safe_load(path.read_text('utf-8'))
            if character.get('id') != path.parent.name:
                raise ValueError('角色 ID 与目录不一致：' + str(path))
            self.characters[character['id']] = character
        return True

    @staticmethod
    def new_character(name):
        return {'version': 1, 'id': uid(), 'name': name.strip() or '新角色',
                'default_expression': None, 'layout': {
                    'region': [0, 0, 100, 100], 'font': None, 'color': '#000000',
                    'max_font_size': 64, 'align': 'center', 'valign': 'middle',
                    'line_spacing': 0.15, 'overlay': None, 'wrap_algorithm': 'original'},
                'expressions': []}

    @staticmethod
    def expression(character, expression_id=None):
        expression_id = expression_id or character['default_expression']
        return next(e for e in character['expressions'] if e['id'] == expression_id)

    @staticmethod
    def layout(character, expression):
        result = copy.deepcopy(character['layout'])
        result.update(expression.get('overrides', {}))
        return result

    def add_expression(self, character, source, name=None):
        relative = self.import_asset(character, source)
        base_name = (name or Path(source).stem).strip().replace('#', '') or '表情'
        existing = {e['name'] for e in character['expressions']}
        name = base_name
        number = 2
        while name in existing:
            name = f'{base_name} {number}'
            number += 1
        expression = {'id': uid(), 'name': name, 'tag': f'#{name}#', 'image': relative, 'overrides': {}}
        if not character['expressions']:
            with Image.open(source) as image:
                w, h = image.size
            character['layout']['region'] = [int(w * .15), int(h * .65), int(w * .85), int(h * .95)]
            character['default_expression'] = expression['id']
        character['expressions'].append(expression)
        return expression

    def validate_expression(self, character, expression):
        layout = self.layout(character, expression)
        with Image.open(self.asset(character, expression['image'])) as image:
            width, height = image.size
        ImageColor.getrgb(layout['color'])
        if layout['align'] not in ('left', 'center', 'right') or layout['valign'] not in ('top', 'middle', 'bottom'):
            raise ValueError('Invalid alignment')
        if not 0 <= layout['line_spacing'] <= 3:
            raise ValueError('Invalid line spacing')
        x1, y1, x2, y2 = layout['region']
        if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
            raise ValueError(f"{expression['name']}：写字区域超出底图或宽高为零（图片 {width} × {height}）")
        if layout.get('font'):
            ImageFont.truetype(str(self.asset(character, layout['font'])), 16)
        if layout.get('overlay'):
            with Image.open(self.asset(character, layout['overlay'])) as overlay:
                if overlay.size != (width, height):
                    raise ValueError(f"{expression['name']}：遮挡层必须与底图尺寸一致")
        if not 1 <= layout['max_font_size'] <= 2048:
            raise ValueError('字号必须在 1–2048 之间')
        return layout

    def validate(self, character):
        if not character['name'].strip() or not character['expressions']:
            raise ValueError('角色必须有名称和至少一个表情')
        self.expression(character)
        tags = set()
        ids = set()
        for expression in character['expressions']:
            tag = expression['tag']
            validate_tag(tag)
            if not expression['name'].strip():
                raise ValueError('表情名称不能为空')
            if tag in tags or expression['id'] in ids:
                raise ValueError('同一角色的表情标签或 ID 不能重复')
            tags.add(tag)
            ids.add(expression['id'])
            self.validate_expression(character, expression)

    def save_character(self, character):
        self.validate(character)
        atomic_yaml(self.asset(character, 'character.yaml'), character)
        self.characters[character['id']] = copy.deepcopy(character)

    def save_state(self):
        atomic_yaml(self.root / 'library.yaml', self.state)

    def activate(self, character_id, expression_id=None):
        character = self.characters[character_id]
        expression_id = expression_id or self.state['last_expressions'].get(character_id)
        if expression_id not in {e['id'] for e in character['expressions']}:
            expression_id = character['default_expression']
        self.validate_expression(character, self.expression(character, expression_id))
        self.state['active_character'] = character_id
        self.state['last_expressions'][character_id] = expression_id
        self.save_state()
        return expression_id

    def duplicate(self, character, name):
        duplicate = copy.deepcopy(character)
        duplicate['id'] = uid()
        duplicate['name'] = name
        source = self.root / 'characters' / character['id'] / 'assets'
        if source.exists():
            shutil.copytree(source, self.root / 'characters' / duplicate['id'] / 'assets')
        for expression in duplicate['expressions']:
            old = expression['id']
            expression['id'] = uid()
            if duplicate['default_expression'] == old:
                duplicate['default_expression'] = expression['id']
        self.save_character(duplicate)
        return duplicate

    def archive(self, character_id):
        # Deletion is recoverable: move the character into the library's trash.
        source = (self.root / 'characters' / character_id).resolve()
        if source.parent != (self.root / 'characters').resolve():
            raise ValueError('非法角色目录')
        destination = self.root / 'trash' / (character_id + '-' + uid())
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.exists():
            shutil.move(str(source), str(destination))
        self.characters.pop(character_id, None)
        self.state['last_expressions'].pop(character_id, None)
        if self.state['active_character'] == character_id:
            self.state['active_character'] = None
        self.save_state()

    def migrate(self, project):
        """Copy the effective legacy configuration; never write the original files."""
        from config_loader import load_config
        project = Path(project)
        config = load_config(str(project / 'config.yaml'))
        backup = self.root / 'backups'
        backup.mkdir(parents=True, exist_ok=True)
        if (project / 'config.yaml').exists():
            shutil.copy2(project / 'config.yaml', backup / ('config-' + uid() + '.yaml'))
        character = self.new_character('我的角色（旧配置）')
        for tag, file in config.baseimage_mapping.items():
            try:
                expression = self.add_expression(character, project / file, tag.strip('#'))
                expression['tag'] = tag
            except (OSError, ValueError) as error:
                self.warnings.append(f'未导入 {tag}：{error}')
        if character['expressions']:
            layout = character['layout']
            layout['region'] = list(config.text_box_topleft) + list(config.image_box_bottomright)
            if (project / config.font_file).is_file():
                layout['font'] = self.import_asset(character, project / config.font_file, 'font')
            layout['wrap_algorithm'] = config.text_wrap_algorithm
            if config.use_base_overlay and config.base_overlay_file and (project / config.base_overlay_file).is_file():
                layout['overlay'] = self.import_asset(character, project / config.base_overlay_file)
            # Keep even invalid legacy layouts, allowing repair in the editor.
            atomic_yaml(self.root / 'characters' / character['id'] / 'character.yaml', character)
            self.characters[character['id']] = character
            self.state['active_character'] = character['id']
            self.state['last_expressions'][character['id']] = character['default_expression']
        self.state['settings'] = {key: getattr(config, key) for key in (
            'hotkey', 'allowed_processes', 'select_all_hotkey', 'cut_hotkey', 'paste_hotkey',
            'send_hotkey', 'block_hotkey', 'delay', 'auto_paste_image', 'auto_send_image', 'emotion_switch_hotkeys')}
        self.save_state()
