"""Resolve verified KernelSU tools without requiring ignored local files."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import common


class ToolCacheTests(unittest.TestCase):
    def prepare(self, root, payload):
        return (patch.object(common, 'ROOT', root / 'workspace'),
                patch.object(common, 'REPO_ROOT', root / 'repo'),
                patch.object(common, 'KSU_ASSETS', {'fixture.apk': hashlib.sha256(payload).hexdigest()}))

    def test_seeds_offline_cache_and_checks_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'workspace').mkdir()
            (root / 'repo/tools').mkdir(parents=True)
            (root / 'repo/tools/fixture.apk').write_bytes(b'verified asset')
            root_patch, repo_patch, hashes_patch = self.prepare(root, b'verified asset')
            with root_patch, repo_patch, hashes_patch, patch.object(common.urllib.request, 'urlretrieve') as download:
                cache = common.fetch_ksu(['fixture.apk'])
            download.assert_not_called()
            self.assertEqual((cache / 'fixture.apk').read_bytes(), b'verified asset')

    def test_missing_local_asset_is_downloaded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'workspace').mkdir()
            root_patch, repo_patch, hashes_patch = self.prepare(root, b'verified asset')

            def download(url, target):
                self.assertIn('/KernelSU/releases/download/v3.3.0/fixture.apk', url)
                Path(target).write_bytes(b'verified asset')

            with root_patch, repo_patch, hashes_patch, patch.object(common.urllib.request, 'urlretrieve', side_effect=download):
                cache = common.fetch_ksu(['fixture.apk'])
            self.assertEqual((cache / 'fixture.apk').read_bytes(), b'verified asset')

    def test_rejects_unverified_offline_asset(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'workspace').mkdir()
            (root / 'repo/tools').mkdir(parents=True)
            (root / 'repo/tools/fixture.apk').write_bytes(b'tampered asset')
            root_patch, repo_patch, hashes_patch = self.prepare(root, b'verified asset')
            with root_patch, repo_patch, hashes_patch, self.assertRaisesRegex(RuntimeError, 'checksum mismatch'):
                common.fetch_ksu(['fixture.apk'])


if __name__ == '__main__':
    unittest.main()
