"""Retain OEM signing metadata when rebuilding APKs in trusted system images.

Android's system-image scan reads signing certificates without checking APK
content digests. This preserves that metadata; it does not re-sign the modified
APK, which cannot be installed as an ordinary verified user APK.
"""
import struct

MAGIC = b'APK Sig Block 42'


def central_directory(data):
    offset = data.rfind(b'PK\x05\x06', max(0, len(data) - 65557))
    if offset < 0 or offset + 22 > len(data):
        raise RuntimeError('APK ZIP end record is missing.')
    comment = struct.unpack_from('<H', data, offset + 20)[0]
    if offset + 22 + comment != len(data):
        raise RuntimeError('Unexpected APK ZIP end record.')
    central = struct.unpack_from('<I', data, offset + 16)[0]
    if data[central:central + 4] != b'PK\x01\x02':
        raise RuntimeError('APK central directory offset is invalid.')
    return offset, central


def signing_block(data):
    _, central = central_directory(data)
    if data[central - 16:central] != MAGIC:
        raise RuntimeError('OEM APK signing block is missing.')
    size = struct.unpack_from('<Q', data, central - 24)[0]
    start = central - size - 8
    if start < 0 or struct.unpack_from('<Q', data, start)[0] != size:
        raise RuntimeError('OEM APK signing block size is invalid.')
    return data[start:central]


def retain_system_signing(original, rebuilt):
    block = signing_block(original)
    end, central = central_directory(rebuilt)
    if rebuilt[central - 16:central] == MAGIC:
        raise RuntimeError('Rebuilt APK already has signing metadata.')
    result = bytearray(rebuilt[:central] + block + rebuilt[central:])
    struct.pack_into('<I', result, end + len(block) + 16, central + len(block))
    if signing_block(result) != block:
        raise RuntimeError('OEM signing metadata was not preserved.')
    return bytes(result)
