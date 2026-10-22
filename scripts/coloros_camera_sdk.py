"""Patch the camera unit SDK by class and method name for the software APS path.

PMX110 uses the byte patches in build_coloros.patch_camera_sdk_jar. Other
firmware ships the same SDK classes at different offsets, so PatchCameraSdk
finds each site by name and checks how many sites it changed.
"""
import hashlib
import io
import os
from pathlib import Path
import subprocess
import zipfile

from coloros_camera_buffers import DEPENDENCIES, fetch_dependencies

# Audited classes.dex inputs and the number of sites each edit must change.
EXPECTED_EDITS = {
    # PLK110 17.0.0.105
    'bfa98f6704e900341bf2e67d3e0bf54a435d91180cccb9d4aed03b42c50cb8e4': {
        'ready': 2, 'aps_mode': 2, 'camera_type': 1, 'capture_metadata': 6,
        'yuv': 1, 'jpeg_orientation': 1, 'preview_camera_id': 1,
    },
}


def patch_camera_sdk_jar(data: bytes, sdk: Path, work: Path) -> bytes:
    sources = Path(__file__).resolve().parents[1] / 'native/coloros_camera'
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        dex = archive.read('classes.dex')
        checksum = hashlib.sha256(dex).hexdigest()
        if checksum not in EXPECTED_EDITS:
            raise RuntimeError('Unsupported ColorOS camera SDK DEX: ' + checksum)
        work.mkdir(parents=True, exist_ok=True)
        for name in ('classes', 'dex', 'tool'):
            (work / name).mkdir(exist_ok=True)
        fetch_dependencies(work)
        android = sdk / 'platforms/android-36/android.jar'
        build_tools = sdk / 'build-tools/36.0.0'
        if not android.exists() or not (build_tools / 'd8').exists():
            raise RuntimeError('Install SDK platform android-36 and build-tools 36.0.0 for the camera SDK patch.')
        subprocess.run(['javac', '--release', '8', '-Xlint:-options', '-classpath', str(android),
                        '-d', str(work / 'classes'), str(sources / 'VirtualCameraSdk.java')], check=True)
        subprocess.run([str(build_tools / 'd8'), '--min-api', '28', '--output', str(work / 'dex'),
                        *map(str, (work / 'classes/com/coloros/avd/camera').glob('*.class'))], check=True)
        classpath = os.pathsep.join(str(work / name) for name, _, _ in DEPENDENCIES)
        subprocess.run(['javac', '--release', '17', '-classpath', classpath,
                        '-d', str(work / 'tool'), str(sources / 'PatchCameraSdk.java')], check=True)
        original, patched = work / 'input-classes.dex', work / 'patched-classes.dex'
        original.write_bytes(dex)
        counts = ','.join(f'{edit}={count}' for edit, count in EXPECTED_EDITS[checksum].items())
        subprocess.run(['java', '-cp', classpath + os.pathsep + str(work / 'tool'), 'PatchCameraSdk',
                        str(original), str(patched), str(work / 'dex/classes.dex'), counts], check=True)
        subprocess.run([str(build_tools / 'dexdump'), '-f', str(patched)],
                       stdout=subprocess.DEVNULL, check=True)
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as target:
            for item in archive.infolist():
                content = patched.read_bytes() if item.filename == 'classes.dex' else archive.read(item.filename)
                target.writestr(item, content)
    return output.getvalue()
