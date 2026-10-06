# Poligon podpisów Jev / Gemma

Próba obejmuje 50 publicznych dokumentów z widocznym podpisem odręcznym oraz
50 stron kontrolnych z 50 innych publicznych plików PDF. W każdym pliku wybrano
jedną kompletną stronę. To benchmark klasyfikacji strony, a nie pomiar
wyszukiwania strony podpisu w całym wielostronicowym dokumencie.

Źródła zostały znalezione w wyszukiwarce, pobrane, przetasowane z ziarnem
`20261005`, wyrenderowane i obejrzane przez Codex przed uruchomieniem modeli.
To próba dogodna z publicznych dokumentów administracji i uczelni, nie losowa
próba reprezentatywna dla całego internetu. Nie potwierdza autentyczności
podpisu ani skuteczności na prywatnych umowach, fakturach czy trudnych notatkach.

Etykieta pozytywna oznacza widoczne odręczne pociągnięcia podpisu lub parafki,
w tym zeskanowany obraz podpisu. Sama pieczątka, drukowane nazwisko, puste pole
albo tekstowa adnotacja o podpisie cyfrowym nie wystarcza. Obecność pola
kryptograficznego PDF jest osobnym zadaniem aplikacji Signum.

Podział: 60 stron do strojenia (30 dodatnich, 30 ujemnych), 40 stron testowych
(20 dodatnich, 20 ujemnych). Wydawca pozostaje w całości po jednej stronie
podziału, również dla tekstowych i zeskanowanych wersji tych samych wzorów.
Manifest `labels.json` zawiera adresy źródeł, skróty plików, strony, etykiety,
korekty przeglądu i przypisanie do podziału. Etykiety zamrożono przed inferencją.

Eksperyment Jev: trzy instrukcje kontekstu (domyślna, krótka angielska, polska),
osiem niezależnych pytań `noul` i pytanie binarne `choice`. Oprócz całej strony
sprawdzono dolną część i cztery zachodzące na siebie stałe fragmenty strony.
Fragmenty modelu nie zależą od ręcznie znalezionego położenia podpisu.
Dokładne teksty i pytania są zamrożone w `protocol.json`; skrypty nie pobierają
nowych promptów z aplikacji podczas kolejnego przebiegu eksperymentu.

Regułę i próg wybiera wyłącznie zbiór do strojenia. Przy remisie pierwszeństwo
ma mniej zapytań i próg bliższy 0,5. Logistyczna kalibracja z regularyzacją jest
dopasowana wyłącznie na tym samym zbiorze. To kalibracja dla tej zbilansowanej
próby, wymagająca dalszej weryfikacji przy innej częstości podpisanych stron.
Program odmawia nadpisania zamrożonej reguły podczas ponownego strojenia.

Gemma używa lokalnego `gemma4:12b` w Ollamie, temperatury 0, okna 8192 i
domyślnego promptu aplikacji Signum. Jev korzysta z przygotowanego lokalnego
`vjev-vision`. Modele uruchamia się kolejno, aby nie konkurowały o GPU.
Oba otrzymują tę samą kompletną stronę JPEG o dłuższym boku do 1120 px;
serwer Jev dodatkowo zmniejsza obraz do swojego limitu 512 px. Strategia z
fragmentami jest osobnym wariantem, którego czas obejmuje wszystkie wymagane
zapytania. Czasy nie obejmują pobierania ani renderowania. Pierwsze żądanie
Gemmy może obejmować ładowanie modelu; mediana ogranicza jego wpływ.
Osobna kontrola `run_gemma_binary.py` porównuje samo wykrywanie obecności podpisu
bez generowania opisu i ramek. Jej prompt i parametry są zapisane w
`gemma_binary_protocol.json` przed oceną testu.

## Powtórzenie

W katalogu głównym projektu ustaw `PYTHONPATH` na `src`, użyj istniejącego
interpretera projektu i uruchom skrypty w tej kolejności:

1. `download_corpus.py` — pobranie według manifestu, kontrola SHA256.
2. `run_jev50.py jev` — surowe warianty Jev, możliwość wznowienia.
3. `run_baseline_jev50.py` — rzeczywisty dotychczasowy klient Signum.
4. `fit_jev50.py` — wybór i zamrożenie reguły na danych do strojenia.
5. `run_jev50.py gemma` — dotychczasowy klient Gemmy.
6. `run_gemma_binary.py` — Gemma wyłącznie do klasyfikacji binarnej.
7. `evaluate_jev50.py` — ocena zamrożonej reguły.
8. `render_corpus.py`, `build_report.py` — obrazy stron, raport i kalkulator HTML.

Domyślne dane lokalne: `H:/podpisy/scratch/jev50`. Pobierane PDF-y i obrazy
pozostają na H:, poza śledzonym kodem repozytorium. Nowy niezależny przebieg
wymaga nowego katalogu danych; nie zastępuj wyników modelu po obejrzeniu testu.

Ręczne oględziny używały najpierw miniatur stron, następnie powiększeń podpisów
i kompletnych stron kontrolnych. Nie były wykonywane przez Jev ani Gemmę.
Surowe poprawne odpowiedzi, czasy i błędy są zapisywane po każdym zapytaniu.
Przy błędzie wewnętrznego parsera klienta Gemmy zapisano wyjątek; klient nie
udostępnia wtedy treści niepoprawnej odpowiedzi. Błąd liczy się jako zła decyzja.

## Własny dokument

Kalkulator wykonuje dwa zapytania na każdą stronę, zachowuje surowe wyniki i
zwraca `has_signature` oraz `calibrated_probability`. Na końcu zatrzymuje
lokalny serwer Jev, jeśli ten przebieg go uruchomił. Nie wymaga abonamentu.

```powershell
$env:PYTHONPATH = 'H:\podpisy\src'
& H:\podpisy\.venv\Scripts\python.exe experiments\jev50\calculator.py 'H:\dokument.pdf' --output 'H:\wynik.json'
```

Tryb liczbowy bez uruchamiania modelu:

```powershell
& H:\podpisy\.venv\Scripts\python.exe experiments\jev50\calculator.py --full 0.3 --bottom 0.8
```

Domyślnie analizowane jest do 500 stron; `--max-pages` ogranicza ten zakres.
Prawdopodobieństwo jest kalibrowane na eksperymentalnym zbiorze 50/50, nie jest
gwarantowaną pewnością dla innej populacji dokumentów. Wynik dotyczy wyglądu
podpisu; nie potwierdza tożsamości podpisującego ani podpisu kryptograficznego.

`calculator.html` pozwala przejrzeć źródła i policzyć decyzję z gotowych wyników,
bez modelu i bez wysyłania dokumentów. Nowy PDF analizuje skrypt Python.

## Dokładniejszy wariant: pięć widoków

`quality-calculator.html` zawiera kalkulator, podgląd wszystkich 120 ocenianych
stron i wyniki dodatkowej próby. `calculator_quality.py` analizuje własny PDF
lub obraz lokalnym vjev-vision, wykonując pięć zapytań na stronę:

```powershell
$env:PYTHONPATH = 'H:\podpisy\src'
& H:\podpisy\.venv\Scripts\python.exe experiments\jev50\calculator_quality.py 'H:\dokument.pdf' --output 'H:\wynik.json'
```

Cała strona i cztery fragmenty po 60% szerokości i wysokości. Dla każdego widoku
średnia `handwritten`, `execution`, `pen_strokes`, `choice.present`; największa
średnia musi osiągnąć 0,535. Prawdopodobieństwo to osobna kalibracja logistyczna
wytrenowana tylko na pierwotnych 60 stronach do strojenia. Odpowiedzi i skróty
wejść są zapisywane w wyniku. `--max-pages` ogranicza analizę, domyślnie do 500.
Wynik `has_visible_signature` odnosi się wyłącznie do przeanalizowanych stron;
brak podpisu w pierwszych N stronach nie rozstrzyga o pozostałych.

Na pierwszym teście wariant osiągnął 40/40, ale wybrano go po obejrzeniu tego
testu. To wynik eksploracyjny. Na następnych 20 nowych stronach uzyskał 20/20,
tak samo jak Gemma binarna. Mediany: Jev 2,22 s, Gemma 0,97 s. Nie zmieniano
parametrów po nowym teście. Nie wykazano przewagi kosztowej. Kalibracja z
małej, zbilansowanej próby wymaga kontroli na dokumentach użytkownika.

## Odtworzenie dodatkowej próby

Manifest `labels_confirmation.json` zawiera 10 stron podpisanych i 10
kontrolnych z 20 różnych PDF-ów. Etykiety pochodzą z oględzin kompletnych stron
Codex przed inferencją. Ich wydawcy i SHA256 nie pokrywają się z pierwotnymi
100 przykładami. Kontrola obejmuje także wykluczenie aliasu domeny Łomży.
Nowe źródła są próbą dogodną z 26 kandydatów, a nie losową próbą internetu.
Niektóre niewykorzystane wcześniej PDF-y pochodziły z pierwotnej puli
wyszukiwania; nie uczestniczyły w strojeniu ani pierwszym teście modeli.

```powershell
$env:PYTHONPATH = 'H:\podpisy\src'
$env:SIGNUM_JEV_LAB_DIR = 'H:\podpisy\scratch\jev50\fresh'
& H:\podpisy\.venv\Scripts\python.exe experiments\jev50\download_corpus.py --labels experiments\jev50\labels_confirmation.json
& H:\podpisy\.venv\Scripts\python.exe experiments\jev50\render_corpus.py
& H:\podpisy\.venv\Scripts\python.exe experiments\jev50\run_jev50.py jev
& H:\podpisy\.venv\Scripts\python.exe experiments\jev50\run_gemma_binary.py
Remove-Item Env:SIGNUM_JEV_LAB_DIR
& H:\podpisy\.venv\Scripts\python.exe experiments\jev50\evaluate_confirmation.py
& H:\podpisy\.venv\Scripts\python.exe experiments\jev50\build_report.py
```

Potrzebne są również zapisane wyniki pierwotnego eksperymentu. Ewaluator
sprawdza zamrożone SHA256 obu reguł, etykiet, źródeł i identyczność pełnych
obrazów wejściowych dla modeli. Nie przeprowadza ponownego strojenia.
`confirmation_results.json` zachowuje wyniki obu prób, pełne odpowiedzi Gemmy
binarnej i skróty surowych logów Jev. Dane i logi pozostają na H:.

Próba została zamknięta na 120 stronach zgodnie z ustaleniem użytkownika.
Próg sukcesu wynosi 98%. Jev z pięcioma widokami: 120/120 (100%), Gemma
binarna: 118/120 (98,33%). Obie metody spełniają próg. Te wyniki obejmują także
strony strojenia i wyboru wariantu; nowa próba potwierdzająca to osobne 20/20
dla obu metod. Nie dostrajaj parametrów ani nie powiększaj tej próby.

Kalkulatory są osobnymi narzędziami badawczymi. Od Signum 1.0.7 aplikacja korzysta
z tej samej metody pięciu widoków. Odtworzenie wszystkich 120 zapisanych odpowiedzi
i porównanie 600 wysyłanych obrazów potwierdziły zgodność implementacji z badaniem.
