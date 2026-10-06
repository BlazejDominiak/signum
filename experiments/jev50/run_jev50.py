"""Resumable local experiment; raw records survive every completed request."""

import argparse
import base64
import hashlib
import json
import os
import time
from pathlib import Path

import requests

from signum.ai import create_vision_model
from signum.ai.parsing import parse_page_analysis
from signum.config import AppConfig
from signum.core.rendering import render_pdf_page, to_model_jpeg

ROOT = Path(os.environ.get("SIGNUM_JEV_LAB_DIR", "H:/podpisy/scratch/jev50"))
PROTOCOL = json.loads(Path(__file__).with_name("protocol.json").read_text(encoding="utf-8"))
QUESTIONS = PROTOCOL["questions"]
STATES = PROTOCOL["states"]
PAGE_PROMPT = PROTOCOL["gemma_prompt"]


def crops(image):
    w, h = image.size
    return {
        "full": image,
        "bottom": image.crop((0, int(h * 0.45), w, h)),
        "tl": image.crop((0, 0, int(w * 0.6), int(h * 0.6))),
        "tr": image.crop((int(w * 0.4), 0, w, int(h * 0.6))),
        "bl": image.crop((0, int(h * 0.4), int(w * 0.6), h)),
        "br": image.crop((int(w * 0.4), int(h * 0.4), w, h)),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("provider", choices=["jev", "gemma"])
    args = ap.parse_args()
    labels = json.loads((ROOT / "labels.json").read_text(encoding="utf-8"))
    out = ROOT / f"{args.provider}_raw.jsonl"
    completed = {}
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            r = json.loads(line)
            if "error" not in r:
                completed[(r["sample"], r.get("view", "full"), r.get("state", "default"))] = r
    config = AppConfig(
        provider="vjev" if args.provider == "jev" else "ollama", ollama_model="gemma4:12b"
    )
    model = create_vision_model(config, api_key="")
    session = requests.Session()
    session.trust_env = False
    try:
        print("CONNECT", model.check_connection(), flush=True)
        with out.open("a", encoding="utf-8") as f:
            for sample in labels["samples"]:
                image = render_pdf_page(
                    ROOT / "pdf" / f"{sample['document']}.pdf", sample["page"]
                ).image
                tasks = (
                    [("full", "default", image)]
                    if args.provider == "gemma"
                    else [(view, "default", im) for view, im in crops(image).items()]
                    + [("full", state, image) for state in ["short", "polish"]]
                )
                for view, state, im in tasks:
                    key = (sample["id"], view, state)
                    if key in completed:
                        continue
                    jpeg = to_model_jpeg(im, 1120)
                    start = time.perf_counter()
                    row = {
                        "sample": sample["id"],
                        "document": sample["document"],
                        "page": sample["page"],
                        "provider": args.provider,
                        "view": view,
                        "state": state,
                        "image_sha256": hashlib.sha256(jpeg).hexdigest(),
                    }
                    try:
                        if args.provider == "jev":
                            payload = {
                                "model": "vjev-vision",
                                "state": [
                                    {"type": "text", "text": STATES[state]},
                                    {
                                        "type": "image",
                                        "source": {
                                            "type": "base64",
                                            "media_type": "image/jpeg",
                                            "data": base64.b64encode(jpeg).decode("ascii"),
                                        },
                                    },
                                ],
                                "questions": QUESTIONS,
                            }
                            raw = model._request("POST", "systemone", json=payload)
                            row["response"] = raw
                            row["scores"] = {
                                k: v["noul"]
                                for k, v in raw["answers"].items()
                                if v["type"] == "noul"
                            }
                            row["scores"]["choice"] = raw["answers"]["binary"]["probabilities"][
                                "present"
                            ]
                        else:
                            raw = model._generate(jpeg, PAGE_PROMPT)
                            result = parse_page_analysis(raw)
                            row["response"] = raw
                            row["signatures"] = [
                                {"kind": s.kind.value, "confidence": s.confidence, "box": s.box_2d}
                                for s in result.signatures
                            ]
                            row["predicted"] = any(
                                s.kind.value in ("handwritten", "initials")
                                for s in result.signatures
                            )
                    except Exception as e:
                        row["error"] = repr(e)
                    row["elapsed_s"] = time.perf_counter() - start
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
                    f.flush()
                    print(
                        sample["id"],
                        view,
                        state,
                        round(row["elapsed_s"], 2),
                        row.get("scores", row.get("predicted", row.get("error"))),
                        flush=True,
                    )
    finally:
        if args.provider == "jev":
            print(model.stop_local(), flush=True)
        else:
            session.post(
                "http://localhost:11434/api/generate",
                json={"model": "gemma4:12b", "keep_alive": 0},
                timeout=30,
            )


if __name__ == "__main__":
    main()
