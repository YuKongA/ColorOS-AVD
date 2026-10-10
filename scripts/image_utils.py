"""Read files from official or AVD EROFS images."""
import subprocess

from common import tool


def erofs(image, path):
    result = subprocess.run([tool('dump.erofs', 'erofs-utils'), '--cat', '--path=' + path, str(image)],
                            check=True, capture_output=True)
    if not result.stdout:
        raise RuntimeError('Empty file: ' + path)
    return result.stdout

