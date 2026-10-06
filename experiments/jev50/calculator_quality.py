"""Five-view signature calculator; parameters trained on the original development set."""

import argparse
import base64
import hashlib
import json
import math
import time
from pathlib import Path

from calculator import probability
from run_jev50 import QUESTIONS, STATES, crops

from signum.ai import create_vision_model
from signum.config import AppConfig
from signum.core.rendering import load_pages, to_model_jpeg

VIEWS = ["full", "tl", "tr", "bl", "br"]
MEAN_KEYS = ["handwritten", "execution", "pen_strokes", "choice"]


def calculate_quality(scores: dict, parameters: dict) -> dict:
    if parameters.get("version") != 1 or parameters.get("feature") != "tiles5.max_mean":
        raise ValueError("Unsupported quality configuration")
    means = {view: sum(probability(scores[view][key]) for key in MEAN_KEYS) / 4 for view in VIEWS}
    score = max(means.values())
    threshold = probability(parameters["threshold"])
    intercept = float(parameters["calibration"]["intercept"])
    slope = float(parameters["calibration"]["slope"])
    if not math.isfinite(intercept) or not math.isfinite(slope) or slope < 0:
        raise ValueError("Invalid monotone calibration")
    z = intercept + slope * 4 * (score - 0.5)
    return {
        "view_means": means,
        "score": score,
        "threshold": threshold,
        "has_signature": score >= threshold,
        "calibrated_probability": 1 / (1 + math.exp(-max(-40, min(40, z)))),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-pages", type=int, default=500)
    parameters = json.loads(Path(__file__).with_name("heuristic_quality.json").read_text())
    args = parser.parse_args()
    pages, count = load_pages(args.input, args.max_pages)
    model = create_vision_model(AppConfig(provider="vjev"), api_key="")
    results = []
    try:
        model.check_connection()
        for page in pages:
            views = crops(page.image)
            scores, responses, hashes = {}, {}, {}
            started = time.perf_counter()
            for view in VIEWS:
                jpeg = to_model_jpeg(views[view], 1120)
                hashes[view] = hashlib.sha256(jpeg).hexdigest()
                payload = {
                    "model": "vjev-vision",
                    "questions": QUESTIONS,
                    "state": [
                        {"type": "text", "text": STATES["default"]},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": base64.b64encode(jpeg).decode("ascii"),
                            },
                        },
                    ],
                }
                responses[view] = model._request("POST", "systemone", json=payload)
                answers = responses[view]["answers"]
                scores[view] = {key: answers[key]["noul"] for key in MEAN_KEYS if key != "choice"}
                scores[view]["choice"] = answers["binary"]["probabilities"]["present"]
            results.append(
                {
                    "page": page.number,
                    **calculate_quality(scores, parameters),
                    "elapsed_s": time.perf_counter() - started,
                    "image_sha256": hashes,
                    "scores": scores,
                    "responses": responses,
                }
            )
    finally:
        model.stop_local()
    result = {
        "input": str(args.input.resolve()),
        "input_sha256": hashlib.sha256(args.input.read_bytes()).hexdigest(),
        "parameters": parameters,
        "page_count": count,
        "pages_analyzed": len(results),
        "has_visible_signature": any(row["has_signature"] for row in results),
        "scope": "Visible handwriting; no authentication, localisation or PDF crypto checks.",
        "calibration_scope": "Balanced original development corpus only.",
        "pages": results,
    }
    rendered = json.dumps(result, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
