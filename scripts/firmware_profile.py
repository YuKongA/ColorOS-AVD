"""Per-OTA build profiles: which audited ports and fixes a firmware needs."""
from dataclasses import dataclass

from native_patches import PLK110_PROFILES, PROFILES

# Device ports. Each one patches content that exists only in some firmware, so
# a profile lists exactly the ports whose inputs were audited for that OTA.
PORT_MTK_GRAPHICS = 'mtk_graphics'  # gralloc_extra, ged and composer_ext libraries
PORT_CAMERA = 'camera'              # camera SDK/APK DEX patches and ODM camera configs
PORT_AOD = 'aod'                    # SystemUI AOD patch and its resource overlay
PORT_DOUBLE_TAP = 'double_tap'      # double tap wake bridge

# Compatibility fixes for firmware that is not a MediaTek build.
FIX_ETHERNET_FEATURE = 'ethernet_feature'  # declare android.hardware.ethernet
FIX_QTI_PERF_PRELOAD = 'qti_perf_preload'  # always preload libqti_performance in zygote
FIX_FLAT_DISPLAY = 'flat_display'          # no rounded corners and no camera cutout
FIX_LAUNCHER_UNIRENDER = 'launcher_unirender'  # the launcher draws itself, not through UniRender
FIX_CAMERA_SDK = 'camera_sdk'              # camera SDK patched by name, ODM camera configs baked


@dataclass(frozen=True)
class FirmwareProfile:
    device: str
    coloros: str
    # Audited native library patches by name, see native_patches.py.
    native: dict
    # OEM live wallpaper videos that need an AVC copy for the Ranchu decoder.
    wallpapers: tuple
    ports: frozenset = frozenset()
    fixes: frozenset = frozenset()
    hwui_renderer: str = 'skiagl'
    # Extra emulator -feature settings the launcher passes, such as '-Name' to turn
    # a host feature off.
    emulator_features: tuple = ()
    # Paths in the merged image that are dropped, on top of the shared list.
    removals: tuple = ()

    def __post_init__(self):
        if self.hwui_renderer not in ('skiagl', 'skiavk'):
            raise ValueError('Unknown HWUI renderer: ' + self.hwui_renderer)

    @property
    def gl_preload(self):
        """Whether zygote may preload the GPU before it forks system_server.

        A Vulkan preload leaves /dev/goldfish_pipe_dprctd open in zygote, and
        the fork then aborts with "Not allowlisted". Only GL can be preloaded.
        """
        return self.hwui_renderer == 'skiagl'


FIRMWARE = {
    # OPPO Find X10 Pro Max, MediaTek.
    '9b05a00858b964a3fc5891a1873c91ad38aa4786fb729c1a19748214adb868ae': FirmwareProfile(
        device='PMX110', coloros='17.0.0.114', native=PROFILES,
        wallpapers=('Mars_1.mp4', 'Mars_2.mp4', 'Mars_3.mp4'),
        ports=frozenset({PORT_MTK_GRAPHICS, PORT_CAMERA, PORT_AOD, PORT_DOUBLE_TAP})),
    # OnePlus 15, Qualcomm. No MediaTek libraries and none of the audited camera
    # or AOD DEX sites, so it runs without those ports. Its camera uses the
    # name-based camera_sdk fix instead.
    'd2a8b95ad93e2eeb3160ad11c6d76f23203c609cddbd45cb67d53fadd919b7ab': FirmwareProfile(
        device='PLK110', coloros='17.0.0.105', native=PLK110_PROFILES,
        wallpapers=('Infiniti_1.mp4', 'Infiniti_2.mp4', 'Infiniti_3.mp4'),
        fixes=frozenset({FIX_ETHERNET_FEATURE, FIX_QTI_PERF_PRELOAD, FIX_FLAT_DISPLAY,
                         FIX_LAUNCHER_UNIRENDER, FIX_CAMERA_SDK}),
        hwui_renderer='skiagl',
        # With HWUI and SurfaceFlinger on Vulkan, heavy screens such as the control
        # center make SurfaceFlinger wait in vkQueueWaitIdle for a host that never
        # answers, until the watchdog kills system_server. Software Vulkan does not
        # stall, and turning off submission with commands on the host GPU stops it.
        emulator_features=('-VulkanQueueSubmitWithCommands',),
        removals=('my_product/overlay/oplus_framework_res_overlay.display.product.24831.apk',)),
}


def profile_for_archive(archive_sha256):
    """Return the profile of an OTA, rejecting any firmware that was not audited."""
    try:
        return FIRMWARE[archive_sha256]
    except KeyError:
        raise RuntimeError('Unsupported ColorOS OTA SHA-256: ' + archive_sha256) from None
