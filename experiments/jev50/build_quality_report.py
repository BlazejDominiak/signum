"""Build the five-view calculator and report the exploratory/confirmation distinction."""

import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
NAMES = {
    "primary": "Jev — dwa widoki",
    "quality": "Jev — pięć widoków",
    "gemma_binary": "Gemma — binarna",
}


def build_quality_report():
    report = json.loads((HERE / "confirmation_results.json").read_text(encoding="utf-8"))
    samples = [*report["original_samples"], *report["confirmation_samples"]]
    slim = {
        "config": report["quality_parameters"],
        "all": report["all_120"],
        "confirmation": report["confirmation"],
        "exploratory": report["exploratory_original_test"],
        "samples": [],
    }
    for sample in samples:
        row = {key: value for key, value in sample.items() if key not in NAMES}
        for method in NAMES:
            row[method] = {
                key: value
                for key, value in sample[method].items()
                if key
                in [
                    "predicted",
                    "error",
                    "elapsed_s",
                    "score",
                    "calibrated_probability",
                    "view_means",
                ]
            }
        slim["samples"].append(row)
    data = json.dumps(slim, ensure_ascii=False).replace("</", "<\\/")
    template = (HERE / "quality.template.html").read_text(encoding="utf-8")
    (HERE / "quality-calculator.html").write_text(
        template.replace("__DATA__", data), encoding="utf-8"
    )
    with (HERE / "sources_confirmation.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "id",
                "document",
                "page",
                "split",
                "has_signature",
                "group",
                "url",
                "pdf_sha256",
            ],
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(report["confirmation_samples"])
    lines = [
        "## Wynik końcowy: 120 stron, próg sukcesu 98%\n",
        "Zgodnie z ustaleniem próba kończy się na 120 stronach: 60 z widocznym podpisem "
        "i 60 kontrolnych z innych PDF-ów. Nie dodawano dalszych dokumentów.\n",
        "| Metoda | Poprawne / 120 | Trafność | Podpisy wykryte / 60 | Fałszywe alarmy / 60 |\n"
        "|---|---:|---:|---:|---:|",
    ]
    for method, name in NAMES.items():
        m = report["all_120"][method]
        lines.append(
            f"| {name} | {m['tp'] + m['tn']}/{m['n']} | {m['accuracy']:.2%} | "
            f"{m['tp']}/60 | {m['valid_fp']}/60 |"
        )
    lines.extend(
        [
            "\n**Jev z pięcioma widokami spełnia ustalony próg sukcesu.** "
            "Wynik 120 stron obejmuje jednak 60 stron strojenia, 40 stron użytych do wyboru "
            "wariantu w analizie dodatkowej oraz 20 nowych stron potwierdzających. "
            "Nie należy przedstawiać całych 120 jako niezależnego testu generalizacji.\n",
            "## Dokładniejszy kalkulator i dodatkowa próba: 20 nowych stron\n",
            "Po pierwotnej ocenie porównano dodatkowo 39 wcześniej zdefiniowanych reguł, "
            "z progami dopasowanymi wyłącznie na 60 stronach do strojenia. Wariant pięciu widoków "
            "osiągnął 40/40 w pierwotnym teście, ale został wybrany po obejrzeniu tego wyniku. "
            "To **analiza eksploracyjna**, a nie niezależne potwierdzenie wybranego wariantu.\n",
            "Następnie znaleziono i obejrzano 20 stron z 20 kolejnych PDF-ów: 10 podpisanych "
            "i 10 kontrolnych. Wydawcy i SHA256 nie pokrywają się z pierwotnymi 100. "
            "Parametry wariantu pięciu widoków zamrożono przed wyborem tej próby; etykiety "
            "zapisano przed inferencją. **Nie dostrajano parametrów po nowym teście**. "
            "Łącznie sprawdzono 60 podpisanych dokumentów i 60 stron kontrolnych "
            "z innych PDF-ów.\n",
            "| Nowa próba | Poprawne | Pominięcia | Fałszywe alarmy | Błędy odpowiedzi | "
            "Mediana / strona |\n"
            "|---|---:|---:|---:|---:|---:|",
        ]
    )
    for method, name in NAMES.items():
        m = report["confirmation"][method]
        lines.append(
            f"| {name} | {m['tp'] + m['tn']}/{m['n']} | {m['valid_fn']} | {m['valid_fp']} | "
            f"{m['inference_errors']} | {m['median_s']:.3f} s |"
        )
    lines.extend(
        [
            "\nW tej nowej próbie dokładniejszy Jev dorównał Gemmie binarnej, lecz był około "
            "2,3 razy wolniejszy. 20/20 to mała próba; nie dowodzi uniwersalnej przewagi "
            "ani statystycznej równoważności. Nie potwierdzono przewagi ceny API czy energii.\n",
            "Reguła: dla całej strony i czterech nakładających się fragmentów po 60% oblicz "
            "`mean(handwritten, execution, pen_strokes, choice.present)`, a następnie "
            "`s = max(pięć średnich)`. Podpis, gdy `s ≥ 0.535`. W każdym zapytaniu pozostaje "
            "ten sam zamrożony zestaw 9 pytań. Pozostałe odpowiedzi służą audytowi. "
            "Średnia jest heurystyką, nie połączonym niezależnym prawdopodobieństwem.\n",
            "Kalibracja wyłącznie na pierwotnych 60 stronach do strojenia: "
            "`p = sigmoid(-1.2752369584469005 + 4.525887113758848 × 4 × (s - 0.5))`. "
            "Brier w nowym teście wynosi "
            f"{report['confirmation']['quality']['brier']:.6f}. Mała, zbilansowana próba "
            "nie potwierdza wiarygodności procentów na dowolnych nowych dokumentach.\n",
            "[Kalkulator pięciu widoków](quality-calculator.html), `calculator_quality.py` "
            "do analizy własnego PDF-u, [20 dodatkowych źródeł](sources_confirmation.csv), "
            "[etykiety](labels_confirmation.json), "
            "[blokada protokołu](confirmation_protocol.json), "
            "[komplet wyników](confirmation_results.json). Podglądy i surowe logi: "
            "`H:/podpisy/scratch/jev50/fresh`. Wariant pięciu widoków poprawił obie "
            "błędne decyzje pierwotnej reguły Jev; wynik "
            "pierwszych 40 stron nadal pozostaje eksploracyjny dla tego wariantu.\n",
            "### Każda strona nowej próby\n",
            "| Źródło / strona | Oględziny | Jev 2 | Jev 5 | Gemma binarna |\n"
            "|---|---|---|---|---|",
        ]
    )
    for sample in report["confirmation_samples"]:
        source_url = sample["url"].replace(" ", "%20")
        values = [
            f"[{sample['id']}]({source_url})",
            "podpis" if sample["has_signature"] else "brak",
        ]
        for method in NAMES:
            values.append(
                "błąd"
                if "error" in sample[method]
                else "podpis"
                if sample[method]["predicted"]
                else "brak"
            )
        lines.append("| " + " | ".join(values) + " |")
    return lines
