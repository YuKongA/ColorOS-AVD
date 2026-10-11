#!/usr/bin/env python3
"""Interactive ColorOS installation, updates, resources, launch and removal."""
import argparse
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

from common import (avd_home, host_check, port_free, sha256, tool,
                    DEFAULT_NAME, DEFAULT_PORT)
from release_files import (REPOSITORY, FAMILY, download, extract_release, read_manifest,
                           release_url, remote_json)


def ask(prompt, default):
    answer = input(f'{prompt} [{default}]: ').strip()
    return answer or str(default)


class Back(Exception):
    """Move one level up in the interactive wizard."""


def prompt(prompt, default):
    value = input(f'{prompt} [{default}]（0 返回上一步）：').strip()
    if value in ('0', 'b', 'B'):
        raise Back()
    return value or str(default)


def menu(title, options):
    print('\n' + title)
    for index, value in enumerate(options, 1):
        print(f'[{index}] {value}')
    print('[0] 返回上一步')
    while True:
        value = input('选择：').strip()
        if value in ('0', 'b', 'B'):
            raise Back()
        if value.isdigit() and 1 <= int(value) <= len(options):
            return int(value) - 1
        print('请输入列表中的编号。')


def select_root(initial=None):
    """Choose and confirm an owned installation directory before the menu."""
    if initial is not None:
        return Path(initial).expanduser().resolve()
    while True:
        value = input(f'安装目录 [{Path.home() / "ColorOS-AVD"}]（0 退出）：').strip()
        if value in ('0', 'q', 'Q'):
            return None
        root = Path(value or Path.home() / 'ColorOS-AVD').expanduser().resolve()
        if root in (Path('/'), Path.home().resolve()) or (root / '.git').exists():
            print('请选择独立目录，例如 ~/ColorOS-AVD。')
            continue
        if root.exists() and not root.is_dir():
            print('该路径不是目录。')
            continue
        state = read_json(root / 'local/runtime.json')
        installed = read_json(root / 'local/installed-release.json')
        description = installed.get('version', '未安装')
        if state.get('name'):
            description += f' / {state["name"]}'
        print(f'将使用目录：{root}\n当前状态：{description}')
        confirmation = input('确认此目录？[Y/n/0 返回]：').strip().lower()
        if confirmation in ('0', 'b'):
            continue
        if confirmation in ('', 'y', 'yes'):
            return root
        print('已取消，请重新选择目录。')


def read_json(path):
    return json.loads(path.read_text()) if path.is_file() else {}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.next')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


@contextmanager
def installation_lock(root):
    root.mkdir(parents=True, exist_ok=True)
    with (root / '.install.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('另一个安装向导正在操作此目录。') from None
        yield


def validate_options(name, port, ram, storage, cores):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', name):
        raise RuntimeError('实例名称使用英文、数字、点、下划线或连字符，最多 64 字符。')
    if port % 2 or not 5556 <= port <= 5682:
        raise RuntimeError('端口必须为 5556–5682 之间的空闲偶数。')
    if not 2 <= ram <= 64 or not 16 <= storage <= 1024 or not 1 <= cores <= (os.cpu_count() or 1):
        raise RuntimeError('RAM 使用 2–64 GiB、存储 16–1024 GiB，核心数不超过宿主机。')
    return {'hw.ramSize': str(round(ram * 1024)), 'disk.dataPartition.size': f'{storage}G', 'hw.cpu.ncore': str(cores)}


def require_environment(sdk, interactive=False):
    sdk = Path(sdk).expanduser().resolve()
    required = ('platform-tools/adb', 'emulator/emulator', 'emulator/qemu-img')
    if not all((sdk / path).is_file() for path in required):
        managers = list(sdk.glob('cmdline-tools/*/bin/sdkmanager'))
        if interactive and managers and ask('SDK 缺少 Emulator/Platform-Tools，是否安装？y/n', 'y').lower() == 'y':
            manager = next((p for p in managers if p.parents[1].name == 'latest'), managers[-1])
            print('请阅读并接受 Android SDK 许可。')
            subprocess.run([str(manager), '--sdk_root=' + str(sdk), '--licenses'], check=True)
            subprocess.run([str(manager), '--sdk_root=' + str(sdk), 'emulator', 'platform-tools'], check=True)
        if not all((sdk / path).is_file() for path in required):
            raise RuntimeError('请在 Android Studio SDK Manager 安装 Android Emulator 和 Platform-Tools，然后重新运行向导。')
    try:
        tool('e2fsck', 'e2fsprogs')
        tool('resize2fs', 'e2fsprogs')
    except RuntimeError:
        brew = shutil.which('brew')
        if interactive and brew and ask('安装用户分区工具 e2fsprogs？y/n', 'y').lower() == 'y':
            subprocess.run([brew, 'install', 'e2fsprogs'], check=True)
        tool('e2fsck', 'e2fsprogs')
        tool('resize2fs', 'e2fsprogs')
    return sdk


def owned_and_idle(root, name, port):
    directory = root / 'avd' / (name + '.avd')
    if root.is_symlink() or (root / 'avd').is_symlink() or directory.is_symlink():
        raise RuntimeError('拒绝链接到其他位置的安装/AVD 目录。')
    entry = avd_home() / (name + '.ini')
    if entry.exists() or entry.is_symlink():
        values = dict(line.split('=', 1) for line in entry.read_text().splitlines() if '=' in line)
        if entry.is_symlink() or Path(values.get('path', '/missing')).expanduser().resolve() != directory:
            raise RuntimeError('同名 AVD 属于其他工作区，请选择不同名称。')
    previous = read_json(root / 'local/runtime.json')
    if previous and previous.get('name') != name:
        raise RuntimeError('此安装目录已属于另一实例；新建实例请使用新目录。')
    for endpoint in {port, previous.get('port', port)}:
        port_free(endpoint)
    import shlex
    for row in subprocess.check_output(['ps', '-ax', '-o', 'command='], text=True).splitlines():
        try:
            args = shlex.split(row)
        except ValueError:
            continue
        if args and ('qemu-system-' in args[0] or args[0].endswith('/emulator')) and '-avd' in args:
            index = args.index('-avd') + 1
            if index < len(args) and args[index] == name:
                raise RuntimeError('请先关闭此 ColorOS 模拟器。')


def run_runtime(root, script, arguments=(), check=True):
    installed = read_json(root / 'local/installed-release.json')
    version = installed.get('version')
    if not version or not re.fullmatch(r'v[0-9A-Za-z_.-]+', version):
        raise RuntimeError('此目录尚未安装发布版 ColorOS。')
    path = root / 'versions' / version / 'runtime/scripts' / script
    if script not in ('setup.py', 'launch.py', 'uninstall.py'):
        raise RuntimeError('Unknown runtime command.')
    environment = dict(os.environ, COLOROS_AVD_WORKSPACE=str(root))
    return subprocess.run([sys.executable, str(path), *arguments], env=environment, check=check)


def wrappers(root, version):
    import shlex
    for name, script, arguments in (
            ('Start.command', 'launch.py', '--wait'), ('Setup.command', 'setup.py', ''),
            ('Uninstall.command', 'uninstall.py', '')):
        path = root / name
        path.write_text('#!/bin/zsh\nset -eu\nPROJECT_ROOT="${0:A:h}"\n'
                        'export COLOROS_AVD_WORKSPACE="$PROJECT_ROOT"\n'
                        f'exec python3 "$PROJECT_ROOT/versions/{version}/runtime/scripts/{script}" {arguments} "$@"\n')
        path.chmod(0o755)
    # Persist the small manager so installation is still manageable offline.
    manager = root / 'installer'
    manager.mkdir(exist_ok=True)
    for name in ('installer.py', 'release_files.py', 'common.py', 'https_transport.py'):
        source = Path(__file__).resolve().parent / name
        if source.resolve() != (manager / name).resolve():
            shutil.copy2(source, manager / name)
    path = root / 'Install.command'
    path.write_text('#!/bin/zsh\nset -eu\nPROJECT_ROOT="${0:A:h}"\n'
                    'exec python3 "$PROJECT_ROOT/installer/installer.py" --root "$PROJECT_ROOT" "$@"\n')
    path.chmod(0o755)


def progress_label(name):
    last = [0.0]
    def progress(done, total):
        now = time.monotonic()
        if now - last[0] >= 1 or done == total:
            print(f'\r{name}: {done / total * 100:5.1f}% ({done / 1024**2:.0f}/{total / 1024**2:.0f} MiB)', end='', flush=True)
            last[0] = now
    return progress


def install(root, sdk, manifest_location, name, port, hardware, manifest_sha256=None):
    root = root.expanduser().resolve()
    if root in (Path('/'), Path.home().resolve()) or (root / '.git').exists():
        raise RuntimeError('请使用独立安装目录，例如 ~/ColorOS-AVD。')
    manifest, base = read_manifest(manifest_location, manifest_sha256)
    with installation_lock(root):
        owned_and_idle(root, name, port)
        previous = read_json(root / 'local/installed-release.json')
        if previous:
            if (previous.get('userdata_family') != FAMILY
                    or previous['files']['images/encryptionkey.img']['sha256'] != manifest['files']['images/encryptionkey.img']['sha256']):
                raise RuntimeError('用户数据家族或加密模板不兼容，请安装到新目录。')
            def order(version):
                return tuple(int(n) for n in re.findall(r'\d+', version))
            if order(manifest['version']) < order(previous['version']):
                raise RuntimeError('拒绝保数据降级，请使用新目录。')
        elif any((root / path).exists() for path in ('images', 'avd', 'local/build.json')):
            raise RuntimeError('此目录含来源不明的固件或 userdata，请选择新的安装目录。')
        avd = root / 'avd' / (name + '.avd')
        raw = avd / 'userdata-qemu.img'
        if raw.exists() and raw.stat().st_size > int(hardware['disk.dataPartition.size'][:-1]) * 1024**3:
            raise RuntimeError('已有用户分区不能缩小，请增加存储容量。')
        total = sum(part['size'] for part in manifest['parts'])
        needed = total + sum(entry['size'] for path, entry in manifest['files'].items() if path != 'images/userdata.img') + 2 * 1024**3
        if shutil.disk_usage(root).free < needed:
            raise RuntimeError(f'磁盘可用空间不足，安装前请至少保留 {needed / 1024**3:.1f} GiB。')
        cache = root / 'downloads' / manifest['version']
        cache.mkdir(parents=True, exist_ok=True)
        parts = []
        for entry in manifest['parts']:
            if isinstance(base, Path):
                path = base / entry['name']
                if path.is_symlink() or path.stat().st_size != entry['size'] or sha256(path) != entry['sha256']:
                    raise RuntimeError('离线分卷校验失败：' + entry['name'])
            else:
                path = download(base + entry['name'], cache / entry['name'], entry, progress_label(entry['name']))
                print()
            parts.append(path)
        versions = root / 'versions'
        versions.mkdir(exist_ok=True)
        version = versions / manifest['version']
        if version.exists():
            for path, entry in manifest['files'].items():
                existing = version / path
                if not existing.is_file() or existing.is_symlink() or sha256(existing) != entry['sha256']:
                    raise RuntimeError('已有版本目录与发布清单不符，请保留现场并使用新目录。')
        else:
            with tempfile.TemporaryDirectory(prefix='.install-', dir=versions) as staging:
                print('正在解压并逐文件校验固件……', flush=True)
                candidate = extract_release(parts, manifest, Path(staging) / 'candidate')
                candidate.rename(version)
        # Back up any existing AVD before changing its firmware/configuration.
        if raw.exists():
            # Use the matching installed runtime, rather than importer globals.
            environment = dict(os.environ, COLOROS_AVD_WORKSPACE=str(root))
            script = root / 'versions' / previous['version'] / 'runtime/scripts'
            code = 'import sys;from pathlib import Path;sys.path.insert(0,sys.argv[1]);from avd_userdata import backup_userdata;backup_userdata(Path(sys.argv[2]))'
            subprocess.run([sys.executable, '-c', code, str(script), str(avd)], env=environment, check=True)
        saved = {}
        for relative in ('local/runtime.json', 'local/build.json', 'local/installed-release.json',
                         'local/instances.json', 'config/avd.ini', 'Start.command', 'Setup.command',
                         'Uninstall.command', 'Install.command', 'avd/' + name + '.avd/config.ini'):
            path = root / relative
            saved[relative] = path.read_bytes() if path.is_file() else None
        registry = avd_home() / (name + '.ini')
        registry_before = registry.read_bytes() if registry.is_file() else None
        old_links = {}
        for relative in ('images', 'tools'):
            path = root / relative
            if path.exists() and not path.is_symlink():
                raise RuntimeError('安装目录含非安装器管理的 ' + relative)
            old_links[relative] = os.readlink(path) if path.is_symlink() else None
        try:
            for relative in ('images', 'tools'):
                link = root / ('.' + relative + '.next')
                link.unlink(missing_ok=True)
                link.symlink_to(Path('versions') / manifest['version'] / relative, target_is_directory=True)
                link.replace(root / relative)
            config = root / 'config'
            config.mkdir(exist_ok=True)
            shutil.copy2(version / 'config/avd.ini', config / 'avd.ini')
            write_json(root / 'local/runtime.json', {'name': name, 'port': port, 'sdk': str(sdk), 'hardware': hardware})
            write_json(root / 'local/build.json', manifest['build'])
            write_json(root / 'local/installed-release.json', manifest)
            run_runtime(root, 'setup.py', ['--sdk', str(sdk), '--name', name, '--port', str(port)])
            wrappers(root, manifest['version'])
        except BaseException:
            for relative, target in old_links.items():
                path = root / relative
                if path.is_symlink():
                    path.unlink()
                if target is not None:
                    path.symlink_to(target, target_is_directory=True)
            for relative, data in saved.items():
                path = root / relative
                if data is None:
                    path.unlink(missing_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(data)
            if registry_before is None:
                registry.unlink(missing_ok=True)
            else:
                registry.write_bytes(registry_before)
            raise
        print(f'安装完成：{name} / {manifest["version"]}\n启动：{root / "Start.command"}\n管理：{root / "Install.command"}')
    return manifest


def collect_install_options(root, state, args):
    hardware = state.get('hardware', {})
    values = {
        'sdk': str(state.get('sdk', Path.home() / 'Library/Android/sdk')),
        'name': state.get('name', DEFAULT_NAME),
        'port': str(state.get('port', DEFAULT_PORT)),
        'ram': str(int(hardware.get('hw.ramSize', '6144')) / 1024),
        'storage': hardware.get('disk.dataPartition.size', '16G').rstrip('G'),
        'cores': hardware.get('hw.cpu.ncore', '4'),
    }
    fields = (
        ('sdk', 'Android SDK 路径'), ('name', 'AVD 名称'), ('port', 'ADB 控制台端口'),
        ('ram', '内存 GiB'), ('storage', '存储 GiB'), ('cores', 'CPU 核数'))
    index = 0
    while True:
        if index == len(fields):
            try:
                name, port = values['name'], int(values['port'])
                ram, storage, cores = float(values['ram']), int(values['storage']), int(values['cores'])
                hardware = validate_options(name, port, ram, storage, cores)
            except (RuntimeError, ValueError) as error:
                print('配置无效：' + str(error))
                index = max(0, len(fields) - 1)
                continue
            print('\n安装摘要')
            print(f'目录：{root}\n实例：{name}\n端口：{port}\n资源：{ram:g} GiB RAM / {storage} GiB data / {cores} 核')
            choice = input('[1] 开始安装/升级  [2] 重新填写  [0] 返回菜单：').strip()
            if choice == '1':
                sdk = require_environment(Path(values['sdk']), True)
                location = args.bundle or release_url(args.release) + 'manifest.json'
                install(root, sdk, location, name, port, hardware, args.manifest_sha256)
                if ask('安装完成后立即启动？y/n', 'y').lower() == 'y':
                    run_runtime(root, 'launch.py')
                return
            if choice == '2':
                index = 0
                continue
            index = len(fields) - 1
            continue
        key, label = fields[index]
        try:
            values[key] = prompt(label, values[key])
            index += 1
        except Back:
            index = max(0, index - 1)


def wizard(args):
    root = select_root(args.root)
    if root is None:
        return
    while True:
        state = read_json(root / 'local/runtime.json')
        installed = read_json(root / 'local/installed-release.json')
        print('\nColorOS-AVD 安装向导\n目录：' + str(root))
        print('版本：' + installed.get('version', '未安装'))
        print('[1] 安装 / 升级   [2] 启动   [3] 调整资源   [4] 卸载   [5] 更换目录   [0] 退出')
        choice = input('选择：').strip()
        if choice == '0': return
        if choice == '5':
            selected = select_root()
            if selected is not None: root = selected
            continue
        try:
            if choice == '1':
                collect_install_options(root, state, args)
            elif choice == '2':
                run_runtime(root.resolve(), 'launch.py')
            elif choice == '3':
                if not installed:
                    raise RuntimeError('请先安装固件。')
                hardware = state.get('hardware', {})
                values = validate_options(state['name'], state['port'],
                    float(ask('内存 GiB', int(hardware.get('hw.ramSize', '6144')) / 1024)),
                    int(ask('存储 GiB', hardware.get('disk.dataPartition.size', '16G').rstrip('G'))),
                    int(ask('CPU 核数', hardware.get('hw.cpu.ncore', '4'))))
                owned_and_idle(root.resolve(), state['name'], state['port'])
                old_storage = int(hardware.get('disk.dataPartition.size', '16G').rstrip('G'))
                if int(values['disk.dataPartition.size'][:-1]) < old_storage:
                    raise RuntimeError('存储只允许增大。')
                write_json(root / 'local/runtime.json', {**state, 'hardware': values})
                run_runtime(root.resolve(), 'setup.py')
                print('资源配置已保存，下一次启动时生效。')
            elif choice == '4':
                delete = ask('同时删除实例数据？y/n', 'n').lower() == 'y'
                run_runtime(root.resolve(), 'uninstall.py', ['--delete-data'] if delete else [])
            else:
                print('请选择 0–5。')
        except Back:
            continue
        except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
            print('操作失败：' + str(error))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', nargs='?', choices=('install', 'start', 'uninstall'))
    parser.add_argument('--root', type=Path)
    parser.add_argument('--sdk', type=Path)
    parser.add_argument('--bundle', type=Path, help='Offline manifest.json')
    parser.add_argument('--release', default='latest')
    parser.add_argument('--manifest-sha256', help=argparse.SUPPRESS)
    parser.add_argument('--name', default=DEFAULT_NAME)
    parser.add_argument('--port', type=int, default=DEFAULT_PORT)
    parser.add_argument('--ram', type=float, default=6)
    parser.add_argument('--storage', type=int, default=16)
    parser.add_argument('--cores', type=int, default=4)
    parser.add_argument('--start', action='store_true')
    parser.add_argument('--delete-data', action='store_true')
    args = parser.parse_args()
    host_check()
    if args.action is None:
        wizard(args)
        return
    root = (args.root or Path.home() / 'ColorOS-AVD').expanduser().resolve()
    if args.action == 'install':
        sdk = require_environment(args.sdk or Path.home() / 'Library/Android/sdk')
        hardware = validate_options(args.name, args.port, args.ram, args.storage, args.cores)
        install(root, sdk, args.bundle or release_url(args.release) + 'manifest.json', args.name, args.port, hardware, args.manifest_sha256)
        if args.start:
            run_runtime(root, 'launch.py')
    elif args.action == 'start':
        run_runtime(root, 'launch.py')
    else:
        run_runtime(root, 'uninstall.py', ['--delete-data'] if args.delete_data else [])


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit('\n已取消；已验证下载会保留。')
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        raise SystemExit('安装失败：' + str(error))
