"""Prepare userdata before launch; verify legacy encrypted growth in a guest."""
from datetime import datetime
import json
from pathlib import Path
import subprocess
import time

from common import ROOT, COLOROS_SOURCE, adb, port_free, sha256
from avd_userdata import backup_userdata, clone, resize, validate_userdata
from userdata_resize import (PENDING, OfflineBackupRequiredError, assert_offline,
                             check_dependencies, publish_guest_capacity)
from userdata_guest import verify_and_grow


def prepare_userdata(config):
    avd = ROOT / 'avd' / (config['name'] + '.avd')
    properties = dict(line.split('=', 1) for line in (avd / 'config.ini').read_text().splitlines() if '=' in line)
    storage = config.get('hardware', {}).get('disk.dataPartition.size', properties.get('disk.dataPartition.size', ''))
    if not isinstance(storage, str) or not storage.endswith('G') or not storage[:-1].isdigit():
        raise RuntimeError('Invalid userdata capacity in the ColorOS AVD configuration.')
    gib, sdk = int(storage[:-1]), Path(config['sdk'])
    folder = None

    def prepare():
        nonlocal folder
        try:
            return resize(sdk, avd, gib, allow_guest=True, backup=folder)
        except OfflineBackupRequiredError:
            folder = backup_userdata(avd)
            return resize(sdk, avd, gib, allow_guest=True, backup=folder)

    pending = avd / PENDING
    result = prepare() if pending.exists() or pending.is_symlink() else None
    userdata = avd / 'userdata-qemu.img'
    if not userdata.exists():
        check_dependencies(sdk)
        print('Creating fresh userdata from the clean ColorOS template.', flush=True)
        clone(ROOT / 'images/userdata.img', userdata)
    validate_userdata(sdk, avd)
    result = result if result is not None else prepare()
    if result.get('guest_required'):
        folder = folder or backup_userdata(avd)
        return prepare_encrypted_storage(config, gib, folder)
    return result


def prepare_encrypted_storage(config, gib, folder):
    sdk = Path(config['sdk'])
    name, port = config['name'], config['port']
    avd = ROOT / 'avd' / (name + '.avd')
    assert_offline(avd)
    port_free(port)
    result = resize(sdk, avd, gib, allow_guest=True, backup=folder)
    if not result.get('guest_required'):
        return result
    build = json.loads((ROOT / 'local/build.json').read_text())
    saved = json.loads((ROOT / 'local/runtime.json').read_text())
    if (build.get('source') != COLOROS_SOURCE or build.get('android_api') != 37
            or saved.get('name') != name or saved.get('port') != port):
        raise RuntimeError('Storage repair requires this workspace\'s registered ColorOS build.')
    # Pin boot inputs before starting the repair guest, including the packed
    # system/vendor and the Root initializer. No external guest is adopted.
    inputs = ('images/system.img', 'images/vendor.img', 'images/kernel-ranchu',
              'images/ramdisk.img', 'tools/ksud-aarch64-linux-android')
    if any((ROOT / path).is_symlink() or not (ROOT / path).is_file() for path in inputs):
        raise RuntimeError('Storage repair boot inputs are missing or linked.')
    hashes = {path: sha256(ROOT / path) for path in inputs}
    (folder / 'boot-inputs.json').write_text(json.dumps(hashes, indent=2) + '\n')
    config = {**config, 'userdata_capacity_token': result['userdata_capacity_token']}
    properties = dict(line.split('=', 1) for line in (avd / 'config.ini').read_text().splitlines() if '=' in line)
    command = [str(sdk / 'emulator/emulator'), '-avd', name, '-sysdir', str(ROOT / 'images'),
               '-port', str(port), '-no-window', '-no-snapshot-load', '-no-snapshot-save',
               '-accel', 'on', '-gpu', 'host', '-memory', properties.get('hw.ramSize', '6144'),
               '-cores', properties.get('hw.cpu.ncore', '4')]
    logs = ROOT / 'logs'
    logs.mkdir(exist_ok=True)
    log = logs / ('storage-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.log')
    print('Checking encrypted userdata capacity; verified backup: ' + str(folder), flush=True)
    with log.open('wb') as output:
        process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, start_new_session=True, close_fds=True)
    owned = False
    try:
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError('Storage repair guest exited; inspect ' + str(log))
            try:
                identity = adb(config, 'emu', 'avd', 'name', capture_output=True, text=True, timeout=5)
                if identity.returncode == 0 and identity.stdout.splitlines()[:1] == [name]:
                    owned = True
                    break
            except subprocess.TimeoutExpired:
                pass
            time.sleep(2)
        else:
            raise RuntimeError('Storage repair guest did not become ready; backup retained.')
        from launch import initialize_root
        # Root setup waits until the owned guest's shell is available.
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            ready = adb(config, 'shell', 'id', capture_output=True, text=True, timeout=10)
            if ready.returncode == 0 and 'uid=' in ready.stdout:
                break
            time.sleep(2)
        else:
            raise RuntimeError('Storage repair ADB shell did not become ready.')
        initialize_root(config)
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            state = adb(config, 'shell', 'getprop sys.boot_completed', capture_output=True, text=True, timeout=10)
            if state.returncode == 0 and state.stdout.strip() == '1':
                break
            time.sleep(2)
        else:
            raise RuntimeError('Storage repair guest did not complete boot; backup retained.')
        record = verify_and_grow(config, gib * 1024**3, backup=folder)
        adb(config, 'shell', 'su -W -c sync', check=True, capture_output=True, timeout=30)
    finally:
        if process.poll() is None:
            try:
                identity = adb(config, 'emu', 'avd', 'name', capture_output=True, text=True, timeout=5) if owned else None
                if identity and identity.returncode == 0 and identity.stdout.splitlines()[:1] == [name]:
                    stopped = adb(config, 'emu', 'kill', capture_output=True, timeout=10)
                    if stopped.returncode:
                        process.terminate()
                else:
                    process.terminate()
            except (OSError, subprocess.SubprocessError):
                process.terminate()
            try:
                process.wait(timeout=45)
            except subprocess.TimeoutExpired:
                raise RuntimeError('Storage repair guest is still running; close it before retrying. Backup retained.') from None
    assert_offline(avd)
    port_free(port)
    if any(sha256(ROOT / path) != checksum for path, checksum in hashes.items()):
        raise RuntimeError('Storage repair boot inputs changed; backup and guest state retained.')
    published = publish_guest_capacity(sdk, avd, gib * 1024**3, record)
    (folder / 'storage-repair.json').write_text(json.dumps(record, indent=2) + '\n')
    return published
