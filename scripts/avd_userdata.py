"""Preserve and grow the ColorOS AVD userdata and encryption overlays."""
import json
from datetime import datetime, timezone
from pathlib import Path
import shutil
import subprocess

from common import sha256
from userdata_resize import assert_offline, resize_userdata, LAYER_NAMES


def data_size(sdk, path):
    return json.loads(subprocess.check_output([str(sdk / 'emulator/qemu-img'), 'info', '--output=json', str(path)], text=True))


def validate_userdata(sdk, avd):
    """Refuse overlays the Emulator would discard for an unexpected backing name."""
    for stem in ('userdata-qemu.img', 'encryptionkey.img'):
        overlay = avd / (stem + '.qcow2')
        if not overlay.is_file():
            continue
        info = data_size(sdk, overlay)
        if info.get('backing-filename') != stem or not (avd / stem).is_file():
            raise RuntimeError('Unexpected userdata/key backing chain; preserved without booting: ' + str(overlay))


def resize(sdk, avd, gib, *, allow_guest=False, backup=None):
    """Verify ext4 capacity, stage growth and preserve encrypted disk chains."""
    if type(gib) is not int or not 6 <= gib <= 1024:
        raise RuntimeError('Use a userdata capacity between 6 and 1024 GiB.')
    return resize_userdata(sdk, avd, gib * 1024**3, allow_guest=allow_guest, backup=backup)


def clone(source, target):
    """Keep sparse APFS templates and offline backups inexpensive to copy."""
    result = subprocess.run(['cp', '-c', '-p', str(source), str(target)], capture_output=True)
    if result.returncode:
        shutil.copy2(source, target)
    return target


def backup_userdata(avd):
    avd = Path(avd)
    if avd.is_symlink() or avd.parent.is_symlink():
        raise RuntimeError('Refusing a linked userdata directory.')
    avd = avd.resolve()
    assert_offline(avd)
    paths = [avd / name for name in LAYER_NAMES if (avd / name).exists()]
    if any(path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1 for path in paths):
        raise RuntimeError('Offline backup requires unaliased regular userdata/key files.')
    before = {path.name: path.stat() for path in paths}
    folder = avd.parent.parent / 'backups' / ('userdata-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    folder.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(avd, folder / 'avd', copy_function=clone, symlinks=True)
    hashes = {}
    for path in paths:
        copied = folder / 'avd' / path.name
        checksum = sha256(path)
        if (sha256(copied) != checksum or any(
                getattr(path.stat(), field) != getattr(before[path.name], field)
                for field in ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns'))):
            raise RuntimeError('Userdata changed during offline backup; resize refused.')
        hashes['avd/' + path.name] = checksum
    assert_offline(avd)
    (folder / 'backup.json').write_text(json.dumps(
        {'name': avd.name.removesuffix('.avd'), 'files': hashes}, indent=2) + '\n')
    print('Userdata backup: ' + str(folder), flush=True)
    return folder

