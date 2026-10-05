"""Offline readiness check, invoked by the Windows first-run launcher."""
import importlib
from importlib import metadata
from pathlib import Path
import sys


def check(root):
    if sys.version_info < (3, 10):
        raise RuntimeError('Python 3.10 or newer is required')
    from pip._vendor.packaging.requirements import Requirement
    for line in (root / 'requirements.txt').read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        requirement = Requirement(line)
        if requirement.marker and not requirement.marker.evaluate():
            continue
        version = metadata.version(requirement.name)
        if version not in requirement.specifier:
            raise RuntimeError(f'{requirement.name} {version} does not satisfy {requirement.specifier}')
    for name in ('PIL.Image', 'keyboard', 'pyperclip', 'win32clipboard', 'win32gui',
                 'psutil', 'pydantic', 'yaml', 'PySide6.QtWidgets'):
        importlib.import_module(name)


if __name__ == '__main__':
    try:
        check(Path(__file__).resolve().parents[1])
        print('Environment ready (offline check).')
    except Exception as error:
        print(f'Environment needs setup: {error}', file=sys.stderr)
        sys.exit(1)
