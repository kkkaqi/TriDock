import plistlib
import struct
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from ipa_runner import ASoftware, Library, inspect_ipa, touchhle_command


class RunnerTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def make_ipa(self, name='输入 文件.ipa', cpu=12, version='1.2', binary=True):
        path = self.root / name
        info = plistlib.dumps({
            'CFBundleIdentifier': 'org.example.demo', 'CFBundleDisplayName': '测试应用',
            'CFBundleExecutable': 'Demo', 'CFBundleShortVersionString': version,
            'MinimumOSVersion': '3.0',
        }, fmt=plistlib.FMT_BINARY if binary else plistlib.FMT_XML)
        with ZipFile(path, 'w') as archive:
            archive.writestr('Payload/Demo.app/Info.plist', info)
            archive.writestr('Payload/Demo.app/Demo', struct.pack('<II', 0xFEEDFACE, cpu))
            archive.writestr('Payload/Demo.app/PlugIns/Test.appex/Info.plist', b'ignored')
        return path

    def test_reads_binary_plist_and_arm_package(self):
        app = inspect_ipa(self.make_ipa())
        self.assertEqual((app.bundle_id, app.name, app.version, app.minimum_os),
                         ('org.example.demo', '测试应用', '1.2', '3.0'))
        self.assertEqual(app.architectures, ('arm',))

    def test_reads_xml_plist_and_arm64_package(self):
        self.assertEqual(inspect_ipa(self.make_ipa(cpu=0x0100000C, binary=False)).architectures,
                         ('arm64',))

    def test_reads_fat_arm_and_arm64(self):
        path = self.make_ipa()
        with ZipFile(path) as original:
            info = original.read('Payload/Demo.app/Info.plist')
        fat = struct.pack('>12I', 0xCAFEBABE, 2, 12, 0, 48, 8, 0, 0x0100000C, 0, 56, 8, 0)
        fat += struct.pack('<4I', 0xFEEDFACE, 12, 0xFEEDFACF, 0x0100000C)
        with ZipFile(path, 'w') as archive:
            archive.writestr('Payload/Demo.app/Info.plist', info)
            archive.writestr('Payload/Demo.app/Demo', fat)
        self.assertEqual(inspect_ipa(path).architectures, ('arm', 'arm64'))

    def test_rejects_invalid_package_without_adding_it_to_library(self):
        path = self.root / 'bad.ipa'
        path.write_bytes(b'bad')
        library = Library(self.root / 'library')
        with self.assertRaises(ValueError):
            library.add(path)
        self.assertEqual(library.apps(), [])

    def test_import_persists_copy_and_replaces_version_by_bundle_id(self):
        root = self.root / 'library'
        source = self.make_ipa()
        first = Library(root).add(source)
        source.unlink()
        self.assertTrue(first.path.is_file())
        Library(root).add(self.make_ipa(version='2.0'))
        library = Library(root)
        self.assertEqual(len(library.apps()), 1)
        self.assertEqual(library.get(first.bundle_id).version, '2.0')

    def test_legacy_command_passes_spaces_without_a_shell(self):
        executable = self.root / 'touchHLE.exe'
        executable.touch()
        app = inspect_ipa(self.make_ipa())
        self.assertEqual(touchhle_command(executable, app), [str(executable), str(app.path)])
        with self.assertRaisesRegex(ValueError, '32'):
            touchhle_command(executable, inspect_ipa(self.make_ipa(cpu=0x0100000C)))

    def test_touchhle_display_modes_use_supported_arguments(self):
        executable = self.root / 'touchHLE.exe'
        executable.touch()
        app = inspect_ipa(self.make_ipa())
        self.assertEqual(touchhle_command(executable, app, 'large')[-1], '--scale-hack=2')
        self.assertEqual(touchhle_command(executable, app, 'fullscreen')[-1], '--fullscreen')
        with self.assertRaises(ValueError):
            touchhle_command(executable, app, 'invalid')

    def test_asoftware_queue_reports_guest_results_and_keeps_source(self):
        home = self.root / 'iOS Runtime'
        (home / 'scripts').mkdir(parents=True)
        (home / 'scripts' / 'run-windows.ps1').touch()
        (home / 'Start-iOS.cmd').touch()
        backend = ASoftware(home)
        app = Library(self.root / 'library').add(self.make_ipa(cpu=0x0100000C))
        self.assertEqual(backend.status(app), ('未提交', ''))
        queued = backend.enqueue(app)
        self.assertEqual(queued.read_bytes(), app.path.read_bytes())
        self.assertEqual(backend.status(app), ('等待安装', ''))
        failed = queued.parent / 'Failed' / queued.name
        failed.parent.mkdir()
        queued.rename(failed)
        failed.with_suffix('.ipa.log').write_text('failed: example', encoding='utf-8')
        self.assertEqual(backend.status(app), ('安装失败', 'failed: example'))
        queued = backend.enqueue(app)
        installed = queued.parent / 'Installed' / queued.name
        installed.parent.mkdir()
        queued.rename(installed)
        self.assertEqual(backend.status(app), ('已安装', ''))
        self.assertTrue(app.path.is_file())


if __name__ == '__main__':
    unittest.main()
