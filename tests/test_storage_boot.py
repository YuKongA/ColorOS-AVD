"""Check backup ordering and recovery before starting an encrypted guest."""
from contextlib import ExitStack
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import storage_boot as storage


class StorageBootTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.avd = self.root / 'avd/Test.avd'
        self.avd.mkdir(parents=True)
        (self.avd / 'config.ini').write_text('disk.dataPartition.size=16G\n')
        (self.avd / 'userdata-qemu.img').write_bytes(b'data')
        self.config = {'sdk': '/sdk', 'name': 'Test', 'port': 5574}
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(storage, 'ROOT', self.root))
        self.stack.enter_context(patch.object(storage, 'validate_userdata'))
        self.resize = self.stack.enter_context(patch.object(storage, 'resize'))
        self.backup = self.stack.enter_context(patch.object(storage, 'backup_userdata', return_value=self.root / 'backup'))
        self.repair = self.stack.enter_context(patch.object(storage, 'prepare_encrypted_storage', return_value={'verified': True}))

    def test_verified_plaintext_needs_no_backup_or_extra_boot(self):
        self.resize.return_value = {'changed': False, 'filesystem_bytes': 16 * 1024**3}
        storage.prepare_userdata(self.config)
        self.backup.assert_not_called()
        self.repair.assert_not_called()

    def test_opaque_disk_growth_requires_backup_before_retry(self):
        events = []

        def resize(*args, **kwargs):
            events.append('resize')
            if kwargs['backup'] is None:
                raise storage.OfflineBackupRequiredError('backup required')
            return {'guest_required': True}

        def backup(*args):
            events.append('backup')
            return self.root / 'backup'

        self.resize.side_effect = resize
        self.backup.side_effect = backup
        storage.prepare_userdata(self.config)
        self.assertEqual(events, ['resize', 'backup', 'resize'])
        self.repair.assert_called_once_with(self.config, 16, self.root / 'backup')

    def test_unproven_capacity_is_backed_up_before_guest_repair(self):
        self.resize.return_value = {'guest_required': True}
        storage.prepare_userdata(self.config)
        self.backup.assert_called_once_with(self.avd)
        self.repair.assert_called_once_with(self.config, 16, self.root / 'backup')

    def test_failed_backup_never_starts_repair_guest(self):
        self.resize.return_value = {'guest_required': True}
        self.backup.side_effect = RuntimeError('incomplete backup')
        with self.assertRaisesRegex(RuntimeError, 'incomplete backup'):
            storage.prepare_userdata(self.config)
        self.repair.assert_not_called()

    def test_pending_recovery_precedes_fresh_template_creation(self):
        (self.avd / 'userdata-qemu.img').unlink()
        (self.avd / storage.PENDING).mkdir()

        def recover(*args, **kwargs):
            (self.avd / 'userdata-qemu.img').write_bytes(b'recovered original')
            return {'changed': False}

        self.resize.side_effect = recover
        with patch.object(storage, 'clone') as clone:
            storage.prepare_userdata(self.config)
        clone.assert_not_called()
        self.assertEqual((self.avd / 'userdata-qemu.img').read_bytes(), b'recovered original')


if __name__ == '__main__':
    unittest.main()
