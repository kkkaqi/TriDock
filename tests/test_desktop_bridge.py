import base64
import json
import os
import plistlib
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from zipfile import ZipFile


BRIDGE = Path(__file__).resolve().parents[1] / 'desktop_bridge.py'


class DesktopBridgeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)

    def invoke(self, action, **payload):
        result = subprocess.run([sys.executable, str(BRIDGE), '--data-dir', str(self.root / 'library'), action],
                                input=json.dumps(payload), capture_output=True, encoding='utf-8',
                                env=dict(os.environ, PYTHONUTF8='1'), check=True)
        return json.loads(result.stdout)

    def add_ipa(self, icon):
        path = self.root / 'Sample Game.ipa'
        with ZipFile(path, 'w') as ipa:
            ipa.writestr('Payload/Demo.app/Info.plist', plistlib.dumps({
                'CFBundleIdentifier': 'com.example.desktop', 'CFBundleDisplayName': '示例',
                'CFBundleExecutable': 'Game', 'CFBundleIconFile': 'Icon.png',
            }))
            ipa.writestr('Payload/Demo.app/Game', struct.pack('<II', 0xFEEDFACE, 12))
            ipa.writestr('Payload/Demo.app/Icon.png', icon)
        self.assertEqual(self.invoke('import', path=str(path)), {'ok': True, 'value': 'com.example.desktop'})

    def test_renderer_uses_the_same_library_and_reads_ipa_metadata(self):
        self.add_ipa(base64.b64decode(
            'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII='))
        library = self.invoke('snapshot')['value']
        self.assertEqual(library['apps'][0]['name'], '示例')
        icon = self.invoke('icon', bundleId='com.example.desktop')['value']
        self.assertTrue(icon.startswith('data:image/png;base64,'))

    def test_early_ios_icon_is_returned_as_standard_png(self):
        def chunk(tag, data):
            return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data))

        header = struct.pack('>IIBBBBB', 2, 1, 8, 6, 0, 0, 0)
        compressor = zlib.compressobj(wbits=-15)
        # Sub-filtered premultiplied BGRA: 50% red followed by opaque blue.
        pixels = compressor.compress(bytes((1, 0, 0, 128, 128, 255, 0, 128, 127))) + compressor.flush()
        self.add_ipa(b'\x89PNG\r\n\x1a\n' + chunk(b'CgBI', b'') + chunk(b'IHDR', header)
                     + chunk(b'IDAT', pixels) + chunk(b'IEND', b''))
        icon = self.invoke('icon', bundleId='com.example.desktop')['value']
        self.assertTrue(icon.startswith('data:image/png;base64,'))
        data = base64.b64decode(icon.split(',', 1)[1])
        self.assertNotIn(b'CgBI', data)
        offset = data.index(b'IDAT')
        size = int.from_bytes(data[offset - 4:offset], 'big')
        self.assertEqual(zlib.decompress(data[offset + 4:offset + 4 + size]), bytes((0, 255, 0, 0, 128, 0, 0, 255, 255)))

    def test_invalid_package_returns_readable_error(self):
        path = self.root / 'invalid.ipa'
        path.write_bytes(b'invalid')
        response = self.invoke('import', path=str(path))
        self.assertFalse(response['ok'])
        self.assertIn('IPA', response['error'])

    def test_display_mode_is_saved_per_app_and_survives_reimport(self):
        icon = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+ip1sAAAAASUVORK5CYII=')
        self.add_ipa(icon)
        bundle = 'com.example.desktop'
        self.assertEqual(self.invoke('snapshot')['value']['apps'][0]['displayMode'], 'window')
        self.assertTrue(self.invoke('display-mode', bundleId=bundle, mode='fullscreen')['ok'])
        self.assertFalse(self.invoke('display-mode', bundleId=bundle, mode='invalid')['ok'])
        self.add_ipa(icon)
        self.assertEqual(self.invoke('snapshot')['value']['apps'][0]['displayMode'], 'fullscreen')

    def test_saving_runtime_paths_preserves_library_settings(self):
        executable = self.root / 'touchHLE.exe'
        executable.touch()
        settings = {'touchhle': str(executable), 'asoftware': '', 'asoftwareWork': ''}
        self.assertTrue(self.invoke('save-settings', **settings)['ok'])
        runtimes = self.invoke('snapshot')['value']['runtimes']
        self.assertEqual(runtimes['touchhle'], str(executable))
        self.assertTrue(runtimes['touchhleReady'])
