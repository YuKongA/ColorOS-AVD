"""Limit AVD removal to the stopped instance owned by this workspace."""
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import uninstall


class ColorOSUninstallTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.registry = self.root / 'registry'
        self.registry.mkdir()
        self.name = 'ColorOS_Test'
        self.data = self.root / 'avd' / (self.name + '.avd')
        self.data.mkdir(parents=True)
        (self.data / 'userdata-qemu.img').write_bytes(b'personal data')
        (self.data / 'encryptionkey.img').write_bytes(b'personal key')
        self.entry = self.registry / (self.name + '.ini')
        self.entry.write_text(f'path={self.data}\ntarget=android-37.0\n')
        (self.root / 'local').mkdir()
        self.instances = self.root / 'local/instances.json'
        self.instances.write_text(json.dumps({self.name: 5574, 'Other': 5580}))
        (self.root / 'local/runtime.json').write_text(json.dumps({'name': self.name, 'port': 5574}))
        self.image = self.root / 'images/system.img'
        self.image.parent.mkdir()
        self.image.write_bytes(b'shared firmware')
        self.other = self.root / 'avd/Other.avd/userdata-qemu.img'
        self.other.parent.mkdir()
        self.other.write_bytes(b'other personal data')
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(uninstall, 'ROOT', self.root))
        stack.enter_context(patch.object(uninstall, 'avd_home', return_value=self.registry))
        self.ports = stack.enter_context(patch.object(uninstall, 'port_free'))
        self.processes = stack.enter_context(patch.object(uninstall.subprocess, 'check_output', return_value=''))

    def test_default_unregister_preserves_data_keys_and_firmware(self):
        uninstall.uninstall(self.name)
        self.assertFalse(self.entry.exists())
        self.assertEqual((self.data / 'userdata-qemu.img').read_bytes(), b'personal data')
        self.assertEqual((self.data / 'encryptionkey.img').read_bytes(), b'personal key')
        self.assertEqual(self.image.read_bytes(), b'shared firmware')
        self.assertEqual(json.loads(self.instances.read_text()), {'Other': 5580})
        self.ports.assert_called_once_with(5574)

    def test_delete_data_removes_only_selected_avd(self):
        uninstall.uninstall(self.name, delete_data=True)
        self.assertFalse(self.data.exists())
        self.assertFalse(self.entry.exists())
        self.assertEqual(self.other.read_bytes(), b'other personal data')
        self.assertEqual(self.image.read_bytes(), b'shared firmware')

    def test_foreign_registry_prevents_any_removal(self):
        original = 'path=/another/workspace/ColorOS_Test.avd\n'
        self.entry.write_text(original)
        with self.assertRaisesRegex(RuntimeError, 'another workspace'):
            uninstall.uninstall(self.name, delete_data=True)
        self.assertEqual(self.entry.read_text(), original)
        self.assertTrue(self.data.exists())
        self.ports.assert_not_called()

    def test_busy_port_prevents_any_removal(self):
        self.ports.side_effect = RuntimeError('Port is occupied')
        with self.assertRaisesRegex(RuntimeError, 'occupied'):
            uninstall.uninstall(self.name, delete_data=True)
        self.assertTrue(self.entry.exists())
        self.assertTrue(self.data.exists())

    def test_running_on_another_port_prevents_any_removal(self):
        self.processes.return_value = '/sdk/emulator/qemu-system-aarch64 -avd ColorOS_Test -port 5590\n'
        with self.assertRaisesRegex(RuntimeError, 'Close this ColorOS AVD'):
            uninstall.uninstall(self.name, delete_data=True)
        self.assertTrue(self.entry.exists())
        self.assertTrue(self.data.exists())

    def test_symlink_to_another_directory_is_rejected(self):
        link = self.root / 'avd/Linked.avd'
        link.symlink_to(self.data, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, 'linked'):
            uninstall.uninstall('Linked', delete_data=True)
        self.assertTrue(self.data.exists())

    def test_path_traversal_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'ASCII AVD name'):
            uninstall.uninstall('../ColorOS_Test', delete_data=True)
        self.assertTrue(self.data.exists())

    def test_repeated_unregister_is_harmless(self):
        uninstall.uninstall(self.name)
        _, removed_registry, removed_data = uninstall.uninstall(self.name)
        self.assertFalse(removed_registry)
        self.assertFalse(removed_data)
        self.assertTrue(self.data.exists())

    def test_cancelled_data_confirmation_preserves_everything(self):
        with patch.object(sys, 'argv', ['uninstall.py', '--delete-data']), \
                patch('builtins.input', return_value='cancel'):
            uninstall.main()
        self.assertTrue(self.entry.exists())
        self.assertTrue(self.data.exists())
        self.ports.assert_not_called()


if __name__ == '__main__':
    unittest.main()
