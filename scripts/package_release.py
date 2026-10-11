#!/usr/bin/env python3
"""Package a verified ColorOS image and its frozen runtime for GitHub Releases."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
import tempfile
import zipfile

from common import REPO_ROOT, sha256, tool, KSU_ASSETS
from init_userdata import create
from lp_image import unpack
from image_utils import erofs
from native_patches import PROFILES
from release_files import (FAMILY, IMAGE_FILES, TOOLS, RUNTIME_SCRIPTS,
                           validate_manifest, allowed_file)


class PartsWriter:
    def __init__(self, directory, version, limit):
        self.directory, self.version, self.limit = directory, version, limit
        self.parts, self.stream, self.used = [], None, 0

    def write(self, data):
        while data:
            if self.stream is None:
                name = f'ColorOS-AVD-{self.version}-macos-arm64.tar.xz.part{len(self.parts) + 1:03d}'
                self.stream = (self.directory / name).open('xb')
                self.digest, self.used = hashlib.sha256(), 0
                self.parts.append({'name': name})
            block, data = data[:self.limit - self.used], data[self.limit - self.used:]
            self.stream.write(block)
            self.digest.update(block)
            self.used += len(block)
            if self.used == self.limit:
                self.close()

    def close(self):
        if self.stream:
            self.stream.close()
            self.parts[-1].update(size=self.used, sha256=self.digest.hexdigest())
            self.stream = None


def verify_images(workspace, scratch):
    metadata = json.loads((workspace / 'local/build.json').read_text())
    if metadata.get('native_patches') is None or metadata.get('adb_authentication') is not True:
        raise RuntimeError('Rebuild current ColorOS sources before publishing.')
    unpack(workspace / 'images/system.img', scratch)
    for profile in PROFILES.values():
        value = erofs(scratch / 'system.img', '/' + profile.path)
        if hashlib.sha256(value).hexdigest() != profile.after:
            raise RuntimeError('Release native library mismatch: ' + profile.path)
    for key in ('composer_alpha_fix', 'audio_pcm_fix'):
        entry = metadata[key]
        value = erofs(scratch / 'vendor.img', entry['native'].removeprefix('/vendor'))
        if hashlib.sha256(value).hexdigest() != entry['native_sha256']:
            raise RuntimeError('Release Vendor patch mismatch: ' + key)
    from erofs_image import Reader
    from build_coloros import main
    import ast
    tree = ast.parse((REPO_ROOT / 'scripts/build_coloros.py').read_text())
    removals = next(ast.literal_eval(node.value) for node in ast.walk(tree)
                    if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'removals' for t in node.targets))
    reader = Reader(scratch / 'system.img')
    try:
        paths = set(path for path, _ in reader.walk())
    finally:
        reader.close()
    for removed in removals:
        if any(path == removed or path.startswith(removed + '/') for path in paths):
            raise RuntimeError('Removed application remains in release: ' + removed)
    return metadata


def write_installer(directory, version):
    names = ('installer.py', 'release_files.py', 'common.py', 'https_transport.py')
    files = {'scripts/' + name: REPO_ROOT / 'scripts' / name for name in names}
    files['Install.command'] = REPO_ROOT / 'Install.command'
    archive = directory / ('ColorOS-AVD-Installer-' + version + '.zip')
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as output:
        for name, source in files.items():
            output.write(source, name)
    bootstrap = REPO_ROOT / 'install.sh'
    (directory / 'install.sh').write_bytes(bootstrap.read_bytes())
    receipt = {'project': 'ColorOS-AVD', 'format': 1, 'version': version,
               'archive': {'name': archive.name, 'size': archive.stat().st_size, 'sha256': sha256(archive)},
               'files': {name: {'size': path.stat().st_size, 'sha256': sha256(path)} for name, path in files.items()}}
    (directory / 'installer.json').write_text(json.dumps(receipt, indent=2) + '\n')
    return receipt


def package(workspace, directory, version, part_mib=1536, preset=6, threads=2):
    directory.mkdir(parents=True, exist_ok=False)
    try:
        with tempfile.TemporaryDirectory(prefix='release-preflight-', dir=workspace / 'work') as temporary:
            scratch = Path(temporary)
            metadata = verify_images(workspace, scratch / 'packed')
            paths = {'images/' + name: workspace / 'images' / name for name in IMAGE_FILES if name != 'userdata.img'}
            for base in ('data/misc/emulator', 'data/misc/modem_simulator'):
                for path in (workspace / 'images' / base).rglob('*'):
                    if path.is_file():
                        paths['images/' + path.relative_to(workspace / 'images').as_posix()] = path
            paths['images/userdata.img'] = create(scratch / 'userdata.img')
            listing = subprocess.check_output([tool('debugfs', 'e2fsprogs'), '-R', 'ls -p /', str(paths['images/userdata.img'])], stderr=subprocess.DEVNULL, text=True)
            names = {line.split('/')[5] for line in listing.splitlines() if line.startswith('/')}
            if names != {'.', '..', 'lost+found'}:
                raise RuntimeError('Release userdata is not empty.')
            for name in TOOLS:
                paths['tools/' + name] = REPO_ROOT / 'tools/SetWallpaper.dex' if name == 'SetWallpaper.dex' else workspace / 'tools' / name
                if name in KSU_ASSETS and sha256(paths['tools/' + name]) != KSU_ASSETS[name]:
                    raise RuntimeError('KernelSU release hash mismatch.')
            paths['config/avd.ini'] = workspace / 'config/avd.ini'
            paths.update({'runtime/scripts/' + name: REPO_ROOT / 'scripts' / name for name in RUNTIME_SCRIPTS})
            files = {}
            for name, path in paths.items():
                if not allowed_file(name) or path.is_symlink() or not path.is_file():
                    raise RuntimeError('Unexpected release source: ' + name)
                files[name] = {'size': path.stat().st_size, 'sha256': sha256(path),
                               'mode': 0o755 if name == 'tools/ksud-aarch64-linux-android' else 0o644}
            metadata['system_sha256'] = files['images/system.img']['sha256']
            metadata['source_commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO_ROOT, text=True).strip()
            writer = PartsWriter(directory, version, part_mib * 1024**2)
            process = subprocess.Popen([tool('xz', 'xz'), '-' + str(preset), '-T' + str(threads), '-c'],
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE)

            def feed():
                with process.stdin, tarfile.open(fileobj=process.stdin, mode='w|') as archive:
                    for name, path in sorted(paths.items()):
                        print('Packaging: ' + name, flush=True)
                        entry = tarfile.TarInfo(name)
                        entry.size, entry.mode, entry.mtime = files[name]['size'], files[name]['mode'], 0
                        with path.open('rb') as source:
                            archive.addfile(entry, source)
                        if sha256(path) != files[name]['sha256']:
                            raise RuntimeError('Release source changed while packaging: ' + name)

            try:
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(feed)
                    while block := process.stdout.read(1024**2):
                        writer.write(block)
                    future.result()
                if process.wait():
                    raise RuntimeError('xz release compression failed.')
            finally:
                writer.close()
                process.stdout.close()
                if process.poll() is None:
                    process.terminate()
                    process.wait()
            manifest = {'project': 'ColorOS-AVD', 'format': 1, 'platform': 'macos-arm64',
                        'version': version, 'compression': 'xz', 'userdata_family': FAMILY,
                        'build': metadata, 'parts': writer.parts, 'files': files}
            validate_manifest(manifest)
            (directory / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
            installer = write_installer(directory, version)
            manifest_hash = sha256(directory / 'manifest.json')
            installer['firmware_manifest_sha256'] = manifest_hash
            (directory / 'installer.json').write_text(json.dumps(installer, indent=2) + '\n')
            sums = ''.join(sha256(path) + '  ' + path.name + '\n' for path in sorted(directory.iterdir()) if path.is_file())
            (directory / 'SHA256SUMS').write_text(sums)
            print(f'Release prepared: {directory}; compressed bytes={sum(p["size"] for p in writer.parts)}', flush=True)
            return manifest
    except BaseException:
        # A failed directory is retained for inspection and never published as complete.
        (directory / 'FAILED').write_text('Packaging did not complete. Do not publish.\n')
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, default=REPO_ROOT / 'work/coloros-release-r1')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--version', default='v0.1.0-coloros17-r1')
    parser.add_argument('--part-mib', type=int, default=1536)
    parser.add_argument('--preset', type=int, choices=range(10), default=6)
    parser.add_argument('--threads', type=int, default=2)
    args = parser.parse_args()
    if not 1 <= args.part_mib < 2048 or not 1 <= args.threads <= 16:
        raise RuntimeError('Use parts below 2 GiB and 1–16 compression threads.')
    directory = args.output or REPO_ROOT / 'work/releases' / args.version
    package(args.workspace.resolve(), directory.resolve(), args.version, args.part_mib, args.preset, args.threads)


if __name__ == '__main__':
    main()
