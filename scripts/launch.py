#!/usr/bin/env python3
"""Cold-boot only the project AVD and initialize KernelSU on fresh userdata."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shlex
import subprocess
import time

from common import COLOROS_SOURCE, ROOT, adb, fetch_ksu, host_check, port_free, runtime, terminate_emulator
from setup import configure


def verify_coloros_userdata(config):
    """Verify the mounted ext4 against the requested capacity on every boot."""
    from userdata_guest import verify_and_grow
    path = ROOT / 'avd' / (config['name'] + '.avd') / 'config.ini'
    properties = dict(line.split('=', 1) for line in path.read_text().splitlines() if '=' in line)
    storage = properties['disk.dataPartition.size']
    return verify_and_grow(config, int(storage.removesuffix('G')) * 1024**3, allow_grow=False)


def wake_display(config):
    """Wake the display after a cold boot, respecting the user's sleep timeout."""
    try:
        adb(config, 'shell', 'input keyevent 224', timeout=5)
        adb(config, 'shell', 'wm dismiss-keyguard', timeout=5)
    except Exception:
        pass


def skip_oobe(config):
    command = '\n'.join([
        'set -e',
        'settings put global device_provisioned 1',
        'settings put secure user_setup_complete 1',
        'pm disable-user --user 0 com.coloros.bootreg 2>/dev/null || true',
        'am force-stop com.coloros.bootreg 2>/dev/null || true',
        'pm disable-user --user 0 com.android.provision 2>/dev/null || true',
        'am force-stop com.android.provision 2>/dev/null || true',
        'input keyevent 224',
        'wm dismiss-keyguard',
        'am start -W -a android.intent.action.MAIN -c android.intent.category.HOME '
        '-n com.android.launcher/com.android.launcher.Launcher',
    ])
    adb(config, 'shell', 'su -W -c ' + shlex.quote(command), check=True, timeout=30)
    print('ColorOS OOBE skipped. Existing userdata was preserved.', flush=True)


def initialize_root(config):
    root = adb(config, 'shell', "su -W -c 'id'", capture_output=True, text=True, timeout=15)
    if 'uid=0(' not in root.stdout:
        binary = ROOT / 'tools/ksud-aarch64-linux-android'
        remote = '/data/local/tmp/coloros-avd-ksud'
        adb(config, 'push', str(binary), remote, check=True, capture_output=True, timeout=30)
        adb(config, 'shell', f'chmod 755 {remote}', check=True, timeout=15)
        result = adb(config, 'shell', remote + ' debug su', input=remote + ' install\nexit\n',
                     text=True, capture_output=True, timeout=30)
        if result.returncode:
            raise RuntimeError('KernelSU initialization failed: ' + result.stderr)
    result = adb(config, 'shell', "su -W -c 'id; getenforce; /data/adb/ksud feature set selinux_hide 0; /data/adb/ksud feature save'",
                 capture_output=True, text=True, timeout=20)
    if 'uid=0(' not in result.stdout or 'Enforcing' not in result.stdout or result.returncode:
        raise RuntimeError('KernelSU root/enforcing validation failed: ' + result.stdout + result.stderr)
    return result


def start_double_tap_wake(config):
    """Bridge primary Ranchu touches to the OEM wake setting, using KernelSU."""
    command = '\n'.join([
        'set -e',
        'dex=/system_ext/framework/ColorOSDoubleTapWake.dex',
        'library=/system_ext/lib64/libcoloros_double_tap.so',
        # Older release images do not include this adapter.
        '[ -f "$dex" ] || exit 0',
        '[ -f "$library" ]',
        'pidof coloros-double-tap >/dev/null && exit 0',
        'CLASSPATH="$dex" app_process /system/bin --nice-name=coloros-double-tap '
        'com.coloros.avd.DoubleTapWake "$library" </dev/null '
        '>/data/local/tmp/coloros-double-tap.log 2>&1 &',
        'sleep 1',
        'pidof coloros-double-tap >/dev/null || '
        '{ cat /data/local/tmp/coloros-double-tap.log; exit 1; }',
    ])
    adb(config, 'shell', 'su -W -c ' + shlex.quote(command), check=True, timeout=15)


def initialize(config, bypass_oobe=False):
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        try:
            result = adb(config, 'shell', 'id', capture_output=True,
                         text=True, timeout=10)
            if result.returncode == 0 and 'uid=' in result.stdout:
                break
        except subprocess.TimeoutExpired:
            pass
        time.sleep(3)
    else:
        raise RuntimeError('ADB did not become ready within 5 minutes. Inspect logs/emulator-current.log.')
    for sensor, value in [('proximity', '5'), ('light', '200')]:
        try:
            adb(config, 'emu', 'sensor', 'set', sensor, value,
                stdout=subprocess.DEVNULL, timeout=5)
        except Exception:
            pass
    result = initialize_root(config)
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        completed = adb(config, 'shell', 'getprop sys.boot_completed', capture_output=True,
                        text=True, timeout=15)
        if completed.returncode == 0 and completed.stdout.strip() == '1':
            pm_check = adb(config, 'shell', 'pm path android 2>/dev/null || true',
                           capture_output=True, text=True, timeout=10)
            if 'package:' in pm_check.stdout:
                break
        time.sleep(3)
    else:
        raise RuntimeError('Boot did not finish within 5 minutes. Inspect logs/emulator-current.log.')
    capacity = verify_coloros_userdata(config)
    adb(config, 'shell',
        "su -W -c 'pidof vendor.oplus.hardware.urcc-service >/dev/null || (/system_ext/bin/vendor.oplus.hardware.urcc-service </dev/null >/dev/null 2>&1 &)'",
        timeout=10)
    start_double_tap_wake(config)
    wake_display(config)
    if bypass_oobe:
        skip_oobe(config)
    manager = adb(config, 'shell', 'pm path me.weishu.kernelsu', capture_output=True, text=True, timeout=15)
    # The release APK keeps its native library compressed. A copy under
    # /system/app without a native library sidecar is therefore visible
    # to PackageManager but its libkernelsu.so is not extracted, so launching
    # the manager crashes with UnsatisfiedLinkError.  Install a data copy when
    # the only registered package is the system preinstall; pm extracts the
    # native library into /data/app/.../lib/ for the linker.
    system_manager = any(
        line.removeprefix('package:').split('=', 1)[0].startswith(('/system/', '/product/', '/my_'))
        for line in manager.stdout.splitlines() if line.startswith('package:')
    )
    if 'package:' not in manager.stdout or system_manager:
        apk = ROOT / 'tools/KernelSU_v3.3.0_32601-release.apk'
        if not apk.is_file():
            apk = Path(__file__).resolve().parent.parent / 'tools/KernelSU_v3.3.0_32601-release.apk'
        remote = '/data/local/tmp/KernelSU.apk'
        adb(config, 'push', str(apk), remote, check=True, timeout=30)
        adb(config, 'shell', f"su -W -c 'pm install -r -g {remote}'", check=True, timeout=60)
        adb(config, 'shell', f"rm -f {remote}", timeout=10)
    adb(config, 'shell', 'rm -f /data/local/tmp/*-ksud', timeout=15)
    (ROOT / 'local').mkdir(exist_ok=True)
    (ROOT / 'local/last-boot.json').write_text(json.dumps(
        {'name': config['name'], 'serial': f"emulator-{config['port']}",
         'validated_at': datetime.now().astimezone().isoformat(), 'root': result.stdout,
         'userdata': capacity}, indent=2) + '\n')
    print(f"ColorOS is ready: emulator-{config['port']}.", flush=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--kill', '-k', action='store_true',
                        help='Terminate any existing emulator on this port before starting')
    parser.add_argument('--skip-oobe', action='store_true',
                        help='Skip provisioning and open the native launcher')
    parser.add_argument('--wait', action='store_true',
                        help='Wait for the emulator process to exit before returning')
    args = parser.parse_args()
    config = runtime()
    build = ROOT / 'local/build.json'
    if not build.is_file() or json.loads(build.read_text()).get('source') != COLOROS_SOURCE:
        raise RuntimeError('Build ColorOS first: python3 scripts/build_coloros.py')
    try:
        port_free(config['port'])
    except RuntimeError as err:
        if args.kill:
            print(f"Port {config['port']} is occupied; terminating existing emulator...", flush=True)
            terminate_emulator(config['sdk'], config['name'], config['port'])
        else:
            raise RuntimeError(
                f"Port {config['port']} is occupied. If an emulator is already running in background, "
                f"terminate it with: ./Start-ColorOS.command --kill"
            ) from err
    if not (ROOT / 'images/userdata.img').is_file():
        raise RuntimeError('Build ColorOS first: python3 scripts/build_coloros.py')
    # Refresh relocated paths before every cold start; collision checks protect other AVDs.
    configure(Path(config['sdk']), config['name'], config['port'])
    fetch_ksu(['ksud-aarch64-linux-android', 'KernelSU_v3.3.0_32601-release.apk'])
    from storage_boot import prepare_userdata
    prepare_userdata(config)
    avd_config = ROOT / 'avd' / (config['name'] + '.avd') / 'config.ini'
    properties = dict(line.split('=', 1) for line in avd_config.read_text().splitlines() if '=' in line)
    logs = ROOT / 'logs'
    logs.mkdir(exist_ok=True)
    log = logs / 'emulator-current.log'
    if log.exists():
        log.rename(logs / ('emulator-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.log'))
    memory = str(int(properties.get('hw.ramSize', '2560')))
    cores = str(int(properties.get('hw.cpu.ncore', '2')))
    command = [str(Path(config['sdk']) / 'emulator/emulator'), '-avd', config['name'],
               '-sysdir', str(ROOT / 'images'), '-port', str(config['port']),
               '-no-snapshot-load', '-no-snapshot-save', '-accel', 'on', '-gpu', 'host',
               '-memory', memory, '-cores', cores, '-show-kernel', '-verbose']
    if args.headless:
        command += ['-no-window']
    with log.open('wb') as output:
        # Keep QEMU independent of the terminal that launched the script.
        # macOS can send a hangup to the emulator wrapper when the shell
        # session closes even though it has its own session id; redirecting
        # stdin and closing all inherited descriptors prevents that cascade.
        process = subprocess.Popen(command, env=os.environ.copy(), stdout=output,
                                   stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                   start_new_session=True, close_fds=True)
    print(f"Starting {config['name']} (PID {process.pid}). Log: {log}", flush=True)
    # The emulator stays running if setup fails; evidence and userdata are retained.
    initialize(config, bypass_oobe=args.skip_oobe)
    if process.poll() is not None:
        raise RuntimeError(
            f"Emulator exited immediately with status {process.returncode}. "
            "Inspect logs/emulator-current.log."
        )
    if args.wait:
        try:
            process.wait()
        except KeyboardInterrupt:
            pass
if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        raise SystemExit(str(error))
