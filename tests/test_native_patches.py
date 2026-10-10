"""Reject unknown OEM libraries and verify every fixed byte edit."""
from dataclasses import replace
import hashlib
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from image_utils import erofs
from native_patches import PROFILES, Site, apply

PARTITIONS = Path(__file__).resolve().parents[1] / 'work/coloros/input/partitions'


class NativePatchTests(unittest.TestCase):
    def test_unknown_libraries_are_rejected(self):
        for profile in PROFILES.values():
            with self.subTest(path=profile.path), self.assertRaisesRegex(RuntimeError, 'Unsupported'):
                apply(b'unknown OEM library', profile)

    def test_input_hash_does_not_replace_site_verification(self):
        data = b'original'
        profile = replace(PROFILES['ged'], before=hashlib.sha256(data).hexdigest(),
                          sites=(Site(0, b'wrong', b'other'),))
        with self.assertRaisesRegex(RuntimeError, 'bytes'):
            apply(data, profile)

    def test_wrong_output_hash_is_rejected(self):
        data = b'original'
        profile = replace(PROFILES['ged'], before=hashlib.sha256(data).hexdigest(),
                          sites=(Site(0, b'original', b'modified'),))
        with self.assertRaisesRegex(RuntimeError, 'output checksum'):
            apply(data, profile)

    @unittest.skipUnless((PARTITIONS / 'system_ext.img').exists() and (PARTITIONS / 'system.img').exists(), 'Official ColorOS partitions not present')
    def test_real_ota_inputs_have_only_the_audited_bytes_changed(self):
        for profile in PROFILES.values():
            with self.subTest(path=profile.path):
                partition, _, path = profile.path.partition('/')
                path = '/system/' + path if partition == 'system' else '/' + path
                source = erofs(PARTITIONS / (partition + '.img'), path)
                result = apply(source, profile)
                self.assertEqual(hashlib.sha256(result).hexdigest(), profile.after)
                self.assertEqual(apply(result, profile), result)
                allowed = set()
                for site in profile.sites:
                    offset = site.offset if site.offset is not None else source.index(site.original)
                    allowed.update(range(offset, offset + len(site.original)))
                changed = {i for i, pair in enumerate(zip(source, result)) if pair[0] != pair[1]}
                self.assertTrue(changed <= allowed)
                self.assertEqual(len(result), len(source))


if __name__ == '__main__':
    unittest.main()
