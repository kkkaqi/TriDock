import argparse
import hashlib
import os
import plistlib
import re
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from xml.parsers.expat import ExpatError
from zipfile import BadZipFile, ZipFile


APP_ROOT = Path.home() / 'Saved Games' / 'IPA Runner'
SCRIPT = Path(__file__).resolve()
ARM_TYPES = {12: 'arm', 0x0100000C: 'arm64'}
NO_CONSOLE = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
DISPLAY_OPTIONS = {'window': (), 'large': ('--scale-hack=2',), 'fullscreen': ('--fullscreen',)}


@dataclass(frozen=True)
class App:
    bundle_id: str
    name: str
    version: str
    minimum_os: str
    architectures: tuple[str, ...]
    path: Path

    @property
    def modern(self):
        return 'arm64' in self.architectures


def read_architectures(stream, size):
    header = stream.read(8)
    if len(header) != 8:
        raise ValueError('IPA 的主程序缺少 Mach-O 文件头。')
    magic = header[:4]
    thin_magics = (b'\xce\xfa\xed\xfe', b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xce', b'\xfe\xed\xfa\xcf')
    fat_magics = (b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf', b'\xbe\xba\xfe\xca', b'\xbf\xba\xfe\xca')
    if magic in thin_magics:
        endian = '<' if magic in thin_magics[:2] else '>'
        cpus = [struct.unpack(endian + 'I', header[4:])[0]]
    elif magic in fat_magics:
        endian = '>' if magic in fat_magics[:2] else '<'
        count = struct.unpack(endian + 'I', header[4:])[0]
        layout = endian + ('IIQQII' if magic in fat_magics[1::2] else 'IIIII')
        stride = struct.calcsize(layout)
        if not 1 <= count <= 64:
            raise ValueError('IPA 的 Mach-O 架构表无效。')
        table = stream.read(count * stride)
        if len(table) != count * stride:
            raise ValueError('IPA 的 Mach-O 架构表不完整。')
        cpus = []
        for cpu, _, offset, length, *_ in struct.iter_unpack(layout, table):
            if offset < 8 + len(table) or length < 8 or offset + length > size:
                raise ValueError('IPA 的 Mach-O 架构偏移无效。')
            cpus.append(cpu)
    else:
        raise ValueError('IPA 的主程序不是可识别的 Mach-O 文件。')
    architectures = tuple(sorted({ARM_TYPES[cpu] for cpu in cpus if cpu in ARM_TYPES}))
    if not architectures:
        raise ValueError('IPA 不包含 ARM 或 ARM64 程序。')
    return architectures


def inspect_ipa(path):
    path = Path(path).resolve()
    if path.suffix.lower() != '.ipa':
        raise ValueError('请选择 .ipa 安装包。')
    try:
        with ZipFile(path) as archive:
            manifests = [item for item in archive.infolist()
                         if re.fullmatch(r'Payload/[^/]+\.app/Info\.plist', item.filename)]
            if len(manifests) != 1 or manifests[0].file_size > 2 * 1024 * 1024:
                raise ValueError('IPA 应包含一个 Payload 下的应用及其 Info.plist。')
            manifest = manifests[0]
            info = plistlib.loads(archive.read(manifest))
            if not isinstance(info, dict):
                raise ValueError('Info.plist 格式无效。')
            bundle_id = info.get('CFBundleIdentifier')
            executable = info.get('CFBundleExecutable')
            if not isinstance(bundle_id, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.-]{0,254}', bundle_id):
                raise ValueError('IPA 缺少有效的 Bundle ID。')
            if not isinstance(executable, str) or not executable or executable in {'.', '..'} or any(c in executable for c in '/\\\x00'):
                raise ValueError('IPA 缺少有效的主程序名称。')
            main = archive.getinfo(manifest.filename.rsplit('/', 1)[0] + '/' + executable)
            with archive.open(main) as stream:
                architectures = read_architectures(stream, main.file_size)
            name = info.get('CFBundleDisplayName') or info.get('CFBundleName') or bundle_id
            version = info.get('CFBundleShortVersionString') or info.get('CFBundleVersion') or ''
            return App(bundle_id, str(name), str(version), str(info.get('MinimumOSVersion') or ''), architectures, path)
    except (BadZipFile, ExpatError, KeyError, plistlib.InvalidFileException, RuntimeError, OverflowError) as error:
        raise ValueError('无法读取 IPA 的应用信息。') from error


class Library:
    def __init__(self, root=APP_ROOT):
        self.root = Path(root).resolve()
        self.packages = self.root / 'packages'
        self.packages.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS apps '
                       '(bundle_id TEXT PRIMARY KEY, name TEXT, version TEXT, minimum_os TEXT, arch TEXT, package TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)')

    def connect(self):
        return sqlite3.connect(self.root / 'library.sqlite3')

    def from_row(self, row):
        return App(*row[:4], tuple(row[4].split(',')), self.packages / row[5])

    def apps(self):
        with closing(self.connect()) as db:
            return [self.from_row(row) for row in db.execute('SELECT * FROM apps ORDER BY name COLLATE NOCASE, bundle_id')]

    def get(self, bundle_id):
        with closing(self.connect()) as db:
            row = db.execute('SELECT * FROM apps WHERE bundle_id=?', (bundle_id,)).fetchone()
        if row is None:
            raise ValueError(f'应用库里没有 {bundle_id}。')
        return self.from_row(row)

    def add(self, source):
        source = Path(source)
        if source.suffix.lower() != '.ipa':
            raise ValueError('请选择 .ipa 安装包。')
        digest = hashlib.sha256()
        with tempfile.NamedTemporaryFile(dir=self.packages, suffix='.ipa', delete=False) as out:
            temporary = Path(out.name)
        try:
            with source.open('rb') as incoming, temporary.open('wb') as out:
                for chunk in iter(lambda: incoming.read(1024 * 1024), b''):
                    digest.update(chunk)
                    out.write(chunk)
            app = inspect_ipa(temporary)
            package = digest.hexdigest() + '.ipa'
            target = self.packages / package
            with closing(self.connect()) as db, db:
                db.execute('BEGIN IMMEDIATE')
                if not target.exists():
                    temporary.replace(target)
                db.execute('INSERT OR REPLACE INTO apps VALUES (?, ?, ?, ?, ?, ?)',
                           (app.bundle_id, app.name, app.version, app.minimum_os, ','.join(app.architectures), package))
            return self.get(app.bundle_id)
        finally:
            temporary.unlink(missing_ok=True)

    def setting(self, key, default=''):
        with closing(self.connect()) as db:
            row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return row[0] if row else default

    def set_setting(self, key, value):
        with closing(self.connect()) as db, db:
            db.execute('INSERT OR REPLACE INTO settings VALUES (?, ?)', (key, str(value)))

    def display_mode(self, app):
        return self.setting(f'display:{app.bundle_id}', 'window')

    def save_display_mode(self, app, mode):
        if app.modern or not isinstance(mode, str) or mode not in DISPLAY_OPTIONS:
            raise ValueError('请选择有效的 touchHLE 显示方式。')
        self.set_setting(f'display:{app.bundle_id}', mode)
        return mode

    def touchhle(self):
        selected = self.setting('touchhle')
        if selected:
            return Path(selected)
        return next((self.root / 'runtime').rglob('touchHLE.exe'), None)

    def asoftware(self):
        selected = self.setting('asoftware')
        if not selected:
            raise ValueError('请在设置中选择 ASoftware iOS 16 安装目录。')
        return ASoftware(Path(selected), self.setting('asoftware_work'))


def touchhle_command(executable, app, display_mode='window'):
    if 'arm' not in app.architectures:
        raise ValueError('touchHLE 运行早期 32 位应用，此安装包需要 64 位运行时。')
    if executable is None or not executable.is_file():
        raise ValueError('请在设置中选择 touchHLE.exe。')
    if not app.path.is_file():
        raise ValueError('找不到应用库中的 IPA，请重新导入。')
    if display_mode not in DISPLAY_OPTIONS:
        raise ValueError('请选择有效的 touchHLE 显示方式。')
    return [str(executable), str(app.path), *DISPLAY_OPTIONS[display_mode]]


def start_legacy(library, app):
    executable = library.touchhle()
    command = touchhle_command(executable, app, library.display_mode(app))
    with tempfile.NamedTemporaryFile(dir=library.root, prefix='touchhle-', suffix='.log', delete=False) as output:
        log = Path(output.name)
        process = subprocess.Popen(command, cwd=executable.parent, stdout=output, stderr=subprocess.STDOUT,
                                   creationflags=NO_CONSOLE)
    return process, log


def powershell_exe():
    return str(Path(os.environ.get('SystemRoot', r'C:\Windows')) / 'System32' / 'WindowsPowerShell' / 'v1.0' / 'powershell.exe')


class ASoftware:
    def __init__(self, home, work=''):
        self.home = Path(home).resolve()
        self.launch_script = self.home / 'scripts' / 'run-windows.ps1'
        if not self.launch_script.is_file() or not (self.home / 'Start-iOS.cmd').is_file():
            raise ValueError('该目录中未找到 ASoftware iOS 16 的启动脚本。')
        self.work = Path(work).resolve() if work else self.home / 'work'
        self.queue = self.work / 'ipa'

    def status(self, app):
        name = app.path.name
        if (self.queue / name).is_file():
            return '等待安装', ''
        for folder, status in (('Installed', '已安装'), ('Failed', '安装失败')):
            result = self.queue / folder / name
            if result.is_file():
                log = result.with_suffix('.ipa.log')
                message = log.read_text(encoding='utf-8', errors='replace').strip() if log.is_file() else ''
                return status, message
        return '未提交', ''

    def enqueue(self, app):
        if not app.modern:
            raise ValueError('ASoftware iOS 16 需要包含 ARM64 主程序的 IPA。')
        destination = self.queue / app.path.name
        status, _ = self.status(app)
        if status == '已安装':
            return self.queue / 'Installed' / destination.name
        if status == '等待安装':
            return destination
        self.queue.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=self.queue, suffix='.pending', delete=False) as out:
            temporary = Path(out.name)
        try:
            shutil.copyfile(app.path, temporary)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        return destination

    def start(self, log):
        command = [powershell_exe(), '-NoProfile', '-ExecutionPolicy', 'RemoteSigned', '-File',
                   str(self.launch_script), '-Persist', '-Work', str(self.work), '-IpaDir', str(self.queue)]
        with log.open('ab') as output:
            return subprocess.Popen(command, cwd=self.home, stdout=output, stderr=subprocess.STDOUT,
                                    creationflags=NO_CONSOLE)


def create_shortcut(library, app):
    if app.modern:
        raise ValueError('ASoftware iOS 16 需要在虚拟机内打开应用。')
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', app.name).strip(' .')[:60] or 'iOS App'
    suffix = hashlib.sha256(app.bundle_id.encode()).hexdigest()[:8]
    pythonw = Path(sys.executable).with_name('pythonw.exe')
    target = pythonw if pythonw.is_file() else Path(sys.executable)
    args = subprocess.list2cmdline([str(SCRIPT), '--data-dir', str(library.root), '--launch', app.bundle_id])
    environment = dict(os.environ, IPARUNNER_NAME=f'{name} (IPA Runner {suffix}).lnk',
                       IPARUNNER_TARGET=str(target), IPARUNNER_ARGS=args,
                       IPARUNNER_ICON=str(library.touchhle() or target))
    script = ('$ErrorActionPreference = "Stop"\n'
              '$shell = New-Object -ComObject WScript.Shell\n'
              '$link = $shell.CreateShortcut((Join-Path $shell.SpecialFolders.Item("Desktop") $env:IPARUNNER_NAME))\n'
              '$link.TargetPath = $env:IPARUNNER_TARGET\n'
              '$link.Arguments = $env:IPARUNNER_ARGS\n'
              '$link.IconLocation = $env:IPARUNNER_ICON + ",0"\n'
              '$link.Save()')
    subprocess.run([powershell_exe(), '-NoProfile', '-NonInteractive', '-Command', script], env=environment,
                   creationflags=NO_CONSOLE, check=True, capture_output=True)
    return environment['IPARUNNER_NAME']


def main():
    parser = argparse.ArgumentParser(description='Windows IPA Runner')
    parser.add_argument('--data-dir', type=Path, default=APP_ROOT)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument('--import', dest='import_path', type=Path)
    actions.add_argument('--launch', metavar='BUNDLE_ID')
    actions.add_argument('--shortcut', metavar='BUNDLE_ID')
    args = parser.parse_args()
    try:
        library = Library(args.data_dir)
        if args.import_path:
            app = library.add(args.import_path)
            print(f'{app.name} | {app.bundle_id} | {app.version} | {", ".join(app.architectures)}')
        elif args.launch:
            process, log = start_legacy(library, library.get(args.launch))
            try:
                if process.wait(timeout=2) != 0:
                    raise ValueError(f'touchHLE 启动失败。日志位于 {log}')
            except subprocess.TimeoutExpired:
                pass
        elif args.shortcut:
            print(create_shortcut(library, library.get(args.shortcut)))
        else:
            from runner_ui import run
            run(library)
        return 0
    except (OSError, ValueError, sqlite3.Error, subprocess.SubprocessError) as error:
        if sys.stderr is not None:
            print(str(error), file=sys.stderr)
        else:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(error), 'IPA Runner', 0x10)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
