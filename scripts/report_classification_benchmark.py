"""Validate a completed 100 x 12 benchmark and produce its report and chart."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import statistics as st
from pathlib import Path

from benchmark_jevk5_classification import OUTPUT, ROOT

MODES = ("venice", "jevk5", "gemma")
NAMES = {
    "venice": "Jev / Venice API",
    "jevk5": "JevK5 4B / lokalnie",
    "gemma": "Gemma 4 12B / lokalnie",
}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def validate(output: Path) -> tuple[dict, dict, dict]:
    protocol = read_json(output / "protocol.json")
    documents = protocol["documents"]
    assert len(documents) == 100
    assert len({d["pdf_sha256"] for d in documents}) == 100
    assert len({d["id"] for d in documents}) == 100
    assert len(protocol["question"]["criteria"]) == 12
    assert max(d["jevk5_prompt_tokens"] for d in documents) <= 4096
    hashes = {d["id"]: hashlib.sha256(d["text"].encode()).hexdigest() for d in documents}
    assert all(d["text_sha256"] == hashes[d["id"]] for d in documents)
    data, summaries = {}, {}
    for mode in MODES:
        data[mode] = [
            json.loads(line)
            for line in (output / f"{mode}-results.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        measured = [r for r in data[mode] if r["phase"] == "measured"]
        expected = {(d["id"], repeat) for d in documents for repeat in range(3)}
        assert len(measured) == 300 and all(r["valid"] for r in measured), mode
        assert {(r["id"], r["repeat"]) for r in measured} == expected, mode
        assert all(r["choice"] in protocol["labels_pl"] for r in measured), mode
        assert all(r["text_sha256"] == hashes[r["id"]] for r in measured), mode
        assert sum(r["phase"] == "warmup" for r in data[mode]) == 1, mode
        summaries[mode] = read_json(output / f"{mode}-summary.json")
        assert abs(st.mean(r["elapsed_s"] for r in measured) - summaries[mode]["mean_s"]) < 1e-9, (
            mode
        )
    jevk5_rows = data["jevk5"]
    assert all(r["forward_passes"] == 1 for r in jevk5_rows)
    assert max(r["longest_pass_tokens"] for r in jevk5_rows) <= 4096
    assert max(r["response"]["prompt_eval_count"] for r in data["gemma"]) < 8192 - 64
    assert all(r["http_status"] == 200 for r in data["venice"])
    protocol_hash = hashlib.sha256((output / "protocol.json").read_bytes()).hexdigest()
    assert summaries["venice"]["metadata"]["protocol_sha256"] == protocol_hash
    return protocol, data, summaries


def export_csv(output: Path, protocol: dict, data: dict) -> None:
    table = []
    for doc in protocol["documents"]:
        row = {
            key: doc[key]
            for key in (
                "id",
                "path",
                "pages",
                "input_characters",
                "text_sha256",
                "token_limit_truncated",
            )
        }
        for mode in MODES:
            trials = [r for r in data[mode] if r["id"] == doc["id"]]
            row[mode + "_mean_s"] = st.mean(r["elapsed_s"] for r in trials)
            row[mode + "_categories"] = "; ".join(
                dict.fromkeys(protocol["labels_pl"][r["choice"]] for r in trials)
            )
        table.append(row)
    with (output / "wyniki.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(table[0]), delimiter=";")
        writer.writeheader()
        writer.writerows(table)


def chart(output: Path, summaries: dict) -> Path:
    os.environ["MPLCONFIGDIR"] = str(output / "cache" / "matplotlib")
    import matplotlib  # noqa: PLC0415

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt  # noqa: PLC0415

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 14})
    fig, ax = plt.subplots(figsize=(12.8, 7.2), facecolor="#f7f8fa")
    ax.set_facecolor("#f7f8fa")
    means = [st.mean(summaries[m]["passes"]) for m in MODES]
    bars = ax.barh(list(NAMES.values()), means, color=["#007c78", "#4686c6", "#65718a"], height=0.5)
    ax.invert_yaxis()
    for bar, value in zip(bars, means, strict=True):
        label = f"{value:.1f} s".replace(".", ",")
        ax.text(
            value + max(means) * 0.02,
            bar.get_y() + bar.get_height() / 2,
            label,
            va="center",
            weight="bold",
            fontsize=17,
            color="#172b42",
        )
    ax.set_xlim(0, max(means) * 1.19)
    ax.set_xlabel("Czas klasyfikacji 100 dokumentów [s]", labelpad=15)
    ax.grid(axis="x", alpha=0.18)
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0, pad=12)
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.text(0.05, 0.93, "100 PDF-ów · 12 kategorii", size=26, weight="bold", color="#172b42")
    fig.text(
        0.05,
        0.875,
        "Te same teksty • średnia z 3 przejść • zapytania kolejno",
        size=14,
        color="#506174",
    )
    fig.text(
        0.05,
        0.055,
        "Klasyfikacja gotowego tekstu; bez odczytu PDF, ładowania i rozgrzewki.\n"
        "Venice: z siecią i oczekiwaniem na limit API. Lokalnie: RTX 5060 Ti 16 GB. 07.10.2026.",
        size=11,
        color="#506174",
        linespacing=1.6,
    )
    fig.subplots_adjust(left=0.27, right=0.94, top=0.77, bottom=0.23)
    assets = ROOT / "docs" / "assets"
    assets.mkdir(exist_ok=True)
    destination = assets / "classification-100x12.png"
    fig.savefig(destination, dpi=150, facecolor=fig.get_facecolor())
    fig.savefig(destination.with_suffix(".svg"), facecolor=fig.get_facecolor())
    plt.close(fig)
    return destination


def report(output: Path, protocol: dict, data: dict, summaries: dict) -> str:
    gemma, jevk5, venice = (summaries[m] for m in ("gemma", "jevk5", "venice"))
    documents = protocol["documents"]
    batches = {m: st.mean(s["passes"]) for m, s in summaries.items()}
    shortened = sum(d["token_limit_truncated"] for d in documents)
    longest = max(documents, key=lambda d: d["original_prompt_tokens"])
    extraction = sum(d["extraction_s"] for d in documents)
    warmup = {m: next(r for r in data[m] if r["phase"] == "warmup") for m in MODES}
    gemma_tokens = [
        r["response"]["prompt_eval_count"] for r in data["gemma"] if r["phase"] == "measured"
    ]
    metadata = venice["metadata"]
    venice_measured = [r for r in data["venice"] if r["phase"] == "measured"]
    request_batch_s = sum(r["request_elapsed_s"] for r in venice_measured) / 3
    wait_batch_s = sum(r["rate_limit_wait_s"] for r in venice_measured) / 3
    pilot_path = output / "pilot-api-rate-limit" / "venice-results.jsonl"
    pilot_rows = (
        [json.loads(line) for line in pilot_path.read_text(encoding="utf-8").splitlines()]
        if pilot_path.exists()
        else []
    )
    pricing = metadata["model"]["model_spec"]["pricing"]
    pilot_cost = sum(
        r["response"].get("usage", {}).get(f"{kind}_tokens", 0) * pricing[kind]["usd"] / 1_000_000
        for r in pilot_rows
        for kind in ("input", "output")
    )
    text = """# Klasyfikacja 100 PDF-ów do 12 kategorii

Pomiar: 2026-10-07. Każdy model klasyfikował ten sam zestaw 100 dokumentów,
trzykrotnie, wybierając dokładnie jedną z 12 ogólnych kategorii.

| Model | Średnio na dokument | Mediana | Średnio 100 dokumentów |
|---|---:|---:|---:|
"""
    for mode in MODES:
        result = summaries[mode]
        text += (
            f"| {NAMES[mode]} | {result['mean_s']:.3f} s | {result['median_s']:.3f} s "
            f"| **{batches[mode]:.2f} s** |\n"
        )
    text += f"""
Jev przez Venice osiągnął **{gemma["mean_s"] / venice["mean_s"]:.2f}×** tempo Gemmy
i **{jevk5["mean_s"] / venice["mean_s"]:.2f}×** tempo lokalnego JevK5.
Stosunek średnich czasów Gemma / JevK5 wyniósł
**{gemma["mean_s"] / jevk5["mean_s"]:.2f}×**.

**Czas Venice w tabeli zawiera oczekiwanie na limit API.** Na setkę składa się
średnio {request_batch_s:.2f} s obsługi żądań z siecią oraz {wait_batch_s:.2f} s
oczekiwania. Sama obsługa żądań jest {gemma["total_s"] / 3 / request_batch_s:.2f}×
krótsza niż czas Gemmy, ale przy kolejnych setkach znaczenie ma też limit konta.

![Czas klasyfikacji 100 dokumentów](assets/classification-100x12.png)

Wszystkie 900 mierzonych odpowiedzi zawierały kategorię z listy.
To sprawdzenie formatu odpowiedzi, nie 100% trafności: ten eksperyment mierzy
czas, bez ręcznie oznaczonego wzorca poprawnych etykiet.

## Kategorie

"""
    text += "\n".join(f"- {label}." for label in protocol["labels_pl"].values()) + "\n"
    text += f"""
## Sposób pomiaru

- Wylosowano 100 unikalnych PDF-ów z istniejącego korpusu `scratch/jev50`
  ({protocol["candidate_files"]} plików przed filtrowaniem), seed {protocol["seed"]}.
  Pomijano duplikaty, błędy odczytu oraz pliki z mniej niż 200 znakami tekstu.
  Dokumenty wybrano przed pomiarami, bez selekcji według wyniku modelu.
- Każdy model dostał identyczny tekst i te same opisy kategorii. Skróty SHA-256
  potwierdzają zgodność wejść we wszystkich 900 pomiarach.
- Maksymalnie 12 000 znaków z początku dokumentu oraz 4096 tokenów pełnego promptu
  według tokenizera JevK5. Drugi limit skrócił dodatkowo {shortened}/100 tekstów,
  jednakowo dla wszystkich modeli. Zakresy tokenów różnych modeli nie są tożsame.
  Warstwa tekstowa niektórych PDF-ów zawiera błędy; nie poprawiano jej na podstawie
  odpowiedzi modelu. Najdłuższy po tokenizacji tekst `{longest["id"]}` miał
  {longest["original_prompt_tokens"]} tokenów pełnego promptu przed dodatkowym
  limitem; po skróceniu zachowano {longest["input_characters"]} znaków tekstu.
- Mierzono wyłącznie klasyfikację gotowego tekstu, bez OCR, opisywania dokumentu,
  podpisów i wycinków. Nie jest to czas analizy wszystkich stron całego PDF-a.
  Odczyt tekstu ze 100 PDF-ów trwał {extraction:.2f} s i jest poza tabelą.
- Każdy model: jedno syntetyczne żądanie rozgrzewki, potem trzy przejścia po
  100 dokumentów w tej samej kolejności. Zapytania szły kolejno, bez równoległości.
  Czas paczki to suma czasów klasyfikacji wraz z oczekiwaniem na limit API;
  nie obejmuje zapisu logów między żądaniami.
  Model lokalny był zwalniany przed uruchomieniem następnego.
- Gemma: `gemma4:12b`, Q4_K_M przez Ollamę, `think=false`, temperatura 0,
  kontekst 8192, do 64 tokenów odpowiedzi, krótki JSON z kategorią.
  Rzeczywiste wejścia: {min(gemma_tokens)}–{max(gemma_tokens)} tokenów według Ollamy.
  Zmienny znacznik pomiaru na początku ograniczał ponowne użycie cache całego tekstu.
- JevK5: 4B BF16, natywny odczyt decyzji z logitów. Przy 12 opcjach licznik
  rzeczywistych wywołań potwierdził **jeden przebieg w każdym z 300 pomiarów**.
  Przy wcześniejszych 48 opcjach potrzebne były cztery. Bez generowania opisu,
  bez cache KV; czas obejmuje tokenizację i synchronizowaną pracę GPU.
- Oficjalny Jev: `jev-latest`, `POST /api/v1/decisions` w Venice. Czas zawiera
  HTTPS, sieć i oczekiwanie na limit liczby żądań. Każde żądanie zawierało
  jedno pytanie z 12 opcjami. API nie
  ujawnia wersji stojącej za aliasem ani czasu samego serwera.

## Trzy przejścia i uruchomienie

| Model | Przejście 1 | Przejście 2 | Przejście 3 |
|---|---:|---:|---:|
"""
    for mode in MODES:
        text += (
            f"| {NAMES[mode]} | "
            + " | ".join(f"{value:.2f} s" for value in summaries[mode]["passes"])
            + " |\n"
        )
    text += f"""
Ładowanie JevK5: {jevk5["metadata"]["load_s"]:.2f} s; osobna rozgrzewka:
{warmup["jevk5"]["elapsed_s"]:.2f} s. Pierwsze żądanie Gemmy wraz z ładowaniem:
{warmup["gemma"]["elapsed_s"]:.2f} s, w tym ładowanie według Ollamy
{warmup["gemma"]["response"]["load_duration"] / 1e9:.2f} s. Rozgrzewka Venice:
{warmup["venice"]["elapsed_s"]:.2f} s. Te wartości są wyłączone z tabeli wynikowej.

Lokalny sprzęt: {jevk5["metadata"]["gpu"]}, 16 GB.
JevK5 używał PyTorch {jevk5["metadata"]["torch"]},
Transformers {jevk5["metadata"]["transformers"]}, referencyjnych kerneli,
bez grafów CUDA, z limitem alokatora 80% VRAM. Szczyt aktywnej pamięci:
{jevk5["metadata"]["peak_vram_bytes"] / 2**30:.2f} GiB.
Jest to porównanie tych konkretnych lokalnych konfiguracji i usługi chmurowej.

Pierwsza próba bez limitu tokenów wyczerpała VRAM przy długim wejściu.
Zachowano ją w `pilot-input-too-long`; nie wchodzi do wyników.
Po ustaleniu wspólnego limitu ponowiono cały test na wszystkich 100 dokumentach.

Pierwsza seria Venice otrzymała HTTP 429 po 100 zaakceptowanych decyzjach
(rozgrzewka i 99 dokumentów). Jest zachowana w `pilot-api-rate-limit`.
W końcowym przebiegu klient ograniczał wysyłanie do 100 żądań w 61 sekundach;
czas oczekiwania jest zapisany osobno i **wliczony w tabelę oraz wykres**.
To ustawienie klienta dobrane po zaobserwowanym błędzie, nie deklaracja
gwarantowanego limitu dla wszystkich kont Venice.
Dokumentacja opisuje [limity zależne od konta i modelu](https://docs.venice.ai/api-reference/endpoint/api_keys/rate_limits).

## Koszt Venice

301 żądań łącznie z rozgrzewką: {metadata["usage_including_warmup"]["input_tokens"]:,}
tokenów wejściowych. Szacowany koszt według katalogu API odczytanego podczas
testu: **${metadata["estimated_usd_at_catalog_rate"]:.6f}**.
Wcześniejsza seria przerwana limitem API: dodatkowo około **${pilot_cost:.6f}**.
Łącznie te dwie serie: **${metadata["estimated_usd_at_catalog_rate"] + pilot_cost:.6f}**.
To koszt obliczony z użycia tokenów, nie odczyt obciążenia rachunku.
Osobne próby demonstracyjne nie wchodzą do tej kwoty.

## Pliki i pokaz

- Protokół, teksty, surowe odpowiedzi, podsumowania i CSV dokument po dokumencie:
  `H:/podpisy/scratch/jevk5-classification-100x12/`.
- Wykres do prezentacji: `docs/assets/classification-100x12.png` oraz `.svg`.
- Poprzedni [raport 10 × 48](JEVK5_CLASSIFICATION.pl.md) i jego wyniki pozostały
  osobno. Zmieniły się kategorie, skład zestawu i limit wejścia, więc różnicy
  między starym a nowym testem nie można przypisać wyłącznie liczbie kategorii.
- [Instrukcja Venice i pokazu](VENICE.pl.md). Klucz pozostaje w ignorowanym `.env`.

Jedno przejście po 100 dokumentów, z wynikami w osobnym katalogu pokazu:

```powershell
.\\scripts\\run_classification_benchmark.ps1 -Model venice
.\\scripts\\run_classification_benchmark.ps1 -Model jevk5
.\\scripts\\run_classification_benchmark.ps1 -Model gemma
```

Uruchamiaj komendy kolejno. Domyślnie każda robi jedno przejście; `-Repeats 3`
wykonuje trzy. Każda oddziela żądanie rozgrzewki od pomiarów właściwych.
"""
    return text


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=OUTPUT)
    args = parser.parse_args()
    protocol, data, summaries = validate(args.output_dir)
    export_csv(args.output_dir, protocol, data)
    image = chart(args.output_dir, summaries)
    destination = ROOT / "docs" / "CLASSIFICATION_100x12.pl.md"
    destination.write_text(report(args.output_dir, protocol, data, summaries), encoding="utf-8")
    print(
        json.dumps(
            {
                "report": str(destination),
                "chart": str(image),
                "verified_calls": 900,
                "mean_batch_s": {m: st.mean(s["passes"]) for m, s in summaries.items()},
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
