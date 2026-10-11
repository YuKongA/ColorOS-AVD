"""Enable the OEM panoramic AOD renderer on a Ranchu virtual display."""
import hashlib
import io
from pathlib import Path
import struct
import subprocess
import zipfile
import zlib

SOURCE_APK_SHA256 = '9a2a917f90f1824314f0ea223a3624efd30dfc95bc940304974da544b1764a03'
SOURCE_DEX_SHA256 = '7ead4e33e139115270c3848bd1a5f28ad4438245f6bbbeeed1e1e2abc9a3380b'
PATCHED_DEX_SHA256 = '84c2a719f61fd053ab14ce1b75cc91843d46c67208f4fd2802ab7a1b8a8b9910'
PANEL_FALLBACK_OFFSET = 0x49bfa8


def patch_panel_fallback(data: bytes) -> bytes:
    """Supply only the software AOD flags in the missing-HAL fallback.

    SmoothTransitionController first queries AIDL, then falls back to this
    HIDL method. Ranchu has neither panel service. Query 217 returns [13]:
    bit 0 avoids blanking the display on entry, bit 2 permits panoramic AOD,
    bit 3 permits its all-day mode. Smooth panel transitions (bit 1) stay off.
    Other queries return null, retaining their unsupported default behavior.
    """
    if hashlib.sha256(data).hexdigest() != SOURCE_DEX_SHA256:
        raise RuntimeError('Unsupported ColorOS SystemUI AOD DEX.')
    offset = PANEL_FALLBACK_OFFSET
    if (struct.unpack_from('<HHHH', data, offset) != (9, 1, 5, 3)
            or data[offset + 16:offset + 24] != bytes.fromhex('1a00d97e1a014a1f')):
        raise RuntimeError('Unexpected SystemUI panel fallback method.')
    # if (featureId != 217) return null; else return new int[] {13};
    # Reuse the existing [I type ID. Keep code_item length, registers, catch
    # handlers and every offset unchanged; the old body is unreachable.
    code = bytes.fromhex('1300d90033080b0012102300724013010d0012024b010002110012001100')
    dex = bytearray(data)
    dex[offset + 16:offset + 16 + len(code)] = code
    dex[12:32] = hashlib.sha1(dex[32:]).digest()
    dex[8:12] = zlib.adler32(dex[12:]).to_bytes(4, 'little')
    result = bytes(dex)
    if hashlib.sha256(result).hexdigest() != PATCHED_DEX_SHA256:
        raise RuntimeError('SystemUI AOD patch output checksum mismatch.')
    return result


def patch_systemui_apk(data: bytes, sdk: Path, work: Path) -> bytes:
    if hashlib.sha256(data).hexdigest() != SOURCE_APK_SHA256:
        raise RuntimeError('Unsupported ColorOS SystemUI APK.')
    work.mkdir(parents=True, exist_ok=True)
    tools = sdk / 'build-tools/36.0.0'
    unaligned, aligned = work / 'unaligned.apk', work / 'SystemUI.apk'
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(unaligned, 'w') as output:
        for entry in source.infolist():
            content = source.read(entry.filename)
            if entry.filename == 'classes3.dex':
                content = patch_panel_fallback(content)
                dex = work / 'classes3.dex'
                dex.write_bytes(content)
                subprocess.run([str(tools / 'dexdump'), '-f', str(dex)],
                               check=True, stdout=subprocess.DEVNULL)
            output.writestr(entry, content)
    subprocess.run([str(tools / 'zipalign'), '-P', '16', '-f', '4',
                    str(unaligned), str(aligned)], check=True)
    from apk_system_signing import retain_system_signing
    result = retain_system_signing(data, aligned.read_bytes())
    aligned.write_bytes(result)
    subprocess.run([str(tools / 'zipalign'), '-c', '-P', '16', '4', str(aligned)], check=True)
    return result
