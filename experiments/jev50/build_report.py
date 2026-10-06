"""Build a durable Polish report and a local browser calculator from frozen results."""

import csv
import hashlib
import json
import math
from pathlib import Path

from build_quality_report import build_quality_report
from fit_jev50 import read_rows
from run_jev50 import ROOT

HERE = Path(__file__).resolve().parent
NAMES = {
    "jev_baseline": "Jev — dotychczasowy klient",
    "heuristic": "Jev — zamrożony kalkulator",
    "gemma": "Gemma — dotychczasowy Signum",
    "gemma_binary": "Gemma — tylko klasyfikacja",
}


def wilson(correct, count):
    p, z = correct / count, 1.959963984540054
    center = (p + z * z / (2 * count)) / (1 + z * z / count)
    margin = z * math.sqrt(p * (1 - p) / count + z * z / (4 * count**2)) / (1 + z * z / count)
    return center - margin, center + margin


def verdict(sample, method):
    if method == "heuristic":
        return "jest" if sample["heuristic_predicted"] else "brak"
    row = sample[method]
    if "error" in row:
        return "błąd odpowiedzi"
    return "jest" if row["predicted"] else "brak"


def main():
    result_bytes = (ROOT / "results.json").read_bytes()
    report = json.loads(result_bytes)
    labels = (ROOT / "labels.json").read_bytes()
    assert hashlib.sha256(labels).hexdigest() == report["config"]["labels_sha256"]
    assert json.loads((HERE / "heuristic.json").read_text()) == report["config"]
    page_hashes = json.loads((ROOT / "page_image_hashes.json").read_text())
    jev_rows = read_rows()
    for sample in report["samples"]:
        pdf = ROOT / "pdf" / f"{sample['document']}.pdf"
        assert hashlib.sha256(pdf.read_bytes()).hexdigest() == sample["pdf_sha256"]
        for method in ["gemma", "gemma_binary"]:
            assert sample[method]["image_sha256"] == page_hashes[sample["id"]]
        assert (
            jev_rows[(sample["id"], "full", "default")]["image_sha256"] == page_hashes[sample["id"]]
        )
    (HERE / "results.json").write_bytes(result_bytes)
    raw_names = ["jev_raw.jsonl", "jev_baseline.jsonl", "gemma_raw.jsonl", "gemma_binary.jsonl"]
    audit = {
        "raw_files": {
            name: {
                "path": str(ROOT / name),
                "sha256": hashlib.sha256((ROOT / name).read_bytes()).hexdigest(),
            }
            for name in raw_names
        },
        "protocol_sha256": hashlib.sha256((HERE / "protocol.json").read_bytes()).hexdigest(),
        "gemma_binary_protocol_sha256": hashlib.sha256(
            (HERE / "gemma_binary_protocol.json").read_bytes()
        ).hexdigest(),
        "labels_sha256": hashlib.sha256(labels).hexdigest(),
        "results_sha256": hashlib.sha256(result_bytes).hexdigest(),
        "verified_pdf_count": len(report["samples"]),
        "verified_identical_gemma_inputs": True,
    }
    (HERE / "audit.json").write_text(json.dumps(audit, indent=2), encoding="utf-8")
    template = (HERE / "calculator.template.html").read_text(encoding="utf-8")
    # Complete results are retained separately. The browser only needs decisions and scores.
    slim = {"config": report["config"], "summary": report["summary"], "samples": []}
    for sample in report["samples"]:
        row = {
            key: value
            for key, value in sample.items()
            if key not in ("jev_baseline", "gemma", "gemma_binary")
        }
        for method in ["jev_baseline", "gemma", "gemma_binary"]:
            row[method] = {
                key: value
                for key, value in sample[method].items()
                if key in ("predicted", "error", "elapsed_s")
            }
        slim["samples"].append(row)
    data = json.dumps(slim, ensure_ascii=False).replace("</", "<\\/")
    (HERE / "calculator.html").write_text(template.replace("__DATA__", data), encoding="utf-8")

    text = [
        "# Poligon Jev / Gemma — obecność podpisów\n",
        "Data: 2026-10-05. Sprzęt: RTX 5060 Ti 16 GB. "
        "Wszystkie dokumenty i inferencje lokalnie na H:.\n",
        "Pierwotna próba: **50 podpisanych publicznych PDF-ów + 50 stron kontrolnych "
        "z 50 innych PDF-ów**. "
        "W każdym dokumencie oceniono jedną wybraną kompletną stronę. Etykiety pochodzą z oględzin "
        "Codex przed inferencją, nie z odpowiedzi Jev ani Gemmy. "
        "Nie weryfikowano autentyczności podpisów.\n",
        "## Oddzielny test: 40 stron\n",
        "20 z podpisem, 20 bez. Wszystkie strony danego wydawcy pozostają w jednym zbiorze; "
        "60 pozostałych stron służyło wyłącznie do wyboru reguły, progu i kalibracji.\n",
    ]
    header = (
        "| Metoda | Poprawne | Trafność | Pominięcia FN | Fałszywe alarmy FP | Błędy¹ | "
        "Mediana | Średnia |\n|---|---:|---:|---:|---:|---:|---:|---:|"
    )

    def table(split):
        lines = [header]
        for method, name in NAMES.items():
            m = report["summary"][split][method]
            lines.append(
                f"| {name} | {m['tp'] + m['tn']}/{m['n']} | {m['accuracy']:.1%} | "
                f"{m['valid_fn']} | {m['valid_fp']} | {m['inference_errors']} | "
                f"{m['median_s']:.3f} s | {m['mean_s']:.3f} s |"
            )
        return "\n".join(lines) + "\n"

    text.append(table("test"))
    text.append(
        "¹ Błąd inferencji lub parsowania liczy się jako niepoprawna decyzja w trafności. "
        "FN/FP w tabeli dotyczą poprawnie odczytanych odpowiedzi i nie zawierają tych błędów. "
        "Nie usuwano trudnych przykładów po odpowiedziach modeli.\n"
    )
    m = report["summary"]["test"]["heuristic"]
    for method in ["gemma", "gemma_binary"]:
        valid = report["summary"]["test"][method]
        value = f"{valid['valid_accuracy']:.1%}" if valid["valid_accuracy"] is not None else "brak"
        text.append(
            f"{NAMES[method]}: pokrycie poprawnymi odpowiedziami "
            f"{valid['valid_n']}/{valid['n']}; trafność wśród tych odpowiedzi {value}. "
            f"Brak odpowiedzi: {valid['error_positive']} stron podpisanych i "
            f"{valid['error_negative']} kontrolnych.\n"
        )
    lower, upper = wilson(m["tp"] + m["tn"], m["n"])
    text.append(
        f"Przy traktowaniu stron jako niezależnych 95% przedział Wilsona dla trafności "
        f"kalkulatora wynosi {lower:.1%}–{upper:.1%}. Dokumenty od tego samego wydawcy "
        "mogą być podobne, więc ten prosty przedział może przeceniać precyzję.\n"
    )
    for comparator in ["gemma", "gemma_binary"]:
        pair = report["summary"]["test"]["paired"][comparator]
        text.append(
            f"Porównanie par z {NAMES[comparator]}: tylko Jev poprawny "
            f"{pair['heuristic_only_correct']}, tylko Gemma poprawna "
            f"{pair['gemma_only_correct']}; dokładny dwustronny test McNemara "
            f"p={pair['mcnemar_exact_p']:.4f}. To opis małej próby, nie dowód "
            "równoważności ani uniwersalnej przewagi modelu.\n"
        )
    text.extend(
        [
            "## Całość: 100 stron (łącznie ze strojeniem)\n",
            table("all"),
            "Ten wynik obejmuje dane użyte do strojenia. Głównym wynikiem generalizacji "
            "jest osobny test powyżej.\n",
            "## Co wygrało na zbiorze do strojenia\n",
            "800 zapytań Jev, 8 wariantów obrazu/kontekstu dla każdej strony, 9 pytań na "
            "wariant. Trzy instrukcje kontekstu: domyślna angielska, krótka angielska, "
            "polska. Widoki: cała strona, dolne 55%, cztery nakładające się ćwiartki "
            "po 60% szerokości i wysokości. Fragmenty są stałe, niezależne od oględzin.\n",
            "Porównano 39 heurystyk, każdą z progami 0,10–0,90 co 0,005. Kryterium: "
            "największa zbilansowana trafność, potem mniej fałszywych alarmów, mniej "
            "zapytań, próg bliżej 0,5 i porządek nazwy. Bez mnożenia skorelowanych "
            "prawdopodobieństw i bez założenia niezależności pytań.\n",
            "Wybrano **max(choice.present całej strony, choice.present dolnych 55%) ≥ "
            "0,455**. Dwa zapytania; 60/60 na zbiorze do strojenia. Regułę zamrożono "
            "przed oceną testu. W kalkulatorze zachowano identyczne 9 pytań, mimo że "
            "decyzja używa tylko pytania binarnego, aby zachować przebadany protokół.\n",
            "## Prawdopodobieństwo\n",
            "Surowy wynik s = max(p_cała, p_dół). Kalibracja logistyczna na 60 stronach "
            "do strojenia z regularyzacją 0,1:\n\n"
            "`p = sigmoid(0.8835469095897316 + 4.074756987698717 × 4 × (s - 0.5))`\n",
            "Decyzję wyznacza próg surowego wyniku, nie p=0,5. Kalibracja pochodzi z "
            "próby 50/50; przy innej częstości podpisów lub innym rodzaju skanów może być "
            "nadmiernie pewna. Nie należy traktować procentu jako potwierdzonej "
            "częstości poprawnych odpowiedzi dla nowych prywatnych dokumentów.\n",
        ]
    )
    text.append(
        f"Brier na osobnym teście (mniej = lepiej): wcześniejsze surowe Jev "
        f"{report['summary']['test']['jev_baseline']['brier']:.4f}; kalibracja "
        f"kalkulatora {report['summary']['test']['heuristic']['brier']:.4f}.\n"
    )
    text.extend(
        [
            "## Dwa błędy zamrożonej reguły w teście\n",
            "`d016_p001`: duży odręczny podpis w górnej części nagłówka pisma. "
            "Kalkulator otrzymał s=0,1029 i pominął podpis. Podgląd: "
            "[pełna strona](../../scratch/jev50/pages/d016_p001.jpg).\n",
            "`d019_p001`: formularz z tekstową adnotacją o podpisie cyfrowym i bladym "
            "znakiem graficznym w tle tego pola, bez odręcznego podpisu. "
            "Kalkulator otrzymał s=0,5893 i zgłosił fałszywy alarm. Podgląd: "
            "[pełna strona](../../scratch/jev50/pages/d019_p001.jpg). "
            "Podpis kryptograficzny jest odrębną cechą dokumentu.\n",
            "Te przykłady są częścią odłożonego testu; ocena reguły nadal wynosi 38/40. "
            "Diagnostyka błędów służy projektowaniu kolejnego eksperymentu, który "
            "potrzebowałby nowego niezależnego testu.\n",
            "## Modele i uczciwość porównania\n",
            "Jev: `yah01/vjev-vision@2fa8b58e40e5bc351a7d6dd39b953469a8f3ded2`, "
            "vjev-serve `37e2ffb2695b9bf278374fdefec24611c3b710c1`. Gemma: lokalne "
            "`gemma4:12b`, 11,9B, Q4_K_M, digest "
            "`4eb23ef187e2c5462566d6a1d3bbbc2f1346d0b4327cbb66d58fffbcc9b2b05c`.\n",
            "Oba modele otrzymują identyczny JPEG kompletnej strony (150 DPI, maksymalny "
            "dłuższy bok 1120 px, jakość 85). Serwer Jev wewnętrznie redukuje obraz do 512 px. "
            "Kalkulator dodatkowo wysyła dolną część jako osobny obraz. SHA256 wejść sprawdza "
            "`build_report.py`. Modele działały kolejno na tym samym GPU.\n",
            "Gemma Signum: temperatura 0, num_ctx 8192, dotychczasowy polski prompt opisujący "
            "dokument, podpisy, parafki, pieczątki i ich współrzędne; retry strukturalny tylko "
            "gdy pierwszy JSON jest niepoprawny. Gemma binarna: jedno pole boolean, ten sam "
            "zakres definicji podpisu, temperatura 0, num_ctx 8192, think=false, limit 64 tokenów, "
            "schemat JSON; jeden przebieg, bez strojenia promptu po ocenie.\n",
            "Czasy to zmierzony czas żądań lokalnego klienta, bez pobierania, renderowania "
            "i startu serwera Jev. Dla Gemmy pierwsze żądanie może obejmować ładowanie modelu; "
            "surowy log je zachowuje. Mediana ogranicza wpływ zimnego startu i błędów. "
            "W trybie binarnym zapisano też czasy ładowania i generacji z API. Czasy Jev "
            "pochodzą z ciepłego przebiegu wariantów eksperymentalnych; suma obu wymaganych "
            "zapytań jest podana dla kalkulatora. To nie pomiar przepustowości wielu dokumentów "
            "ani kosztu energii. Nie mierzono cen chmurowych API.\n",
            "Samo przyspieszenie wobec pełnej analizy Gemmy nie dowodzi przyspieszenia "
            "jednakowego zadania — dlatego pokazano również kontrolę binarną. Nie mierzono "
            "jakości współrzędnych Gemmy ani wycinków podpisów.\n",
            "Dokumentacja protokołu: [Ollama /api/chat](https://docs.ollama.com/api/chat), "
            "[vjev-serve](https://github.com/BubbleCal/vjev-serve). Dokładne instrukcje użyte "
            "w próbie zapisano w `protocol.json` i `gemma_binary_protocol.json`.\n",
            "## Dobór i ograniczenia\n",
            "Przejrzano pulę 161 PDF-ów odnalezionych w wyszukiwarce i na stronach źródłowych, "
            "przetasowaną z ziarnem 20261005. Wybrano podpisane strony i kontrolki po "
            "oględzinach miniatur, powiększeń oraz kompletnych stron. To próba dogodna "
            "administracji/uczelni, nie reprezentatywna losowa próba internetu. Przypadek "
            "niejednoznaczny wykluczono przed inferencją. Korekty etykiet zapisano w manifeście.\n",
            "Strona kontrolna bez podpisu nie oznacza, że cały wielostronicowy PDF jest "
            "niepodpisany. Nie oceniono całych PDF-ów ani trudnego rozróżniania podpisów "
            "od zwykłych notatek na reprezentatywnym zbiorze rękopisów. Ręczna adnotacja "
            "jest pojedynczym przeglądem Codex, bez drugiego niezależnego annotatora. "
            "Publiczne dokumenty mogły występować w danych treningowych modeli.\n",
            "Najpierw parser eksperymentalny odczytywał błędny klucz `probs`, mimo że API "
            "zwracało `probabilities`. Wszystkie surowe odpowiedzi zostały zachowane; "
            "odtworzono wyniki z poprawnego klucza bez ponownej inferencji ani podmiany "
            "odpowiedzi. Usunięto z analizy wyłącznie ten dokładny błąd klienta; inne błędy "
            "liczą się jako błędne decyzje.\n",
            "## Artefakty i uruchomienie\n",
            "`calculator.html` — interaktywny przegląd wyników i kalkulator liczbowy. "
            "`calculator.py` — lokalna analiza nowego PDF/obrazu. `results.json` — "
            "komplet decyzji i surowe odpowiedzi porównań. `audit.json` — skróty wyników "
            "i surowych logów. `sources.csv` / `labels.json` — wszystkie źródła i etykiety. "
            "Dane PDF, podglądy i 800 surowych odpowiedzi Jev: `H:/podpisy/scratch/jev50`. "
            "Instrukcje w `README.md`. Domyślny klient GUI pozostaje osobną metodą bazową.\n",
            "## Wyniki każdego dokumentu\n",
            "| Strona / źródło | Zbiór | Oględziny | Jev wcześniej | Jev kalkulator | "
            "Gemma Signum | Gemma binarna |\n"
            "|---|---|---|---|---|---|---|",
        ]
    )
    for sample in report["samples"]:
        source_url = sample["url"].replace(" ", "%20")
        vals = [
            f"[{sample['id']}]({source_url})",
            sample["split"],
            "podpis" if sample["has_signature"] else "brak",
        ]
        vals.extend(verdict(sample, method) for method in NAMES)
        text.append("| " + " | ".join(vals) + " |")
    if (HERE / "confirmation_results.json").exists():
        text[3:3] = build_quality_report()
    (HERE / "RESULTS.pl.md").write_text("\n".join(text) + "\n", encoding="utf-8")
    with (HERE / "sources.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        keys = ["id", "document", "page", "split", "has_signature", "group", "url", "pdf_sha256"]
        writer = csv.DictWriter(handle, fieldnames=keys, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report["samples"])
    print("Report, browser calculator, sources and audit built; all PDF hashes verified.")


if __name__ == "__main__":
    main()
