import argparse
import base64
import json
import plistlib
import re
import sqlite3
import subprocess
import sys
from pathlib import Path, PurePosixPath
from xml.parsers.expat import ExpatError
from zipfile import BadZipFile, ZipFile

from ipa_icons import display_png
from ipa_runner import APP_ROOT, ASoftware, Library, create_shortcut, start_legacy


def app_icon(app):
    try:
        with ZipFile(app.path) as archive:
            manifest = next(item for item in archive.infolist()
                            if re.fullmatch(r'Payload/[^/]+\.app/Info\.plist', item.filename)
                            and item.file_size <= 2 * 1024 * 1024)
            info = plistlib.loads(archive.read(manifest))
            icons = info.get('CFBundleIcons') or {}
            primary = icons.get('CFBundlePrimaryIcon') or {}
            names = []
            for item in (primary.get('CFBundleIconFiles'), info.get('CFBundleIconFiles')):
                if isinstance(item, list):
                    names.extend(name for name in item if isinstance(name, str))
            single = info.get('CFBundleIconFile')
            if isinstance(single, str):
                names.append(single)
            names = [PurePosixPath(name).stem.lower() for name in names]
            if not names:
                names = ['icon', 'appicon']
            folder = PurePosixPath(manifest.filename).parent
            best = (0, b'')
            for entry in archive.infolist():
                candidate = PurePosixPath(entry.filename)
                stem = re.split(r'[@~]', candidate.stem.lower(), maxsplit=1)[0]
                if (candidate.parent != folder or candidate.suffix.lower() != '.png' or
                        stem not in names or entry.file_size > 512 * 1024):
                    continue
                pixels, data = display_png(archive.read(entry))
                if data and pixels > best[0]:
                    best = (pixels, data)
            if best[1]:
                return 'data:image/png;base64,' + base64.b64encode(best[1]).decode('ascii')
    except (OSError, BadZipFile, ExpatError, plistlib.InvalidFileException, RuntimeError, StopIteration, AttributeError):
        pass
    return ''


def snapshot(library):
    touchhle = library.touchhle()
    try:
        library.asoftware()
        asoftware_ready = True
    except ValueError:
        asoftware_ready = False
    return {
        'apps': [{'bundleId': app.bundle_id, 'name': app.name, 'version': app.version,
                  'minimumOs': app.minimum_os, 'architectures': app.architectures, 'modern': app.modern,
                  'revision': app.path.stem,
                  'displayMode': None if app.modern else library.display_mode(app)} for app in library.apps()],
        'runtimes': {'touchhle': str(touchhle or ''), 'touchhleReady': bool(touchhle and touchhle.is_file()),
                     'asoftware': library.setting('asoftware'), 'asoftwareReady': asoftware_ready,
                     'asoftwareWork': library.setting('asoftware_work')},
        'dataDir': str(library.root),
    }


def save_settings(library, values):
    touchhle = values.get('touchhle', '').strip()
    asoftware = values.get('asoftware', '').strip()
    work = values.get('asoftwareWork', '').strip()
    if touchhle:
        path = Path(touchhle)
        if path.name.lower() != 'touchhle.exe' or not path.is_file():
            raise ValueError('请选择有效的 touchHLE.exe。')
    if asoftware:
        ASoftware(Path(asoftware), work)
    for key, value in (('touchhle', touchhle), ('asoftware', asoftware), ('asoftware_work', work)):
        library.set_setting(key, Path(value).resolve() if value else '')
    return snapshot(library)


def confirm_started(process, log, display_name):
    try:
        if process.wait(timeout=1.5) != 0:
            raise ValueError(f'{display_name} 启动失败。请在数据目录查看 {log.name}。')
    except subprocess.TimeoutExpired:
        pass


def handle(library, action, payload):
    if action == 'snapshot':
        return snapshot(library)
    if action == 'import':
        return library.add(payload['path']).bundle_id
    if action == 'save-settings':
        return save_settings(library, payload)
    if action == 'open-ios':
        log = library.root / 'asoftware.log'
        confirm_started(library.asoftware().start(log), log, 'iOS 16')
        return None
    app = library.get(payload['bundleId'])
    if action == 'display-mode':
        return library.save_display_mode(app, payload['mode'])
    if action == 'icon':
        return app_icon(app)
    if action == 'status':
        return library.asoftware().status(app)
    if action == 'enqueue':
        library.asoftware().enqueue(app)
        return library.asoftware().status(app)
    if action == 'shortcut':
        return create_shortcut(library, app)
    process, log = start_legacy(library, app)
    confirm_started(process, log, 'touchHLE')
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, default=APP_ROOT)
    parser.add_argument('action', choices=('snapshot', 'import', 'save-settings', 'open-ios',
                                           'icon', 'status', 'enqueue', 'shortcut', 'launch', 'display-mode'))
    args = parser.parse_args()
    try:
        value = handle(Library(args.data_dir), args.action, json.load(sys.stdin))
        result = {'ok': True, 'value': value}
    except (ValueError, OSError, KeyError, sqlite3.Error, subprocess.SubprocessError) as error:
        result = {'ok': False, 'error': str(error)}
    print(json.dumps(result, ensure_ascii=True))


if __name__ == '__main__':
    main()
