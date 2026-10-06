"""Download the frozen public corpus into H:, verifying the original SHA256."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path

import requests

ROOT = Path(os.environ.get("SIGNUM_JEV_LAB_DIR", "H:/podpisy/scratch/jev50"))


def download(sample: dict) -> str:
    target = ROOT / "pdf" / f"{sample['document']}.pdf"
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != sample["pdf_sha256"]:
            raise ValueError(f"Existing file checksum mismatch: {target}")
        return f"Verified {sample['document']}"
    session = requests.Session()
    response = session.get(sample["url"], timeout=(15, 90))
    response.raise_for_status()
    data = response.content
    if not data.startswith(b"%PDF") or hashlib.sha256(data).hexdigest() != sample["pdf_sha256"]:
        raise ValueError(f"Source changed; refuse replacement for {sample['document']}")
    target.write_bytes(data)
    return f"Downloaded {sample['document']}"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, default=Path(__file__).with_name("labels.json"))
    args = parser.parse_args()
    original = args.labels.read_bytes()
    manifest = json.loads(original)
    (ROOT / "pdf").mkdir(parents=True, exist_ok=True)
    (ROOT / "labels.json").write_bytes(original)
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        for result in executor.map(download, manifest["samples"]):
            print(result, flush=True)


if __name__ == "__main__":
    main()
