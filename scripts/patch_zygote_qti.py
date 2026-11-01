"""Always preload libqti_performance in zygote on Qualcomm builds."""
import hashlib
import io
import zipfile
import zlib

# One entry per audited framework.jar, keyed by classes5.dex SHA-256.
# ZygoteInit.preloadSharedLibraries gates System.loadLibrary("qti_performance")
# behind Build.isQcomPlatform(), which is false on ranchu (ro.boot.hardware), so
# the QTI Performance natives never bind and the first call kills the process:
# system_server, the camera app and the workload classifier. Nop the if-eqz so
# the library always loads.
PATCHES = {
    # PLK110 17.0.0.105
    '6ed849373a795db2d3f52857883e26478512a4d3a5ef1c1620d173b5cd62d83e': {
        'jar': 'c5687ac90b362607e47959f9b7fb0d893e0fe1dcb49c258fa76cbb07ccb19b37',
        'site': 0x478872,
        'before': bytes.fromhex('7100 1808 0000 0a00 3800 0f00 1b00 7a2f 0100 7110 75f3 0000'.replace(' ', '')),
    },
    # PJF110 16.0.5
    '79abe0f6ed8446ec27345a3e169d94ae6f5ed9896148b1a7a64d6e3c5e395e7e': {
        'jar': '3f0dcf8d8412cc70d8e8837cf5366a9960f2c9527ee377e7f6ff7e6114a6ebdf',
        'site': 0x3c1f42,
        'before': bytes.fromhex('7100 3206 0000 0a00 3800 0f00 1b00 5828 0100 7110 f9e9 0000'.replace(' ', '')),
    },
}

DEX = 'classes5.dex'
IF_EQZ = slice(8, 12)


def patch_dex(data: bytes) -> bytes:
    checksum = hashlib.sha256(data).hexdigest()
    if checksum not in PATCHES:
        raise RuntimeError('Unsupported framework classes5.dex: ' + checksum)
    site = PATCHES[checksum]['site']
    before = PATCHES[checksum]['before']
    if data[site:site + len(before)] != before or data.count(before) != 1:
        raise RuntimeError('Unexpected ZygoteInit qti_performance preload code.')
    dex = bytearray(data)
    dex[site + IF_EQZ.start:site + IF_EQZ.stop] = bytes(4)
    dex[12:32] = hashlib.sha1(dex[32:]).digest()
    dex[8:12] = zlib.adler32(dex[12:]).to_bytes(4, 'little')
    return bytes(dex)


def patch_jar(data: bytes) -> bytes:
    if hashlib.sha256(data).hexdigest() not in {entry['jar'] for entry in PATCHES.values()}:
        raise RuntimeError('Unsupported ColorOS framework.jar.')
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(output, 'w') as target:
        for item in source.infolist():
            content = source.read(item.filename)
            target.writestr(item, patch_dex(content) if item.filename == DEX else content)
    return output.getvalue()
