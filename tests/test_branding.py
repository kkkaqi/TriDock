"""Brand changes must retain the historical library and installer upgrade identity."""
import json
import struct
import unittest
from pathlib import Path

from ipa_runner import APP_ROOT

ROOT = Path(__file__).resolve().parents[1]


class BrandingTests(unittest.TestCase):
    def test_new_display_name_keeps_legacy_data_and_upgrade_identity(self):
        package = json.loads((ROOT / 'package.json').read_text(encoding='utf-8'))
        self.assertEqual(package['productName'], 'TriDock（三栖）')
        self.assertEqual(package['name'], 'tridock')
        self.assertEqual(APP_ROOT.name, 'IPA Runner')
        config = (ROOT / 'electron-builder.yml').read_text(encoding='utf-8')
        self.assertIn('appId: com.kkkaqi.ipa-runner', config)
        self.assertIn('artifactName: TriDock-', config)

    def test_windows_icon_contains_small_and_large_frames(self):
        data = (ROOT / 'electron/renderer/icon.ico').read_bytes()
        reserved, kind, count = struct.unpack_from('<HHH', data)
        self.assertEqual((reserved, kind), (0, 1))
        frames = set()
        for i in range(count):
            width, height, _, _, planes, bits, size, offset = struct.unpack_from('<BBBBHHII', data, 6 + 16 * i)
            frames.add(width or 256)
            self.assertEqual(width, height)
            self.assertEqual((planes, bits), (1, 32))
            self.assertLessEqual(offset + size, len(data))
            self.assertEqual(data[offset:offset + 8], b'\x89PNG\r\n\x1a\n')
        self.assertTrue({16, 32, 48, 256}.issubset(frames))
