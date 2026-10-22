"""Build scoped ColorOS video/panorama adapters from reviewable Java sources."""
import hashlib
import io
import os
from pathlib import Path
import subprocess
import zipfile

from https_transport import secure_urlopen

DEPENDENCIES = (
    ('dexlib2.jar', 'https://dl.google.com/dl/android/maven2/com/android/tools/smali/'
     'smali-dexlib2/3.0.9/smali-dexlib2-3.0.9.jar',
     '8b547506f62f91d74b70f4beb4989b99e1ff61fc50b2525e9796ca35f0a351dc'),
    ('guava.jar', 'https://repo.maven.apache.org/maven2/com/google/guava/guava/'
     '31.1-android/guava-31.1-android.jar',
     '32ac2ed709d96d278b5d2e3e5cea178fa4939939c525fb647532f013308db309'),
)


def fetch_dependencies(work: Path):
    """Download the pinned dexlib2 build dependencies into work."""
    for name, url, checksum in DEPENDENCIES:
        path = work / name
        if not path.exists():
            print('Fetching camera DEX build dependency: ' + name, flush=True)
            with secure_urlopen(url, timeout=60) as response:
                downloaded = response.read()
            if hashlib.sha256(downloaded).hexdigest() != checksum:
                raise RuntimeError('Camera build dependency checksum mismatch: ' + name)
            path.write_bytes(downloaded)
        if hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
            raise RuntimeError('Camera build dependency checksum mismatch: ' + name)


def patch_camera_buffers_apk(data: bytes, sdk: Path, work: Path, *, signing_source: bytes) -> bytes:
    sources = Path(__file__).resolve().parents[1] / 'native/coloros_camera'
    work.mkdir(parents=True, exist_ok=True)
    for name in ('classes', 'dex', 'tool'):
        (work / name).mkdir(exist_ok=True)
    fetch_dependencies(work)
    android = sdk / 'platforms/android-36/android.jar'
    build_tools = sdk / 'build-tools/36.0.0'
    if not android.exists() or not (build_tools / 'd8').exists():
        raise RuntimeError('Install SDK platform android-36 and build-tools 36.0.0 for the camera adapters.')
    subprocess.run(['javac', '--release', '8', '-Xlint:-options', '-classpath', str(android),
                    '-d', str(work / 'classes'), str(sources / 'VirtualCameraBuffers.java')], check=True)
    subprocess.run([str(build_tools / 'd8'), '--min-api', '28', '--output', str(work / 'dex'),
                    *map(str, (work / 'classes/com/coloros/avd/camera').glob('*.class'))], check=True)
    classpath = os.pathsep.join(str(work / name) for name, _, _ in DEPENDENCIES)
    subprocess.run(['javac', '--release', '17', '-classpath', classpath,
                    '-d', str(work / 'tool'), str(sources / 'PatchCameraDex.java')], check=True)
    classpath += os.pathsep + str(work / 'tool')
    # classes7 has already received the fixed-width quick-JPEG edit.
    expected = {
        'classes.dex': ('22dc4c4d144b02e12dbb189cb8defaec3cc257a6b3a2f3afa40dd7a220c57b81', 1),
        'classes2.dex': ('67ada1f66ed924ba4e2a22db66caf848125560738b32f9b0e18ce6f6a77b0482', 3),
        'classes3.dex': ('1376ea8d559dd0eb5a5681d8d0d926cabff44cdfa0e68c138aba3edf6e7d3aa7', 1),
        'classes4.dex': ('76e586dd063f4c94089e179754040301bb07674dbc23b6c9fba07db357dcdb52', 1),
        'classes5.dex': ('abba57354337b23f9a9d57d4223bba0ba768fdb22ff5ba9bee16074178e0f0de', 1),
        'classes34.dex': ('a03429fce1fcdf4636134a61f4887fc311637bdb96cd34d0ccb13d575625a061', 10),
        'classes7.dex': ('67dbb7332e7d5fcee46e0b34c6c176ce81e04dac82d3157cbab0c5648f68543c', 48),
    }
    replacements = {}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name, (checksum, count) in expected.items():
            content = archive.read(name)
            if hashlib.sha256(content).hexdigest() != checksum:
                raise RuntimeError('Unsupported ColorOS camera DEX: ' + name)
            original, patched = work / ('input-' + name), work / ('patched-' + name)
            original.write_bytes(content)
            command = ['java', '-cp', classpath, 'PatchCameraDex', str(original), str(patched), str(count)]
            if name == 'classes7.dex':
                command.append(str(work / 'dex/classes.dex'))
            subprocess.run(command, check=True)
            subprocess.run([str(build_tools / 'dexdump'), '-f', str(patched)],
                           stdout=subprocess.DEVNULL, check=True)
            replacements[name] = patched.read_bytes()
        unaligned = work / 'camera-unaligned.apk'
        with zipfile.ZipFile(unaligned, 'w') as output:
            for item in archive.infolist():
                output.writestr(item, replacements.get(item.filename, archive.read(item.filename)))
    aligned = work / 'camera-aligned.apk'
    # Moving DEX entries moves embedded native libraries. The Android linker
    # requires these stored ZIP members to remain page aligned.
    subprocess.run([str(build_tools / 'zipalign'), '-P', '16', '-f', '4',
                    str(unaligned), str(aligned)], check=True)
    subprocess.run([str(build_tools / 'zipalign'), '-c', '-P', '16', '4', str(aligned)], check=True)
    from apk_system_signing import retain_system_signing
    result = retain_system_signing(signing_source, aligned.read_bytes())
    aligned.write_bytes(result)
    subprocess.run([str(build_tools / 'zipalign'), '-c', '-P', '16', '4', str(aligned)], check=True)
    return result
