#!/usr/bin/env python3
"""Register a built ColorOS image as an isolated Android Studio AVD."""
import argparse
import json
from pathlib import Path
import re

from common import (ROOT, REPO_ROOT, COLOROS_SOURCE, DEFAULT_NAME, DEFAULT_PORT,
                    avd_home, fetch_ksu, host_check, port_free, runtime, sdk_path)


def configure(sdk, name, port):
    path = ROOT.resolve() / 'avd' / (name + '.avd')
    registry = avd_home() / (name + '.ini')
    instances_path = ROOT / 'local/instances.json'
    instances = json.loads(instances_path.read_text()) if instances_path.exists() else {}
    if name in instances and instances[name] != port:
        port_free(instances[name])
    if registry.exists():
        current = dict(line.split('=', 1) for line in registry.read_text().splitlines() if '=' in line)
        registered = current.get('path')
        if not registered or Path(registered).expanduser().resolve() != path:
            raise RuntimeError(f'AVD {name} belongs to another workspace. Use --name with a new name.')
    path.mkdir(parents=True, exist_ok=True)
    config_file = ROOT / 'config/avd.ini'
    template = (config_file if config_file.exists() else REPO_ROOT / 'config/avd.ini').read_text()
    properties = dict(line.split('=', 1) for line in template.splitlines() if '=' in line)
    target = properties['target']
    # Retain per-instance hardware choices across launcher reconfiguration.
    saved = ROOT / 'local/runtime.json'
    previous = json.loads(saved.read_text()) if saved.exists() else {}
    hardware = previous.get('hardware', {})
    for key, value in hardware.items():
        if key not in ('hw.ramSize', 'hw.cpu.ncore', 'disk.dataPartition.size'):
            raise RuntimeError('Unexpected per-instance hardware key: ' + key)
        properties[key] = str(value)
    template = ''.join(key + '=' + value + '\n' for key, value in properties.items())
    template += f'image.sysdir.1={ROOT / "images"}/\n'
    template += 'AvdId=' + name + '\navd.ini.displayname=' + name + '\n'

    (path / 'config.ini').write_text(template)
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(f'avd.ini.encoding=UTF-8\npath={path}\ntarget={target}\n')
    (ROOT / 'local').mkdir(exist_ok=True)
    (ROOT / 'local/runtime.json').write_text(json.dumps(
        {**previous, 'sdk': str(sdk), 'name': name, 'port': port, 'hardware': hardware}, indent=2) + '\n')
    instances[name] = port
    instances_path.write_text(json.dumps(instances, indent=2) + '\n')
    print(f'Registered {name} at emulator-{port}. Existing userdata was preserved.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk', type=Path)
    parser.add_argument('--name')
    parser.add_argument('--port', type=int)
    args = parser.parse_args()
    host_check()
    saved = runtime()
    name = args.name or saved.get('name', DEFAULT_NAME)
    port = args.port if args.port is not None else saved.get('port', DEFAULT_PORT)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', name):
        raise RuntimeError('Use an ASCII AVD name up to 64 characters.')
    if port % 2 or not 5556 <= port <= 5682:
        raise RuntimeError('Use a free, even emulator console port between 5556 and 5682.')
    port_free(port)
    build = ROOT / 'local/build.json'
    if not build.is_file() or json.loads(build.read_text()).get('source') != COLOROS_SOURCE:
        raise RuntimeError('Build ColorOS first: python3 scripts/build_coloros.py')
    required = ('system.img', 'ramdisk.img', 'kernel-ranchu', 'source.properties', 'userdata.img')
    missing = [name for name in required if not (ROOT / 'images' / name).is_file()]
    if missing:
        raise RuntimeError('Incomplete ColorOS build. Missing: ' + ', '.join(missing))
    fetch_ksu(['ksud-aarch64-linux-android', 'KernelSU_v3.3.0_32601-release.apk'])
    configure(sdk_path(args.sdk or saved.get('sdk')), name, port)
    print('Ready. Double-click Start-ColorOS.command to boot.')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError) as error:
        raise SystemExit(str(error))
