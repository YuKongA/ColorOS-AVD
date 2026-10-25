"""Check portable release inventory, xz extraction and resumed downloads."""
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import release_files as release


def entry(data, **extra):
    return {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(), **extra}


class Response(io.BytesIO):
    def __init__(self, data, status=200, headers=None):
        super().__init__(data)
        self.status, self.headers = status, headers or {}

    def getcode(self):
        return self.status


class ReleaseFilesTests(unittest.TestCase):
    def manifest(self):
        paths = (['images/' + p for p in release.IMAGE_FILES]
                 + ['tools/' + p for p in release.TOOLS]
                 + ['runtime/scripts/' + p for p in release.RUNTIME_SCRIPTS] + ['config/avd.ini'])
        files = {p: entry(b'fixture', mode=0o644) for p in paths}
        files['images/userdata.img']['size'] = 16 * 1024**3
        return {'project': 'ColorOS-AVD', 'format': 1, 'platform': 'macos-arm64',
                'compression': 'xz', 'version': 'v0.1.0-coloros17-r1', 'userdata_family': release.FAMILY,
                'build': {'source': 'official-coloros-ota', 'android_api': 37, 'adb_authentication': True,
                          'system_sha256': files['images/system.img']['sha256']},
                'files': files, 'parts': [{'name': 'fixture.tar.xz.part001', **entry(b'part')} ]}

    def test_inventory_refuses_private_state_unknown_runtime_and_wrong_template(self):
        for path in ('avd/userdata-qemu.img', '../secret', 'runtime/scripts/unknown.py'):
            value = self.manifest()
            value['files'][path] = entry(b'secret', mode=0o644)
            with self.subTest(path=path), self.assertRaises(RuntimeError):
                release.validate_manifest(value)
        value = self.manifest()
        value['files']['images/userdata.img']['size'] = 6 * 1024**3
        with self.assertRaisesRegex(RuntimeError, '16 GiB'):
            release.validate_manifest(value)

    def test_current_format_is_accepted(self):
        release.validate_manifest(self.manifest())

    def test_plk110_userdata_family_is_accepted(self):
        value = self.manifest()
        value['userdata_family'] = 'coloros-plk110-api37-ranchu-4k'
        release.validate_manifest(value)

    def test_unsupported_userdata_family_is_rejected(self):
        value = self.manifest()
        value['userdata_family'] = 'coloros-unknown-api37-ranchu-4k'
        with self.assertRaisesRegex(RuntimeError, 'Unsupported ColorOS release manifest'):
            release.validate_manifest(value)

    def test_new_bundle_omits_helper_and_published_bundle_still_validates(self):
        value = self.manifest()
        helper = 'tools/SetWallpaper.dex'
        self.assertNotIn(helper, value['files'])
        release.validate_manifest(value)
        value['files'][helper] = entry(b'legacy helper', mode=0o644)
        release.validate_manifest(value)

    def test_legacy_helper_still_requires_a_valid_checksum(self):
        value = self.manifest()
        value['files']['tools/SetWallpaper.dex'] = entry(b'legacy helper', mode=0o644)
        value['files']['tools/SetWallpaper.dex']['sha256'] = 'invalid'
        with self.assertRaisesRegex(RuntimeError, 'checksum'):
            release.validate_manifest(value)

    def test_complete_and_resumed_downloads_require_full_hash(self):
        payload = b'payload'
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'part'
            target.with_name('part.partial').write_bytes(b'pay')
            response = Response(b'load', 206, {'Content-Range': 'bytes 3-6/7'})
            with patch.object(release, 'secure_urlopen', return_value=response) as opened:
                release.download('https://example.test/part', target, entry(payload))
            self.assertEqual(opened.call_args.args[0].get_header('Range'), 'bytes=3-')
            self.assertEqual(target.read_bytes(), payload)
            with patch.object(release, 'secure_urlopen') as opened:
                release.download('https://example.test/part', target, entry(payload))
                opened.assert_not_called()

    def test_partial_tls_failure_preserves_original_cache(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'part'
            target.write_bytes(b'previous good cache')
            with patch.object(release, 'secure_urlopen', return_value=Response(b'wrong!!')):
                with self.assertRaisesRegex(RuntimeError, 'checksum'):
                    release.download('https://example.test/part', target, entry(b'payload'))
            self.assertEqual(target.read_bytes(), b'previous good cache')

    def test_xz_parts_extract_and_preserve_sparse_file(self):
        payloads = {'images/userdata.img': b'\0' * 2 * 1024**2,
                    'config/avd.ini': b'target=android-37.0\nhw.cpu.arch=arm64\n'}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'archive.tar.xz'
            with tarfile.open(archive, 'w:xz') as tar:
                for name, data in payloads.items():
                    info = tarfile.TarInfo(name)
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))
            data = archive.read_bytes()
            parts = []
            for i in range(0, len(data), 127):
                path = root / str(i)
                path.write_bytes(data[i:i + 127])
                parts.append(path)
            manifest = {'files': {name: entry(data, mode=0o644) for name, data in payloads.items()}}
            output = release.extract_release(parts, manifest, root / 'output')
            for name, expected in payloads.items():
                self.assertEqual((output / name).read_bytes(), expected)
            self.assertLess((output / 'images/userdata.img').stat().st_blocks * 512, len(payloads['images/userdata.img']))

    def test_archive_symlinks_and_traversal_are_rejected(self):
        for name, kind in (('../outside', tarfile.REGTYPE), ('images/system.img', tarfile.SYMTYPE)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                path = root / 'bad.tar.xz'
                with tarfile.open(path, 'w:xz') as tar:
                    info = tarfile.TarInfo(name)
                    info.type, info.linkname = kind, '/private/file'
                    tar.addfile(info)
                with self.assertRaises(RuntimeError):
                    release.extract_release([path], {'files': {name: entry(b'', mode=0o644)}}, root / 'output')
                self.assertFalse((root.parent / 'outside').exists())


if __name__ == '__main__':
    unittest.main()
