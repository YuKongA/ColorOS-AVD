"""Build a resource overlay that leaves Ranchu eth0 to the radio service."""
from pathlib import Path
import subprocess


def build(sdk: Path, work: Path) -> bytes:
    source = Path(__file__).resolve().parents[1] / 'native/coloros_connectivity'
    tools = sdk / 'build-tools/36.0.0'
    android = sdk / 'platforms/android-36/android.jar'
    if not android.is_file() or not all((tools / n).is_file() for n in ('aapt2', 'zipalign', 'apksigner')):
        raise RuntimeError('Install Android SDK platform 36 and build-tools 36.0.0 for the connectivity overlay.')
    compiled = work / 'compiled'
    compiled.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(tools / 'aapt2'), 'compile', '--dir', str(source / 'res'),
                    '-o', str(compiled)], check=True)
    unsigned, aligned, signed = (work / n for n in ('unsigned.apk', 'aligned.apk', 'ColorOSConnectivityOverlay.apk'))
    subprocess.run([str(tools / 'aapt2'), 'link', '-o', str(unsigned),
                    '--manifest', str(source / 'AndroidManifest.xml'), '-I', str(android),
                    str(compiled / 'values_config.arsc.flat')], check=True)
    subprocess.run([str(tools / 'zipalign'), '-f', '4', str(unsigned), str(aligned)], check=True)
    # This overlay has no code or privileged permissions. A local signing key
    # provides a valid APK signature; product placement supplies overlay policy.
    key = work / 'overlay.keystore'
    if not key.exists():
        subprocess.run(['keytool', '-genkeypair', '-noprompt', '-keystore', str(key),
                        '-storepass', 'android', '-keypass', 'android', '-alias', 'overlay',
                        '-keyalg', 'RSA', '-keysize', '2048', '-validity', '10000',
                        '-dname', 'CN=ColorOS AVD Connectivity'], check=True, capture_output=True)
    subprocess.run([str(tools / 'apksigner'), 'sign', '--ks', str(key), '--ks-key-alias', 'overlay',
                    '--ks-pass', 'pass:android', '--key-pass', 'pass:android',
                    '--v4-signing-enabled', 'false', '--out', str(signed), str(aligned)],
                   check=True, capture_output=True)
    subprocess.run([str(tools / 'apksigner'), 'verify', str(signed)], check=True, capture_output=True)
    return signed.read_bytes()
