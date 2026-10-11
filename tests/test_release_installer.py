"""Check atomic release activation, ownership and runtime preservation."""
from contextlib import ExitStack
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import installer
from test_release_files import entry


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        base = Path(self.temporary.name).resolve()
        self.root = base / 'installation'
        self.bundle = base / 'bundle'
        self.bundle.mkdir()
        self.registry = base / 'registry'
        self.registry.mkdir()
        payloads = {'images/system.img': b'system', 'images/encryptionkey.img': b'keys',
                    'images/userdata.img': b'empty', 'tools/ksud-aarch64-linux-android': b'ksud',
                    'config/avd.ini': b'target=android-37.0\nhw.cpu.arch=arm64\n'}
        part = self.bundle / 'fixture.tar.xz.part001'
        with tarfile.open(part, 'w:xz') as tar:
            for name, data in payloads.items():
                item = tarfile.TarInfo(name)
                item.size = len(data)
                tar.addfile(item, io.BytesIO(data))
        self.manifest = {'version': 'v0.1.0-coloros17-r1', 'userdata_family': installer.FAMILY,
                         'build': {'source': 'official-coloros-ota'},
                         'files': {name: entry(data, mode=0o644) for name, data in payloads.items()},
                         'parts': [{'name': part.name, **entry(part.read_bytes())}]}
        self.hardware = installer.validate_options('ColorOS_Test', 5588, 6, 16, 4)
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(installer, 'read_manifest', return_value=(self.manifest, self.bundle)))
        stack.enter_context(patch.object(installer, 'avd_home', return_value=self.registry))
        stack.enter_context(patch.object(installer, 'port_free'))
        stack.enter_context(patch.object(installer.subprocess, 'check_output', return_value=''))
        self.runtime = stack.enter_context(patch.object(installer, 'run_runtime'))

    def install(self):
        return installer.install(self.root, Path('/sdk'), self.bundle / 'manifest.json', 'ColorOS_Test', 5588, self.hardware)

    def test_new_install_produces_versioned_runtime_and_local_wrappers(self):
        self.install()
        self.assertTrue((self.root / 'images').is_symlink())
        self.assertEqual((self.root / 'images/system.img').read_bytes(), b'system')
        self.assertEqual(json.loads((self.root / 'local/runtime.json').read_text())['hardware'], self.hardware)
        for name in ('Start.command', 'Install.command', 'Uninstall.command', 'Setup.command'):
            self.assertTrue((self.root / name).stat().st_mode & 0o111)
        self.runtime.assert_called_once()

    def test_registration_failure_rolls_back_files_and_new_registry(self):
        def fail(*args):
            (self.registry / 'ColorOS_Test.ini').write_text('partial registry')
            raise RuntimeError('registration interrupted')
        self.runtime.side_effect = fail
        with self.assertRaisesRegex(RuntimeError, 'interrupted'):
            self.install()
        self.assertFalse((self.root / 'images').exists())
        self.assertFalse((self.root / 'local/installed-release.json').exists())
        self.assertFalse((self.registry / 'ColorOS_Test.ini').exists())

    def test_foreign_registry_refuses_install_before_download(self):
        path = self.registry / 'ColorOS_Test.ini'
        path.write_text('path=/another/workspace/Test.avd\n')
        with self.assertRaisesRegex(RuntimeError, '其他工作区'):
            self.install()
        self.assertEqual(path.read_text(), 'path=/another/workspace/Test.avd\n')
        self.assertFalse((self.root / 'versions').exists())

    def test_unknown_userdata_is_not_adopted(self):
        (self.root / 'avd').mkdir(parents=True)
        with self.assertRaisesRegex(RuntimeError, '来源不明'):
            self.install()
        self.assertFalse((self.root / 'versions').exists())

    def test_directory_selector_confirms_existing_directory_and_allows_retry(self):
        candidate = self.root / 'candidate'
        candidate.mkdir(parents=True)
        with patch('builtins.input', side_effect=[str(candidate), 'n', str(candidate), '']):
            self.assertEqual(installer.select_root(), candidate.resolve())

    def test_default_root_prefers_current_working_directory(self):
        with patch.object(installer.Path, 'cwd', return_value=self.root):
            self.assertEqual(installer.default_install_root(), self.root)

    def test_repo_working_directory_uses_safe_child_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            current = Path(directory)
            (current / '.git').mkdir()
            with patch.object(installer.Path, 'cwd', return_value=current), \
                    patch.dict(installer.os.environ, {}, clear=True):
                self.assertEqual(installer.default_install_root(), current.resolve() / 'ColorOS-AVD')

    def test_install_form_zero_returns_to_previous_field(self):
        args = type('Args', (), {'bundle': self.bundle / 'manifest.json', 'release': 'latest',
                                 'manifest_sha256': None})()
        values = iter(['/sdk', 'ColorOS_Test', '0', 'ColorOS_Test', '5588', '0',
                       '5588', '6', '0', '6', '16', '0', '16', '4', '1', 'n'])
        with patch('builtins.input', side_effect=lambda _: next(values)), \
                patch.object(installer, 'require_environment', return_value=Path('/sdk')), \
                patch.object(installer, 'install') as install:
            installer.collect_install_options(self.root, {}, args)
        install.assert_called_once()


if __name__ == '__main__':
    unittest.main()
