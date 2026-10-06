"""Prompt i schemat odpowiedzi dla modeli wizyjnych.

Prompt został dostrojony empirycznie na gemma4:12b (Ollama): konwencja
``box_2d = [ymin, xmin, ymax, xmax]`` w skali 0-1000 daje na tym modelu
IoU ~0.6-0.9, a jawna lista negatywna (drukowany tekst, puste linie)
eliminuje fałszywe pozytywy.

Prompt składa się z dwóch części: merytorycznej (użytkownik może ją edytować
w ustawieniach) oraz stałej końcówki z wymaganym formatem odpowiedzi — parser
i structured outputs zależą od tego schematu, więc końcówki nie wolno
pozostawiać w rękach użytkownika.
"""

from __future__ import annotations

from signum.ai.jev_prompts import JEV_PROMPT_INSTRUCTIONS

PROMPT_INSTRUCTIONS = """Jesteś ekspertem analizy dokumentów. Otrzymujesz obraz JEDNEJ strony dokumentu.

Zadania:
1. "description": bardzo krótki opis rodzaju dokumentu po polsku (2-6 słów), np. "Umowa o dzieło", "Faktura VAT", "Formularz świadomej zgody".
2. "signatures": lista WSZYSTKICH podpisów odręcznych, parafek i pieczątek widocznych na stronie.

Wskazówki:
- handwritten (podpis odręczny): odręczne pociągnięcia pióra/długopisu, często pochyłe pętle, zwykle nad linią podpisu lub obok dopisku typu "(podpis)". Może być nieczytelny.
- initials (parafka): bardzo krótki odręczny znak (inicjały, 1-3 znaki), często na marginesie lub przy poprawkach.
- stamp (pieczątka): odbita pieczęć — okrągła lub prostokątna ramka z tekstem, często niebieska/fioletowa/czerwona.
- NIE zgłaszaj drukowanego tekstu, logo, pustych linii ani pustych pól podpisu.
- Jeśli strona nie zawiera żadnych podpisów ani pieczątek, zwróć pustą listę "signatures"."""

PROMPT_FORMAT = """Dla każdego znaleziska podaj "box_2d" = [ymin, xmin, ymax, xmax] w skali 0-1000 względem całej strony oraz "confidence" 0-100.
Odpowiedz WYŁĄCZNIE poprawnym JSON zgodnym ze schematem:
{"description": "...", "signatures": [{"type": "handwritten|initials|stamp", "confidence": 0-100, "box_2d": [ymin, xmin, ymax, xmax]}]}"""


def build_page_prompt(
    custom_instructions: str = "", provider: str = "ollama", jev_instructions: str = "",
) -> str:
    """Składa pełny prompt strony: część merytoryczna + stały format odpowiedzi.

    Pusta wartość ``custom_instructions`` oznacza domyślną część merytoryczną.
    """
    if provider == "vjev":
        return jev_instructions.strip() or JEV_PROMPT_INSTRUCTIONS
    instructions = custom_instructions.strip() or PROMPT_INSTRUCTIONS
    return f"{instructions}\n\n{PROMPT_FORMAT}"


PAGE_PROMPT = build_page_prompt()

# Schemat JSON dla structured outputs Ollamy — używany wyłącznie w ponowieniu,
# gdy odpowiedź bez wymuszania nie zawiera obiektu JSON (wymuszanie gramatyką
# obniża recall detekcji). Dla API chmurowych służy jako dokumentacja formatu
# (wymuszamy promptem + odpornym parserem).
RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "signatures": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": ["handwritten", "initials", "stamp"],
                    },
                    "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
                    "box_2d": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 4,
                        "maxItems": 4,
                    },
                },
                "required": ["type", "confidence", "box_2d"],
            },
        },
    },
    "required": ["description", "signatures"],
}
