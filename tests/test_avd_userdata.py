"""Protect encrypted AVD layers when changing their virtual capacity."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import avd_userdata as userdata

QEMU_IMG = Path.home() / 'Library/Android/sdk/emulator/qemu-img'


class UserdataTests(unittest.TestCase):
    def test_refuses_foreign_backing_chain(self):
        with tempfile.TemporaryDirectory() as directory:
            avd = Path(directory)
            (avd / 'userdata-qemu.img').touch()
            (avd / 'userdata-qemu.img.qcow2').touch()
            with patch.object(userdata, 'data_size', return_value={'backing-filename': '/foreign/userdata-qemu.img'}):
                with self.assertRaisesRegex(RuntimeError, 'backing chain'):
                    userdata.validate_userdata(Path('/sdk'), avd)

    @unittest.skipUnless(QEMU_IMG.is_file(), 'Android Emulator qemu-img is not installed')
    def test_refuses_shrink_before_any_data_write(self):
        with tempfile.TemporaryDirectory() as directory:
            avd = Path(directory)
            raw = avd / 'userdata-qemu.img'
            with raw.open('wb') as output:
                output.truncate(32 * 1024**3)
            overlay = avd / 'userdata-qemu.img.qcow2'
            subprocess.run([str(QEMU_IMG), 'create', '-f', 'qcow2', '-F', 'raw',
                            '-b', raw.name, overlay.name], cwd=avd, check=True, capture_output=True)
            before = {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in (raw, overlay)}
            with self.assertRaisesRegex(RuntimeError, 'reduced'):
                userdata.resize(QEMU_IMG.parents[1], avd, 16)
            self.assertEqual(before, {p.name: (p.stat().st_size, p.stat().st_mtime_ns) for p in (raw, overlay)})

    @unittest.skipUnless(QEMU_IMG.is_file(), 'Android Emulator qemu-img is not installed')
    def test_unknown_raw_filesystem_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            avd = Path(directory)
            sdk = QEMU_IMG.parents[1]
            raw = avd / 'userdata-qemu.img'
            with raw.open('wb') as output:
                output.write(b'preserved userdata')
                output.truncate(4 * 1024**2)
            overlay = avd / 'userdata-qemu.img.qcow2'
            subprocess.run([str(QEMU_IMG), 'create', '-f', 'qcow2', '-F', 'raw',
                            '-b', raw.name, overlay.name], cwd=avd,
                           check=True, capture_output=True)
            key = avd / 'encryptionkey.img'
            key.write_bytes(b'preserved encryption key')
            userdata.validate_userdata(sdk, avd)
            with self.assertRaisesRegex(RuntimeError, 'guest-scoped'):
                userdata.resize(sdk, avd, 16)
            for path in (raw, overlay):
                self.assertEqual(userdata.data_size(sdk, path)['virtual-size'], 4 * 1024**2)
            with raw.open('rb') as source:
                self.assertEqual(source.read(18), b'preserved userdata')
            self.assertEqual(key.read_bytes(), b'preserved encryption key')
            userdata.validate_userdata(sdk, avd)


if __name__ == '__main__':
    unittest.main()
