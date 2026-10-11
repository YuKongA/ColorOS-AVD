"""Preserve trusted-system APK certificates and valid ZIP offsets."""
import io
import struct
import sys
from pathlib import Path
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from apk_system_signing import central_directory, retain_system_signing, signing_block, MAGIC


def apk(payload):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as archive:
        archive.writestr('classes.dex', payload)
    return buffer.getvalue()


class SigningTests(unittest.TestCase):
    def original(self):
        data = apk(b'original dex')
        end, central = central_directory(data)
        payload = b'certificate metadata'
        size = len(payload) + 24
        block = struct.pack('<Q', size) + payload + struct.pack('<Q', size) + MAGIC
        result = bytearray(data[:central] + block + data[central:])
        struct.pack_into('<I', result, end + len(block) + 16, central + len(block))
        return bytes(result)

    def test_rebuilt_zip_retains_exact_signing_metadata_and_modified_dex(self):
        original = self.original()
        rebuilt = apk(b'modified dex')
        result = retain_system_signing(original, rebuilt)
        self.assertEqual(signing_block(result), signing_block(original))
        with zipfile.ZipFile(io.BytesIO(result)) as archive:
            self.assertEqual(archive.read('classes.dex'), b'modified dex')
            self.assertIsNone(archive.testzip())

    def test_missing_oem_signing_block_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'signing block is missing'):
            retain_system_signing(apk(b'unsigned'), apk(b'modified'))

    def test_existing_signing_block_is_not_duplicated(self):
        with self.assertRaisesRegex(RuntimeError, 'already has'):
            retain_system_signing(self.original(), self.original())


if __name__ == '__main__':
    unittest.main()
