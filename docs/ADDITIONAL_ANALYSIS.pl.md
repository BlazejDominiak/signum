# Dodatkowa analiza — wdrożenie i eksperyment Signum 1.0.10

Data: 2026-10-07. Wykonano rzeczywiste lokalne inferencje na RTX 5060 Ti 16 GB.
Gemma: `gemma4:12b`, Q4_K_M, Ollama 0.32.13. Jev: przygotowany lokalnie
`vjev-vision`, ten sam model i klasyfikator co w dotychczasowej aplikacji.

## Co zmienia przełącznik

W ustawieniach Ollamy i Jev dodano niezależnie zapamiętywane pole
**Dodatkowa analiza**. Dla Gemmy wyłączenie pozostawia pytania o obecność
podpisu/parafki i pieczątki wraz z ocenami liczbowymi, bez opisu i współrzędnych.
Włączenie zachowuje dotychczasową pełną analizę. Domyślnie jest włączone.

Dla Jev domyślnie pozostaje wyłączone. Podstawowy klasyfikator pięciu widoków,
prompt, pytania, próg i kalibracja nie zostały zmienione. Dodatkowy tryb wykonuje:

1. Ocenę przynależności do 48 kategorii w jednym żądaniu. Wybiera do dwóch
   etykiet z oceną co najmniej 0,6, np. „Umowa; Edukacja i kursy”. Kategorie
   mogą się pokrywać; ich oceny nie są rozkładem sumującym się do jedności.
2. Gdy analiza podstawowa wykryła oznaczenie, sprawdzenie 20 fragmentów
   w siatce czterech kolumn i pięciu wierszy. Pytania uwzględniają także
   niepełne fragmenty podpisu. Pieczątki są rozpatrywane oddzielnie.
3. Scalenie trafień sąsiadujących bokiem lub rogiem, dodanie marginesu
   i ponowne sprawdzenie obrazu. Model odpowiada również, czy widzi jeden podpis.
   Przy braku potwierdzenia sprawdzany jest węższy obszar; podgląd nadal
   pokazuje szerszy kontekst. Zbyt duże obszary nie są prezentowane jako wycinki.

Warstwa dodatkowa nie może zmienić podstawowej decyzji o obecności podpisu ani
jej prawdopodobieństwa. Brak wycinka nie usuwa wykrycia. Wycinek może obejmować
kilka podpisów; nie stanowi dokładnego zliczenia wszystkich oznaczeń.

## Wyniki na tych samych 20 stronach

Użyto wcześniej pobranych publicznych stron: 10 z podpisem i 10 bez, z zestawu
`scratch/jev50/fresh/labels.json`. Był to eksperyment wdrożeniowy, w którym
sprawdzano i dopracowywano lokalizację. Modele uruchamiano kolejno. Przed
pomiarem wykonywano ładowanie i próbę syntetycznego obrazu. Czasy obejmują
analizę modelu, bez renderowania PDF i zapisu podglądów.

| Tryb | Poprawna obecność podpisu | Mediana na stronę | Łącznie 20 stron |
|---|---:|---:|---:|
| Gemma — podstawowy | 19/20 | 1,27 s | 25,40 s |
| Gemma — dodatkowa analiza | 20/20 | 3,06 s | 79,85 s |
| Jev — dodatkowa analiza | 20/20 | 7,61 s | 121,39 s |

Nowa podstawowa Gemma pominęła podpis na `n003_p002`. Jej odpowiedź zawiera
dwie oceny liczbowe, więc nie jest identyczna z dawnym testem jednego pola
`has_signature`. Nie należy podmieniać historycznego wyniku nowym.

W Jev suma czasów pierwszych pięciu podstawowych wywołań miała medianę 2,27 s.
To pomiar części wywołań w tym samym przebiegu, a nie oddzielny pełny pomiar
trybu podstawowego. Dodatkowe 20 obrazów i weryfikacja regionów kosztują czas:
w tym wdrożeniu pełna dodatkowa analiza Jev była wolniejsza od pełnej Gemmy.

### Lokalizacja i kategorie

- Przybliżony wycinek **podpisu** uzyskano na **8 z 10 podpisanych stron**.
  Na `n013_p009` nie powstał wycinek; na `n023_p005` powstał tylko wycinek
  sklasyfikowany jako pieczątka. Obie strony zachowały poprawną podstawową
  decyzję „podpisany”. To liczba stron z wycinkiem, nie odsetek wszystkich
  indywidualnych podpisów znalezionych na stronach.
- Dwa kontrolowane obrazy z rzeczywistym fragmentem podpisu umieszczonym
  na granicy dwóch i czterech pól dały poprawne wykrycie i obejmujący podpis
  wycinek: **2/2**. Obrazy te nie wchodzą do tabeli 20 stron.
- Oględziny podglądów potwierdzają, że ramki bywają szerokie, łączą kilka
  podpisów lub nie obejmują wszystkich podpisów na stronie.
- Kategorie dają użyteczny skrót, ale nie zastępują dokładnego tytułu.
  Przykładowo umowa na papierze z opłatą skarbową (`n018_p001`) otrzymała
  etykiety administracyjne/podatkowe. Zestaw skupia się na umowach i nie ma
  osobnych wzorcowych etykiet dla 48 kategorii, więc nie wyliczano ich trafności.

Dla wszystkich 22 stron/obrazów porównano odpowiedzi pierwszych pięciu wywołań
z wynikiem wzbogaconym: prawdopodobieństwo i zbiór rodzajów wykrytych oznaczeń
pozostały identyczne.

## Sprawdzenie wcześniejszego czasu Gemmy

Odtworzono dokładny dawny prompt i schemat jednego pola `has_signature`, bez
trybu rozumowania, na sześciu różnych stronach w dwóch przejściach. Wynik:
12/12 poprawnych odpowiedzi. Model rzeczywiście odpowiadał bardzo szybko:

- Pierwsze żądanie z ładowaniem: **25,03 s**, w tym **22,86 s** ładowania.
- Pozostałe pięć stron pierwszego przejścia: mediana **0,97 s**.
- Drugie przejście sześciu stron: mediana **0,90 s**.

Odpowiedź pierwszego żądania miała tylko osiem tokenów. Surowe metryki Ollamy
zawierają osobno ładowanie, przetworzenie wejścia i generowanie. Około 0,98 s
jest odtwarzalne dla załadowanego modelu i tak krótkiej odpowiedzi; nie opisuje
uruchomienia ani rozbudowanej analizy z tytułem i wycinkami.

Wcześniejszy wynik jakości również został potwierdzony w zapisanym raporcie:
Jev pięć widoków **120/120**, Gemma binarna **118/120**. Chodzi o strony.
Skład tej próby i jej przeznaczenie opisuje
[walidacja Jev](JEV_VALIDATION.pl.md#zamknięta-próba-120-stron-i-integracja-107).

## Artefakty i odtworzenie

- `scratch/additional-analysis/raport.html` — samodzielny raport z osadzonymi
  obrazami, wycinkami i ocenami kategorii.
- `scratch/additional-analysis/summary.json` — zbiorcze wyniki.
- `scratch/additional-analysis/{tryb}/results.jsonl` — czasy i odpowiedzi.
  Dla Jev zapisano pytania, odpowiedzi i skróty obrazów z każdego wywołania;
  dla Gemmy także surowe metryki czasu Ollamy.
- `scripts/experiment_additional_analysis.py` — skrypt eksperymentu.
- `installer/output/Signum-Setup-1.0.10.exe` — zbudowany instalator.

Uruchomienie w skonfigurowanym środowisku projektu, z pobranymi już plikami
korpusu i przygotowanymi modelami, bez równoległego obciążenia GPU:

```powershell
python scripts/experiment_additional_analysis.py audit --limit 6 --repeat 2
python scripts/experiment_additional_analysis.py gemma-basic --limit 20
python scripts/experiment_additional_analysis.py gemma-full --limit 20
python scripts/experiment_additional_analysis.py jev-extra --limit 20 --boundary
```

Skrypt zastępuje wyniki poprzedniego przebiegu w katalogu danego trybu.
Aktualne obrazy wskazują pola `previews` w `results.jsonl` i `preview.html`;
w katalogu mogą pozostać nieużywane obrazy z wcześniejszych prób.

Walidacja wdrożenia: **281 testów zaliczonych**, Ruff i mypy bez błędów.
Budowa instalatora zakończona powodzeniem wraz z testem uruchomienia
spakowanej aplikacji.
