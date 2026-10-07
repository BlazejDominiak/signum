"""Local, reproducible audit and extra-analysis pilot using already downloaded PDFs."""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import json
import os
import statistics
import subprocess
import time
from dataclasses import asdict
from pathlib import Path

import requests
from PIL import Image

from signum.ai import create_vision_model
from signum.ai.base import PageAnalysis
from signum.config import AppConfig
from signum.core.cropping import crop_box_2d, overview_box_2d
from signum.core.rendering import render_pdf_page, to_model_jpeg

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "scratch" / "additional-analysis"
CORPUS = ROOT / "scratch" / "jev50" / "fresh"


def ensure_ollama(session: requests.Session) -> subprocess.Popen | None:
    try:
        session.get("http://127.0.0.1:11434/api/version", timeout=2).raise_for_status()
        return None
    except requests.ConnectionError:
        pass
    env = os.environ.copy()
    env.update(
        OLLAMA_MODELS="H:/Ollama/models",
        OLLAMA_HOST="127.0.0.1:11434",
        OLLAMA_NO_CLOUD="1",
        TEMP=str(OUTPUT),
        TMP=str(OUTPUT),
    )
    with (OUTPUT / "ollama-server.log").open("ab") as log:
        process = subprocess.Popen(
            ["C:/Users/B/AppData/Local/Programs/Ollama/ollama.exe", "serve"],
            env=env,
            stdout=log,
            stderr=log,
            stdin=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    for _ in range(100):
        try:
            session.get("http://127.0.0.1:11434/api/version", timeout=1).raise_for_status()
            return process
        except (requests.ConnectionError, requests.Timeout):
            if process.poll() is not None:
                raise RuntimeError("Ollama failed; see ollama-server.log") from None
            time.sleep(0.2)
    raise RuntimeError("Ollama did not become ready")


def save_preview(sample: str, image, result: PageAnalysis, folder: Path) -> list[str]:
    files = []
    image.thumbnail((850, 1200))
    image.save(folder / f"{sample}-page.jpg", quality=90)
    for index, finding in enumerate(result.signatures):
        if finding.box_2d:
            for suffix, factory in (("crop", crop_box_2d), ("overview", overview_box_2d)):
                view = factory(image, finding.box_2d)
                if view:
                    name = f"{sample}-{index}-{suffix}.png"
                    view.save(folder / name)
                    view.close()
                    files.append(name)
    return files


def boundary_samples(folder: Path) -> list[dict]:
    """Move one public real ink signature across two and four grid cells."""
    source = render_pdf_page(CORPUS / "pdf" / "n002.pdf", 1).image
    width, height = source.size
    mark = source.crop((int(width * 0.14), int(height * 0.85),
                        int(width * 0.31), int(height * 0.94)))
    mark.thumbnail((300, 180))
    samples = []
    for key, center_y in (("boundary-two", 375), ("boundary-four", 500)):
        canvas = Image.new("RGB", (1000, 1250), "white")
        canvas.paste(mark, (500 - mark.width // 2, center_y - mark.height // 2))
        path = folder / f"{key}-input.png"
        canvas.save(path)
        canvas.close()
        samples.append({"id": key, "has_signature": True, "image": str(path)})
    mark.close()
    source.close()
    return samples


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "mode", choices=["audit", "gemma-basic", "gemma-full", "jev-basic", "jev-extra"]
    )
    parser.add_argument("--limit", type=int, default=6)
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--boundary", action="store_true")
    args = parser.parse_args()
    folder = OUTPUT / args.mode
    folder.mkdir(parents=True, exist_ok=True)
    samples = json.loads((CORPUS / "labels.json").read_text(encoding="utf-8"))["samples"]
    positives = [s for s in samples if s["has_signature"]]
    negatives = [s for s in samples if not s["has_signature"]]
    samples = [s for pair in zip(positives, negatives, strict=True) for s in pair][: args.limit]
    if args.boundary:
        samples.extend(boundary_samples(folder))
    session = requests.Session()
    session.trust_env = False
    process = None
    model = None
    rows = []
    try:
        if args.mode.startswith("gemma") or args.mode == "audit":
            process = ensure_ollama(session)
            metadata = {
                endpoint: session.get(f"http://127.0.0.1:11434/api/{endpoint}", timeout=10).json()
                for endpoint in ("version", "tags", "ps")
            }
            (folder / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        if args.mode != "audit":
            config = AppConfig(
                provider="vjev" if args.mode.startswith("jev") else "ollama",
                ollama_url="http://127.0.0.1:11434",
                ollama_additional_analysis=args.mode == "gemma-full",
                vjev_additional_analysis=args.mode == "jev-extra",
            )
            model = create_vision_model(config, api_key="")
            started = time.perf_counter()
            print(model.check_connection(), flush=True)
            # Jev preflight already runs a synthetic image; do the same for Ollama
            # so model loading is reported separately from warm page latency.
            if args.mode.startswith("gemma"):
                with Image.new("RGB", (64, 64), "white") as blank:
                    model.analyze_page(to_model_jpeg(blank, 1120))
            (folder / "preflight.json").write_text(
                json.dumps({"elapsed_s": time.perf_counter() - started})
            )
        control = json.loads((ROOT / "experiments/jev50/gemma_binary_protocol.json").read_text())
        with (folder / "results.jsonl").open("w", encoding="utf-8") as handle:
            for repeat in range(args.repeat):
                for sample in samples:
                    started = time.perf_counter()
                    if "image" in sample:
                        with Image.open(sample["image"]) as source:
                            image = source.convert("RGB")
                    else:
                        image = render_pdf_page(
                            CORPUS / "pdf" / f"{sample['document']}.pdf", sample["page"]
                        ).image
                    render_s = time.perf_counter() - started
                    jpeg = to_model_jpeg(image, 1120)
                    row = {
                        "id": sample["id"],
                        "expected": sample["has_signature"],
                        "repeat": repeat,
                        "render_s": render_s,
                        "image_sha256": hashlib.sha256(jpeg).hexdigest(),
                    }
                    started = time.perf_counter()
                    try:
                        if args.mode == "audit":
                            payload = {
                                **control["request"],
                                "messages": [
                                    {
                                        "role": "user",
                                        "content": control["prompt"],
                                        "images": [base64.b64encode(jpeg).decode("ascii")],
                                    }
                                ],
                            }
                            response = session.post(
                                "http://127.0.0.1:11434/api/chat", json=payload, timeout=300
                            )
                            response.raise_for_status()
                            row["response"] = response.json()
                            row["predicted"] = json.loads(row["response"]["message"]["content"])[
                                "has_signature"
                            ]
                        else:
                            calls = []
                            if hasattr(model, "_decide"):
                                original = model._decide

                                def traced(
                                    jpeg, prompt, questions=None, original=original, calls=calls
                                ):
                                    tick = time.perf_counter()
                                    data = original(jpeg, prompt, questions)
                                    calls.append(
                                        {
                                            "elapsed_s": time.perf_counter() - tick,
                                            "image_sha256": hashlib.sha256(jpeg).hexdigest(),
                                            "questions": questions,
                                            "response": data,
                                        }
                                    )
                                    return data

                                model._decide = traced
                            try:
                                result = model.analyze_image(image, 1120)
                            finally:
                                if hasattr(model, "_decide"):
                                    model._decide = original
                            row["analysis_s"] = time.perf_counter() - started
                            row["analysis"] = asdict(result)
                            row["predicted"] = any(s.kind != "stamp" for s in result.signatures)
                            row["calls"] = calls or getattr(model, "last_metrics", [])
                            row["previews"] = save_preview(sample["id"], image, result, folder)
                        row.setdefault("analysis_s", time.perf_counter() - started)
                    except Exception as exc:
                        row["error"] = repr(exc)
                    finally:
                        image.close()
                    row["total_s"] = time.perf_counter() - started + render_s
                    rows.append(row)
                    handle.write(json.dumps(row, ensure_ascii=False) + "\n")
                    handle.flush()
                    print(
                        args.mode,
                        sample["id"],
                        repeat,
                        row.get("predicted", row.get("error")),
                        round(row.get("analysis_s", 0), 3),
                        row.get("analysis", {}).get("description", ""),
                        flush=True,
                    )
    finally:
        if model:
            model.release_resources()
        elif args.mode == "audit":
            session.post(
                "http://127.0.0.1:11434/api/generate",
                json={"model": "gemma4:12b", "keep_alive": 0},
                timeout=30,
            )
        if process:
            process.terminate()
            process.wait(timeout=30)
        session.close()
    summary = {
        "mode": args.mode,
        "n": len(rows),
        "correct": sum(r.get("predicted") == r["expected"] for r in rows if "predicted" in r),
        "median_analysis_s": statistics.median(r["analysis_s"] for r in rows if "analysis_s" in r),
    }
    (folder / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    body = [
        "<!doctype html><meta charset=utf-8><title>Analiza dodatkowa</title>",
        "<style>body{font:16px system-ui;margin:32px}"
        "img{max-width:420px;max-height:550px;border:1px solid #ccc;margin:8px}"
        "section{border-top:1px solid #aaa;padding:16px}pre{white-space:pre-wrap}</style>",
        f"<h1>{html.escape(args.mode)}</h1><pre>{html.escape(json.dumps(summary, indent=2))}</pre>",
    ]
    for row in rows:
        details = {k: v for k, v in row.items() if k not in ("calls", "response", "previews")}
        escaped = html.escape(json.dumps(details, ensure_ascii=False, indent=2))
        body.append(f"<section><h2>{html.escape(row['id'])}</h2><pre>{escaped}</pre>")
        for file in [f"{row['id']}-page.jpg", *row.get("previews", [])]:
            if (folder / file).is_file():
                body.append(f'<img src="{html.escape(file)}">')
        body.append("</section>")
    (folder / "preview.html").write_text("\n".join(body), encoding="utf-8")
    print(summary, flush=True)


if __name__ == "__main__":
    main()
