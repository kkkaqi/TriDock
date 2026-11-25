"""Exercise the actual Electron IPC/UI with synthetic external runtime files, never boot a VM."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='runner-system-smoke-') as directory:
    temp = Path(directory)
    home = temp / 'oniro fixture'
    home.mkdir()
    for name in ('run.bat', 'run.sh', 'bzImage', 'ramdisk.img', 'updater.img', 'system.img', 'vendor.img', 'userdata.img', 'hdc.exe'):
        (home / name).write_bytes(b'fixture')
    tools = temp / 'tools'
    tools.mkdir()
    for name in ('qemu-system-x86_64.exe', 'bash.exe'):
        (tools / name).write_bytes(b'fixture-not-executed')
    package = temp / 'Sample.hap'
    with ZipFile(package, 'w') as archive:
        archive.writestr('module.json', json.dumps({'app': {'bundleName': 'com.example.smoke'},
                                                  'module': {'mainElement': 'EntryAbility'}}))
    runtime_zip = temp / 'oniro-runtime.zip'
    with ZipFile(runtime_zip, 'w') as archive:
        for file in home.iterdir():
            archive.write(file, 'download/oniro/images/' + file.name)
    destination = temp / 'extracted'
    destination.mkdir()
    env = dict(os.environ, PATH=str(tools) + os.pathsep + os.environ.get('PATH', ''), IPA_RUNNER_SMOKE_DATA=str(temp / 'library'),
               IPA_RUNNER_SMOKE_SYSTEM=json.dumps(dict(platform='openharmony', name='OpenHarmony · UI 测试',
                                                       home=str(home), tool=str(home / 'hdc.exe'))),
               IPA_RUNNER_SMOKE_HAP=str(package),
               IPA_RUNNER_SMOKE_RUNTIME_ZIP=str(runtime_zip), IPA_RUNNER_SMOKE_DESTINATION=str(destination),
               IPA_RUNNER_SMOKE_PNG=str(ROOT / '.build-cache' / 'system-manager-smoke.png'))
    command = [str(ROOT / 'dist' / 'win-unpacked' / 'TriDock.exe'), '--smoke'] if '--packaged' in sys.argv else [
        'node', str(ROOT / 'node_modules' / 'electron' / 'cli.js'), '.', '--smoke']
    result = subprocess.run(command,
                            cwd=ROOT, env=env, capture_output=True, encoding='utf-8', errors='replace', timeout=90)
    print(result.stdout)
    if result.returncode:
        print(result.stderr)
    if result.returncode == 0 and 'Electron smoke passed' not in result.stdout:
        raise SystemExit('Electron exited without running the smoke checks.')
    raise SystemExit(result.returncode)
