"""Render the complete frozen page of every sample for local manual inspection."""

import hashlib
import json

from run_jev50 import ROOT

from signum.core.rendering import render_pdf_page, to_model_jpeg


def main():
    target = ROOT / "pages"
    target.mkdir(exist_ok=True)
    samples = json.loads((ROOT / "labels.json").read_text(encoding="utf-8"))["samples"]
    digests = {}
    for sample in samples:
        page = render_pdf_page(ROOT / "pdf" / f"{sample['document']}.pdf", sample["page"])
        jpeg = to_model_jpeg(page.image, 1120)
        (target / f"{sample['id']}.jpg").write_bytes(jpeg)
        digests[sample["id"]] = hashlib.sha256(jpeg).hexdigest()
    (ROOT / "page_image_hashes.json").write_text(json.dumps(digests, indent=2))
    print(f"Rendered {len(digests)} complete pages")


if __name__ == "__main__":
    main()
