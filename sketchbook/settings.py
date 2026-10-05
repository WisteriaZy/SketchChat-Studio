"""Defaults also apply to existing libraries without rewriting their files."""
import math


def chat_settings(values):
    settings = dict(values)
    defaults = {'delay': .25, 'paste_delay': .8, 'clipboard_timeout': 2.0,
                'include_clipboard_image': False, 'follow_expression': True}
    for key, value in defaults.items():
        settings.setdefault(key, value)
    for key, minimum, maximum in [('delay', .25, 5), ('paste_delay', .3, 10), ('clipboard_timeout', .5, 10)]:
        number = float(settings[key])
        if not math.isfinite(number):
            raise ValueError('Invalid chat delay: ' + key)
        settings[key] = max(minimum, min(maximum, number))
    settings['include_clipboard_image'] = settings['include_clipboard_image'] is True
    return settings
