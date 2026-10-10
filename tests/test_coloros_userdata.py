"""Require exact guest verification instead of guessing from df output."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import launch
import userdata_guest


class ColorOSUserdataTests(unittest.TestCase):
    def test_normal_initialization_uses_read_only_capacity_verification(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            avd = root / 'avd/Test.avd'
            avd.mkdir(parents=True)
            (avd / 'config.ini').write_text('disk.dataPartition.size=16G\n')
            config = {'name': 'Test', 'port': 5574, 'sdk': '/sdk'}
            record = {'verified': True, 'changed': False}
            with patch.object(launch, 'ROOT', root), patch.object(userdata_guest, 'verify_and_grow', return_value=record) as verify:
                self.assertEqual(launch.verify_coloros_userdata(config), record)
            verify.assert_called_once_with(config, 16 * 1024**3, allow_grow=False)


if __name__ == '__main__':
    unittest.main()
