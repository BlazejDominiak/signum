# Jev przez Venice w Signum

W zakładce **Kategoryzowanie dokumentów** otwórz **Ustawienia AI…** i dodaj
połączenie API z formatem **Decisions (Jev / Venice)**:

- adres bazowy: `https://api.venice.ai/api/v1`;
- model: `jev-latest`;
- klucz API zapisany w systemowym magazynie poświadczeń.

Program wysyła tekst PDF-a do usługi. Ten tryb nie wykonuje OCR.
Jev otrzymuje osobne pytanie dla każdej kategorii i zwraca niezależne oceny.
Signum przypisuje do trzech najwyższych wyników przekraczających próg 0,74.
Profil dotyczy domyślnego promptu i katalogu etykiet; zmiana definicji wymaga
odpowiedniej kalibracji. Wyniki w paśmie ±0,03 otrzymują oznaczenie HITL.

Wybierz dokument i **Sprawdź etykiety…**, aby obejrzeć wszystkie oceny,
zmienić przypisanie i zapisać sprawdzony wynik. Dwukrotne kliknięcie nazwy
pliku otwiera źródłowy PDF.

Jev tekstowy w Venice i lokalny `vjev-vision` do podpisów mają osobne ustawienia.
Do klasyfikacji tekstu nie wybieraj formatu Chat Completions.
