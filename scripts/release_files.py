"""Download and extract the portable, checksummed ColorOS release format."""
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import tarfile
import urllib.parse

from common import COLOROS_SOURCE, sha256
from https_transport import secure_urlopen

REPOSITORY = 'YuKongA/ColorOS-AVD'
RUNTIME_SCRIPTS = (
    'common.py', 'setup.py', 'launch.py', 'uninstall.py', 'avd_userdata.py',
    'storage_boot.py', 'userdata_resize.py', 'userdata_guest.py', 'https_transport.py',
)
IMAGE_FILES = (
    'NOTICE.txt', 'VerifiedBootParams.textproto', 'advancedFeatures.ini', 'build.prop',
    'encryptionkey.img', 'kernel-ranchu', 'kernel_cmdline.txt', 'ramdisk.img',
    'source.properties', 'system.img', 'vendor.img', 'userdata.img',
)
TOOLS = ('ksud-aarch64-linux-android', 'KernelSU_v3.3.0_32601-release.apk', 'SetWallpaper.dex')
FAMILY = 'coloros-pmx110-api37-ranchu-4k'


def safe_path(value):
    if (not isinstance(value, str) or not value or '\\' in value or '\0' in value
            or PurePosixPath(value).is_absolute() or any(p in ('', '.', '..') for p in value.split('/'))):
        raise RuntimeError('Invalid release path.')
    return value


def allowed_file(path):
    safe_path(path)
    return (path in {'images/' + name for name in IMAGE_FILES}
            or path in {'tools/' + name for name in TOOLS}
            or path in {'runtime/scripts/' + name for name in RUNTIME_SCRIPTS}
            or path == 'config/avd.ini'
            or path.startswith(('images/data/misc/emulator/', 'images/data/misc/modem_simulator/')))


def checksum_entry(entry):
    if (not isinstance(entry, dict) or type(entry.get('size')) is not int or entry['size'] < 0
            or not isinstance(entry.get('sha256'), str) or not re.fullmatch('[0-9a-f]{64}', entry['sha256'])):
        raise RuntimeError('Invalid release checksum entry.')


def validate_manifest(value):
    if (not isinstance(value, dict) or value.get('project') != 'ColorOS-AVD'
            or value.get('format') != 1 or value.get('platform') != 'macos-arm64'
            or value.get('compression') != 'xz' or value.get('userdata_family') != FAMILY
            or not re.fullmatch(r'v[0-9A-Za-z_.-]+', value.get('version', ''))
            or value.get('build', {}).get('source') != COLOROS_SOURCE
            or value['build'].get('android_api') != 37 or value['build'].get('adb_authentication') is not True):
        raise RuntimeError('Unsupported ColorOS release manifest.')
    files = value.get('files')
    if not isinstance(files, dict) or len(files) > 1000:
        raise RuntimeError('Invalid release inventory.')
    for path, entry in files.items():
        if not allowed_file(path):
            raise RuntimeError('Unexpected release file: ' + path)
        checksum_entry(entry)
        if entry.get('mode') not in (0o644, 0o755):
            raise RuntimeError('Unexpected release permissions: ' + path)
    required = ({'images/' + p for p in IMAGE_FILES} | {'tools/' + p for p in TOOLS}
                | {'runtime/scripts/' + p for p in RUNTIME_SCRIPTS} | {'config/avd.ini'})
    if not required <= files.keys():
        raise RuntimeError('Release is missing required images or runtime files.')
    if files['images/userdata.img']['size'] != 16 * 1024**3:
        raise RuntimeError('Release needs a clean 16 GiB userdata template.')
    parts = value.get('parts')
    if not isinstance(parts, list) or not 1 <= len(parts) <= 32:
        raise RuntimeError('Invalid release parts.')
    names = set()
    for part in parts:
        checksum_entry(part)
        name = part.get('name', '')
        if not re.fullmatch(r'[A-Za-z0-9_.-]+\.tar\.xz\.part[0-9]{3}', name) or name in names or not 0 < part['size'] < 2 * 1024**3:
            raise RuntimeError('Invalid or duplicate release part.')
        names.add(name)
    if value['build'].get('system_sha256') != files['images/system.img']['sha256']:
        raise RuntimeError('System image differs from build metadata.')
    return value


def remote_json(url, limit=4 * 1024**2):
    with secure_urlopen(url, timeout=30) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise RuntimeError('Remote metadata is too large.')
    return json.loads(data)


def release_url(version='latest'):
    base = 'https://github.com/' + REPOSITORY + '/releases/'
    if version == 'latest':
        return base + 'latest/download/'
    if not re.fullmatch(r'v[0-9A-Za-z_.-]+', version):
        raise RuntimeError('Invalid release version.')
    return base + 'download/' + version + '/'


def read_manifest(location, expected_sha256=None):
    if str(location).startswith('https://'):
        value = remote_json(str(location))
        base = str(location).rsplit('/', 1)[0] + '/'
        # Pin all subsequent downloads to this tag, even if Latest changes.
        if '/latest/download/' in base:
            base = release_url(value.get('version', ''))
    else:
        path = Path(location).expanduser().resolve()
        value, base = json.loads(path.read_text()), path.parent
    if expected_sha256:
        # The bootstrap receipt pins the exact published manifest bytes.
        if str(location).startswith('https://'):
            with secure_urlopen(str(location), timeout=30) as response:
                data = response.read(4 * 1024**2 + 1)
        else:
            data = Path(location).expanduser().read_bytes()
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            raise RuntimeError('Firmware manifest differs from the installer receipt.')
        value = json.loads(data)
        if isinstance(base, str) and '/latest/download/' in str(location):
            base = release_url(value.get('version', ''))
    return validate_manifest(value), base


def download(url, target, entry, progress=None):
    """Resume parts, hash complete content, and publish only verified downloads."""
    checksum_entry(entry)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise RuntimeError('Refusing a linked download destination.')
    if target.is_file() and target.stat().st_size == entry['size'] and sha256(target) == entry['sha256']:
        return target
    partial = target.with_name(target.name + '.partial')
    if partial.is_symlink():
        raise RuntimeError('Refusing a linked partial download.')
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > entry['size']:
        partial.unlink()
        offset = 0
    if offset < entry['size']:
        import urllib.request
        request = urllib.request.Request(url, headers={'Range': f'bytes={offset}-'} if offset else {})
        with secure_urlopen(request, timeout=60) as response:
            code = response.getcode()
            if offset and code == 206:
                expected = f'bytes {offset}-{entry["size"] - 1}/{entry["size"]}'
                if response.headers.get('Content-Range') != expected:
                    raise RuntimeError('Download server returned an unexpected range.')
            elif code == 200:
                offset = 0
            else:
                raise RuntimeError('Unexpected download response.')
            with partial.open('ab' if offset else 'wb') as output:
                while block := response.read(1024**2):
                    if offset + len(block) > entry['size']:
                        raise RuntimeError('Download exceeded its expected size.')
                    output.write(block)
                    offset += len(block)
                    if progress:
                        progress(offset, entry['size'])
    if partial.stat().st_size != entry['size'] or sha256(partial) != entry['sha256']:
        partial.unlink(missing_ok=True)
        raise RuntimeError('Download checksum mismatch: ' + target.name)
    partial.replace(target)
    return target


class PartsReader(io.RawIOBase):
    def __init__(self, paths):
        self.paths = iter(paths)
        self.stream = None

    def readable(self):
        return True

    def read(self, size=-1):
        chunks, remaining = [], size
        while remaining:
            if self.stream is None:
                path = next(self.paths, None)
                if path is None:
                    break
                self.stream = Path(path).open('rb')
            block = self.stream.read(remaining)
            if block:
                chunks.append(block)
                if size >= 0:
                    remaining -= len(block)
            else:
                self.stream.close()
                self.stream = None
        return b''.join(chunks)

    def close(self):
        if self.stream is not None:
            self.stream.close()
        super().close()


def extract_release(parts, manifest, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    seen = set()
    with PartsReader(parts) as source, tarfile.open(fileobj=source, mode='r|xz') as archive:
        for member in archive:
            path = safe_path(member.name)
            entry = manifest['files'].get(path)
            if entry is None or path in seen or not member.isfile() or member.size != entry['size']:
                raise RuntimeError('Unexpected release archive entry: ' + path)
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            checksum = hashlib.sha256()
            with archive.extractfile(member) as input_file, target.open('xb') as output:
                while block := input_file.read(1024**2):
                    checksum.update(block)
                    # Templates contain mostly zeroes; retain sparse allocation.
                    if block.count(0) == len(block):
                        output.seek(len(block), 1)
                    else:
                        output.write(block)
                output.truncate(member.size)
            if checksum.hexdigest() != entry['sha256']:
                raise RuntimeError('Extracted file checksum mismatch: ' + path)
            target.chmod(entry['mode'])
            seen.add(path)
    if seen != manifest['files'].keys():
        raise RuntimeError('Release archive is incomplete.')
    properties = dict(line.split('=', 1) for line in (destination / 'config/avd.ini').read_text().splitlines() if '=' in line)
    if (properties.get('hw.cpu.arch') != 'arm64' or properties.get('target') != 'android-37.0'
            or any(key in properties for key in ('path', 'path.rel', 'image.sysdir.1'))):
        raise RuntimeError('Release AVD configuration is not portable.')
    return destination
