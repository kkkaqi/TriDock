import json
import tempfile
import unittest
import subprocess
import sys
from unittest.mock import patch
from pathlib import Path
from zipfile import ZipFile

from system_manager import SystemManager, process_identity


class SystemManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manager = SystemManager(self.root / 'library')

    def android(self, target='Demo'):
        home = self.root / 'sdk'
        for file in ['emulator/emulator.exe', 'platform-tools/adb.exe', 'build-tools/36.0.0/aapt2.exe']:
            path = home / file
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch()
        return self.manager.create(dict(platform='android', name=target, home=str(home), target=target,
                                        memory=2048, cpus=2))

    def harmony(self):
        home = self.root / 'oniro'
        home.mkdir(exist_ok=True)
        for file in ['run.bat', 'run.sh', 'bzImage', 'ramdisk.img', 'updater.img', 'vendor.img', 'userdata.img', 'system.img', 'hdc.exe']:
            (home / file).touch()
        return self.manager.create(dict(platform='openharmony', name='Oniro', home=str(home),
                                        tool=str(home / 'hdc.exe'), memory=4096, cpus=4))

    def test_new_install_has_no_instances_or_images(self):
        self.assertEqual(self.manager.snapshot()['instances'], [])
        self.assertFalse(any(self.root.rglob('*.img')))

    def test_instances_persist_without_copying_runtime(self):
        item = self.android()
        other = SystemManager(self.root / 'library').snapshot()['instances'][0]
        self.assertEqual(other['id'], item['id'])
        self.assertEqual(other['home'], str((self.root / 'sdk').resolve()))
        self.assertFalse(any((self.root / 'library').rglob('emulator.exe')))

    def test_invalid_environment_is_rejected(self):
        with self.assertRaises(ValueError):
            self.manager.create(dict(platform='android', name='bad', home=str(self.root), target='Demo'))

    def test_duplicate_android_target_rejected(self):
        self.android()
        with self.assertRaises(ValueError):
            self.android()

    def test_shell_characters_cannot_be_avd_names(self):
        with self.assertRaises(ValueError):
            self.android('Demo & calc')

    def test_cpu_and_memory_limits(self):
        item = self.android()
        with self.assertRaises(ValueError):
            self.manager.create(dict(item, name='bad', target='Other', memory=-1))

    def test_android_commands_pin_serial_and_resources(self):
        item = self.android()
        command = self.manager.start_command(item)
        self.assertIn('-no-snapshot', command)
        self.assertEqual(command[command.index('-memory') + 1], '2048')
        self.assertEqual(self.manager.device_command(item, ['install', '-r', 'x.apk'])[1:3],
                         ['-s', item['device']])

    def test_harmony_instances_get_separate_ports(self):
        first = self.harmony()
        second = self.harmony()
        self.assertNotEqual(first['device'], second['device'])
        self.assertGreaterEqual(int(first['target']), 1)
        self.assertIn('--instance', self.manager.start_command(second))
        self.assertEqual(self.manager.device_command(second, ['install', 'x.hap'])[1:3],
                         ['-t', second['device']])

    def test_harmony_incomplete_guest_images_are_rejected(self):
        first = self.harmony()
        (Path(first['home']) / 'vendor.img').unlink()
        with self.assertRaises(ValueError):
            self.manager.validate(first)

    def test_package_platform_mismatch_rejected(self):
        item = self.android()
        package = self.root / 'test.hap'
        package.write_bytes(b'bad')
        with self.assertRaises(ValueError):
            self.manager.import_package(item['id'], package)

    def test_hap_import_and_remove_do_not_delete_external_files(self):
        item = self.harmony()
        package = self.root / 'test.hap'
        with ZipFile(package, 'w') as out:
            out.writestr('module.json', json.dumps({'app': {'bundleName': 'com.example.demo'},
                           'module': {'mainElement': 'EntryAbility', 'name': 'entry'}}))
        app = self.manager.import_package(item['id'], package)
        self.assertEqual(app['bundleId'], 'com.example.demo')
        self.assertEqual(len(self.manager.snapshot()['packages']), 1)
        self.manager.remove(item['id'])
        self.assertTrue(package.is_file())
        self.assertTrue((self.root / 'oniro' / 'system.img').is_file())
        self.assertEqual(self.manager.snapshot()['packages'], [])

    def test_invalid_hap_does_not_enter_library(self):
        item = self.harmony()
        package = self.root / 'broken.hap'
        package.write_bytes(b'bad')
        with self.assertRaises(ValueError):
            self.manager.import_package(item['id'], package)
        self.assertEqual(self.manager.snapshot()['packages'], [])

    def test_start_missing_avd_reports_error_without_running(self):
        item = self.android()
        (self.root / 'sdk' / 'emulator' / 'emulator.exe').unlink()
        with self.assertRaises(ValueError):
            self.manager.start(item['id'])

    def test_process_identity_tracks_owned_process_lifetime(self):
        process = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
        try:
            token = process_identity(process.pid)
            self.assertTrue(token)
            self.assertTrue(self.manager.running(dict(pid=process.pid, token=token)))
            self.assertFalse(self.manager.running(dict(pid=process.pid, token='different-generation')))
        finally:
            process.terminate()
            process.wait(timeout=10)
        self.assertFalse(self.manager.running(dict(pid=process.pid, token=token)))

    def test_hdc_connection_failure_is_retried_during_boot(self):
        item = self.harmony()
        attempts = []
        def command(_item, args, **kwargs):
            attempts.append(args)
            if 'tconn' in args and len(attempts) == 1:
                raise ValueError('not ready')
            return 'runner-ready' if 'shell' in args else 'OK'
        with patch.object(self.manager, 'running', return_value=True), \
                patch.object(self.manager, 'command', side_effect=command), patch('system_manager.time.sleep'):
            self.manager.ready(item)
        self.assertEqual(sum('tconn' in args for args in attempts), 2)

    def test_ios_snapshot_reconciles_queue_status(self):
        item = self.android()
        item.update(platform='ios', work=str(self.root / 'work'))
        self.manager.save(item)
        self.manager.save_package(dict(id='submission', instance=item['id'], path='original.ipa',
                                      queueName='unique.ipa', state='等待安装'))
        with patch('system_manager.ASoftware') as provider:
            provider.return_value.status.return_value = ('安装失败', 'invalid signature')
            package = self.manager.snapshot()['packages'][0]
        self.assertEqual(package['state'], '安装失败')
        self.assertEqual(package['detail'], 'invalid signature')

    @unittest.skipUnless(sys.platform == 'win32', 'Windows process management')
    def test_start_and_stop_only_the_owned_process(self):
        item = self.android()
        with patch.object(self.manager, 'command', return_value='Demo'), \
                patch('system_manager.port_open', return_value=False), \
                patch.object(self.manager, 'start_command', return_value=[sys.executable, '-c', 'import time; time.sleep(30)']):
            running = self.manager.start(item['id'])
        try:
            self.assertTrue(self.manager.running(running))
            self.manager.stop(item['id'])
            self.assertFalse(self.manager.running(running))
        finally:
            if self.manager.running(running):
                subprocess.run(['taskkill.exe', '/PID', str(running['pid']), '/F'], capture_output=True)

    def test_ios_install_queues_unique_hash_before_start(self):
        item = self.android()
        item.update(platform='ios', work=str(self.root / 'work'))
        self.manager.save(item)
        source = self.root / 'same-name.ipa'
        source.write_bytes(b'fixture-content')
        from system_manager import file_digest
        app = dict(id='package', instance=item['id'], path=str(source), sha256=file_digest(source), state='未安装')
        self.manager.save_package(app)
        queue = self.root / 'work' / 'ipa'
        with patch('system_manager.ASoftware') as provider, \
                patch.object(self.manager, 'running', return_value=False), patch.object(self.manager, 'start') as start:
            provider.return_value.queue = queue
            provider.return_value.status.return_value = ('未提交', '')
            def verify_submission(_id):
                self.assertTrue((queue / (app['sha256'] + '.ipa')).is_file())
                self.assertFalse((queue / 'same-name.ipa').exists())
            start.side_effect = verify_submission
            self.manager.install(app['id'])
        self.assertEqual(source.read_bytes(), b'fixture-content')

    def test_existing_external_device_port_cannot_be_hijacked(self):
        item = self.android()
        with patch('system_manager.port_open', return_value=True), patch('system_manager.subprocess.Popen') as launch:
            with self.assertRaises(ValueError):
                self.manager.start(item['id'])
            launch.assert_not_called()

    def test_probe_does_not_claim_readiness_for_a_stopped_system(self):
        item = self.android()
        with patch.object(self.manager, 'running', return_value=False), patch.object(self.manager, 'command') as command:
            self.assertEqual(self.manager.probe(item['id'])['state'], 'stopped')
            command.assert_not_called()

    def test_android_probe_requires_boot_completed(self):
        item = self.android()
        with patch.object(self.manager, 'running', return_value=True), patch.object(self.manager, 'command', return_value='0'):
            self.assertEqual(self.manager.probe(item['id'])['state'], 'booting')
        with patch.object(self.manager, 'running', return_value=True), patch.object(self.manager, 'command', return_value='1'):
            self.assertEqual(self.manager.probe(item['id'])['state'], 'ready')

    def test_ios_probe_remains_unverified_even_when_process_runs(self):
        item = self.android()
        item['platform'] = 'ios'
        self.manager.save(item)
        with patch.object(self.manager, 'running', return_value=True):
            self.assertEqual(self.manager.probe(item['id'])['state'], 'unverified')


if __name__ == '__main__':
    unittest.main()
