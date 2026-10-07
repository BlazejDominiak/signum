"""Live document classification with TypeSafe Jev via the Venice Decisions API."""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

from benchmark_jevk5_classification import OUTPUT
from venice_api import VeniceClient


def main() -> int:
    parser = argparse.ArgumentParser(description="Pokaz klasyfikacji dokumentów przez Jev / Venice")
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--sample", help="Identyfikator dokumentu z zapisanego testu")
    inputs.add_argument("--file", type=Path, help="PDF lub plik tekstowy do klasyfikacji")
    inputs.add_argument(
        "--list", action="store_true", help="Pokaż dokumenty testowe bez użycia API"
    )
    parser.add_argument("--protocol", type=Path, default=OUTPUT / "protocol.json")
    args = parser.parse_args()
    protocol_path = args.protocol
    if not protocol_path.exists():
        parser.error("Brak zapisanego protocol.json; najpierw przygotuj zestaw benchmarku")
    protocol = json.loads(protocol_path.read_text(encoding="utf-8"))
    if args.list:
        for doc in protocol["documents"]:
            print(f"{doc['id']:18} {doc['pages']:2} stron, {doc['input_characters']:5} znaków")
        return 0
    if args.file:
        if args.file.suffix.lower() == ".pdf":
            from pypdf import PdfReader  # noqa: PLC0415

            content = " ".join(page.extract_text() or "" for page in PdfReader(args.file).pages)
        else:
            content = args.file.read_text(encoding="utf-8-sig")
        content = re.sub(r"\s+", " ", content).strip()[: protocol["max_characters"]]
        name = args.file.name
    else:
        sample_id = args.sample or protocol["documents"][0]["id"]
        doc = next((d for d in protocol["documents"] if d["id"] == sample_id), None)
        if doc is None:
            parser.error("Nieznany dokument. Użyj --list, aby wyświetlić identyfikatory")
        name, content = doc["id"], doc["text"]
    if not content:
        parser.error("Dokument nie zawiera tekstu. Ten pokaz nie wykonuje OCR")
    client = VeniceClient()
    category_count = len(protocol["question"]["criteria"])
    print(f"Dokument: {name} | {len(content)} znaków | {category_count} kategorii", flush=True)
    print(f"Model: {client.config['VENICE_DECISION_MODEL']} / Venice", flush=True)
    start = time.perf_counter()
    try:
        status, result = client.decide(content, protocol["question"])
    finally:
        client.session.close()
    elapsed = time.perf_counter() - start
    if status != 200:
        print(f"API zwróciło HTTP {status}: {result.get('error', 'brak decyzji')}")
        return 1
    answer = result.get("answers", {}).get("document_type", {})
    choice = answer.get("choice")
    if choice not in protocol["labels_pl"]:
        print("API nie zwróciło prawidłowej kategorii")
        return 1
    print(f"\nWynik: {protocol['labels_pl'][choice]}")
    print(f"Czas odpowiedzi z internetem: {elapsed:.3f} s")
    print(f"Pewność modelu: {answer.get('confidence', 0):.1%}")
    print("\nNajwyższe oceny:")
    ranked = sorted(answer.get("probabilities", {}).items(), key=lambda p: -p[1])[:3]
    for key, value in ranked:
        print(f"  {protocol['labels_pl'].get(key, key)}: {value:.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
