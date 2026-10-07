# Venice: Jev w teście i pokazie

Jev działa jako model decyzyjny, dostępny poza interfejsem czatu Venice:

- Adres bazowy: `https://api.venice.ai/api/v1`.
- Model: `jev-latest`.
- Lista modeli decyzyjnych: `GET /models?type=decision`.
- Klasyfikacja: `POST /decisions` z polami `model`, `state` i `questions`.

Potwierdzono rzeczywiste odpowiedzi API na koncie użytkownika 2026-10-07.
[Dokumentacja Venice](https://venice.ai/lp/jev) opisuje ten osobny endpoint.
GLM 5.2 z gotowej instrukcji Venice jest modelem czatu; jego wybranie nie jest
potrzebne do używania Jev. Samo podmienienie nazwy modelu w kliencie czatu
nie zastępuje wywołania endpointu decyzji.

## Konfiguracja

Lokalny `.env` zawiera `VENICE_API_KEY`, `VENICE_BASE_URL`,
`VENICE_CHAT_MODEL=zai-org-glm-5-2` i `VENICE_DECISION_MODEL=jev-latest`.
Plik jest ignorowany przez Git. Przenośny szablon `.env.example` ma pusty klucz.
Zmienne środowiskowe mają pierwszeństwo przed `.env`.

`scripts/venice_api.py` udostępnia `VeniceClient.decide()` dla Jev oraz
`VeniceClient.chat()` dla zgodnego z OpenAI endpointu `/chat/completions`.
Nie wymaga nowej biblioteki — korzysta z istniejącego `requests`.
Nie zmienia ustawień dostawcy w aplikacji Signum; oficjalny Jev w tym pokazie
klasyfikuje tekst. Dotychczasowy `vjev-vision` jest osobnym modelem obrazowym.

## Pokaz na tym komputerze

PowerShell, w katalogu `H:\podpisy`:

```powershell
# Lista 100 dokumentów użytych w aktualnym porównaniu, bez wywołania API:
.\scripts\venice_demo.ps1 -List

# Jedna klasyfikacja na żywo:
.\scripts\venice_demo.ps1 -Sample fresh_n006

# Inny PDF lub tekst:
.\scripts\venice_demo.ps1 -File 'H:\dokumenty\przyklad.pdf'
```

Pokaz podaje wybraną kategorię, pełny czas odpowiedzi z internetem, pewność
modelu i trzy najwyższe oceny. Używa 12 ogólnych kategorii z zapisanego protokołu,
do 12 000 znaków tekstu. Zapisane próbki mają dodatkowo wspólny dla wszystkich
trzech modeli limit 4096 tokenów pełnego promptu według tokenizera JevK5;
skrócił on dodatkowo 13 ze 100 tekstów. Własny plik przez `-File` ma wyłącznie
limit znaków i nie jest częścią kontrolowanego porównania.
Pokaz nie wykonuje OCR, opisu ani wykrywania podpisów.
Wybrany tekst jest wysyłany do Venice.

Pełna setka w pokazie — jedno przejście plus osobna rozgrzewka:

```powershell
.\scripts\run_classification_benchmark.ps1 -Model venice
.\scripts\run_classification_benchmark.ps1 -Model jevk5
.\scripts\run_classification_benchmark.ps1 -Model gemma
```

Uruchamiaj modele kolejno. `-Repeats 3` daje trzy przejścia.
Wyniki pokazu trafiają do `scratch/classification-live-demo`, dzięki czemu
nie zastępują zapisanego benchmarku. JevK5 używa istniejącego Pythona 3.11
i lokalnego runtime CUDA, pozostałe tryby Pythona 3.13.
Po zaobserwowanym HTTP 429 benchmark Venice ogranicza wysyłanie do 100 żądań
w 61 sekundach. Wypisuje przerwy i wlicza je w czas klasyfikacji; w surowych
wynikach czas obsługi żądań oraz oczekiwanie są też zapisane osobno.
Przy używaniu tego samego klucza równolegle może pojawić się dodatkowe oczekiwanie.

Launcher korzysta z istniejącego Pythona 3.13 i bibliotek projektu na tym
komputerze. W innym skonfigurowanym środowisku można uruchomić bezpośrednio:

```powershell
python scripts/venice_demo.py --sample fresh_n006
python scripts/benchmark_jevk5_classification.py venice
```

Druga komenda wykonuje 300 pomiarów i jedną rozgrzewkę: trzy przejścia
po 100 dokumentów. `--repeats 1` wykonuje jedno przejście na potrzeby pokazu.
Zastępuje poprzednie
pliki `venice-results.jsonl` i `venice-summary.json` w
`scratch/jevk5-classification-100x12`, pozostawiając wyniki lokalnych modeli.
Do pokazu zalecany jest powyższy launcher `run_classification_benchmark.ps1`,
który zapisuje dane osobno.

Poprzedni protokół 10 dokumentów i 48 kategorii pozostaje w
`scratch/jevk5-classification/protocol.json`. Można go użyć w pokazie przez
`-Protocol 'H:\podpisy\scratch\jevk5-classification\protocol.json'`, a w benchmarku
przez `--output-dir scratch/jevk5-classification`. Wyniki obu wariantów są osobne.

Raport 100 × 12: [porównanie trzech modeli](CLASSIFICATION_100x12.pl.md).
Poprzedni raport 10 × 48: [Jev, JevK5 i Gemma](JEVK5_CLASSIFICATION.pl.md).
