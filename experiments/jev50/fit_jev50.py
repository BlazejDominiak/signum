import hashlib
import json
import math
import os
import statistics
from pathlib import Path

ROOT = Path(os.environ.get("SIGNUM_JEV_LAB_DIR", "H:/podpisy/scratch/jev50"))


def read_rows():
    result = {}
    for line in (ROOT / "jev_raw.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if "response" not in row:
            continue
        # Repair only the logged client-side key-name mistake; never rerun or replace a prediction.
        row["scores"]["choice"] = row["response"]["answers"]["binary"]["probabilities"]["present"]
        if row.get("error") == "KeyError('probs')":
            row.pop("error")
        if "error" not in row:
            result[(row["sample"], row["view"], row["state"])] = row
    return result


def features(rows, sample):
    out = {}
    cost = {}
    spec = {}

    def add(name, value, keys, description):
        out[name] = value
        cost[name] = sum(rows[(sample, *k)]["elapsed_s"] for k in keys)
        spec[name] = {"requests": len(keys), "keys": keys, "description": description}

    for state in ["default", "short", "polish"]:
        key = ("full", state)
        if (sample, *key) not in rows:
            continue
        s = rows[(sample, *key)]["scores"]
        h = s["handwritten"]
        e = s["execution"]
        p = s["pen_strokes"]
        c = s["choice"]
        a = 1 - s["absence"]
        for name, value, description in [
            ("presence", max(h, s["initials"]), "max(handwritten, initials)"),
            ("handwritten", h, "handwritten"),
            ("execution", e, "execution"),
            ("pen", p, "pen_strokes"),
            ("choice", c, "choice.present"),
            ("mean3", (h + e + p) / 3, "mean(handwritten, execution, pen_strokes)"),
            (
                "median3",
                statistics.median([h, e, p]),
                "median(handwritten, execution, pen_strokes)",
            ),
            (
                "mean_choice",
                (h + e + p + c) / 4,
                "mean(handwritten, execution, pen_strokes, choice.present)",
            ),
            (
                "absence_mix",
                (h + e + p + a) / 4,
                "mean(handwritten, execution, pen_strokes, 1-absence)",
            ),
            (
                "negative_penalty",
                (h + e + p + c) / 4 * (1 - 0.3 * max(s["notes"], s["empty"])),
                "mean4 * (1 - 0.3 * max(notes, empty))",
            ),
        ]:
            add(f"{state}.{name}", value, [key], description)
    if all((sample, v, "default") in rows for v in ["full", "bottom", "tl", "tr", "bl", "br"]):
        for views, tag in [
            (["full", "bottom"], "bottom2"),
            (["full", "tl", "tr", "bl", "br"], "tiles5"),
        ]:
            scores = [rows[(sample, v, "default")]["scores"] for v in views]
            add(
                f"{tag}.max_handwritten",
                max(s["handwritten"] for s in scores),
                [(v, "default") for v in views],
                "max handwriting over fixed views",
            )
            add(
                f"{tag}.max_choice",
                max(s["choice"] for s in scores),
                [(v, "default") for v in views],
                "max binary choice over fixed views",
            )
            add(
                f"{tag}.max_mean",
                max(
                    (s["handwritten"] + s["execution"] + s["pen_strokes"] + s["choice"]) / 4
                    for s in scores
                ),
                [(v, "default") for v in views],
                "max(mean4) over fixed views",
            )
        for bound in [0.55, 0.65, 0.75]:
            full = rows[(sample, "full", "default")]["scores"]["choice"]
            use_tiles = 0.25 < full < bound
            views = ["full", "tl", "tr", "bl", "br"] if use_tiles else ["full"]
            value = max(rows[(sample, v, "default")]["scores"]["choice"] for v in views)
            add(
                f"adaptive{bound}.choice",
                value,
                [(v, "default") for v in views],
                f"full choice; fixed tiles only if 0.25 < full < {bound}",
            )
    return out, cost, spec


def metrics(truth, pred):
    tp = sum(y and p for y, p in zip(truth, pred, strict=True))
    tn = sum(not y and not p for y, p in zip(truth, pred, strict=True))
    fp = sum(not y and p for y, p in zip(truth, pred, strict=True))
    fn = sum(y and not p for y, p in zip(truth, pred, strict=True))
    return {
        "n": len(truth),
        "tp": tp,
        "tn": tn,
        "fp": fp,
        "fn": fn,
        "accuracy": (tp + tn) / len(truth),
        "recall": tp / (tp + fn),
        "specificity": tn / (tn + fp),
        "balanced_accuracy": 0.5 * (tp / (tp + fn) + tn / (tn + fp)),
    }


def sigmoid(z):
    return 1 / (1 + math.exp(-max(-40, min(40, z))))


def calibration(xs, ys):
    # Monotone, ridge regularised logistic calibration on development pages only.
    b = 0.0
    a = 1.0
    for _ in range(100):
        g0 = b * 0.1
        g1 = a * 0.1
        h00 = 0.1
        h01 = 0.0
        h11 = 0.1
        for original_x, y in zip(xs, ys, strict=True):
            x = (original_x - 0.5) * 4
            p = sigmoid(b + a * x)
            w = p * (1 - p)
            g0 += p - y
            g1 += (p - y) * x
            h00 += w
            h01 += w * x
            h11 += w * x * x
        det = h00 * h11 - h01 * h01
        db = (h11 * g0 - h01 * g1) / det
        da = (-h01 * g0 + h00 * g1) / det
        b -= db
        a = max(0.0, a - da)
        if abs(db) + abs(da) < 1e-8:
            break
    return {"intercept": b, "slope": a, "input_transform": "4*(score-0.5)", "ridge": 0.1}


def main():
    labels = json.loads((ROOT / "labels.json").read_text(encoding="utf-8"))
    rows = read_rows()
    # Do not access test labels or scores during fitting.
    dev = [s for s in labels["samples"] if s["split"] == "dev"]
    vectors = {}
    costs = {}
    specs = {}
    for sample in dev:
        x, c, sp = features(rows, sample["id"])
        vectors[sample["id"]] = x
        costs[sample["id"]] = c
        specs.update(sp)
    common = set.intersection(*(set(x) for x in vectors.values()))
    rank = []
    if len(rows) != 800:
        raise RuntimeError(f"Expected 800 successful experiments, got {len(rows)}")
    truth = [s["has_signature"] for s in dev]
    for name in sorted(common):
        values = [vectors[s["id"]][name] for s in dev]
        thresholds = [i / 200 for i in range(20, 181)]
        options = [(metrics(truth, [x >= t for x in values]), t) for t in thresholds]
        m, t = max(
            options, key=lambda mt: (mt[0]["balanced_accuracy"], -mt[0]["fp"], -abs(mt[1] - 0.5))
        )
        rank.append(
            {
                "feature": name,
                "threshold": t,
                "dev": m,
                "mean_elapsed_s": statistics.mean(costs[s["id"]][name] for s in dev),
                "spec": specs[name],
            }
        )
    rank.sort(
        key=lambda r: (
            -r["dev"]["balanced_accuracy"],
            r["dev"]["fp"],
            r["spec"]["requests"],
            abs(r["threshold"] - 0.5),
            r["feature"],
        )
    )
    chosen = rank[0]
    name = chosen["feature"]
    xs = [vectors[s["id"]][name] for s in dev]
    cal = calibration(xs, truth)
    frozen = {
        "version": 1,
        "labels_sha256": hashlib.sha256((ROOT / "labels.json").read_bytes()).hexdigest(),
        "model": "yah01/vjev-vision@2fa8b58e40e5bc351a7d6dd39b953469a8f3ded2",
        "feature": name,
        "threshold": chosen["threshold"],
        "calibration": cal,
        "spec": chosen["spec"],
        "selected_on": "60 dev pages only; publisher-disjoint 40 test pages untouched",
        "development": chosen["dev"],
    }
    target = ROOT / "heuristic_frozen.json"
    if target.exists():
        raise RuntimeError("Frozen config exists: refuse to tune again after test evaluation")
    target.write_text(json.dumps(frozen, indent=2), encoding="utf-8")
    (ROOT / "development_candidates.json").write_text(json.dumps(rank, indent=2), encoding="utf-8")
    print(json.dumps(frozen, indent=2))
    print("TOP_DEV", [(r["feature"], r["threshold"], r["dev"]["accuracy"]) for r in rank[:10]])


if __name__ == "__main__":
    main()
