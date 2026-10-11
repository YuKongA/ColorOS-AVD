"""Build the Ranchu double-tap-to-wake bridge (DEX + evdev JNI)."""
from pathlib import Path
import subprocess


def build(sdk: Path, work: Path) -> tuple[bytes, bytes]:
    source = Path(__file__).resolve().parents[1] / 'native/double_tap_wake'
    android = sdk / 'platforms/android-36/android.jar'
    d8 = sdk / 'build-tools/36.0.0/d8'
    compilers = list(sdk.glob('ndk/*/toolchains/llvm/prebuilt/darwin-*/bin/aarch64-linux-android35-clang++'))
    if not android.is_file() or not d8.is_file() or not compilers:
        raise RuntimeError('Double-tap bridge needs SDK 36, build-tools 36.0.0 and the ARM64 NDK.')
    compiler = max(compilers, key=lambda p: tuple(int(v) for v in p.parents[5].name.split('.')))
    for directory in ('classes', 'dex'):
        (work / directory).mkdir(parents=True, exist_ok=True)
    subprocess.run(['javac', '--release', '8', '-Xlint:-options', '-classpath', str(android), '-d',
                    str(work / 'classes'), str(source / 'DoubleTapWake.java')], check=True)
    subprocess.run([str(d8), '--min-api', '28', '--output', str(work / 'dex'),
                    str(work / 'classes/com/coloros/avd/DoubleTapWake.class')], check=True)
    library = work / 'libcoloros_double_tap.so'
    subprocess.run([str(compiler), str(source / 'touchscreen.cpp'), '-std=c++17',
                    '-O2', '-Wall', '-Wextra', '-Werror', '-fPIC', '-shared', '-static-libstdc++',
                    '-Wl,-z,max-page-size=16384', '-llog', '-o', str(library)], check=True)
    return (work / 'dex/classes.dex').read_bytes(), library.read_bytes()
