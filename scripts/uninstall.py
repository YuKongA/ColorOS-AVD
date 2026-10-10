#!/usr/bin/env python3
"""Unregister this workspace's ColorOS AVD, optionally deleting its data."""
import argparse
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess

from common import ROOT, DEFAULT_NAME, avd_home, port_free


def saved_json(path):
    return json.loads(path.read_text()) if path.is_file() else {}


def uninstall(name, delete_data=False):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', name):
        raise RuntimeError('Use an ASCII AVD name up to 64 characters.')
    root = ROOT.resolve()
    directory = root / 'avd' / (name + '.avd')
    registry = avd_home() / (name + '.ini')
    if directory.parent.is_symlink() or directory.is_symlink():
        raise RuntimeError('Refusing an AVD directory linked to another location.')
    if directory.exists() and not directory.is_dir():
        raise RuntimeError('Expected an AVD directory: ' + str(directory))
    if registry.is_symlink():
        raise RuntimeError('Refusing a linked AVD registry entry.')
    if registry.exists():
        properties = dict(line.split('=', 1) for line in registry.read_text().splitlines() if '=' in line)
        registered = properties.get('path')
        if not registered or Path(registered).expanduser().resolve() != directory:
            raise RuntimeError(f'AVD {name} belongs to another workspace; nothing was removed.')

    instances_path = root / 'local/instances.json'
    instances = saved_json(instances_path)
    runtime = saved_json(root / 'local/runtime.json')
    ports = {instances[name]} if name in instances else set()
    if runtime.get('name') == name and 'port' in runtime:
        ports.add(runtime['port'])
    for port in ports:
        port_free(port)
    # Android Studio can launch the same AVD on a different console port.
    rows = subprocess.check_output(['ps', '-ax', '-o', 'command='], text=True)
    for row in rows.splitlines():
        try:
            args = shlex.split(row)
        except ValueError:
            continue
        if not args or ('qemu-system-' not in args[0] and not args[0].endswith('/emulator')):
            continue
        for flag, expected in (('-avd', name), ('-data', str(directory / 'userdata-qemu.img'))):
            if flag in args:
                index = args.index(flag) + 1
                if index < len(args) and args[index] == expected:
                    raise RuntimeError('Close this ColorOS AVD before uninstalling; nothing was removed.')

    removed_data = delete_data and directory.exists()
    removed_registry = registry.exists()
    if removed_data:
        shutil.rmtree(directory)
    if removed_registry:
        registry.unlink()
    if name in instances:
        del instances[name]
        instances_path.write_text(json.dumps(instances, indent=2) + '\n')
    return directory, removed_registry, removed_data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', help='AVD name; defaults to the saved ColorOS instance')
    parser.add_argument('--delete-data', action='store_true',
                        help='Also delete this AVD directory, including userdata and encryption keys')
    args = parser.parse_args()
    runtime = saved_json(ROOT / 'local/runtime.json')
    name = args.name or runtime.get('name', DEFAULT_NAME)
    if args.delete_data:
        print(f'将删除 {name} 的全部用户数据和加密密钥。构建镜像和备份会保留。')
        if input(f'输入实例名称 {name} 确认删除：').strip() != name:
            print('已取消，未移除任何文件。')
            return
    directory, removed_registry, removed_data = uninstall(name, delete_data=args.delete_data)
    print(f'{name}：' + ('已移除 AVD 注册信息。' if removed_registry else '没有 AVD 注册信息。'))
    if args.delete_data:
        print('已删除实例数据。' if removed_data else '实例数据目录不存在。')
    else:
        print(f'用户数据保留在 {directory}；执行 Setup.command 可重新注册。')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, ValueError, EOFError) as error:
        raise SystemExit(str(error))
    except KeyboardInterrupt:
        raise SystemExit('\n已取消。')
