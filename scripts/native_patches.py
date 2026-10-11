"""Content-pinned edits for the audited ColorOS native libraries."""
from dataclasses import dataclass
import hashlib


@dataclass(frozen=True)
class Site:
    offset: int | None
    original: bytes
    replacement: bytes


@dataclass(frozen=True)
class Profile:
    path: str
    before: str
    after: str
    sites: tuple[Site, ...]


RETURN_ZERO = bytes.fromhex('00008052c0035fd6')
PROFILES = {
    'bluetooth': Profile(
        'system/lib64/libbluetooth_jni.so',
        '4cd62b0dbfa0cf325721a6e86673ddf68698b30c5e9a7982d4126fb85623594e',
        '188c4e516a3320cd00ffdbb5c4579972fe3aec858f80fc8ff956a8a6b01a4aca',
        # ControllerImpl::impl::read_local_hdt_features_handler. Rootcanal
        # returns UNKNOWN_HCI_COMMAND for the proprietary HDT query. Preserve
        # BTI, clear local_hdt_features_ and return before the OEM assertion.
        (Site(0xd99540, bytes.fromhex('5f2403d55e8600f8ffc304d1'),
                        bytes.fromhex('5f2403d51f100639c0035fd6')),)),
    'gralloc': Profile(
        'system_ext/lib64/libgralloc_extra_sys.so',
        '5f29022d542ccef28fd8e7879d57448efa99d03545171d837793feec8f2b92a0',
        '866788e4099f92125252828378e9c4a71a52c5e796cb53345f099af112bae22c',
        tuple(Site(offset, bytes.fromhex(original), RETURN_ZERO) for offset, original in (
            (0x4660, '5f2403d5ffc302d1'), (0x4030, '5f2403d5ffc302d1'),
            (0x4b70, '5f2403d50a2440b9'), (0x4ba0, '5f2403d50a3840b9'),
            (0x4bd0, '5f2403d500040f12')))),
    'ged': Profile(
        'system_ext/lib64/libged_sys.so',
        'c50071275703c6f5e7f7f24a31b12b0eab87119e88d7e9db2c092eaa65003816',
        '406f0179f2abc62218e97760ae54e38417c4d96918500813c307b48f4b8d78ec',
        tuple(Site(offset, bytes.fromhex(original), RETURN_ZERO) for offset, original in (
            (0xcd30, '68000090080540b9'), (0xc950, 'ff8305d1fd7b11a9'),
            (0xcc00, '68000090080540b9'), (0xce40, '68000090080540b9'),
            (0xcee0, '68000090080540b9'), (0xc0c0, 'e80f1bfcfdfb00a9'),
            (0xc380, 'fd7bbca9f70b00f9')))),
    'hwui': Profile(
        'system/lib64/libhwui.so',
        'caa0653b672f5c0407123617d7dac41d6f7e82c48a64eaa92341a1535dcc86ab',
        '69befcff21f6eb56326e7128e7f946298a35f22e88c8b1eca3eb062db9f6e21a',
        (Site(None, b'               uint outlineType = floatBitsToUint(%s[10]);',
                    b'               int outlineType = int(%s[10]);             '),)),
}


def apply(data: bytes, profile: Profile) -> bytes:
    checksum = hashlib.sha256(data).hexdigest()
    if checksum == profile.after:
        return data
    if checksum != profile.before:
        raise RuntimeError('Unsupported native patch input: ' + profile.path + ' SHA-256=' + checksum)
    result = bytearray(data)
    for site in profile.sites:
        offset = site.offset
        if offset is None:
            if data.count(site.original) != 1:
                raise RuntimeError('Unexpected native patch pattern count: ' + profile.path)
            offset = data.index(site.original)
        if (len(site.original) != len(site.replacement)
                or data[offset:offset + len(site.original)] != site.original):
            raise RuntimeError('Unexpected native patch bytes: ' + profile.path)
        result[offset:offset + len(site.original)] = site.replacement
    patched = bytes(result)
    if len(patched) != len(data) or hashlib.sha256(patched).hexdigest() != profile.after:
        raise RuntimeError('Native patch output checksum mismatch: ' + profile.path)
    return patched


def receipt():
    return {name: {'path': profile.path, 'before': profile.before, 'after': profile.after}
            for name, profile in PROFILES.items()}
