"""A complete light palette: never mix Windows dark text roles with light QSS."""
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette


def apply_light_theme(app):
    app.setStyle('Fusion')
    hints = app.styleHints()
    if hasattr(hints, 'setColorScheme'):
        hints.setColorScheme(Qt.ColorScheme.Light)
    palette = QPalette()
    colors = {
        'Window': '#f5f7fb', 'WindowText': '#243247', 'Base': '#ffffff',
        'AlternateBase': '#edf2f8', 'Text': '#243247', 'Button': '#ffffff',
        'ButtonText': '#243247', 'BrightText': '#ffffff', 'Highlight': '#dbeafe',
        'HighlightedText': '#17345c', 'ToolTipBase': '#ffffff', 'ToolTipText': '#243247',
        'PlaceholderText': '#65758b', 'Link': '#2563eb', 'LinkVisited': '#7142a6',
        'Light': '#ffffff', 'Midlight': '#edf2f8', 'Mid': '#cbd5e1',
        'Dark': '#94a3b8', 'Shadow': '#64748b', 'Accent': '#2563eb',
    }
    for name, value in colors.items():
        role = getattr(QPalette.ColorRole, name, None)
        if role is not None:
            for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive, QPalette.ColorGroup.Disabled):
                palette.setColor(group, role, QColor(value))
    for name in ('WindowText', 'Text', 'ButtonText', 'PlaceholderText'):
        palette.setColor(QPalette.ColorGroup.Disabled, getattr(QPalette.ColorRole, name), QColor('#788493'))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Base, QColor('#eef1f5'))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Button, QColor('#eef1f5'))
    app.setPalette(palette)
