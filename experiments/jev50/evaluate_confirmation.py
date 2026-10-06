"""Evaluate both frozen calculators without fitting on the fresh confirmation pages."""

import argparse
import hashlib
import json
import math
import statistics
from dataclasses import asdict
from pathlib import Path

import fit_jev50 as fit
from calculator import calculate
from calculator_quality import VIEWS, calculate_quality

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summarize(samples, method):
    truth = [s["has_signature"] for s in samples]
    predictions = [
        s[method]["predicted"] if "error" not in s[method] else not s["has_signature"]
        for s in samples
    ]
    valid = [s for s in samples if "error" not in s[method]]
    result = {
        **fit.metrics(truth, predictions),
        "inference_errors": len(samples) - len(valid),
        "valid_fp": sum(s[method]["predicted"] and not s["has_signature"] for s in valid),
        "valid_fn": sum(not s[method]["predicted"] and s["has_signature"] for s in valid),
        "median_s": statistics.median(s[method]["elapsed_s"] for s in samples),
        "mean_s": statistics.mean(s[method]["elapsed_s"] for s in samples),
    }
    if method != "gemma_binary" and valid:
        result["brier"] = statistics.mean(
            (s[method]["calibrated_probability"] - s["has_signature"]) ** 2 for s in valid
        )
    return result


def evaluate(root, labels, primary, quality):
    fit.ROOT = root
    rows = fit.read_rows()
    raw = {
        (row["sample"], row["view"], row["state"]): row
        for row in map(json.loads, (root / "jev_raw.jsonl").read_text().splitlines())
    }
    gemma = {
        row["sample"]: row
        for row in map(json.loads, (root / "gemma_binary.jsonl").read_text().splitlines())
    }
    assert len(raw) == len(labels["samples"]) * 8
    assert len(gemma) == len(labels["samples"])
    images = json.loads((root / "page_image_hashes.json").read_text())
    samples = []
    for sample in labels["samples"]:
        sid = sample["id"]
        assert sha(root / "pdf" / f"{sample['document']}.pdf") == sample["pdf_sha256"]
        assert gemma[sid]["image_sha256"] == images[sid]
        assert raw[(sid, "full", "default")]["image_sha256"] == images[sid]
        item = {**sample, "gemma_binary": gemma[sid]}
        for name, views in [("primary", ["full", "bottom"]), ("quality", VIEWS)]:
            keys = [(sid, view, "default") for view in views]
            elapsed = sum(raw[key]["elapsed_s"] for key in keys)
            if not all(key in rows for key in keys):
                item[name] = {"error": "Missing valid Jev response", "elapsed_s": elapsed}
                continue
            if name == "primary":
                values = [rows[key]["scores"]["choice"] for key in keys]
                decision = asdict(calculate(*values, primary))
            else:
                scores = {view: rows[(sid, view, "default")]["scores"] for view in views}
                decision = calculate_quality(scores, quality)
                # Check the deployed calculator agrees with the predefined benchmark feature.
                if all((sid, view, "default") in rows for view in [*VIEWS, "bottom"]):
                    feature = fit.features(rows, sid)[0][quality["feature"]]
                    assert math.isclose(decision["score"], feature, abs_tol=1e-12)
            item[name] = {
                **decision,
                "predicted": decision["has_signature"],
                "elapsed_s": elapsed,
                "requests": len(views),
            }
        samples.append(item)
    return samples


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("H:/podpisy/scratch/jev50"))
    args = parser.parse_args()
    lock = json.loads((HERE / "confirmation_protocol.json").read_text())
    for file, key in [
        ("labels_confirmation.json", "labels_sha256"),
        ("heuristic.json", "primary_sha256"),
        ("heuristic_quality.json", "quality_sha256"),
    ]:
        assert sha(HERE / file) == lock[key], f"Frozen protocol changed: {file}"
    assert sha(args.root / "fresh" / "labels.json") == lock["labels_sha256"]
    original = json.loads((HERE / "labels.json").read_text())
    fresh = json.loads((HERE / "labels_confirmation.json").read_text())
    for field in ["group", "pdf_sha256", "document", "id"]:
        assert not {s[field] for s in original["samples"]} & {s[field] for s in fresh["samples"]}
    assert not any(s["group"] == "lomza.bip.net.pl" for s in fresh["samples"])
    primary = json.loads((HERE / "heuristic.json").read_text())
    quality = json.loads((HERE / "heuristic_quality.json").read_text())
    exploratory = evaluate(args.root, original, primary, quality)
    confirmation = evaluate(args.root / "fresh", fresh, primary, quality)
    report = {
        "protocol": lock,
        "quality_parameters": quality,
        "exploratory_original_test": {
            name: summarize([s for s in exploratory if s["split"] == "test"], name)
            for name in ["primary", "quality", "gemma_binary"]
        },
        "confirmation": {
            name: summarize(confirmation, name) for name in ["primary", "quality", "gemma_binary"]
        },
        "all_120": {
            name: summarize([*exploratory, *confirmation], name)
            for name in ["primary", "quality", "gemma_binary"]
        },
        "success_criterion": {
            "maximum_sample_size": 120,
            "accuracy_threshold": 0.98,
            "quality_success": summarize([*exploratory, *confirmation], "quality")["accuracy"]
            >= 0.98,
            "scope": (
                "Descriptive result includes development and exploratory selection pages. "
                "Fresh confirmation is reported separately."
            ),
        },
        "original_samples": exploratory,
        "confirmation_samples": confirmation,
        "raw_audit": {
            f"{prefix}{file}": sha(args.root / prefix / file)
            for prefix in ["", "fresh/"]
            for file in ["jev_raw.jsonl", "gemma_binary.jsonl"]
        },
        "error_policy": "Inference errors count as incorrect; no examples dropped after inference.",
        "caution": (
            "Quality was selected after original test inspection. Only the fresh twenty pages "
            "provide new confirmation. No parameters refitted on confirmation."
        ),
    }
    (HERE / "confirmation_results.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(report["confirmation"], indent=2))


if __name__ == "__main__":
    main()
