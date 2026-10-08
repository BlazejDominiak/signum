"""Identity captured with the contents used for classification."""
from pathlib import Path

Fingerprint = tuple[int, int, int, int]


def fingerprint(path: Path) -> Fingerprint:
    info = path.stat()
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns
