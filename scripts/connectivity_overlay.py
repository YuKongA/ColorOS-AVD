"""Build a resource overlay that leaves Ranchu eth0 to the radio service."""
from pathlib import Path

from resource_overlay import build as build_resource_overlay


def build(sdk: Path, work: Path) -> bytes:
    source = Path(__file__).resolve().parents[1] / 'native/coloros_connectivity'
    return build_resource_overlay(source, sdk, work, 'ColorOSConnectivityOverlay.apk')
