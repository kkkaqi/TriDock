"""Read-only discovery and bounded extraction of user-supplied runtime environments."""
import ctypes
import os
import platform
import re
import shutil
import stat
import tempfile
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile

MIB = 1024**2
GIB = 1024**3
ONIRO_FILES = ('run.bat', 'run.sh', 'bzImage', 'ramdisk.img', 'updater.img', 'system.img', 'vendor.img', 'userdata.img')
CATALOG = [
    dict(id='android', name='Android · SDK Emulator', compatibility='Android SDK 的 x86/x86_64 AVD；API 版本从本地配置读取',
         source='https://developer.android.com/studio/run/managing-avds',
         instructions='使用 Android Studio 的 SDK Manager 下载 Emulator、Platform-Tools、Build-Tools 和系统镜像，再在 Device Manager 创建虚拟设备。导入 SDK 根目录即可自动列出设备。'),
    dict(id='ios', name='iOS 16 · ASoftware', compatibility='ASoftware iOS 16 已部署环境；完整部署后导入，应用兼容性需单独验证',
         source='https://github.com/alpersamur3/asoft-ios',
         instructions='下载 ASoftware 并按其说明完成 iOS 16 部署，再导入包含 Start-iOS.cmd 的目录。单独 IPSW 和尚未部署系统盘的源码包不能直接启动。'),
    dict(id='openharmony', name='OpenHarmony · Oniro x86_64', compatibility='Oniro x86_64 完整模拟器镜像包；不含商业 HarmonyOS NEXT 兼容承诺',
         source='https://docs.oniroproject.org/device-development/developer-boards/emulator/',
         instructions='下载 x86_64 预构建镜像。安装 QEMU、Git Bash/MSYS2 和 OpenHarmony SDK，并启用 Windows Hypervisor Platform。选择 images 目录或下载好的 ZIP。'),
]


def host_info():
    result = dict(architecture=platform.machine(), cpus=os.cpu_count() or 1,
                  totalMemory=None, availableMemory=None, virtualization=None)
    if os.name == 'nt':
        class Memory(ctypes.Structure):
            _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [
                (name, ctypes.c_ulonglong) for name in ('total', 'available', 'page', 'availablePage', 'virtual', 'availableVirtual', 'extended')]
        memory = Memory()
        memory.length = ctypes.sizeof(memory)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(memory)):
            result.update(totalMemory=memory.total, availableMemory=memory.available)
        try:
            hypervisor = ctypes.WinDLL('WinHvPlatform.dll')
            present, written = ctypes.c_uint32(), ctypes.c_uint32()
            if hypervisor.WHvGetCapability(0, ctypes.byref(present), 4, ctypes.byref(written)) == 0:
                result['virtualization'] = bool(present.value)
        except (OSError, AttributeError):
            pass
    return result


def read_ini(path):
    path = Path(path)
    if not path.is_file() or path.stat().st_size > MIB:
        return {}
    return dict(line.split('=', 1) for raw in path.read_text(encoding='utf-8-sig', errors='replace').splitlines()
                if (line := raw.strip()) and '=' in line and not line.startswith(('#', ';')))


def roots_under(root):
    """Only inspect a bounded directory tree. Never search whole drives or follow child links."""
    if not root.is_dir():
        return []
    found, pending = [root], [(root, 0)]
    while pending and len(found) < 2000:
        folder, depth = pending.pop(0)
        if depth >= 3:
            continue
        try:
            for child in folder.iterdir():
                if child.is_dir() and not child.is_symlink() and child.name not in ('node_modules', '.git'):
                    found.append(child)
                    pending.append((child, depth + 1))
                    if len(found) >= 2000:
                        break
        except OSError:
            continue
    return found


def detect_root(source, selected):
    matches = []
    for root in roots_under(source):
        detected = 'android' if (root / 'emulator' / 'emulator.exe').is_file() else (
            'ios' if (root / 'Start-iOS.cmd').is_file() else (
                'openharmony' if (root / 'run.bat').is_file() and ((root / 'bzImage').is_file() or (root / 'Image').is_file()) else ''))
        if detected:
            matches.append((detected, root))
    preferred = [pair for pair in matches if pair[0] == selected]
    if len(preferred) > 1:
        raise ValueError('目录内发现多套运行环境，请直接选择要导入的那一套目录。')
    return preferred[0] if preferred else (matches[0] if len(matches) == 1 else (selected, source))


def avd_directory():
    if os.environ.get('ANDROID_AVD_HOME'):
        return Path(os.environ['ANDROID_AVD_HOME'])
    base = Path(os.environ.get('ANDROID_USER_HOME') or Path.home() / '.android')
    return base / 'avd'


def android_devices(sdk, directory=None):
    directory = Path(directory) if directory else avd_directory()
    devices = []
    if not directory.is_dir():
        return devices
    for path in sorted(directory.glob('*.ini'))[:200]:
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,254}', path.stem):
            continue
        meta = read_ini(path)
        folder = Path(meta['path']) if meta.get('path') else directory.parent / meta.get('path.rel', path.stem + '.avd')
        if not folder.is_absolute():
            folder = directory.parent / folder
        config = read_ini(folder / 'config.ini')
        image = Path(config.get('image.sysdir.1', ''))
        if not image.is_absolute():
            image = sdk / image
        match = re.search(r'android-(\d+)', str(image))
        image_files = [image / 'system.img', image / 'ramdisk.img']
        kernel = next((image / name for name in ('kernel-ranchu', 'kernel-qemu') if (image / name).is_file()), None)
        complete = bool(config and kernel and kernel.stat().st_size > 0 and
                        all(p.is_file() and p.stat().st_size > 0 for p in image_files))
        devices.append(dict(name=path.stem, path=str(folder.resolve()), architecture=config.get('abi.type', '未知'),
                            version=f'Android API {match[1]}' if match else '未知（配置未声明 API）',
                            image=str(image.resolve()), complete=complete))
    return devices


def local_executable(name, fallbacks=()):
    found = shutil.which(name)
    if found:
        return Path(found)
    return next((Path(p) for p in fallbacks if Path(p).is_file() and Path(p).stat().st_size > 0), None)


def inspect_environment(values):
    selected = values.get('platform', '')
    if selected not in {item['id'] for item in CATALOG}:
        raise ValueError('请选择系统平台。')
    if not values.get('home'):
        raise ValueError('请选择下载好的运行环境目录。')
    source = Path(values['home']).resolve()
    if source.is_file():
        raise ValueError('请选择完整运行环境目录，或先使用 ZIP 导入。单独 IMG、ISO、IPSW 暂不能直接导入。')
    detected, home = detect_root(source, selected)
    result = dict(platform=detected, architecture='未知', version='未知（文件未声明版本）',
                  values=dict(values, platform=detected, home=str(home)), checks=[], devices=[],
                  host=host_info(), bootVerified=False, requiredBytes=0, recommendedBytes=4 * GIB)
    checks = result['checks']
    storage = home
    def check(ok, title, detail, level='error'):
        checks.append(dict(level='pass' if ok else level, title=title, message=detail))
    check(home.is_dir(), '运行目录', str(home) if home.is_dir() else '所选运行目录不存在。')
    check(detected == selected, '系统类型', f'识别到 {detected}，请切换平台后重新检查。' if detected != selected else f'已识别 {detected} 目录结构。')
    def required(file, title='必要文件'):
        path = Path(file)
        check(path.is_file() and path.stat().st_size > 0, title,
              path.name if path.is_file() and path.stat().st_size > 0 else f'缺失或为空：{path.name}')
    if detected == 'android':
        for name in ('emulator/emulator.exe', 'platform-tools/adb.exe'):
            required(home / name)
        check(any(p.stat().st_size for p in (home / 'build-tools').glob('*/aapt2.exe') if p.is_file()),
              'APK 读取工具', '需要 Android SDK Build-Tools 中的 aapt2.exe。')
        result['values']['avdHome'] = str(Path(values.get('avdHome') or avd_directory()).resolve())
        result['devices'] = android_devices(home, result['values']['avdHome'])
        storage = Path(result['values']['avdHome'])
        result['requiredBytes'] = 256 * MIB
        chosen = next((d for d in result['devices'] if d['name'] == values.get('target')), None)
        if not values.get('target') and result['devices']:
            chosen = result['devices'][0]
        check(bool(chosen), '虚拟设备', '请选择识别到的 AVD；没有设备时，请先在 Android Studio 的 Device Manager 创建。')
        if chosen:
            storage = Path(chosen['path'])
            userdata = Path(chosen['image']) / 'userdata.img'
            if not (storage / 'userdata-qemu.img').is_file() and userdata.is_file():
                result['requiredBytes'] += userdata.stat().st_size
            result['recommendedBytes'] = max(4 * GIB, result['requiredBytes'] + 512 * MIB)
            result['values']['target'] = chosen['name']
            result.update(architecture=chosen['architecture'], version=chosen['version'])
            check(chosen['complete'], '系统镜像', 'AVD 配置及 system.img、ramdisk.img、内核文件存在。' if chosen['complete'] else 'AVD 的系统镜像或内核文件缺失/为空，请在 SDK Manager 补齐后重新检查。')
            check(chosen['architecture'] in ('x86', 'x86_64'), '镜像架构', f'当前适配范围为 x86/x86_64，检测到 {chosen["architecture"]}。')
    elif detected == 'openharmony':
        result['architecture'] = 'arm64' if (home / 'Image').is_file() else 'x86_64'
        for name in ONIRO_FILES:
            required(home / name)
        check(result['architecture'] == 'x86_64', '镜像架构', '需使用 Oniro x86_64 版本；ARM64 版本不在本适配器范围。')
        tool = values.get('tool') or (str(home / 'hdc.exe') if (home / 'hdc.exe').is_file() else shutil.which('hdc.exe'))
        result['values']['tool'] = str(Path(tool).resolve()) if tool else ''
        required(tool or home / 'hdc.exe', '设备连接工具 hdc')
        if tool:
            check(Path(tool).name.lower() == 'hdc.exe', 'HDC 文件名', '请选择 SDK 中的 hdc.exe。')
        programs = Path(os.environ.get('ProgramFiles', 'C:/Program Files'))
        qemu = local_executable('qemu-system-x86_64.exe', [programs / 'qemu/qemu-system-x86_64.exe'])
        bash = local_executable('bash.exe', [programs / 'Git/bin/bash.exe', programs / 'Git/usr/bin/bash.exe', Path('C:/msys64/usr/bin/bash.exe')])
        result['values']['extraPaths'] = list(dict.fromkeys(str(tool.parent) for tool in (qemu, bash) if tool))
        for tool, title in ((qemu, 'QEMU'), (bash, 'Git Bash / MSYS2')):
            check(bool(tool), title, f'已找到：{tool}' if tool else f'需安装 {title} 或将其加入 PATH，重新打开软件后检查。')
        result['requiredBytes'] = sum((home / name).stat().st_size for name in ('userdata.img', 'updater.img') if (home / name).is_file()) + 256 * MIB
        result['recommendedBytes'] = result['requiredBytes'] + 4 * GIB
    else:
        result['architecture'] = 'arm64（CPU 模拟）'
        work = Path(values.get('work') or home / 'work').resolve()
        storage = work
        result['values']['work'] = str(work)
        for name in ('Start-iOS.cmd', 'scripts/run-windows.ps1', 'tools/qemu-sweet.py', 'tools/mkadt.py', 'tools/mkpayload.py'):
            required(home / name)
        kernels = sorted((home / 'xnu').glob('out-*/kernel.development.sweet'))
        kernel = next((p for p in reversed(kernels) if p.stat().st_size > 0), None)
        check(bool(kernel), 'iOS 内核', str(kernel) if kernel else '缺少已构建的 kernel.development.sweet，请先完成 ASoftware 部署。')
        disks = [work / 'root' / name for name in ('ios16-base.qcow2', 'ios16-root-20H392-v5.qcow2')]
        disk = next((p for p in disks if p.is_file() and p.stat().st_size > 0), None)
        check(bool(disk), 'iOS 系统盘', str(disk) if disk else '未找到已部署的 iOS 16 系统盘。请先通过 ASoftware 完成部署。')
        qemus = [work / 'qemu/qemu-system-aarch64.exe', work / 'qemu/v11.1.2-asoft/qemu-system-aarch64.exe', home / 'qemu/bin/qemu-system-aarch64.exe']
        qemu = next((p for p in qemus if p.is_file() and p.stat().st_size > 0), None)
        check(bool(qemu), 'iOS QEMU', str(qemu) if qemu else '缺少 ASoftware 配套的 qemu-system-aarch64.exe。')
        if qemu:
            image_tool = qemu.parent / 'qemu-img.exe'
            fallback = Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'qemu/qemu-img.exe'
            check(any(p.is_file() and p.stat().st_size > 0 for p in (image_tool, fallback)),
                  'iOS 磁盘工具', '需要配套的 qemu-img.exe 创建持久化用户盘。')
        python = home / 'python/python.exe'
        check(python.is_file() and python.stat().st_size > 0, 'iOS Python',
              '需要 ASoftware 配套的 python/python.exe；请通过其安装程序补齐运行依赖。')
        for name, path in (('runtimeQemu', qemu), ('kernel', kernel), ('disk', disk)):
            if path:
                result['values'][name] = str(path)
        result['requiredBytes'] = 256 * MIB
        result['recommendedBytes'] = 4 * GIB
    # Resource checks never execute imported runtime programs.
    host = result['host']
    try:
        memory = int(values.get('memory', 4096))
        cpus = int(values.get('cpus', 4))
    except (ValueError, TypeError):
        memory, cpus = 4096, 4
        check(False, '资源设置', 'CPU 和内存必须是整数。')
    check(1024 <= memory <= 65536 and 1 <= cpus <= 32, '资源范围', '内存 1024～65536 MB，CPU 1～32 核。')
    check(host['architecture'].lower() in ('amd64', 'x86_64'), '电脑架构', f'当前 Windows x64 适配器，电脑架构：{host["architecture"]}。')
    required_memory = 16 * GIB if detected == 'ios' else (memory + 2048) * MIB
    if host['totalMemory'] is not None:
        check(host['totalMemory'] >= required_memory, '物理内存', f'电脑共 {host["totalMemory"] / GIB:.1f} GB；当前配置建议至少 {required_memory / GIB:.1f} GB。')
    else:
        check(False, '物理内存', '无法读取物理内存，请确认电脑满足运行环境要求。', 'warning')
    if host['availableMemory'] is not None:
        check(host['availableMemory'] >= required_memory / 2, '当前可用内存', f'可用 {host["availableMemory"] / GIB:.1f} GB；同时运行其他程序可能降低速度。', 'warning')
    check(cpus <= host['cpus'], 'CPU 分配', f'电脑有 {host["cpus"]} 个逻辑核心，分配 {cpus} 核。', 'warning')
    if detected != 'ios':
        check(host['virtualization'] is True, '虚拟化加速', 'Windows Hypervisor 可用。' if host['virtualization'] else '未确认 Windows Hypervisor 可用，请检查虚拟化和 Windows Hypervisor Platform；系统可能启动失败或较慢。', 'warning')
    result['storagePath'] = str(storage)
    while not storage.exists() and storage.parent != storage:
        storage = storage.parent
    try:
        free = shutil.disk_usage(storage).free
        result['freeBytes'] = free
        check(free >= result['requiredBytes'], '必要磁盘空间', f'磁盘可用 {free / GIB:.2f} GB；首次实例数据至少预留 {result["requiredBytes"] / GIB:.2f} GB（估计值）。')
        check(free >= result['recommendedBytes'], '运行空间建议', f'建议预留 {result["recommendedBytes"] / GIB:.2f} GB，应用、快照和后续数据增长另计。', 'warning')
    except OSError:
        result['freeBytes'] = None
        check(False, '磁盘空间', '无法读取目标磁盘的可用空间。')
    result['canCreate'] = not any(c['level'] == 'error' for c in checks)
    return result


def archive_entries(archive):
    entries = archive.infolist()
    if len(entries) > 50000:
        raise ValueError('ZIP 文件数量过多。')
    seen = set()
    total = 0
    reserved = re.compile(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', re.I)
    for entry in entries:
        name = entry.filename
        parts = PurePosixPath(name).parts
        mode = entry.external_attr >> 16
        if (not parts or '\\' in name or name.startswith('/') or any(p in ('.', '..') or ':' in p or
                any(ord(c) < 32 for c in p) or any(c in p for c in '<>"|?*') or p.endswith((' ', '.')) or
                reserved.match(p) for p in parts) or stat.S_ISLNK(mode) or entry.flag_bits & 1):
            raise ValueError(f'ZIP 含不安全或不支持的条目：{name[:150]}')
        normalized = '/'.join(parts).casefold()
        if normalized in seen:
            raise ValueError('ZIP 包含重名文件或大小写冲突。')
        seen.add(normalized)
        total += entry.file_size
        if total > 256 * GIB or (entry.file_size > MIB and entry.file_size > max(entry.compress_size, 1) * 1000):
            raise ValueError('ZIP 展开大小或压缩率异常，请从已解压目录导入。')
    return entries, total


def inspect_archive(path):
    path = Path(path).resolve()
    if path.suffix.lower() != '.zip':
        raise ValueError('压缩包导入目前支持 ZIP；其他格式请自行解压后选择目录。')
    try:
        with ZipFile(path) as archive:
            entries, total = archive_entries(archive)
            names = {PurePosixPath(entry.filename).name.lower() for entry in entries}
            detected = 'ios' if 'start-ios.cmd' in names else ('openharmony' if 'run.bat' in names and ('bzimage' in names or 'image' in names) else ('android' if 'emulator.exe' in names else '未知'))
            return dict(path=str(path), platform=detected, packedBytes=path.stat().st_size, unpackedBytes=total,
                        files=len(entries), execution='未执行任何脚本；解压后仍需检查环境。')
    except (BadZipFile, NotImplementedError) as error:
        raise ValueError('无法读取 ZIP 压缩包。') from error


def extract_environment(path, destination):
    path, destination = Path(path).resolve(), Path(destination).resolve()
    if not destination.is_dir():
        raise ValueError('请选择已存在的存放目录。')
    inspect_archive(path)
    with ZipFile(path) as archive:
        entries, total = archive_entries(archive)
        if shutil.disk_usage(destination).free < total + 256 * MIB:
            raise ValueError('目标磁盘空间不足，无法展开此压缩包。')
        # Always create a new child. No existing file is overwritten, even for repeated imports.
        target = Path(tempfile.mkdtemp(prefix='runner-import-', dir=destination))
        try:
            for entry in entries:
                file = target.joinpath(*PurePosixPath(entry.filename).parts)
                if entry.is_dir():
                    file.mkdir(parents=True, exist_ok=True)
                    continue
                file.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, file.open('xb') as output:
                    shutil.copyfileobj(source, output, length=MIB)
            return str(target)
        except BaseException as error:
            # target was just created by mkdtemp within the chosen directory, never user-owned.
            if target.parent == destination and target.name.startswith('runner-import-'):
                shutil.rmtree(target)
            if isinstance(error, (BadZipFile, NotImplementedError, RuntimeError)):
                raise ValueError('ZIP 解压失败，压缩包可能损坏或使用不支持的压缩方法。') from error
            raise
