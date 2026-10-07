"""Testy odpornego parsera odpowiedzi modeli wizyjnych."""

from __future__ import annotations

import pytest

from signum.ai.base import AIResponseError
from signum.ai.parsing import extract_first_json_object, parse_page_analysis
from signum.core.models import SignatureKind


class TestExtractFirstJsonObject:
    def test_czysty_json(self) -> None:
        assert extract_first_json_object('{"a": 1}') == {"a": 1}

    def test_smieci_po_jsonie_jak_z_gemmy(self) -> None:
        # Zaobserwowane na gemma4:12b mimo structured outputs.
        raw = '{"description": "umowa", "signatures": []}\n        <|tool_response>'
        assert extract_first_json_object(raw)["description"] == "umowa"

    def test_json_w_bloku_markdown(self) -> None:
        raw = 'Oto wynik:\n```json\n{"description": "faktura", "signatures": []}\n```'
        assert extract_first_json_object(raw)["description"] == "faktura"

    def test_nawiasy_w_stringach_nie_psuja_balansu(self) -> None:
        raw = '{"description": "wzor {x} i \\"cytat\\"", "signatures": []}'
        assert "wzor {x}" in extract_first_json_object(raw)["description"]

    def test_brak_jsona_rzuca_wyjatek(self) -> None:
        with pytest.raises(AIResponseError):
            extract_first_json_object("model nie zwrócił niczego sensownego")

    def test_niedomkniety_json_rzuca_wyjatek(self) -> None:
        with pytest.raises(AIResponseError):
            extract_first_json_object('{"description": "urwane')


class TestParsePageAnalysis:
    @pytest.mark.parametrize("raw", [
        "{}", '{"signatures":null}', '{"signatures":{}}',
        '{"signatures":[null]}', '{"signatures":[{"type":"unknown"}]}',
    ])
    def test_nieprawidlowy_wynik_nie_oznacza_braku_podpisow(self, raw: str) -> None:
        with pytest.raises(AIResponseError):
            parse_page_analysis(raw)

    def test_pelna_odpowiedz(self) -> None:
        raw = (
            '{"description": "Umowa najmu", "signatures": ['
            '{"type": "handwritten", "confidence": 95, "box_2d": [800, 600, 880, 900]},'
            '{"type": "stamp", "confidence": 80, "box_2d": [780, 130, 900, 340]}]}'
        )
        analysis = parse_page_analysis(raw)
        assert analysis.description == "Umowa najmu"
        assert len(analysis.signatures) == 2
        assert analysis.signatures[0].kind is SignatureKind.HANDWRITTEN
        assert analysis.signatures[0].box_2d == (800, 600, 880, 900)
        assert analysis.signatures[1].kind is SignatureKind.STAMP

    def test_pusta_lista_podpisow(self) -> None:
        analysis = parse_page_analysis('{"description": "Regulamin", "signatures": []}')
        assert analysis.signatures == ()

    def test_nieznany_typ_jest_pomijany(self) -> None:
        raw = (
            '{"description": "x", "signatures": ['
            '{"type": "watermark", "confidence": 90, "box_2d": [0, 0, 10, 10]},'
            '{"type": "initials", "confidence": 70, "box_2d": [10, 10, 40, 60]}]}'
        )
        analysis = parse_page_analysis(raw)
        assert len(analysis.signatures) == 1
        assert analysis.signatures[0].kind is SignatureKind.INITIALS

    def test_synonimy_typow(self) -> None:
        raw = (
            '{"description": "x", "signatures": ['
            '{"type": "Signature", "confidence": 60, "box_2d": [1, 1, 5, 5]},'
            '{"type": "SEAL", "confidence": 60, "box_2d": [1, 1, 5, 5]}]}'
        )
        kinds = [s.kind for s in parse_page_analysis(raw).signatures]
        assert kinds == [SignatureKind.HANDWRITTEN, SignatureKind.STAMP]

    @pytest.mark.parametrize(
        "box",
        [
            [900, 100, 800, 300],  # ymax < ymin
            [100, 900, 300, 800],  # xmax < xmin
            [0, 0, 1200, 500],  # poza skalą 0-1000
            [1, 2, 3],  # za mało współrzędnych
            "nie-lista",
            ["NaN", 0, 10, 10],
            [0, 0, "Infinity", 10],
            None,
        ],
    )
    def test_zla_ramka_daje_none(self, box: object) -> None:
        import json

        raw = json.dumps(
            {
                "description": "x",
                "signatures": [{"type": "handwritten", "confidence": 50, "box_2d": box}],
            }
        )
        analysis = parse_page_analysis(raw)
        assert analysis.signatures[0].box_2d is None

    @pytest.mark.parametrize(
        ("raw_conf", "expected"),
        [
            (150, 100),
            (-5, 0),
            (0.87, 87),
            ("wysoka", 50),
            ("NaN", 50),
            ("Infinity", 50),
            (None, 50),
            (63.4, 63),
        ],
    )
    def test_normalizacja_pewnosci(self, raw_conf: object, expected: int) -> None:
        import json

        raw = json.dumps(
            {
                "description": "x",
                "signatures": [{"type": "stamp", "confidence": raw_conf, "box_2d": [1, 1, 5, 5]}],
            }
        )
        assert parse_page_analysis(raw).signatures[0].confidence == expected

    def test_opis_przyciety_do_limitu(self) -> None:
        import json

        raw = json.dumps({"description": "x" * 500, "signatures": []})
        assert len(parse_page_analysis(raw).description) == 120
