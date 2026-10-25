"""Guard firmware profiles and the PLK110 framework.jar patch."""
import hashlib
import io
from pathlib import Path
import re
import sys
import unittest
import zipfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'scripts'))
from firmware_profile import (FIRMWARE, FIX_QTI_PERF_PRELOAD, PORT_CAMERA, PORT_MTK_GRAPHICS,
                              FirmwareProfile, profile_for_archive)
from image_utils import erofs
from patch_zygote_qti import patch_dex, patch_jar
from coloros_camera_sdk import patch_camera_sdk_jar

PLK110_PARTITIONS = REPO / 'work/plk110/input/partitions'
PMX110 = '9b05a00858b964a3fc5891a1873c91ad38aa4786fb729c1a19748214adb868ae'
PLK110 = 'd2a8b95ad93e2eeb3160ad11c6d76f23203c609cddbd45cb67d53fadd919b7ab'


class FirmwareProfileTest(unittest.TestCase):
    def test_unknown_firmware_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'Unsupported ColorOS OTA'):
            profile_for_archive('0' * 64)

    def test_registry_is_keyed_by_archive_sha256(self):
        for key in FIRMWARE:
            self.assertRegex(key, re.compile('[0-9a-f]{64}'))

    def test_pmx110_keeps_every_audited_port(self):
        profile = profile_for_archive(PMX110)
        self.assertEqual(profile.device, 'PMX110')
        self.assertIn(PORT_MTK_GRAPHICS, profile.ports)
        self.assertIn(PORT_CAMERA, profile.ports)
        self.assertEqual((profile.hwui_renderer, profile.gl_preload, profile.fixes, profile.removals),
                         ('skiagl', True, frozenset(), ()))

    def test_plk110_has_no_mediatek_ports(self):
        profile = profile_for_archive(PLK110)
        self.assertEqual(profile.ports, frozenset())
        self.assertIn(FIX_QTI_PERF_PRELOAD, profile.fixes)

    def test_userdata_family_matches_device_identifier(self):
        self.assertEqual(profile_for_archive(PMX110).userdata_family,
                         'coloros-pmx110-api37-ranchu-4k')
        self.assertEqual(profile_for_archive(PLK110).userdata_family,
                         'coloros-plk110-api37-ranchu-4k')

    def test_plk110_turns_off_the_stalling_host_feature_and_pmx110_changes_nothing(self):
        self.assertEqual(profile_for_archive(PLK110).emulator_features,
                         ('-VulkanQueueSubmitWithCommands',))
        self.assertEqual(profile_for_archive(PMX110).emulator_features, ())

    def test_vulkan_renderer_never_preloads_the_gpu_in_zygote(self):
        profile = FirmwareProfile(device='x', coloros='1', native={}, wallpapers=(),
                                  hwui_renderer='skiavk')
        self.assertFalse(profile.gl_preload)

    def test_unknown_renderer_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Unknown HWUI renderer'):
            FirmwareProfile(device='x', coloros='1', native={}, wallpapers=(), hwui_renderer='vulkan')

    def test_wallpapers_are_video_files(self):
        for profile in FIRMWARE.values():
            self.assertTrue(profile.wallpapers)
            self.assertTrue(all(name.endswith('.mp4') for name in profile.wallpapers))


class CameraSdkPatchTest(unittest.TestCase):
    def test_unaudited_sdk_dex_is_rejected_before_building(self):
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, 'w') as jar:
            jar.writestr('classes.dex', b'unaudited dex')
        with self.assertRaisesRegex(RuntimeError, 'Unsupported ColorOS camera SDK DEX'):
            patch_camera_sdk_jar(archive.getvalue(), Path('/nonexistent-sdk'), Path('/nonexistent-work'))


class ZygoteQtiPatchTest(unittest.TestCase):
    def test_unknown_jar_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'Unsupported ColorOS framework.jar'):
            patch_jar(b'unknown framework')

    def test_unknown_dex_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'Unsupported framework classes5.dex'):
            patch_dex(b'unknown dex')

    @unittest.skipUnless((PLK110_PARTITIONS / 'system.img').is_file(), 'PLK110 partitions are not present')
    def test_real_framework_jar_changes_only_the_preload_branch(self):
        original = erofs(PLK110_PARTITIONS / 'system.img', '/system/framework/framework.jar')
        patched = patch_jar(original)
        self.assertNotEqual(hashlib.sha256(patched).hexdigest(), hashlib.sha256(original).hexdigest())
        with zipfile.ZipFile(io.BytesIO(original)) as before, zipfile.ZipFile(io.BytesIO(patched)) as after:
            self.assertEqual(before.namelist(), after.namelist())
            changed = [name for name in before.namelist() if before.read(name) != after.read(name)]
            self.assertEqual(changed, ['classes5.dex'])
            old, new = before.read('classes5.dex'), after.read('classes5.dex')
        self.assertEqual(len(old), len(new))
        # The if-eqz of the Build.isQcomPlatform() check becomes two nops. Past the
        # 32 byte header, which holds the new checksum and signature, nothing else moves.
        branch = 0x478872 + 8
        changed = [i for i in range(32, len(old)) if old[i] != new[i]]
        self.assertTrue(changed)
        self.assertTrue(all(branch <= i < branch + 4 for i in changed))
        self.assertEqual(new[branch:branch + 4], bytes(4))

if __name__ == '__main__':
    unittest.main()
