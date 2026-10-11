#!/usr/bin/env python3
"""Build an isolated AVD GSI candidate from the official ColorOS 17 OTA."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import zipfile

from native_patches import PROFILES, apply as apply_native_patch, receipt as native_patch_receipt

SOURCE_SHA256 = '9b05a00858b964a3fc5891a1873c91ad38aa4786fb729c1a19748214adb868ae'


def build_native_service(source: Path, sdk: Path, destination: Path) -> bytes:
    """Compile device services from repository sources into the workspace."""
    candidates = list(sdk.glob(
        'ndk/*/toolchains/llvm/prebuilt/darwin-*/bin/aarch64-linux-android35-clang++'))
    if not candidates:
        raise RuntimeError('Install Android NDK with the ARM64 API 35 compiler.')
    compiler = max(candidates, key=lambda p: tuple(int(v) for v in p.parents[5].name.split('.')))
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(compiler), str(source), '-O2', '-fPIE', '-pie',
                    '-static-libstdc++', '-Wl,-z,max-page-size=16384',
                    '-lbinder_ndk', '-llog', '-ldl', '-o', str(destination)], check=True)
    destination.chmod(0o755)
    return destination.read_bytes()


def merged_fstab(data):
    lines = data.splitlines(keepends=True)
    if sum(line.startswith((b'product ', b'system_ext ')) for line in lines) != 4:
        raise RuntimeError('Unexpected first-stage partition mount table.')
    return b''.join(b'#' + line[1:] if line.startswith((b'product ', b'system_ext ')) else line
                    for line in lines)


def patch_ramdisk(path):
    from common import tool
    lz4 = tool('lz4', 'lz4')
    raw = bytearray(subprocess.check_output([lz4, '-dc', str(path)]))
    cursor, matches = 0, 0
    while cursor < len(raw):
        if raw[cursor:cursor + 6] != b'070701':
            idx = raw.find(b'070701', cursor)
            if idx == -1:
                break
            cursor = idx
        header = raw[cursor:cursor + 110]
        size, name_size = int(header[54:62], 16), int(header[94:102], 16)
        name = raw[cursor + 110:cursor + 110 + name_size].rstrip(b'\0')
        start = (cursor + 110 + name_size + 3) // 4 * 4
        if name == b'first_stage_ramdisk/fstab.ranchu':
            raw[start:start + size] = merged_fstab(raw[start:start + size])
            matches += 1
        cursor = (start + size + 3) // 4 * 4
    if matches != 1:
        raise RuntimeError(f'Expected exactly one ranchu fstab in the newc ramdisk, found {matches}.')
    temporary = Path(path).with_suffix('.next.img')
    subprocess.run([lz4, '-l', '-f', '-', str(temporary)], input=raw, check=True, capture_output=True)
    if subprocess.check_output([lz4, '-dc', str(temporary)]) != raw:
        raise RuntimeError('Ramdisk verification failed.')
    temporary.replace(path)

def patch_camera_sdk_jar(data: bytes, diagnostic_log=False) -> bytes:
    import zipfile, io, hashlib, zlib
    buf_in = io.BytesIO(data)
    buf_out = io.BytesIO()
    with zipfile.ZipFile(buf_in, 'r') as zin, zipfile.ZipFile(buf_out, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            content = zin.read(item.filename)
            if item.filename == 'classes.dex':
                if hashlib.sha256(content).hexdigest() != 'cb8309be179afa56964da745b9c62a82a7420671af76af446c363fbbd62ebce8':
                    raise RuntimeError('Unsupported ColorOS camera SDK DEX')
                dex = bytearray(content)
                target = bytes.fromhex('6200a141 6e100a02 0000')
                nop = bytes.fromhex('00000000 00000000 0000')
                p = dex.find(target)
                while p != -1:
                    dex[p:p+10] = nop
                    p = dex.find(target, p+10)
                # Vendor tags are now supplied by the Ranchu bridge.  Keep the
                # SDK's readiness callback intact so CameraUnit can continue
                # into normal stream configuration.
                # Force justParseVendorTag = false in CameraConfigHelper.initialize so full camera init always runs
                seq_perm = bytes.fromhex('7110 8a5c 0300 0a00 1201 3800 0a00 7110 335c 0300 0a00 3900 0400 1210 2802 0110'.replace(' ', ''))
                p_perm = dex.find(seq_perm)
                if p_perm != -1:
                    dex[p_perm:p_perm+32] = bytes.fromhex('1200 1201' + '0000' * 14)
                # 3. Fallback customCameraType to Integer.parseInt(cameraId) so Camera 0 -> "rear_main", Camera 1 -> "front_main"
                p_init = dex.find(bytes.fromhex('380a0500440a0a03280201ba'))
                if p_init != -1:
                    dex[p_init:p_init+12] = bytes.fromhex('7110118d07000a0a00000000')
                # 4. Use unassigned APS mode 4 to select NoneApsImpl with the processor active to avoid MTK vendor libAlgoProcess crash
                target_aps = bytes.fromhex('6000 f551 0f00'.replace(' ', ''))
                p_aps = dex.find(target_aps)
                if p_aps != -1:
                    dex[p_aps:p_aps+6] = bytes.fromhex('1240 0f00 0000')
                # The physical sApsMode still says FULL even though getApsMode
                # selects software preview. Do not advertise ISP capture:
                # portrait/video snapshots otherwise wait for vendor results.
                capture_support = 0x273088
                if (struct.unpack_from('<HHHH', dex, capture_support) != (3, 0, 0, 0)
                        or dex[capture_support + 16:capture_support + 20] != bytes.fromhex('6000 f551')):
                    raise RuntimeError('Unexpected APS capture support method')
                dex[capture_support + 16:capture_support + 38] = bytes.fromhex('1200 0f00') + bytes(18)
                # ApsCaptureResult reads these optional MTK/Oplus arrays without
                # checking vendor tag availability. NoneApsImpl does not use
                # them; leave the SDK's existing null defaults in place.
                for field in ('9849', '9549', '8e49', '9b49', '9c49'):
                    before = bytes.fromhex('6201 ' + field + ' 6e20 806e 1000 0c00')
                    expected = 2 if field == '8e49' else 1
                    if dex.count(before) != expected:
                        raise RuntimeError('Unexpected optional capture metadata reads: ' + field)
                    dex = dex.replace(before, bytes.fromhex('1200') + bytes(len(before) - 2))
                # NoneApsImpl must use the logical camera in the request tag;
                # Google's emulated front HAL reports physical IDs 4/5 and
                # Ranchu's scene HAL has no physical-camera result at all.
                start, end = 0x2721fa, 0x272248
                expected = bytes.fromhex('6e10 1c6e 0700 0c02 6203 5a00')
                if dex[start:start + len(expected)] != expected:
                    raise RuntimeError('Unexpected NoneApsImpl camera ID lookup')
                code = bytes.fromhex(
                    '6e10 1c6e 0700 0c02 '  # ApsPreviewParam.getMetaObj
                    '6e10 1101 0200 0c02 '  # CaptureResult.getRequest
                    '6e10 0a01 0200 0c02 '  # CaptureRequest.getTag
                    '1f02 9c06 5222 bc3c '  # CameraRequestTag.mRearFrontCameraId
                    '5912 b251 1204 1215')  # PreviewFrame.mCameraId, loop constants
                dex[start:end] = code + bytes(end - start - len(code))
                from coloros_camera_yuv import patch_yuv_copier
                patch_yuv_copier(dex)
                from coloros_camera_capture import patch_capture_orientation
                patch_capture_orientation(dex)
                if diagnostic_log:
                    # ALog's JNI loads successfully but its MTK log sink is absent.
                    # Use its existing Android logcat fallback for diagnostics.
                    dex = dex.replace(bytes.fromhex('6300 df44'),
                                      bytes.fromhex('1210 0000'))
                dex[12:32] = hashlib.sha1(dex[32:]).digest()
                dex[8:12] = zlib.adler32(dex[12:]).to_bytes(4, 'little')
                content = bytes(dex)
            zout.writestr(item, content)
    return buf_out.getvalue()


def transcode_wallpaper_video(source: Path, destination: Path) -> bytes:
    """Make the OEM Mars video decodable by the Ranchu media codec.

    The OTA videos are BT.709 SDR but use HEVC Main 10.  Ranchu's bundled
    HEVC decoder cannot parse that profile, while its 8-bit AVC decoder can.
    Keep the source dimensions, frame rate and limited-range BT.709 signalling
    so the wallpaper artwork and luminance mapping stay unchanged.
    """
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise RuntimeError('Install ffmpeg to transcode the OEM Mars wallpapers.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        ffmpeg, '-hide_banner', '-loglevel', 'error', '-y', '-i', str(source),
        '-map', '0:v:0', '-an',
        '-vf', 'scale=in_range=tv:out_range=tv:in_color_matrix=bt709:out_color_matrix=bt709,format=yuv420p',
        '-c:v', 'libx264', '-preset', 'medium', '-crf', '16', '-threads', '4',
        '-profile:v', 'high', '-pix_fmt', 'yuv420p', '-color_range', 'tv',
        '-colorspace', 'bt709', '-color_trc', 'bt709', '-color_primaries', 'bt709',
        '-movflags', '+faststart', str(destination)
    ], check=True)
    return destination.read_bytes()


def patch_camera_apk(data: bytes) -> bytes:
    """Disable only the private-ISP quick-JPEG request in BaseMode.

    Ranchu captures through ordinary Camera2 YUV streams and software APS.
    Retain CameraConfig's feature lookup/defaults for every other feature.
    """
    import io
    import zipfile
    import hashlib
    import zlib
    target = bytes.fromhex('6203 c3c4 1a04 db72 7110 8813 0400 0a04')
    replacement = target[:8] + bytes.fromhex('1204 0000 0000 0000')
    inp, out = io.BytesIO(data), io.BytesIO()
    with zipfile.ZipFile(inp, 'r') as zin, zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            content = zin.read(item.filename)
            if item.filename == 'classes7.dex':
                if hashlib.sha256(content).hexdigest() != 'a1a0bfca85bb3d57706ea9a00cd2a825736f5f4577947835b9c12b73ba5684cd':
                    raise RuntimeError('Unsupported ColorOS Camera BaseMode DEX')
                count = content.count(target)
                if count != 1:
                    raise RuntimeError(f'Unexpected BaseMode quick-JPEG request count: {count}')
                content = content.replace(target, replacement, 1)
                dex = bytearray(content)
                dex[12:32] = hashlib.sha1(dex[32:]).digest()
                dex[8:12] = zlib.adler32(dex[12:]).to_bytes(4, 'little')
                content = bytes(dex)
            zout.writestr(item, content)
    return out.getvalue()


def patch_gralloc_extra_sys(data: bytes) -> bytes:
    return apply_native_patch(data, PROFILES['gralloc'])


def patch_ged_sys(data: bytes) -> bytes:
    return apply_native_patch(data, PROFILES['ged'])


def virtual_camera_config(data: bytes) -> bytes:
    """Keep CameraUnit use cases on streams provided by Ranchu's two cameras.

    MTK tuning/raw/DOL streams have no sizes on Ranchu. CameraUnit otherwise
    fails while selecting a Size, before submitting a Camera2 session.
    """
    config = json.loads(data.decode('utf-8'))
    ordinary = {'preview', 'capture', 'capture_yuv', 'video',
                'video_recorder', 'preview_frame'}
    config['camera_id_list'] = ['0', '1']
    for case, streams in config['usecase_info'].items():
        if not isinstance(streams, list) or any(not isinstance(s, dict) for s in streams):
            raise RuntimeError('Unexpected CameraUnit streams for ' + case)
        config['usecase_info'][case] = [s for s in streams if s and set(s) <= ordinary]
    for case in ('sat_photo_case', 'front_single_photo_case', 'simple_preview_case'):
        if not any('preview' in s for s in config['usecase_info'][case]):
            raise RuntimeError('Virtual camera configuration lost preview: ' + case)
    for mode in config['mode_operation_mode']:
        config['mode_operation_mode'][mode] = '0'
    # Filtering RAW/tuning alone leaves pro/night with no capture stream and
    # portrait with multiple previews for cameras which do not exist on AVD.
    for case in config['usecase_info']:
        if (re.search(r'(^|_)photo(_|$)', case)
                or any(token in case for token in ('portrait', 'professional', 'night_case'))):
            config['usecase_info'][case] = [
                {'preview': 'var_camera'},
                {'capture': 'var_camera'}]
    for mode in config.get('feature_operation_mode', {}):
        config['feature_operation_mode'][mode] = {}
    config['capture_stream_number'] = {}
    config['vendor_tag_type_values']['com.oplus.tuning.data.buffer.support'] = '0'
    config['vendor_tag_type_values']['com.oplus.feature.mtk.insensor.zoom'] = '0'
    # Portrait needs the phone's SAT/depth stream and its ISP bokeh path.
    # Leaving it in mode_type_list makes the UI enter a mode that can never
    # produce a valid Ranchu capture, so remove it from the advertised modes.
    config['mode_cameraType_sensor_number'] = {}
    for role in ('rear_main', 'front_main'):
        modes = config['mode_type_list'][role]
        modes[:] = [mode for mode in modes if mode != 'portrait_mode']
        for mode in ('photo_mode', 'professional_mode', 'night_mode'):
            if mode not in modes:
                modes.append(mode)
    return json.dumps(config, indent=2).encode('utf-8')


def normalize_display_properties(data: bytes, density: int = 560) -> bytes:
    """Keep the framework density in sync with the AVD's physical density.

    Keep the original Find X10 Pro Max logical density. The AVD template uses the
    same high-resolution panel geometry as the OTA identity (1272x2772).
    """
    if density <= 0:
        raise ValueError('density must be positive')
    replacement = f'ro.sf.lcd_density={density}'.encode()
    pattern = re.compile(rb'(?m)^ro\.sf\.lcd_density=\d+[ \t]*$')
    normalized, count = pattern.subn(replacement, data)
    if count == 0:
        normalized += b'\n' + replacement + b'\n'
    return normalized


def main():
    repo = Path(__file__).resolve().parent.parent
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip', type=Path, default=repo / 'rom/9edada09fc494e0cac8151f3ba336907.zip')
    parser.add_argument('--partitions', type=Path, default=repo / 'work/coloros/input/partitions')
    parser.add_argument('--workspace', type=Path, default=repo / 'work/coloros')
    parser.add_argument('--diagnostic-adb', action='store_true',
                        help='Temporarily disable ADB authentication on this isolated candidate')
    args = parser.parse_args()

    workspace = args.workspace.resolve()
    if workspace in (repo, repo / 'work') or workspace in repo.parents:
        raise RuntimeError('Use a separate official candidate workspace.')

    os.environ['COLOROS_AVD_WORKSPACE'] = str(workspace)

    from common import ROOT, fetch_ksu, firmware_idle, host_check, sdk_path, sha256
    from image_utils import erofs
    from erofs_image import Reader, build
    from init_userdata import create
    from lp_image import pack, unpack
    from patch_composer import build_vendor
    from patch_audio import build_vendor as build_audio_vendor
    from patch_camera_scene import build_vendor as build_scene_vendor
    from setup import configure

    host_check()
    firmware_idle(5574)

    if not args.zip.is_file():
        raise RuntimeError(f'ColorOS OTA zip not found at {args.zip}')

    archive_sha256 = sha256(args.zip)
    if archive_sha256 != SOURCE_SHA256:
        raise RuntimeError(f'Unsupported ColorOS OTA SHA-256: {archive_sha256}; expected {SOURCE_SHA256}')

    base = sdk_path() / 'system-images/android-36/google_apis_playstore/arm64-v8a'
    if not base.is_dir() or 'Pkg.Revision=7' not in (base / 'source.properties').read_text().splitlines():
        raise RuntimeError('Use the verified API 36 ARM64 revision 7 hardware base.')

    for directory in ('work', 'images', 'logs', 'config', 'local', 'tools'):
        (ROOT / directory).mkdir(parents=True, exist_ok=True)

    partitions = args.partitions.resolve()
    partitions.mkdir(parents=True, exist_ok=True)

    required = (
        'system', 'system_ext', 'product',
        'my_product', 'my_stock', 'my_region',
        'my_heytap', 'my_carrier', 'my_engineering',
        'my_manifest', 'my_bigball', 'odm'
    )

    if any(not (partitions / (name + '.img')).exists() for name in required):
        dumper = shutil.which('payload-dumper-go') or Path.home() / 'go/bin/payload-dumper-go'
        if not Path(dumper).is_file():
            dumper = repo / 'tools/payload-dumper-go'
        if not Path(dumper).is_file():
            raise RuntimeError('Install payload-dumper-go first.')
        print('Extracting required partitions from ColorOS OTA zip...', flush=True)
        subprocess.run([
            str(dumper), '-c', '4', '-p', ','.join(required),
            '-o', str(partitions), str(args.zip.resolve())
        ], check=True)

    system = partitions / 'system.img'
    prop = erofs(system, '/system/build.prop')
    product = erofs(partitions / 'product.img', '/etc/build.prop')

    if b'ro.system.build.version.sdk=37' not in prop and b'ro.build.version.sdk=37' not in prop:
        raise RuntimeError('Unexpected source partition version (expected Android 17 / SDK 37).')

    # ColorOS Euclid properties from my_manifest and my_product
    manifest_prop = erofs(partitions / 'my_manifest.img', '/build.prop')
    my_product_prop = erofs(partitions / 'my_product.img', '/build.prop')

    software_prefixes = (
        b'ro.oplus.', b'ro.coloros.', b'ro.product.vendor.',
        b'ro.product.odm.', b'ro.build.version.oplus',
        b'persist.sys.oplus.', b'persist.sys.hardcoder',
        b'ro.vendor.oplus.'
    )
    software_keys = (
        b'ro.product.model', b'ro.product.name', b'ro.product.device',
        b'ro.product.brand', b'ro.product.manufacturer',
        b'ro.build.oplus_ext_partitions', b'ro.build.version.ota',
        b'ro.oplus.product.series', b'ro.sys.oplus_support_app32_version'
    )

    identity = []
    for source in (manifest_prop, my_product_prop):
        for line in source.splitlines():
            line = line.strip()
            if not line or line.startswith(b'#'):
                continue
            key = line.partition(b'=')[0]
            if line.startswith(software_prefixes) or key in software_keys:
                if line not in identity:
                    identity.append(line)
    for cid in (
        b'ro.sf.lcd_density=560',
        b'ro.oplus.resolution.high=1272,2772',
        b'ro.oplus.system.camera.name=com.oplus.camera',
        # Ranchu can provide YUV/JPEG but has no JPEG_R/10-bit stream.  The
        # real device advertises this flag, which makes ColorOS request the
        # unsupported format and leaves the preview surface black.
        b'oplus.software.camera.10bit=0',
        b'ro.vendor.oplus.camera.backCamSize=200MP+200MP+200MP',
        b'ro.vendor.oplus.camera.frontCamSize=50MP',
        b'ro.vendor.oplus.camera.isHasselbladCamera=0',
        b'ro.oplus.image.odm.type=26015',
        b'ro.odm.build.media_performance_class=37',
    ):
        if cid not in identity:
            identity.append(cid)
    product += b'\n# Official ColorOS Euclid software identity for the ranchu vendor.\n'
    product += b'\n'.join(identity) + b'\n'

    print('Preparing the official ColorOS candidate on an isolated AVD workspace.', flush=True)
    unpack(base / 'system.img', ROOT / 'work/base')

    vendor = ROOT / 'work/vendor.img'
    shutil.copyfile(ROOT / 'work/base/vendor.img', vendor)

    fstab = erofs(vendor, '/etc/fstab.ranchu')
    patched_fstab = merged_fstab(fstab)
    content = vendor.read_bytes()
    if content.count(fstab) != 1 or content.count(b'ro.zygote.disable_gl_preload=1') != 1:
        raise RuntimeError('Unexpected ranchu vendor layout.')
    vendor.write_bytes(content.replace(fstab, patched_fstab).replace(
        b'ro.zygote.disable_gl_preload=1', b'ro.zygote.disable_gl_preload=0'))

    composer_manifest = build_vendor(vendor, ROOT / 'work/vendor-alpha-fixed.img',
                                     ROOT / 'work/vendor-alpha-tree')
    (ROOT / 'work/vendor-alpha-fixed.img').replace(vendor)

    audio_manifest = build_audio_vendor(vendor, ROOT / 'work/vendor-audio-fixed.img',
                                        ROOT / 'work/vendor-audio')
    (ROOT / 'work/vendor-audio-fixed.img').replace(vendor)

    scene_manifest = build_scene_vendor(vendor, ROOT / 'work/vendor-scene-fixed.img',
                                        ROOT / 'work/vendor-scene', sdk_path())
    (ROOT / 'work/vendor-scene-fixed.img').replace(vendor)

    if (partitions / 'odm.img').is_file():
        print('Baking ODM camera configs into vendor image...', flush=True)
        odm_reader = Reader(partitions / 'odm.img')
        camera_configs = {}
        from coloros_camera_profiles import disable_portrait_mode, virtual_media_profiles
        camera_configs['etc/media_profiles_V1_0.xml'] = (
            virtual_media_profiles(erofs(vendor, '/etc/media_profiles_V1_0.xml')),
            0o644, 'u:object_r:vendor_configs_file:s0')
        for p, _ in odm_reader.walk():
            if p.startswith('etc/camera/config') and not p.endswith('/'):
                data = erofs(partitions / 'odm.img', '/' + p)
                rel = p.removeprefix('etc/camera/config/')
                if rel == 'camera_unit_config':
                    data = virtual_camera_config(data)
                elif rel == 'camera_unit_feature_config.protobuf':
                    data = disable_portrait_mode(data)
                if rel:
                    camera_configs['odm/etc/camera/config/' + rel] = (data, 0o644, 'u:object_r:vendor_configs_file:s0')
        if 'odm/etc/camera/config/camera_unit_feature_config.protobuf' in camera_configs:
            from coloros_camera_profiles import pack_feature_config
            pb_data = camera_configs['odm/etc/camera/config/camera_unit_feature_config.protobuf'][0]
            vendor_map = [
                'com.oplus.camera.capture.hdr.cap.mode.value:common,photo,video,night',
                'com.oplus.camera.preview.hdr.cap.mode.value:common,photo,video,night',
                'com.oplus.camera.support.activity.rotate:0',
                'com.oplus.feature.breeno.scan:0'
            ]
            packed = pack_feature_config(pb_data, vendor_map)
            camera_configs['odm/etc/camera/config/oplus_camera_feature_config'] = (packed, 0o644, 'u:object_r:vendor_configs_file:s0')
        sec_so = erofs(partitions / 'odm.img', '/lib64/libOplusSecurity.so')
        camera_configs['lib64/libOplusSecurity.so'] = (sec_so, 0o644, 'u:object_r:same_process_hal_file:s0')
        camera_configs['odm/lib64/libOplusSecurity.so'] = (sec_so, 0o644, 'u:object_r:same_process_hal_file:s0')
        build(ROOT / 'work/vendor-odm-fixed.img', [('', vendor)], ROOT / 'work/vendor-odm-tree', camera_configs)
        (ROOT / 'work/vendor-odm-fixed.img').replace(vendor)
    replacements = {}
    def put(path, data, mode=0o644, label='u:object_r:system_file:s0'):
        replacements[path] = (data, mode, label)

    from connectivity_overlay import build as build_connectivity_overlay
    put('product/overlay/ColorOSConnectivityOverlay/ColorOSConnectivityOverlay.apk',
        build_connectivity_overlay(sdk_path(), ROOT / 'work/connectivity-overlay'))
    from resource_overlay import build as build_resource_overlay
    put('product/overlay/ColorOSAodOverlay/ColorOSAodOverlay.apk',
        build_resource_overlay(repo / 'native/coloros_aod', sdk_path(),
                               ROOT / 'work/aod-overlay', 'ColorOSAodOverlay.apk'))
    from coloros_aod import patch_systemui_apk
    put('system_ext/priv-app/SystemUI/SystemUI.apk', patch_systemui_apk(
        erofs(partitions / 'system_ext.img', '/priv-app/SystemUI/SystemUI.apk'),
        sdk_path(), ROOT / 'work/aod-systemui'))
    from double_tap_wake import build as build_double_tap_wake
    wake_dex, wake_library = build_double_tap_wake(sdk_path(), ROOT / 'work/double-tap-wake')
    put('system_ext/framework/ColorOSDoubleTapWake.dex', wake_dex)
    put('system_ext/lib64/libcoloros_double_tap.so', wake_library,
        label='u:object_r:system_lib_file:s0')

    # Patch system/build.prop
    prop = normalize_display_properties(prop)
    product = normalize_display_properties(product)
    # Euclid loads my_product/build.prop after the merged system properties.
    # Patch the source file itself so its panel density cannot reintroduce the
    # physical 560 dpi value at boot.
    put('my_product/build.prop', normalize_display_properties(my_product_prop),
        0o644, 'u:object_r:vendor_configs_file:s0')
    prop = prop.replace(
        b'media.settings.xml=/vendor/etc/media_profiles_vendor.xml',
        b'media.settings.xml=/vendor/etc/media_profiles_V1_0.xml'
    )
    if args.diagnostic_adb:
        prop = prop.replace(b'ro.adb.secure=1', b'ro.adb.secure=0')
    prop += b'\n# ColorOS-AVD virtual hardware and native effects.\n'
    prop += b'ro.mediaserver.64b.enable=true\n'
    prop += b'debug.hwui.renderer=skiagl\n'
    prop += b'debug.renderengine.backend=skiavkthreaded\n'
    prop += b'persist.sys.background_blur_supported=true\n'
    put('system/build.prop', prop, 0o600)

    # Put updated product/etc/build.prop and euclid_build.prop
    put('product/etc/build.prop', product)
    put('system/euclid_build.prop', b'\n'.join(identity) + b'\n')
    # Patch com.oplus.camera.unit.sdk.jar to remove main-thread blocking deadlock
    raw_sdk_jar = erofs(partitions / 'my_product.img', '/product_overlay/framework/com.oplus.camera.unit.sdk.jar')
    put('product/framework/com.oplus.camera.unit.sdk.jar', patch_camera_sdk_jar(raw_sdk_jar, diagnostic_log=True))
    raw_camera_apk = erofs(partitions / 'my_product.img', '/app/OplusCamera/OplusCamera.apk')
    from coloros_camera_buffers import patch_camera_buffers_apk
    put('my_product/app/OplusCamera/OplusCamera.apk', patch_camera_buffers_apk(
        patch_camera_apk(raw_camera_apk), sdk_path(), ROOT / 'work/camera-bridge',
        signing_source=raw_camera_apk))
    if (partitions / 'odm.img').is_file():
        sec_so = erofs(partitions / 'odm.img', '/lib64/libOplusSecurity.so')
        put('product/lib64/libOplusSecurity.so', sec_so, 0o644, 'u:object_r:system_lib_file:s0')
    # Patch libgralloc_extra_sys.so to prevent bad handle rejection on AVD emulator buffers
    raw_ge_so = erofs(partitions / 'system_ext.img', '/lib64/libgralloc_extra_sys.so')
    put('system_ext/lib64/libgralloc_extra_sys.so', patch_gralloc_extra_sys(raw_ge_so),
        label='u:object_r:system_lib_file:s0')
    raw_ged_so = erofs(partitions / 'system_ext.img', '/lib64/libged_sys.so')
    put('system_ext/lib64/libged_sys.so', patch_ged_sys(raw_ged_so),
        label='u:object_r:system_lib_file:s0')
    put('system_ext/lib64/libcomposer_ext.so',
        apply_native_patch(erofs(partitions / 'system_ext.img', '/lib64/libcomposer_ext.so'),
                           PROFILES['composer_ext']), label='u:object_r:system_lib_file:s0')

    # Put all camera JNI and rendering libraries into product/lib64 with proper system_lib_file context
    my_product_reader = Reader(partitions / 'my_product.img')
    for p, _ in my_product_reader.walk():
        if p.startswith('lib64/') and p.endswith('.so'):
            so_data = erofs(partitions / 'my_product.img', '/' + p)
            put('product/' + p, so_data, 0o644, 'u:object_r:system_lib_file:s0')
    # Ranchu ADB setup script in system_ext
    name = 'init.ranchu.adb.setup.sh'
    domain = 'goldfish_system_setup'
    put('system_ext/bin/' + name, erofs(ROOT / 'work/base/system_ext.img', '/bin/' + name),
        0o755, 'u:object_r:' + domain + '_exec:s0')

    contexts = erofs(partitions / 'system_ext.img', '/etc/selinux/system_ext_file_contexts')
    contexts += ('\n/system_ext/bin/' + re.escape(name) + ' u:object_r:' + domain + '_exec:s0\n').encode()
    contexts += b'/system_ext/bin/vendor.oplus.hardware.sendextcamcmd-service u:object_r:hal_camera_default_exec:s0\n'
    put('system_ext/etc/selinux/system_ext_file_contexts', contexts)

    prop_contexts = erofs(partitions / 'system_ext.img', '/etc/selinux/system_ext_property_contexts')
    prop_contexts += b'\n# Emulator boot transport properties.\n'
    prop_contexts += b'ro.boot.qemu. u:object_r:bootloader_prop:s0\n'
    prop_contexts += b'ro.boot.hardware.gltransport u:object_r:bootloader_prop:s0 exact string\n'
    put('system_ext/etc/selinux/system_ext_property_contexts', prop_contexts)

    svc_contexts = erofs(partitions / 'system_ext.img', '/etc/selinux/system_ext_service_contexts')
    svc_contexts += b'\nvendor.oplus.hardware.urcc.IUrcc/default u:object_r:oplus_resource_manager_service:s0\n'
    svc_contexts += b'vendor.oplus.hardware.sendextcamcmd.ISendExtCamCmdService/default u:object_r:hal_camera_service:s0\n'
    put('system_ext/etc/selinux/system_ext_service_contexts', svc_contexts)

    # Init script
    init = erofs(ROOT / 'work/base/system_ext.img', '/etc/init/init.system_ext.rc')
    init += b'\n' + erofs(ROOT / 'work/base/system_ext.img', '/etc/init/init.system_ext.radio.rc')
    init += b'\non post-fs-data\n'
    init += b'    setprop persist.sys.usb.config adb\n'
    init += b'    setprop sys.usb.config adb\n'
    init += b'    setprop debug.renderengine.backend skiavkthreaded\n'
    init += b'    setprop persist.sys.background_blur_supported true\n'
    init += b'\non property:ro.persistent_properties.ready=true\n'
    init += b'    setprop persist.sys.background_blur_supported true\n'
    init += b'\nservice vendor.urcc-default /system_ext/bin/vendor.oplus.hardware.urcc-service\n'
    init += b'    class hal\n    user root\n    group root system\n    seclabel u:r:su:s0\n'
    init += b'\nservice vendor.sendextcamcmd-default /system_ext/bin/vendor.oplus.hardware.sendextcamcmd-service\n'
    init += b'    class hal\n    user root\n    group root camera system\n    seclabel u:r:hal_camera_default:s0\n'
    put('system_ext/etc/init/init.coloros_avd.rc', init)

    # URCC Stub HAL daemon and VINTF manifest
    urcc_bin = build_native_service(
        repo / 'native/urcc_service.cpp', sdk_path(),
        ROOT / 'work/native-services/vendor.oplus.hardware.urcc-service')
    put('system_ext/bin/vendor.oplus.hardware.urcc-service', urcc_bin, 0o755)
    sendext_bin = build_native_service(
        repo / 'native/sendextcamcmd_service.cpp', sdk_path(),
        ROOT / 'work/native-services/vendor.oplus.hardware.sendextcamcmd-service')
    put('system_ext/bin/vendor.oplus.hardware.sendextcamcmd-service', sendext_bin, 0o755,
        'u:object_r:hal_camera_default_exec:s0')
    sendext_manifest = erofs(partitions / 'odm.img',
                              '/etc/vintf/manifest/manifest_oplus_sendextcamcmd.xml')
    sendext_manifest = sendext_manifest.replace(b'type="device"', b'type="framework"')
    put('system_ext/etc/vintf/manifest/manifest_oplus_sendextcamcmd.xml', sendext_manifest)

    # Patch libhwui.so to fix GLSL ES 1.00 syntax error in OplusCausticShadowEffect
    hwui_data = erofs(system, '/system/lib64/libhwui.so')
    put('system/lib64/libhwui.so', apply_native_patch(hwui_data, PROFILES['hwui']),
        0o644, 'u:object_r:system_lib_file:s0')
    put('system/lib64/libbluetooth_jni.so',
        apply_native_patch(erofs(system, '/system/lib64/libbluetooth_jni.so'), PROFILES['bluetooth']),
        0o644, 'u:object_r:system_lib_file:s0')
    cached = (
        'ksud-aarch64-apple-darwin', 'lkm-aarch64-android15-6.6_kernelsu.ko',
        'ksud-aarch64-linux-android', 'KernelSU_v3.3.0_32601-release.apk'
    )
    fetch_ksu(cached)

    # Preinstall KernelSU manager into system/app so it is available out of the box
    ksu_apk = (ROOT / 'tools/KernelSU_v3.3.0_32601-release.apk').read_bytes()
    put('system/app/KernelSU/KernelSU.apk', ksu_apk)

    # Keep the OEM Mars components as the default wallpaper.  The OTA videos
    # are BT.709 SDR HEVC Main 10, which the Ranchu HEVC decoder cannot parse;
    # transcode only the video payload to 8-bit AVC while retaining the OEM
    # component mapping and visual content.
    wallpaper_root = '/decouping_wallpaper/default/liveWallpaper/'
    (ROOT / 'work' / 'wallpaper-source').mkdir(parents=True, exist_ok=True)
    for name in ('Mars_1.mp4', 'Mars_2.mp4', 'Mars_3.mp4'):
        source = ROOT / 'work' / 'wallpaper-source' / name
        source.write_bytes(erofs(partitions / 'my_product.img', wallpaper_root + name))
        data = transcode_wallpaper_video(source, ROOT / 'work' / 'wallpaper-avc' / name)
        put('my_product' + wallpaper_root + name, data)

    image = ROOT / 'work/coloros-system.img'
    merge_list = [
        ('', system),
        ('system_ext', partitions / 'system_ext.img'),
        ('product', partitions / 'product.img'),
        ('product:product_overlay', partitions / 'my_product.img'),
        ('my_product', partitions / 'my_product.img'),
        ('my_stock', partitions / 'my_stock.img'),
        ('my_region', partitions / 'my_region.img'),
        ('my_heytap', partitions / 'my_heytap.img'),
        ('my_carrier', partitions / 'my_carrier.img'),
        ('my_engineering', partitions / 'my_engineering.img'),
        ('my_manifest', partitions / 'my_manifest.img'),
        ('my_bigball', partitions / 'my_bigball.img'),
    ]

    print('Merging ColorOS Euclid partitions into standalone system EROFS...', flush=True)
    removals = (
        'product/framework/oat/arm64/com.oplus.camera.unit.sdk.odex',
        'product/framework/oat/arm64/com.oplus.camera.unit.sdk.vdex',
        # Remove the requested application shells. The similarly named system
        # components that were not requested (for example VideoGallery and
        # MyDevices) remain in the merged image.
        'my_stock/del-app/KeKeUserCenterMember',   # 我的 OPPO
        'my_stock/del-app/OPPOStore',              # OPPO 商城
        'my_stock/del-app/OplusQuickGame',         # 小游戏
        'my_stock/del-app/Gamecenter',             # 游戏中心
        'my_stock/del-app/OppoCompass2',           # 指南针
        'my_stock/del-app/OppoNote2',              # 笔记
        'my_stock/del-app/AIPaper',                # NoteBook/笔记
        'my_stock/del-app/OcrScanner',             # AI 拍一拍
        'my_stock/del-app/NewSoundRecorder',       # 录音
        'my_stock/del-app/OplusEmail',             # 邮件
        'my_stock/del-app/OplusDocumentsReader',   # 文档阅读器
        'my_stock/del-app/OppoTranslation',        # 翻译
        'my_stock/del-app/FamilyGuard',            # 家人守护
        'my_stock/del-app/Tips',                   # 使用技巧
        'my_stock/del-app/OPBreathMode',           # 禅定空间
        'my_stock/priv-app/TravelEngine',          # 逍遥游
        'my_stock/del-app/BackupAndRestore',       # 手机搬家
        'my_stock/del-app/BrowserVideo',           # OPPO 视频
        'my_stock/del-app/Music',                  # 音乐
        'my_stock/del-app/FinShellWallet',         # 钱包
        'my_product/del-app/SogouInput_U_Product_Del',  # 搜狗输入法定制版
        'my_product/del-app/heytapbook',           # 书城
        'my_product/priv-app/RemoteControl',       # 红外遥控
    )
    build(image, merge_list, ROOT / 'work/official-tree', replacements, removals=removals)

    for path in base.iterdir():
        if path.is_file() and path.name not in ('system.img', 'package.xml'):
            shutil.copy2(path, ROOT / 'images' / path.name)
    for relative in ('data/misc/modem_simulator', 'data/misc/emulator'):
        shutil.copytree(base / relative, ROOT / 'images' / relative, dirs_exist_ok=True)

    print('Patching ramdisk with KernelSU...', flush=True)
    with (ROOT / 'logs/kernelsu-patch.log').open('wb') as log:
        subprocess.run([
            str(ROOT / 'tools/ksud-aarch64-apple-darwin'), 'boot-patch',
            '-b', str(ROOT / 'images/ramdisk.img'), '--ramdisk', '--kmi', 'android15-6.6',
            '--allow-shell', '-m', str(ROOT / 'tools/lkm-aarch64-android15-6.6_kernelsu.ko'),
            '-o', str(ROOT / 'work'), '--out-name', 'ramdisk-kernelsu.img'
        ], check=True, stdout=log, stderr=subprocess.STDOUT)

    shutil.copy2(ROOT / 'work/ramdisk-kernelsu.img', ROOT / 'images/ramdisk.img')
    print('Patching ramdisk fstab...', flush=True)
    patch_ramdisk(ROOT / 'images/ramdisk.img')

    print('Creating clean userdata...', flush=True)
    create()

    print('Packing super GPT image...', flush=True)
    pack(base / 'system.img', ROOT / 'images/system.img', [
        ('system', image),
        ('vendor', vendor),
        ('system_dlkm', ROOT / 'work/base/system_dlkm.img')
    ])

    avd_ini = f"""avd.ini.encoding=UTF-8
avd.ini.displayname=ColorOS 17 Official - Android 17
abi.type=arm64-v8a
hw.cpu.arch=arm64
hw.cpu.ncore=4
hw.ramSize=6144
hw.lcd.width=1272
hw.lcd.height=2772
hw.lcd.density=560
hw.lcd.depth=32
hw.lcd.vsync=60
hw.gpu.enabled=yes
hw.gpu.mode=host
hw.gps=yes
hw.gsmModem=yes
hw.camera.back=virtualscene
hw.camera.front=emulated
hw.audioInput=yes
hw.audioOutput=yes
hw.battery=yes
hw.keyboard=yes
hw.mainKeys=no
hw.dPad=no
hw.trackBall=no
hw.sensors.orientation=yes
hw.sensors.proximity=yes
hw.sensors.magnetic_field=yes
hw.sensors.accelerometer=yes
hw.useext4=yes
disk.dataPartition.size=16G
disk.cachePartition=yes
disk.cachePartition.size=66MB
PlayStore.enabled=false
showDeviceFrame=no
fastboot.forceColdBoot=yes
fastboot.forceFastBoot=no
firstboot.saveToLocalSnapshot=no
tag.id=google_apis_playstore
tag.display=ColorOS Official
target=android-37.0
kernel.parameters=androidboot.selinux=enforcing
runtime.network.latency=none
runtime.network.speed=full
vm.heapSize=256M
"""
    (ROOT / 'config/avd.ini').write_text(avd_ini)

    metadata = {
        'coloros': '17.0.0.114',
        'source': 'official-coloros-ota',
        'android_api': 37,
        'archive_sha256': archive_sha256,
        'kernel_page_size': 4096,
        'hardware_base_api': 36,
        'kernel_kmi': 'android15-6.6',
        'surfaceflinger_backend': 'skiavkthreaded',
        'composer_alpha_fix': composer_manifest,
        'audio_pcm_fix': audio_manifest,
        'camera_scene_fix': scene_manifest,
        'native_patches': native_patch_receipt(),
        'double_tap_wake': {
            'system_ext/framework/ColorOSDoubleTapWake.dex': hashlib.sha256(wake_dex).hexdigest(),
            'system_ext/lib64/libcoloros_double_tap.so': hashlib.sha256(wake_library).hexdigest(),
        },
        'adb_authentication': not args.diagnostic_adb,
    }
    (ROOT / 'local/build.json').write_text(json.dumps(metadata, indent=2) + '\n')

    name = 'ColorOS17_API37'
    port = 5574
    configure(sdk_path(), name, port)
    print(f'ColorOS GSI candidate ready: {name} (emulator-{port}).', flush=True)


if __name__ == '__main__':
    main()
