"""Frozen signature-page calculator selected on the development set only.

Run from the repository root with PYTHONPATH=src. Does not change GUI defaults.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from run_jev50 import QUESTIONS, STATES

from signum.ai import create_vision_model
from signum.config import AppConfig
from signum.core.rendering import load_pages, to_model_jpeg


@dataclass(frozen=True)
class SignatureDecision:
    full_score: float
    bottom_score: float
    score: float
    threshold: float
    has_signature: bool
    calibrated_probability: float


def probability(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Probability must be a finite number in [0, 1].")
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise ValueError("Probability must be a finite number in [0, 1].")
    return result


def calculate(
    full_score: float,
    bottom_score: float,
    parameters: dict,
) -> SignatureDecision:
    if parameters.get("version") != 1 or parameters.get("feature") != "bottom2.max_choice":
        raise ValueError("Unsupported heuristic configuration.")
    full, bottom = probability(full_score), probability(bottom_score)
    threshold = probability(parameters["threshold"])
    score = max(full, bottom)
    calibration = parameters["calibration"]
    intercept, slope = float(calibration["intercept"]), float(calibration["slope"])
    if not math.isfinite(intercept) or not math.isfinite(slope) or slope < 0:
        raise ValueError("Invalid monotone calibration parameters.")
    logit = intercept + slope * 4 * (score - 0.5)
    calibrated = 1 / (1 + math.exp(-max(-40, min(40, logit))))
    return SignatureDecision(full, bottom, score, threshold, score >= threshold, calibrated)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input", type=Path, nargs="?", help="PDF/image; omit for numeric calculator"
    )
    parser.add_argument(
        "--parameters", type=Path, default=Path(__file__).with_name("heuristic.json")
    )
    parser.add_argument("--full", type=float)
    parser.add_argument("--bottom", type=float)
    parser.add_argument("--max-pages", type=int, default=500)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    parameters = json.loads(args.parameters.read_text(encoding="utf-8"))
    if args.input is None:
        if args.full is None or args.bottom is None:
            parser.error("Provide an input document or both --full and --bottom.")
        print(json.dumps(asdict(calculate(args.full, args.bottom, parameters)), indent=2))
        return

    model = create_vision_model(AppConfig(provider="vjev"), api_key="")
    pages, count = load_pages(args.input, args.max_pages)
    results: list[dict] = []
    try:
        model.check_connection()
        for page in pages:
            image = page.image
            bottom = image.crop((0, int(image.height * 0.45), image.width, image.height))
            responses = []
            view_hashes = []
            start = time.perf_counter()
            for view in (image, bottom):
                jpeg = to_model_jpeg(view, 1120)
                view_hashes.append(hashlib.sha256(jpeg).hexdigest())
                encoded = base64.b64encode(jpeg).decode("ascii")
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
                                "data": encoded,
                            },
                        },
                    ],
                }
                responses.append(model._request("POST", "systemone", json=payload))
            scores = [r["answers"]["binary"]["probabilities"]["present"] for r in responses]
            decision = calculate(*scores, parameters)
            results.append(
                {
                    "page": page.number,
                    **asdict(decision),
                    "elapsed_s": time.perf_counter() - start,
                    "image_sha256": dict(zip(["full", "bottom"], view_hashes, strict=True)),
                    "responses": responses,
                }
            )
    finally:
        model.stop_local()
    output = {
        "input": str(args.input.resolve()),
        "input_sha256": hashlib.sha256(
            args.input.read_bytes(),
        ).hexdigest(),
        "parameters": parameters,
        "page_count": count,
        "pages_analyzed": len(results),
        "has_visible_signature": any(r["has_signature"] for r in results),
        "scope": (
            "Handwritten appearance only, without signature authentication or PDF crypto checks."
        ),
        "calibration_scope": (
            "Balanced experimental corpus; not a guaranteed population probability."
        ),
        "pages": results,
    }
    rendered = json.dumps(output, indent=2, ensure_ascii=False)
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered)


if __name__ == "__main__":
    main()
