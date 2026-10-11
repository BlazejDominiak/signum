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
from signum.i18n import catalog, tr

PROMPT_INSTRUCTIONS = catalog()["prompt.vision.instructions"]["pl"]

PROMPT_FORMAT = catalog()["prompt.vision.format"]["pl"]


def default_instructions() -> str:
    return tr("prompt.vision.instructions")


def localized_prompt_format() -> str:
    return tr("prompt.vision.format")


def build_page_prompt(
    custom_instructions: str = "", provider: str = "ollama", jev_instructions: str = "",
) -> str:
    """Składa pełny prompt strony: część merytoryczna + stały format odpowiedzi.

    Pusta wartość ``custom_instructions`` oznacza domyślną część merytoryczną.
    """
    if provider == "vjev":
        return jev_instructions.strip() or JEV_PROMPT_INSTRUCTIONS
    instructions = custom_instructions.strip() or default_instructions()
    return f"{instructions}\n\n{localized_prompt_format()}"


PAGE_PROMPT = f"{PROMPT_INSTRUCTIONS}\n\n{PROMPT_FORMAT}"

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
