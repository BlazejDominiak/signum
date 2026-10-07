# Jev, JevK5 i Gemma: szybkość klasyfikacji dokumentów

Data: 2026-10-07. **Oficjalny Jev przez Venice był 4.72 razy
szybszy od lokalnej Gemmy i 7.71 razy od JevK5**,
licząc średni czas wyboru jednej z 48 kategorii. Lokalnie użyto RTX 5060 Ti 16 GB.
Czas Venice obejmuje internet; API nie zwraca czasu samej inferencji serwera.

| Model | Średnio na dokument | Mediana | Średnio komplet 10 PDF-ów |
|---|---:|---:|---:|
| Jev przez Venice (`jev-latest`) | 0.427 s | 0.421 s | 4.270 s |
| Gemma 4 12B, Q4_K_M, Ollama | 2.016 s | 2.068 s | 20.165 s |
| JevK5 v0.3, 4B, BF16, PyTorch | 3.294 s | 3.316 s | 32.941 s |

Każdy model wykonał 30 pomiarów: te same 10 dokumentów, trzy przejścia.
Wszystkie odpowiedzi wskazywały istniejącą kategorię. Nie jest to ocena trafności:
nie przygotowywano wzorcowych etykiet, a poniżej widać rozbieżności klasyfikacji.

## Co dokładnie zmierzono

- Wylosowano 10 różnych PDF-ów z istniejącego publicznego korpusu
  `scratch/jev50` (187 plików przed filtrowaniem), seed 20261007.
  Pomijano identyczne pliki, błędy odczytu i tekst krótszy niż 200 znaków.
  Zestaw zapisano przed uruchomieniem modeli, bez wyboru według odpowiedzi.
- Wszystkie trzy modele otrzymały ten sam wydobyty tekst oraz te same 48 kategorii.
  JevK5 jest tekstowy, więc Gemma także pracowała na tekście, bez obrazów,
  OCR, opisów, wykrywania podpisów i wycinków.
- Wspólny limit wynosił 12 000 znaków od początku dokumentu; dotyczył
  5/10 plików. Dokumenty miały od 1 do 27 stron.
  Jest to czas klasyfikacji tego wejścia, nie czas przeczytania wszystkich
  stron najdłuższego PDF-a. Nie wykonywano OCR; warstwa tekstowa może być niepełna.
- Wydobycie tekstu ze wszystkich 10 PDF-ów trwało łącznie 2.407 s i zostało
  wyłączone z czasu modeli. Ładowanie i rozgrzewkę również oddzielono.
- Gemma zwracała wyłącznie identyfikator kategorii w krótkim JSON-ie:
  `think=false`, temperatura 0, kontekst 8192, limit 64 tokenów odpowiedzi.
  Czas obejmuje lokalne HTTP, przetworzenie wejścia i odpowiedź.
- JevK5 używał oficjalnego odczytu decyzji z logitów, bez generowania tekstu.
  Przy 48 opcjach runtime robi **cztery przebiegi**: trzy grupy po 16 i finał.
  Zwraca także prawdopodobieństwa wszystkich kategorii. Czas obejmuje tokenizację,
  cztery przebiegi i składanie wyniku w procesie Pythona.
- Pomiary GPU synchronizowano. Modele działały kolejno, bez współdzielenia VRAM.
  Zmienny znacznik pomiaru na początku promptu Gemmy ograniczał ponowne użycie
  cache całego dokumentu. JevK5 pracował z `use_cache=False`.
- Venice: 30 kolejnych żądań HTTPS do `/api/v1/decisions`, bez równoległości,
  poprzedzonych jednym żądaniem rozgrzewki. Każde zawierało jedno pytanie
  `choice` z kompletem 48 kategorii. Zapisane skróty tekstów potwierdzają
  identyczność wejścia z testami lokalnymi. Nie zmieniano zestawu dokumentów.

## Wyniki dokument po dokumencie

Czas to średnia z trzech pomiarów. Kilka etykiet w komórce oznacza zmianę
odpowiedzi pomiędzy powtórzeniami, a nie klasyfikację wieloetykietową.

| PDF | Znaki wejścia | Jev / Venice | Gemma | JevK5 | Kategoria Jev | Kategoria Gemmy | Kategoria JevK5 |
|---|---:|---:|---:|---:|---|---|---|
| fresh_n006 | 2584 | 0.380 s | 1.462 s | 1.303 s | Umowa | Umowa | Umowa |
| jev50_d109 | 12000 | 0.422 s | 2.281 s | 4.576 s | Umowa | Umowa | Ochrona środowiska |
| jev50_d068 | 12000 | 0.501 s | 2.393 s | 4.364 s | Dotacje i finansowanie | Wniosek | Dotacje i finansowanie |
| jev50_d084 | 12000 | 0.432 s | 2.327 s | 4.070 s | Umowa | Umowa | Umowa |
| fresh_n009 | 568 | 0.415 s | 1.361 s | 0.863 s | Zawiadomienie | Zawiadomienie | Zawiadomienie |
| jev50_d041 | 1157 | 0.438 s | 1.346 s | 1.179 s | Decyzja | Zamówienie; Decyzja | Decyzja |
| jev50_d051 | 3523 | 0.378 s | 1.485 s | 1.468 s | Umowa | Umowa; Aneks | Umowa |
| jev50_d142 | 3188 | 0.390 s | 1.839 s | 2.538 s | Decyzja | Zamówienie; Decyzja | Decyzja |
| jev50_d032 | 12000 | 0.452 s | 2.609 s | 4.585 s | Administracja | Administracja | Ochrona środowiska |
| jev50_d085 | 12000 | 0.461 s | 3.063 s | 7.995 s | Umowa | Dotacje i finansowanie | Umowa |

## Ładowanie, pamięć i ograniczenia lokalnego runtime

JevK5: ładowanie 8.81 s, następnie rozgrzewka
1.05 s. Gemma: pierwsze syntetyczne żądanie
25.20 s, z czego raportowane przez Ollamę ładowanie
24.40 s.

Końcowy pomiar JevK5 używał istniejącego PyTorcha 2.12.0.dev20260217+cu128
i Transformers 5.18.0, z referencyjnymi implementacjami
warstw Qwen3.5, bez `causal_conv1d` i `flash-linear-attention`. Wariant końcowy
nie magazynował grafów CUDA. Rezerwację alokatora ograniczono do 80% VRAM;
szczyt aktywnej pamięci PyTorcha wyniósł
10.92 GiB.

Wcześniejsza próba z kilkoma grafami oraz próba bez ograniczenia rezerwacji
zapełniały VRAM i powodowały gwałtowne spowolnienia w Windows. Przerwano je;
logi są w `pilot-graphs-memory` i `pilot-eager-memory`. Nie wchodzą do tabeli.
Wynik dotyczy działającej lokalnej konfiguracji. Nie odtwarza zoptymalizowanego
środowiska H100 autora. Oficjalny Jev był mierzony osobno przez Venice, z siecią.

## Model i pliki

Pobrane wagi przeniesiono do:
`H:/Ollama/models/JevK5/model.safetensors` (8 411 558 400 bajtów).
Plik nie pozostał na C:. SHA-256 przed i po przeniesieniu oraz w metadanych
repozytorium: `13824e47f2e40fe052f06943976cf742cb366ba305741a111e75a8ebae907a9c`.
Obok znajdują się tokenizer, konfiguracje i karta modelu. Katalog służy
do przechowywania wag; nie rejestrowano ich jako modelu czatu Ollamy.

JevK5 jest niezależną alternatywą zbudowaną na Qwen3.5-4B, z dostrojeniem
i odczytem decyzji bez generowania odpowiedzi. To inny model niż Jev TypeSafe.
Źródła: [karta JevK5](https://huggingface.co/alibiserikbay/JevK5),
[oficjalny runtime autora](https://github.com/allebee/jevk5).

- Rewizja wag: `c4f7fdb3aeab5582336406e78d3bef11bf98833d`.
- Runtime 0.3.3: `H:/Tools/JevK5`, rewizja
  `f26426d16f59e8bbe1470e5b162cc89329e29b29`.
- Skrypt: `scripts/benchmark_jevk5_classification.py`.
- Protokół, teksty, metryki i CSV: `scratch/jevk5-classification/`.
- Surowe wyniki: `gemma-results.jsonl`, `jevk5-results.jsonl`, `venice-results.jsonl`.
- Tryb `jevk5-graphs` w skrypcie jest diagnostyczny; nie użyto go w wyniku końcowym.

Nie instalowano nowych bibliotek ani nie pobierano drugiej kopii wag.
Użyto istniejących środowisk Python 3.13 do PDF/Ollamy oraz Python 3.11 do CUDA.

## Oficjalny Jev przez Venice — dostęp i koszt

[Venice](https://venice.ai/lp/jev) udostępnia Jev wyłącznie przez API decyzji,
poza zwykłą listą czatów. Potwierdzono to na koncie użytkownika:
`GET /models?type=decision` zwróciło `jev-latest`, a
`POST https://api.venice.ai/api/v1/decisions` wykonał wszystkie 31 żądań
benchmarku (30 pomiarów i rozgrzewkę). Odpowiedzi podają alias `jev-latest`,
bez numeru wersji modelu TypeSafe.

Pierwsza próba przed doładowaniem konta zwróciła HTTP 402 mimo informacji
o promocji na stronie Venice. Po doładowaniu przez użytkownika zapytania
działają. Modelowy katalog API podaje $0.042 za milion tokenów wejściowych
i zero za wyjście. Zużycie benchmarku z rozgrzewką:
**90542 tokenów wejściowych**;
szacowany koszt według tego cennika to
**$0.003803** (poniżej jednego centa).
To kalkulacja z tokenów i cennika, nie odczyt obciążenia rachunku.
Podany klucz inferencyjny nie ma uprawnień administracyjnych do salda.
Osobne krótkie próby połączenia i uruchomienie pokazu nie wchodzą do tych 31 żądań.

Integracja: `scripts/venice_api.py`. Klucz jest wyłącznie w lokalnym,
ignorowanym przez Git `.env`; `.env.example` zawiera puste pole klucza.
Instrukcja pokazu: [Venice w projekcie](VENICE.pl.md).
