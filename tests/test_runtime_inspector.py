import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

from runtime_inspector import inspect_environment, inspect_archive, extract_environment
from system_manager import SystemManager


class InspectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.host = dict(architecture='AMD64', totalMemory=32 * 1024**3,
                         availableMemory=20 * 1024**3, cpus=8, virtualization=True)
        self.addCleanup(patch.stopall)
        patch('runtime_inspector.host_info', return_value=self.host).start()
        patch('runtime_inspector.shutil.which', return_value='C:/tools/tool.exe').start()

    def oniro(self):
        home = self.root / 'download' / 'oniro' / 'images'
        home.mkdir(parents=True)
        for name in ('run.bat', 'run.sh', 'bzImage', 'ramdisk.img', 'system.img', 'vendor.img', 'userdata.img', 'updater.img', 'hdc.exe'):
            (home / name).write_bytes(b'fixture')
        return home

    def test_nested_environment_is_identified_without_running_scripts(self):
        home = self.oniro()
        before = sorted(str(p) for p in self.root.rglob('*'))
        result = inspect_environment(dict(platform='openharmony', home=str(home.parent.parent)))
        self.assertTrue(result['canCreate'], result['checks'])
        self.assertEqual(result['values']['home'], str(home.resolve()))
        self.assertEqual(result['architecture'], 'x86_64')
        self.assertEqual(before, sorted(str(p) for p in self.root.rglob('*')))

    def test_arm_oniro_is_not_mislabeled_as_x64(self):
        home = self.oniro()
        (home / 'bzImage').rename(home / 'Image')
        result = inspect_environment(dict(platform='openharmony', home=str(home)))
        self.assertFalse(result['canCreate'])
        self.assertEqual(result['architecture'], 'arm64')

    def test_missing_image_is_a_blocking_error(self):
        home = self.oniro()
        (home / 'vendor.img').unlink()
        result = inspect_environment(dict(platform='openharmony', home=str(home)))
        self.assertFalse(result['canCreate'])
        self.assertTrue(any('vendor.img' in c['message'] and c['level'] == 'error' for c in result['checks']))

    def test_android_devices_are_discovered_from_configuration(self):
        sdk = self.root / 'sdk'
        for name in ('emulator/emulator.exe', 'platform-tools/adb.exe', 'build-tools/36.0.0/aapt2.exe'):
            file = sdk / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b'fixture')
        avds = self.root / 'avds'
        device = avds / 'Demo.avd'
        device.mkdir(parents=True)
        image = sdk / 'system-images' / 'android-35' / 'google_apis' / 'x86_64'
        image.mkdir(parents=True)
        (image / 'system.img').write_bytes(b'image')
        (image / 'kernel-ranchu').write_bytes(b'kernel')
        (image / 'ramdisk.img').write_bytes(b'ramdisk')
        (avds / 'Demo.ini').write_text('path=' + str(device), encoding='utf-8')
        (device / 'config.ini').write_text('abi.type=x86_64\nimage.sysdir.1=system-images/android-35/google_apis/x86_64/\n', encoding='utf-8')
        with patch.dict('os.environ', {'ANDROID_AVD_HOME': str(avds)}):
            result = inspect_environment(dict(platform='android', home=str(sdk)))
        self.assertTrue(result['canCreate'], result['checks'])
        self.assertEqual(result['values']['target'], 'Demo')
        self.assertEqual(result['architecture'], 'x86_64')
        self.assertEqual(result['version'], 'Android API 35')
        self.assertEqual(result['storagePath'], str(device.resolve()))
        self.assertGreater(result['requiredBytes'], 0)
        with patch.dict('os.environ', {'ANDROID_AVD_HOME': str(avds)}), patch('runtime_inspector.shutil.disk_usage') as disk:
            disk.return_value.free = 0
            self.assertFalse(inspect_environment(dict(platform='android', home=str(sdk)))['canCreate'])
            self.assertEqual(Path(disk.call_args.args[0]), device)

    def test_ios_scripts_alone_are_not_a_prepared_system(self):
        home = self.root / 'ios'
        (home / 'scripts').mkdir(parents=True)
        (home / 'Start-iOS.cmd').write_text('')
        (home / 'scripts' / 'run-windows.ps1').write_text('')
        result = inspect_environment(dict(platform='ios', home=str(home)))
        self.assertFalse(result['canCreate'])
        self.assertTrue(any('系统盘' in c['message'] for c in result['checks']))

    def test_insufficient_disk_prevents_creation(self):
        home = self.oniro()
        with patch('runtime_inspector.shutil.disk_usage') as disk:
            disk.return_value.free = 1
            result = inspect_environment(dict(platform='openharmony', home=str(home)))
        self.assertFalse(result['canCreate'])

    def test_unknown_versions_remain_unverified(self):
        result = inspect_environment(dict(platform='openharmony', home=str(self.oniro())))
        self.assertIn('未知', result['version'])
        self.assertFalse(result['bootVerified'])

    def test_prepared_ios_paths_are_discovered(self):
        home = self.root / 'ios'
        for name in ('Start-iOS.cmd', 'scripts/run-windows.ps1', 'tools/qemu-sweet.py',
                     'tools/mkadt.py', 'tools/mkpayload.py', 'python/python.exe',
                     'xnu/out-0104/kernel.development.sweet', 'work/root/ios16-base.qcow2',
                     'work/qemu/qemu-system-aarch64.exe', 'work/qemu/qemu-img.exe'):
            file = home / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_bytes(b'fixture')
        result = inspect_environment(dict(platform='ios', home=str(home)))
        self.assertTrue(result['canCreate'], result['checks'])
        self.assertEqual(result['values']['disk'], str(home / 'work/root/ios16-base.qcow2'))
        (home / 'tools/mkpayload.py').unlink()
        self.assertFalse(inspect_environment(dict(platform='ios', home=str(home)))['canCreate'])

    def test_guided_records_are_rechecked_before_launch(self):
        manager = SystemManager(self.root / 'library')
        home = self.oniro()
        item = manager.create(dict(platform='openharmony', home=str(home), name='test', guided=True))
        self.assertTrue(item['guided'])
        (home / 'vendor.img').unlink()
        with patch('subprocess.Popen') as start:
            with self.assertRaises(ValueError):
                manager.start(item['id'])
            start.assert_not_called()

    def test_guided_create_cannot_bypass_failed_inspection(self):
        manager = SystemManager(self.root / 'library')
        home = self.oniro()
        (home / 'vendor.img').unlink()
        with self.assertRaises(ValueError):
            manager.create(dict(platform='openharmony', home=str(home), name='test', guided=True))
        self.assertEqual(manager.snapshot()['instances'], [])

    def test_insufficient_physical_memory_is_blocking(self):
        self.host['totalMemory'] = 2 * 1024**3
        result = inspect_environment(dict(platform='openharmony', home=str(self.oniro()), memory=4096))
        self.assertFalse(result['canCreate'])

    def archive(self, entries):
        path = self.root / 'runtime.zip'
        with ZipFile(path, 'w') as archive:
            for name, value in entries:
                archive.writestr(name, value)
        return path

    def test_archive_inspection_is_read_only_then_extracts_to_new_child(self):
        path = self.archive([('oniro/run.bat', 'fixture'), ('oniro/bzImage', 'kernel')])
        result = inspect_archive(path)
        self.assertEqual(result['platform'], 'openharmony')
        self.assertEqual(result['unpackedBytes'], 13)
        destination = self.root / 'destination'
        destination.mkdir()
        (destination / 'keep.txt').write_text('keep')
        extracted = Path(extract_environment(path, destination))
        self.assertEqual((extracted / 'oniro' / 'bzImage').read_text(), 'kernel')
        self.assertEqual((destination / 'keep.txt').read_text(), 'keep')

    def test_archive_traversal_and_windows_paths_rejected(self):
        for name in ('../escape', 'C:/escape', '/escape', 'folder/../../escape', 'x/evil:stream', 'x\\..\\escape', 'CON.txt'):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    inspect_archive(self.archive([(name, 'bad')]))

    def test_archive_symlink_rejected(self):
        info = ZipInfo('link')
        info.create_system = 3
        info.external_attr = (0o120777 << 16)
        with self.assertRaises(ValueError):
            inspect_archive(self.archive([(info, '../outside')]))

    def test_archive_case_collisions_rejected(self):
        with self.assertRaises(ValueError):
            inspect_archive(self.archive([('A.txt', 'a'), ('a.txt', 'b')]))

    def test_zipbomb_ratio_rejected(self):
        path = self.root / 'bomb.zip'
        with ZipFile(path, 'w', compression=ZIP_DEFLATED) as archive:
            archive.writestr('giant.img', b'0' * (2 * 1024 * 1024))
        with self.assertRaises(ValueError):
            inspect_archive(path)

    def test_insufficient_extraction_space_creates_no_directory(self):
        path = self.archive([('oniro/run.bat', 'fixture')])
        destination = self.root / 'destination'
        destination.mkdir()
        with patch('runtime_inspector.shutil.disk_usage') as disk:
            disk.return_value.free = 1
            with self.assertRaises(ValueError):
                extract_environment(path, destination)
        self.assertEqual(list(destination.iterdir()), [])

    def test_failed_extraction_removes_only_its_new_directory(self):
        path = self.archive([('data/file.txt', 'fixture')])
        destination = self.root / 'destination'
        destination.mkdir()
        keep = destination / 'keep.txt'
        keep.write_text('keep')
        with patch('runtime_inspector.shutil.copyfileobj', side_effect=OSError('disk disconnected')):
            with self.assertRaises(OSError):
                extract_environment(path, destination)
        self.assertEqual(list(destination.iterdir()), [keep])


if __name__ == '__main__':
    unittest.main()
