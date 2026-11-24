"""Image-free runtime management. External environments always remain user-owned."""
import ctypes
import hashlib
import json
import os
import re
import shutil
import sqlite3
import socket
import subprocess
import tempfile
import time
import uuid
from contextlib import closing, contextmanager
from pathlib import Path
from types import SimpleNamespace
from zipfile import BadZipFile, ZipFile

from ipa_runner import ASoftware, inspect_ipa, powershell_exe, NO_CONSOLE
from runtime_inspector import inspect_environment

PLATFORMS = {'android': '.apk', 'ios': '.ipa', 'openharmony': '.hap'}
IDENTIFIER = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,254}\Z')


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def port_open(port):
    with socket.socket() as connection:
        connection.settimeout(.3)
        return connection.connect_ex(('127.0.0.1', port)) == 0


def process_identity(pid):
    """Return a process creation token, preventing PID reuse from targeting other apps."""
    if not pid:
        return ''
    if os.name != 'nt':
        try:
            return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
        except OSError:
            return ''
    from ctypes import wintypes
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return ''
    try:
        code = wintypes.DWORD()
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:
            return ''
        values = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in values)):
            return ''
        return str((values[0].dwHighDateTime << 32) | values[0].dwLowDateTime)
    finally:
        kernel.CloseHandle(handle)


class SystemManager:
    def __init__(self, root):
        self.root = Path(root) / 'systems'
        self.root.mkdir(parents=True, exist_ok=True)
        self.database = self.root / 'systems.sqlite'
        self.children = {}
        with closing(self.connect()) as db, db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS instances (id TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS packages (id TEXT PRIMARY KEY, instance TEXT NOT NULL, data TEXT NOT NULL);
            ''')

    def connect(self):
        return sqlite3.connect(self.database, timeout=20)

    def items(self, table):
        with closing(self.connect()) as db:
            return [json.loads(row[0]) for row in db.execute(f'SELECT data FROM {table} ORDER BY rowid')]

    def get(self, instance_id):
        return next((item for item in self.items('instances') if item['id'] == instance_id), None) or self.missing()

    @staticmethod
    def missing():
        raise ValueError('找不到该系统实例，请刷新列表。')

    def save(self, item):
        with closing(self.connect()) as db, db:
            db.execute('INSERT OR REPLACE INTO instances VALUES (?, ?)', (item['id'], json.dumps(item)))
        return item

    def snapshot(self):
        instances = self.items('instances')
        for item in instances:
            item['state'] = '运行中' if self.running(item) else '已停止'
            item['log'] = str(self.log_path(item))
            try:
                item['freeBytes'] = shutil.disk_usage(item['home']).free
            except OSError:
                item['freeBytes'] = None
        packages = self.items('packages')
        for app in packages:
            item = next((x for x in instances if x['id'] == app['instance']), None)
            if item and item['platform'] == 'ios' and app.get('queueName'):
                try:
                    app['state'], app['detail'] = ASoftware(Path(item['home']), item['work']).status(
                        SimpleNamespace(path=Path(app['queueName'])))
                except (ValueError, OSError) as error:
                    app['detail'] = str(error)
        return {'instances': instances, 'packages': packages}

    @staticmethod
    def running(item):
        return bool(item.get('token') and process_identity(item.get('pid')) == item['token'])

    @staticmethod
    def require_file(path):
        path = Path(path)
        if not path.is_file():
            raise ValueError(f'缺少文件：{path}。请按下载说明准备完整运行环境。')
        return str(path)

    def validate(self, item):
        home = Path(item['home'])
        if item['platform'] == 'android':
            self.require_file(home / 'emulator' / 'emulator.exe')
            self.require_file(home / 'platform-tools' / 'adb.exe')
        elif item['platform'] == 'ios':
            ASoftware(home, item['work'])
        else:
            for name in ('run.bat', 'run.sh', 'bzImage', 'ramdisk.img', 'updater.img', 'system.img', 'vendor.img', 'userdata.img'):
                self.require_file(home / name)
            self.require_file(item['tool'])

    def create(self, values):
        with self.operation_lock():
            return self._create(values)

    def _create(self, values):
        if values.get('guided'):
            report = inspect_environment(values)
            if not report['canCreate']:
                raise ValueError('；'.join(c['message'] for c in report['checks'] if c['level'] == 'error'))
            values = dict(report['values'], guided=True)
        platform = values.get('platform')
        if platform not in PLATFORMS:
            raise ValueError('请选择 Android、iOS 或 OpenHarmony。')
        name = str(values.get('name', '')).strip()
        if not name or len(name) > 80:
            raise ValueError('请输入 1～80 字的实例名称。')
        if not values.get('home'):
            raise ValueError('请选择已下载并解压的运行环境目录。')
        home = str(Path(values['home']).resolve())
        try:
            memory, cpus = int(values.get('memory', 4096)), int(values.get('cpus', 4))
        except (ValueError, TypeError):
            raise ValueError('内存和 CPU 必须为整数。') from None
        if not 1024 <= memory <= 65536 or not 1 <= cpus <= 32:
            raise ValueError('内存范围为 1024～65536 MB，CPU 范围为 1～32 核。')
        others = self.items('instances')
        item = dict(id=uuid.uuid4().hex, platform=platform, name=name, home=home,
                    memory=memory, cpus=cpus, pid=0, token='', tool='', target='', device='', work='')
        if values.get('guided'):
            item.update(guided=True, version=report['version'], architecture=report['architecture'])
            for key in ('avdHome', 'runtimeQemu', 'kernel', 'disk', 'extraPaths'):
                if values.get(key):
                    item[key] = values[key]
        if platform == 'android':
            target = str(values.get('target', '')).strip()
            if not IDENTIFIER.fullmatch(target):
                raise ValueError('请输入有效 AVD 名称，只能包含字母、数字、点、下划线和连字符。')
            if any(x['platform'] == platform and x['target'] == target for x in others):
                raise ValueError('该 AVD 已添加，请为另一个实例创建独立 AVD。')
            port = next(p for p in range(5554, 5682, 2) if f'emulator-{p}' not in {x['device'] for x in others})
            item.update(target=target, device=f'emulator-{port}')
        elif platform == 'openharmony':
            index = next((i for i in range(1, 100) if not any(x['platform'] == platform and
                         x['target'] == str(i) for x in others)), None)
            if index is None:
                raise ValueError('OpenHarmony 实例数量已达到 99 个上限。')
            tool = Path(values.get('tool') or home + '/hdc.exe').resolve()
            if tool.name.lower() != 'hdc.exe':
                raise ValueError('请选择 OpenHarmony SDK 中的 hdc.exe。')
            item.update(tool=str(tool), target=str(index), device=f'127.0.0.1:{55555 + index}')
        else:
            # ASoftware's base work tree contains the prepared guest disks; do not create blank copies.
            work = str(Path(values.get('work') or Path(home) / 'work').resolve())
            if any(x['platform'] == platform and x['work'].casefold() == work.casefold() for x in others):
                raise ValueError('该 iOS 数据目录已被实例使用。请选择另一套已部署环境。')
            item.update(work=work)
        self.validate(item)
        return self.save(item)

    def log_path(self, item):
        return self.root / (item['id'] + '.log')

    def remove(self, instance_id):
        with self.operation_lock():
            return self._remove(instance_id)

    def _remove(self, instance_id):
        item = self.get(instance_id)
        if self.running(item):
            raise ValueError('请先关闭系统，再移除管理记录。')
        with closing(self.connect()) as db, db:
            db.execute('DELETE FROM packages WHERE instance=?', (instance_id,))
            db.execute('DELETE FROM instances WHERE id=?', (instance_id,))

    def start_command(self, item):
        home = Path(item['home'])
        if item['platform'] == 'android':
            return [str(home / 'emulator' / 'emulator.exe'), '-avd', item['target'], '-port',
                    item['device'].split('-')[1], '-memory', str(item['memory']), '-cores', str(item['cpus']),
                    '-no-snapshot', '-no-boot-anim']
        if item['platform'] == 'ios':
            runtime = ASoftware(home, item['work'])
            args = [powershell_exe(), '-NoProfile', '-ExecutionPolicy', 'RemoteSigned', '-File',
                    str(runtime.launch_script), '-Persist', '-Work', str(runtime.work), '-IpaDir', str(runtime.queue)]
            for key, flag in (('runtimeQemu', '-Qemu'), ('kernel', '-Kernel'), ('disk', '-Disk')):
                if item.get(key):
                    args.extend([flag, item[key]])
            return args
        # Fixed script name and validated numeric arguments; never interpolate a user path into cmd code.
        return [os.environ.get('COMSPEC', 'cmd.exe'), '/d', '/c', 'run.bat', '--instance', item['target'],
                '-m', f'{item["memory"]}M', '-s', str(item['cpus'])]

    def command(self, item, args, timeout=30):
        result = subprocess.run(args, cwd=item['home'], capture_output=True, encoding='utf-8', errors='replace',
                                timeout=timeout, creationflags=NO_CONSOLE, env=self.environment(item))
        output = (result.stdout + '\n' + result.stderr).strip()
        with self.log_path(item).open('a', encoding='utf-8') as log:
            log.write(f'\n[{time.strftime("%Y-%m-%d %H:%M:%S")}] {Path(args[0]).name}\n{output}\n')
        if result.returncode:
            raise ValueError(output[-2000:] or '操作失败，请查看实例日志。')
        return output

    @staticmethod
    def environment(item):
        env = dict(os.environ)
        if item.get('extraPaths'):
            env['PATH'] = os.pathsep.join(item['extraPaths']) + os.pathsep + env.get('PATH', '')
        if item.get('avdHome') and item['platform'] == 'android':
            env['ANDROID_AVD_HOME'] = item['avdHome']
        return env

    def start(self, instance_id):
        with self.operation_lock():
            return self._start(instance_id)

    @contextmanager
    def operation_lock(self):
        # Cross-process serialization: bridge requests each run in a separate Python process.
        with (self.root / 'operation.lock').open('a+b') as lock:
            if os.name == 'nt':
                import msvcrt
                if lock.seek(0, 2) == 0:
                    lock.write(b'0')
                    lock.flush()
                lock.seek(0)
                msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == 'nt':
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock, fcntl.LOCK_UN)

    def _start(self, instance_id):
        item = self.get(instance_id)
        if self.running(item):
            return item
        self.validate(item)
        if item.get('guided'):
            report = inspect_environment(item)
            if not report['canCreate']:
                raise ValueError('启动前检查未通过：' + '；'.join(c['message'] for c in report['checks'] if c['level'] == 'error'))
            for key in ('runtimeQemu', 'kernel', 'disk', 'extraPaths'):
                if report['values'].get(key):
                    item[key] = report['values'][key]
        if item['platform'] != 'ios':
            ports = [int(item['device'].split('-')[1]), int(item['device'].split('-')[1]) + 1] if item['platform'] == 'android' else [int(item['device'].split(':')[1])]
            if any(port_open(port) for port in ports):
                raise ValueError('实例设备端口已被外部运行环境占用，请先关闭冲突的模拟器。')
        if item['platform'] == 'ios':
            if any(x['platform'] == 'ios' and self.running(x) for x in self.items('instances')):
                raise ValueError('ASoftware 当前只能运行一个 iOS 实例。请先关闭其他 iOS 实例。')
            for port in (4445, 8765):
                if port_open(port):
                    raise ValueError(f'iOS 运行端口 {port} 已占用。请先关闭外部 iOS 运行环境。')
        if item['platform'] == 'android':
            available = self.command(item, [str(Path(item['home']) / 'emulator' / 'emulator.exe'), '-list-avds'])
            if item['target'] not in available.splitlines():
                raise ValueError('找不到该 AVD。请先在 Android Studio 的设备管理器中下载镜像并创建虚拟设备。')
        with self.log_path(item).open('ab') as log:
            process = subprocess.Popen(self.start_command(item), cwd=item['home'], stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT, creationflags=NO_CONSOLE, env=self.environment(item))
        token = process_identity(process.pid)
        try:
            code = process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            item.update(pid=process.pid, token=token)
            self.children[process.pid] = process
            return self.save(item)
        raise ValueError(f'启动程序提前结束（退出码 {code}），请查看实例日志。')

    def stop(self, instance_id):
        with self.operation_lock():
            return self._stop(instance_id)

    def _stop(self, instance_id):
        item = self.get(instance_id)
        if self.running(item):
            if os.name != 'nt':
                raise ValueError('关闭系统进程目前仅支持 Windows。')
            self.command(item, ['taskkill.exe', '/PID', str(item['pid']), '/T', '/F'])
            child = self.children.pop(item['pid'], None)
            if child:
                child.wait(timeout=5)
            if self.running(item):
                raise ValueError('系统尚未关闭，请查看日志。')
        item.update(pid=0, token='')
        self.save(item)

    def device_command(self, item, args):
        tool = str(Path(item['home']) / 'platform-tools' / 'adb.exe') if item['platform'] == 'android' else item['tool']
        return [tool, '-s' if item['platform'] == 'android' else '-t', item['device'], *args]

    def ready(self, item):
        if item['platform'] == 'ios':
            return
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            if not self.running(item):
                raise ValueError('系统进程已退出，请查看实例日志。')
            try:
                if item['platform'] == 'openharmony':
                    self.command(item, [item['tool'], 'tconn', item['device']], timeout=8)
                probe = ['shell', 'getprop', 'sys.boot_completed'] if item['platform'] == 'android' else ['shell', 'echo', 'runner-ready']
                out = self.command(item, self.device_command(item, probe), timeout=8)
                if (item['platform'] == 'android' and out.strip() == '1') or out.strip() == 'runner-ready':
                    return
            except (ValueError, subprocess.TimeoutExpired):
                pass
            time.sleep(2)
        raise ValueError('系统仍未就绪，请等待引导完成后重试。详细信息见实例日志。')

    def probe(self, instance_id):
        item = self.get(instance_id)
        if not self.running(item):
            return dict(state='stopped', message='系统进程已停止，请查看日志。')
        if item['platform'] == 'ios':
            return dict(state='unverified', message='iOS 进程运行中，请在系统窗口确认锁屏或桌面；未验证设备就绪。')
        try:
            if item['platform'] == 'openharmony':
                self.command(item, [item['tool'], 'tconn', item['device']], timeout=5)
            probe = ['shell', 'getprop', 'sys.boot_completed'] if item['platform'] == 'android' else ['shell', 'echo', 'runner-ready']
            output = self.command(item, self.device_command(item, probe), timeout=5)
            ready = output.strip() == ('1' if item['platform'] == 'android' else 'runner-ready')
            return dict(state='ready' if ready else 'booting', message='目标设备已就绪。' if ready else '系统正在引导，设备尚未就绪。')
        except (ValueError, OSError, subprocess.SubprocessError):
            return dict(state='booting', message='系统进程运行中，设备尚未连接，请稍后重试。')

    def import_package(self, instance_id, path):
        item = self.get(instance_id)
        path = Path(path).resolve()
        if path.suffix.lower() != PLATFORMS[item['platform']]:
            raise ValueError(f'此实例只接受 {PLATFORMS[item["platform"]]} 安装包。')
        self.require_file(path)
        bundle, ability, name = '', '', path.stem
        if item['platform'] == 'ios':
            app = inspect_ipa(path)
            if not app.modern:
                raise ValueError('此 iOS 实例需要 ARM64 IPA；早期 IPA 请使用原应用库的 touchHLE。')
            bundle, name = app.bundle_id, app.name
        elif item['platform'] == 'android':
            tools = sorted((Path(item['home']) / 'build-tools').glob('*/aapt2.exe'),
                           key=lambda p: tuple(int(x) for x in re.findall(r'\d+', p.parent.name)), reverse=True)
            if not tools:
                raise ValueError('请通过 Android SDK Manager 安装 Build-Tools（需要 aapt2.exe）。')
            output = self.command(item, [str(tools[0]), 'dump', 'badging', str(path)])
            match = re.search(r"package: name='([^']+)'", output)
            bundle = match[1] if match else ''
        else:
            try:
                with ZipFile(path) as archive:
                    entry = archive.getinfo('module.json')
                    if entry.file_size > 2 * 1024 * 1024:
                        raise ValueError('HAP 模块信息过大。')
                    info = json.loads(archive.read(entry))
                    bundle = info.get('app', {}).get('bundleName', '')
                    ability = info.get('module', {}).get('mainElement', '')
            except (BadZipFile, KeyError, json.JSONDecodeError, UnicodeError, AttributeError) as error:
                raise ValueError('无法读取 HAP 的 module.json；请选择完整 Stage 模型 HAP。') from error
        if not isinstance(bundle, str) or not IDENTIFIER.fullmatch(bundle):
            raise ValueError('安装包缺少有效应用标识。')
        if ability and (not isinstance(ability, str) or not IDENTIFIER.fullmatch(ability)):
            raise ValueError('HAP 的启动 Ability 名称无效。')
        digest = file_digest(path)
        key = hashlib.sha256(f'{instance_id}/{bundle}'.encode()).hexdigest()
        app = dict(id=key, instance=instance_id, bundleId=bundle, name=name, ability=ability,
                   path=str(path), sha256=digest, state='未安装')
        self.save_package(app)
        return app

    def save_package(self, app):
        with closing(self.connect()) as db, db:
            db.execute('INSERT OR REPLACE INTO packages VALUES (?, ?, ?)',
                       (app['id'], app['instance'], json.dumps(app)))

    def install(self, package_id, launch=False):
        app = next((x for x in self.items('packages') if x['id'] == package_id), None)
        if not app:
            raise ValueError('找不到应用记录。')
        item = self.get(app['instance'])
        path = Path(self.require_file(app['path']))
        if file_digest(path) != app['sha256']:
            raise ValueError('安装包已改变，请重新导入。')
        if item['platform'] == 'ios':
            runtime = ASoftware(Path(item['home']), item['work'])
            app['queueName'] = app['sha256'] + '.ipa'
            submission = SimpleNamespace(path=Path(app['queueName']))
            if runtime.status(submission)[0] not in ('等待安装', '已安装'):
                runtime.queue.mkdir(parents=True, exist_ok=True)
                if shutil.disk_usage(runtime.queue).free < path.stat().st_size + 64 * 1024 * 1024:
                    raise ValueError('iOS 安装队列所在磁盘空间不足。')
                with tempfile.NamedTemporaryFile(dir=runtime.queue, suffix='.pending', delete=False) as output:
                    pending = Path(output.name)
                try:
                    shutil.copyfile(path, pending)
                    pending.replace(runtime.queue / app['queueName'])
                finally:
                    pending.unlink(missing_ok=True)
            app['state'] = runtime.status(submission)[0]
            self.save_package(app)
            if not self.running(item):
                self.start(item['id'])
            return '已提交 IPA，请在 iOS 桌面查看安装结果并打开应用。'
        if not self.running(item):
            item = self.start(item['id'])
        self.ready(item)
        if app['state'] != '已安装':
            args = ['install', '-r', str(path)] if item['platform'] == 'android' else ['install', str(path)]
            output = self.command(item, self.device_command(item, args), timeout=120)
            if not re.search(r'\bsuccess\b|successfully', output, re.I) or re.search(r'\bfail(?:ed|ure)?\b', output, re.I):
                raise ValueError(f'设备未确认安装成功：{output[-1500:]}')
            app['state'] = '已安装'
            self.save_package(app)
        if launch:
            if item['platform'] == 'android':
                args = ['shell', 'monkey', '-p', app['bundleId'], '-c', 'android.intent.category.LAUNCHER', '1']
            else:
                if not app['ability']:
                    return '已安装，未找到主 Ability，请从系统桌面启动。'
                args = ['shell', 'aa', 'start', '-b', app['bundleId'], '-a', app['ability']]
            output = self.command(item, self.device_command(item, args))
            if re.search(r'error|failed|no activities|aborted', output, re.I):
                raise ValueError(output[-1500:])
            return '已发送应用启动请求。'
        return '应用已安装。'
