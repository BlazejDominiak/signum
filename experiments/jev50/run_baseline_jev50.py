import json
import time

from run_jev50 import PROTOCOL, ROOT

from signum.ai import create_vision_model
from signum.ai.jev_prompts import decision_questions
from signum.config import AppConfig
from signum.core.rendering import render_pdf_page, to_model_jpeg


def main():
    root = ROOT
    assert decision_questions() == PROTOCOL["baseline_jev_questions"], "Baseline client changed"
    model = create_vision_model(AppConfig(provider="vjev"), api_key="")
    done = set()
    out = root / "jev_baseline.jsonl"
    if out.exists():
        done = {json.loads(x)["sample"] for x in out.read_text().splitlines()}
    try:
        print(model.check_connection(), flush=True)
        with out.open("a", encoding="utf-8") as f:
            for s in json.loads((root / "labels.json").read_text(encoding="utf-8"))["samples"]:
                if s["id"] in done:
                    continue
                im = render_pdf_page(root / "pdf" / f"{s['document']}.pdf", s["page"]).image
                t = time.perf_counter()
                row = {"sample": s["id"]}
                try:
                    row["response"] = model._decide(
                        to_model_jpeg(im, 1120), PROTOCOL["states"]["default"]
                    )
                    ans = row["response"]["answers"]
                    row["score"] = max(ans["handwritten"]["noul"], ans["initials"]["noul"])
                    row["predicted"] = row["score"] >= 0.5
                except Exception as e:
                    row["error"] = repr(e)
                row["elapsed_s"] = time.perf_counter() - t
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
                print(
                    s["id"],
                    row.get("score", row.get("error")),
                    round(row["elapsed_s"], 2),
                    flush=True,
                )
    finally:
        print(model.stop_local(), flush=True)


if __name__ == "__main__":
    main()
