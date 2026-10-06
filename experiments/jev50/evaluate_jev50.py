import hashlib
import json
import math
import statistics

from fit_jev50 import ROOT, features, metrics, read_rows, sigmoid


def main():
    config = json.loads((ROOT / "heuristic_frozen.json").read_text())
    labels = json.loads((ROOT / "labels.json").read_text(encoding="utf-8"))
    assert (
        config["labels_sha256"] == hashlib.sha256((ROOT / "labels.json").read_bytes()).hexdigest()
    )
    rows = read_rows()
    baseline = {
        json.loads(line)["sample"]: json.loads(line)
        for line in (ROOT / "jev_baseline.jsonl").read_text().splitlines()
    }
    gemma = {
        json.loads(line)["sample"]: json.loads(line)
        for line in (ROOT / "gemma_raw.jsonl").read_text(encoding="utf-8").splitlines()
    }
    binary = {
        json.loads(line)["sample"]: json.loads(line)
        for line in (ROOT / "gemma_binary.jsonl").read_text(encoding="utf-8").splitlines()
    }
    assert len(baseline) == len(gemma) == len(binary) == 100
    results = []
    for s in labels["samples"]:
        values, cost, spec = features(rows, s["id"])
        score = values[config["feature"]]
        cal = config["calibration"]
        prob = sigmoid(cal["intercept"] + cal["slope"] * 4 * (score - 0.5))
        results.append(
            {
                **s,
                "heuristic_score": score,
                "full_score": rows[(s["id"], "full", "default")]["scores"]["choice"],
                "bottom_score": rows[(s["id"], "bottom", "default")]["scores"]["choice"],
                "heuristic_probability": prob,
                "heuristic_predicted": score >= config["threshold"],
                "heuristic_elapsed_s": cost[config["feature"]],
                "heuristic_requests": spec[config["feature"]]["requests"],
                "jev_baseline": baseline[s["id"]],
                "gemma": gemma[s["id"]],
                "gemma_binary": binary[s["id"]],
            }
        )
    report = {
        "config": config,
        "summary": {},
        "samples": results,
        "error_policy": (
            "Failed inference or parsing counts as a wrong answer; never silently dropped."
        ),
    }
    for split in ["dev", "test", "all"]:
        subset = [r for r in results if split == "all" or r["split"] == split]
        truth = [r["has_signature"] for r in subset]
        summ = {}
        for name in ["jev_baseline", "gemma", "gemma_binary", "heuristic"]:
            if name == "heuristic":
                pred = [r["heuristic_predicted"] for r in subset]
                times = [r["heuristic_elapsed_s"] for r in subset]
                errors = 0
            else:
                pred = [
                    r[name].get("predicted", not r["has_signature"])
                    if "error" not in r[name]
                    else not r["has_signature"]
                    for r in subset
                ]
                times = [r[name]["elapsed_s"] for r in subset]
                errors = sum("error" in r[name] for r in subset)
            summ[name] = {
                **metrics(truth, pred),
                "inference_errors": errors,
                "mean_s": statistics.mean(times),
                "median_s": statistics.median(times),
                "total_s": sum(times),
            }
            valid = subset if name == "heuristic" else [r for r in subset if "error" not in r[name]]
            answers = [
                r["heuristic_predicted"] if name == "heuristic" else r[name]["predicted"]
                for r in valid
            ]
            valid_correct = sum(
                p == r["has_signature"] for p, r in zip(answers, valid, strict=True)
            )
            summ[name].update(
                {
                    "valid_n": len(valid),
                    "coverage": len(valid) / len(subset),
                    "valid_accuracy": valid_correct / len(valid) if valid else None,
                    "valid_fp": sum(
                        p and not r["has_signature"] for p, r in zip(answers, valid, strict=True)
                    ),
                    "valid_fn": sum(
                        not p and r["has_signature"] for p, r in zip(answers, valid, strict=True)
                    ),
                    "error_positive": 0
                    if name == "heuristic"
                    else sum("error" in r[name] and r["has_signature"] for r in subset),
                    "error_negative": 0
                    if name == "heuristic"
                    else sum("error" in r[name] and not r["has_signature"] for r in subset),
                }
            )
        for name in ["jev_baseline", "heuristic"]:
            scores = [
                r["jev_baseline"].get("score", 0.5)
                if name == "jev_baseline"
                else r["heuristic_probability"]
                for r in subset
            ]
            summ[name]["brier"] = statistics.mean(
                (x - y) ** 2 for x, y in zip(scores, truth, strict=True)
            )
        # Paired outcomes, exact two-sided McNemar (descriptive at this small sample).
        summ["paired"] = {}
        for comparator in ["gemma", "gemma_binary"]:
            hbetter = sum(
                r["heuristic_predicted"] == r["has_signature"]
                and (
                    "error" in r[comparator] or r[comparator].get("predicted") != r["has_signature"]
                )
                for r in subset
            )
            gbetter = sum(
                r["heuristic_predicted"] != r["has_signature"]
                and "error" not in r[comparator]
                and r[comparator].get("predicted") == r["has_signature"]
                for r in subset
            )
            n = hbetter + gbetter
            p = (
                min(1.0, 2 * sum(math.comb(n, k) for k in range(min(hbetter, gbetter) + 1)) / 2**n)
                if n
                else 1.0
            )
            summ["paired"][comparator] = {
                "heuristic_only_correct": hbetter,
                "gemma_only_correct": gbetter,
                "mcnemar_exact_p": p,
            }
        report["summary"][split] = summ
    (ROOT / "results.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(report["summary"], indent=2))
    print(
        "ERRORS",
        [
            (
                r["id"],
                r["has_signature"],
                r["heuristic_score"],
                r["jev_baseline"].get("predicted"),
                r["gemma"].get("predicted"),
            )
            for r in results
            if r["heuristic_predicted"] != r["has_signature"]
            or r["gemma"].get("predicted") != r["has_signature"]
            or r["jev_baseline"].get("predicted") != r["has_signature"]
        ],
    )


if __name__ == "__main__":
    main()
