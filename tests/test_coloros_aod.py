"""Limit AOD adaptation to the audited missing-panel-service fallback."""
import hashlib
from pathlib import Path
import struct
import sys
import unittest
import zipfile
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from coloros_aod import PANEL_FALLBACK_OFFSET, patch_panel_fallback, patch_systemui_apk

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'work/coloros/input/partitions/system_ext.img'


class AodPatchTests(unittest.TestCase):
    def test_unknown_dex_and_apk_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'Unsupported'):
            patch_panel_fallback(b'unknown SystemUI DEX')
        with self.assertRaisesRegex(RuntimeError, 'Unsupported'):
            patch_systemui_apk(b'unknown APK', Path('/sdk'), Path('/unused'))

    @unittest.skipUnless(SOURCE.is_file(), 'Official ColorOS partition not present')
    def test_original_dex_metadata_and_unrelated_code_are_preserved(self):
        from image_utils import erofs
        import io
        with zipfile.ZipFile(io.BytesIO(erofs(SOURCE, '/priv-app/SystemUI/SystemUI.apk'))) as apk:
            original = apk.read('classes3.dex')
        patched = patch_panel_fallback(original)
        self.assertEqual(len(patched), len(original))
        self.assertEqual(struct.unpack_from('<I', patched, 32)[0], len(patched))
        self.assertEqual(patched[12:32], hashlib.sha1(patched[32:]).digest())
        self.assertEqual(struct.unpack_from('<I', patched, 8)[0], zlib.adler32(patched[12:]))
        start = PANEL_FALLBACK_OFFSET + 16
        self.assertEqual(patched[32:start], original[32:start])
        self.assertEqual(patched[start + 30:], original[start + 30:])
        # The code_item header and exception handlers keep their original
        # positions, which matters when Android verifies and loads SystemUI.
        self.assertEqual(patched[PANEL_FALLBACK_OFFSET:start], original[PANEL_FALLBACK_OFFSET:start])


if __name__ == '__main__':
    unittest.main()
