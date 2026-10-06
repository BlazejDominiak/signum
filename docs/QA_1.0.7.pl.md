# Sprawdzenie Signum 1.0.7 — 5 października 2026

Instalator: `H:/podpisy/installer/output/Signum-Setup-1.0.7.exe` (46 770 398 bajtów).
SHA-256: `84B7F8AD0C3A40EC2864FCC3F9AA7EC4D0A7D87A6A485AD67A71D6E8660487D2`.

## Wykonane sprawdzenia

- 205 testów automatycznych przeszło; Ruff i mypy nie zgłosiły błędów.
- Zbudowane `Signum.exe` przeszło test podstawowego runtime'u oraz rzeczywisty
  test lokalnego Jev obejmujący pięć widoków obrazu. Po teście serwer zwolnił GPU.
- Rzeczywista analiza dwóch istniejących dokumentów z poligonu poprawnie
  rozróżniła podpis w nagłówku od tekstowego podpisu cyfrowego z logo.
  Sprawdzono także eksport HTML i CSV oraz zakończenie pracy serwera.
- Odtworzenie zapisanych odpowiedzi dla zamkniętych 120 stron dało identyczne
  decyzje i prawdopodobieństwa jak kalkulator. Porównano wszystkie 600 obrazów
  wejściowych; próby nie powiększono.
- Przejrzano renderowane okna Qt przy skalowaniu 100% i 150%, z czcionką Segoe UI:
  ustawienia wszystkich czterech dostawców oraz wyniki dodatnie i ujemne.
  Testy widgetów obejmują również zapis ustawień, obsługę błędów i otwieranie
  lokalnego dokumentu źródłowego.

## Poprawki funkcjonalne i UX

- Aplikacja używa sprawdzonej heurystyki Jev z pięcioma widokami; pokazuje
  prawdopodobieństwo także przy braku podpisu. Nie przedstawia obecności jako liczby podpisów.
- Pieczątka sama nie oznacza podpisania dokumentu. Przy ograniczeniu liczby
  analizowanych stron wynik ujemny wyraźnie dotyczy tylko badanej części PDF-a.
- Z panelu wyników można otworzyć dokument źródłowy; komunikat o braku wycinka
  wyjaśnia brak współrzędnych w odpowiedzi Jev.
- Ustawienia dopasowują wysokość do wybranego dostawcy, długie opisy zawijają
  tekst, przyciski Zapisz/Anuluj pozostają widoczne. Edycja promptu jest zwijana.
- Poprawiono szerokości kolumn i podział miejsca między tabelą a szczegółami.
- Zarządzany lokalny Jev zwalnia GPU po zakończeniu lub anulowaniu analizy;
  anulowanie jest sprawdzane między kolejnymi widokami.

## Instalator i granice weryfikacji

Przyczyną ucięcia tekstu była etykieta strony wymagań utworzona z pustą treścią:
późniejsza zmiana tekstu nie aktualizowała jej wysokości. Zastąpiono ją polem
wypełniającym stronę, z zawijaniem tekstu i przewijaniem. Powiększono kreator
oraz skrócono etykiety wymaganych potwierdzeń, zachowując ich znaczenie.
Inno Setup pomyślnie skompilował gotowy instalator.

Renderowanie okien dotyczy widgetów aplikacji w trybie offscreen, nie pełnej
obsługi systemowego pulpitu. Nie przeklikano natywnego kreatora instalacji:
uruchomienie narzędzia do sterowania oknami zakończyło się przekroczeniem czasu
zgody aplikacji. Nie wykonywano płatnych testów zdalnych API bez kluczy.
Nie potwierdzono instalacji na osobnym komputerze ani zgodności z inną kartą GPU.

Logi i podglądy: `scratch/ux-tests.log`, `scratch/ux/`,
`scratch/build-1.0.7-final.log`. Wyniki jakości i ograniczenia kalibracji opisuje
[raport Jev](JEV_VALIDATION.pl.md).
