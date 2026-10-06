# Lokalny vjev-vision — sprawdzenie integracji 2026-10-05

Usunięto dostawcę Featherless. Lokalny Jev został uruchomiony ze spakowanego
Signum 1.0.6, z rzeczywistymi wagami bf16 na RTX 5060 Ti 16 GB. Test obrazu
zakończył się kodem 0. Wagi i dodatkowe biblioteki są w H:/Tools/SignumJev;
nie zainstalowano skilla Codex ani abonamentu. Pierwsze ładowanie wag: około 15 s.

Poniżej jest kontrola obecności podpisów i pieczątek na pięciu syntetycznych
przykładach repozytorium, przy progu noul 0,5. Gemma4:12b działała lokalnie przez
Ollamę, z tym samym wejściem 1120 px. Jev zmniejsza stronę do 512 px.
Czasy to pojedyncze pomiary, bez powtórzeń; pierwszy wynik Gemmy obejmuje
załadowanie jej modelu, a Jev był już rozgrzany syntetycznym testem obrazu.
To test integracji na małej próbce, nie dowód równoważnej jakości na rzeczywistych dokumentach.

| Przykład | Jev zgodny z oczekiwaniem | Gemma4 zgodna z oczekiwaniem | Jev, s | Gemma4, s |
|---|---|---|---:|---:|
| skan_protokol_podpisany.png | True | True | 0.339 | 61.167 |
| skan_regulamin_bez_podpisu.jpg | True | True | 0.329 | 9.461 |
| umowa_podpis_graficzny.pdf | True | True | 0.33 | 18.96 |
| faktura_bez_podpisu.pdf | True | True | 0.333 | 5.251 |
| wniosek_puste_pole_podpisu.pdf | True | True | 0.332 | 5.001 |

Oba modele poprawnie określiły obecność/brak oznaczeń w 5/5 przykładów.
Jev nie podał ramek ani wycinków. Rozpoznawanie rodzaju dokumentu było gorsze:
Jev wybrał „inne” m.in. dla podpisanej umowy i protokołu, podczas gdy Gemma
rozpoznała ich rodzaj. Nie ma podstaw, aby twierdzić, że cała analiza jest równie dobra.

Pełny pipeline: 7 przykładów (PDF i obrazy), 4 dokumenty z podpisami,
0 błędów; podpisy cyfrowe były wykrywane niezależnie ze struktury PDF.
Przetwarzanie partii trwało około 2 s po preflight.

Kontrola kodu: ruff i mypy bez błędów, 192 testy pytest zaliczone.
Sprawdzono autostart, ochronę zatrzymania tokenem, ponowne użycie serwera,
API obrazu, raport HTML/CSV i zwolnienie GPU po zamknięciu serwera.

Przypięte wersje:
- Model yah01/vjev-vision: 2fa8b58e40e5bc351a7d6dd39b953469a8f3ded2.
- BubbleCal/vjev-serve: 37e2ffb2695b9bf278374fdefec24611c3b710c1.
- Transformers 5.18.0; istniejący Torch 2.12.0.dev20260217+cu128.
- Serwer tylko 127.0.0.1:8800, tryb offline, model API: vjev-vision.

Surowe decyzje i użycie tokenów: H:/Tools/SignumJev/validation.json.
Diagnostyka gotowego exe: H:/Tools/SignumJev/packaged-self-test.json.

## Większa próba publicznych dokumentów

Pierwotny poligon obejmował 50 publicznych PDF-ów z widocznym podpisem odręcznym oraz
50 stron kontrolnych z 50 innych PDF-ów. Oceniono jedną wybraną kompletną
stronę na dokument; etykiety pochodzą z oględzin przed inferencją. To próba
dokumentów administracji i uczelni, nie pomiar przeszukiwania całych PDF-ów.

Po 800 zapytaniach Jev porównano 39 reguł na 60 stronach do strojenia i
zamrożono regułę przed oceną 40 stron od innych wydawców. Kalkulator uzyskał
38/40 (95%), wcześniejszy klient Jev 37/40 (92,5%). Reguła bierze większe
`choice.present` całej strony i dolnych 55%, przy progu 0,455. Dwa błędy
kalkulatora to podpis w nagłówku pisma i znak graficzny przy podpisie cyfrowym.

[Pełny raport i porównanie z Gemmą](../experiments/jev50/RESULTS.pl.md),
[kalkulator oraz podglądy źródeł](../experiments/jev50/calculator.html),
[uruchomienie na własnym PDF-ie](../experiments/jev50/README.md).
Od Signum 1.0.7 program używa dla Jev przebadanego wariantu pięciu widoków.
Pierwotny test pozostaje opisem metody bazowej, a nie wynikiem nowego klienta.

## Zamknięta próba 120 stron i integracja 1.0.7

Wariant pięciu widoków uzyskał 120/120: 60 stron z podpisem oraz 60 kontrolnych.
Gemma binarna: 118/120. Próba obejmuje 60 stron strojenia, 40 stron użytych przy
wyborze wariantu w analizie dodatkowej i 20 nowych stron potwierdzających.
Na tych ostatnich oba modele osiągnęły 20/20. Próby nie zwiększamy.

Reguła programu: największa średnia czterech odpowiedzi (`handwritten`,
`execution`, `pen_strokes`, `choice.present`) z pięciu stałych widoków, próg
0,535. Rozmiar każdego JPEG-u to 1120 px. Program zachowuje pełny obraz roboczy
do wydzielenia fragmentów. Prawdopodobieństwo jest kalibrowane na pierwotnych
60 stronach, również dla stron bez podpisu. Zmiana promptu może zmienić jakość
i kalibrację; przebadano prompt domyślny.

Kontrola integracji odtworzyła zapisane odpowiedzi wszystkich 120 stron:
600 JPEG-ów i prompty aplikacji są identyczne z wejściami poligonu, decyzje
i prawdopodobieństwa zgodne z kalkulatorem. Rzeczywisty pipeline ponownie
sprawdził d016 (podpis w nagłówku) i d019 (tekstowy podpis cyfrowy z logo).
Nie dodano nowych dokumentów. Jev po partii lub anulowaniu zwalnia GPU.

GUI i HTML/CSV pokazują prawdopodobieństwa poszczególnych stron, bez udawania
liczby podpisów. Sama pieczątka nie oznacza podpisania dokumentu. Przy limicie
stron program informuje, że nie oceniono reszty PDF-u. Dokument źródłowy można
otworzyć bezpośrednio z panelu szczegółów.

[Kalkulator pięciu widoków](../experiments/jev50/quality-calculator.html).
Kalibracja dotyczy zbilansowanej próby i wymaga kontroli na nowych dokumentach;
nie zmierzono przewagi kosztowej API ani zużycia energii.
