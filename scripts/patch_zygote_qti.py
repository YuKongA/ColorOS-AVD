"""Always preload libqti_performance in zygote on the Qualcomm PLK110 build."""
import hashlib
import io
import zipfile
import zlib

SOURCE_JAR_SHA256 = 'c5687ac90b362607e47959f9b7fb0d893e0fe1dcb49c258fa76cbb07ccb19b37'
SOURCE_DEX_SHA256 = '6ed849373a795db2d3f52857883e26478512a4d3a5ef1c1620d173b5cd62d83e'
DEX = 'classes5.dex'
# ZygoteInit.preloadSharedLibraries: Build.isQcomPlatform() ? loadLibrary("qti_performance").
# isQcomPlatform is ro.boot.hardware.startsWith("qcom"), which is "ranchu" here and
# must stay so for HAL selection. The QTI Performance natives then never bind and the
# first call from a system thread kills system_server with an UnsatisfiedLinkError.
SITE = 0x478872
BEFORE = bytes.fromhex('7100 1808 0000 0a00 3800 0f00 1b00 7a2f 0100 7110 75f3 0000'.replace(' ', ''))
# Replace only the if-eqz (2 code units) with nops; the UnsatisfiedLinkError handler stays.
IF_EQZ = slice(8, 12)


def patch_dex(data: bytes) -> bytes:
    if hashlib.sha256(data).hexdigest() != SOURCE_DEX_SHA256:
        raise RuntimeError('Unsupported framework classes5.dex.')
    if data[SITE:SITE + len(BEFORE)] != BEFORE or data.count(BEFORE) != 1:
        raise RuntimeError('Unexpected ZygoteInit qti_performance preload code.')
    dex = bytearray(data)
    dex[SITE + IF_EQZ.start:SITE + IF_EQZ.stop] = bytes(4)
    dex[12:32] = hashlib.sha1(dex[32:]).digest()
    dex[8:12] = zlib.adler32(dex[12:]).to_bytes(4, 'little')
    return bytes(dex)


def patch_jar(data: bytes) -> bytes:
    if hashlib.sha256(data).hexdigest() != SOURCE_JAR_SHA256:
        raise RuntimeError('Unsupported ColorOS framework.jar.')
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(output, 'w') as target:
        for item in source.infolist():
            content = source.read(item.filename)
            target.writestr(item, patch_dex(content) if item.filename == DEX else content)
    return output.getvalue()
