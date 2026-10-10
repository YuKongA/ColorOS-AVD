"""Keep ColorOS instance registration isolated and preserve existing data."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import common
import launch
import setup


class ColorOSSetupTests(unittest.TestCase):
    def test_registration_preserves_userdata_and_hardware(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = root / 'registry'
            (root / 'config').mkdir()
            (root / 'config/avd.ini').write_text('target=android-37.0\nhw.ramSize=6144\ndisk.dataPartition.size=16G\n')
            (root / 'local').mkdir()
            (root / 'local/runtime.json').write_text(json.dumps({'hardware': {'hw.ramSize': '8192', 'disk.dataPartition.size': '24G'}}))
            data = root / 'avd/ColorOS_Test.avd/userdata-qemu.img'
            data.parent.mkdir(parents=True)
            data.write_bytes(b'existing user data')
            with patch.object(setup, 'ROOT', root), patch.object(setup, 'avd_home', return_value=registry):
                setup.configure(root / 'sdk', 'ColorOS_Test', 5574)
                setup.configure(root / 'sdk', 'ColorOS_Test', 5574)
            config = (data.parent / 'config.ini').read_text()
            self.assertIn('hw.ramSize=8192\n', config)
            self.assertIn('disk.dataPartition.size=24G\n', config)
            self.assertEqual(data.read_bytes(), b'existing user data')
            self.assertIn('target=android-37.0\n', (registry / 'ColorOS_Test.ini').read_text())

    def test_foreign_registry_is_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            registry = root / 'registry'
            registry.mkdir()
            entry = registry / 'ColorOS_Test.ini'
            original = 'path=/another/workspace/ColorOS_Test.avd\n'
            entry.write_text(original)
            with patch.object(setup, 'ROOT', root), patch.object(setup, 'avd_home', return_value=registry):
                with self.assertRaisesRegex(RuntimeError, 'another workspace'):
                    setup.configure(root / 'sdk', 'ColorOS_Test', 5574)
            self.assertEqual(entry.read_text(), original)
            self.assertFalse((root / 'avd').exists())

    def test_launcher_refuses_other_firmware_before_stopping_or_configuring(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'local').mkdir()
            (root / 'local/build.json').write_text('{"source": "other-firmware"}')
            with patch.object(launch, 'ROOT', root), patch.object(launch, 'runtime', return_value={}), \
                    patch.object(sys, 'argv', ['launch.py', '--kill']), \
                    patch.object(launch, 'terminate_emulator') as stop, patch.object(launch, 'configure') as configure:
                with self.assertRaisesRegex(RuntimeError, 'Build ColorOS first'):
                    launch.main()
                stop.assert_not_called()
                configure.assert_not_called()

    def test_coloros_skip_oobe_uses_oppo_launcher(self):
        with patch.object(launch, 'adb') as adb:
            launch.skip_oobe({'port': 5574})
        command = adb.call_args.args[2]
        self.assertIn('com.coloros.bootreg', command)
        self.assertIn('com.android.launcher/com.android.launcher.Launcher', command)


if __name__ == '__main__':
    unittest.main()
