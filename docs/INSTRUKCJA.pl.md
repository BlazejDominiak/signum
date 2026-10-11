# Signum — instrukcja użytkownika

Signum to aplikacja dla Windows do klasyfikowania PDF-ów, porządkowania ich
w folderach oraz wykrywania podpisów w dokumentach i skanach. Możesz wybrać
modele lokalne lub obsługiwane API, edytować kategorie i instrukcje, porównywać
wyniki modeli oraz ręcznie poprawiać etykiety przed porządkowaniem plików.

[Opis projektu](../README.md) · [Historia zmian](../CHANGELOG.md) ·
[Instalator Windows](../installer/output/Signum-Setup-1.1.8.exe)

## Dwa sposoby pracy

| Zakładka | Do czego służy | Wyniki |
|---|---|---|
| **Kategoryzowanie dokumentów** | Klasyfikacja tekstu PDF do 2–12 własnych kategorii, maksymalnie trzy etykiety dokumentu, porównywanie modeli i kopiowanie lub przenoszenie do folderów. | Kolekcja zapisywana między sesjami, dziennik operacji, CSV i JSON. |
| **Sprawdzanie podpisów** | Wykrywanie podpisów odręcznych, parafek i pieczątek, odczyt pól podpisów cyfrowych oraz porównanie Ollamy z Jev. | Wyniki poszczególnych przebiegów, dostępne wycinki, raporty HTML i CSV. |

Każda zakładka ma własną kolejkę, wyniki i ustawienia. Kategoryzacja wymaga
warstwy tekstowej PDF — nie wykonuje OCR. Analiza podpisów korzysta z obrazów
stron, więc obsługuje również skany bez tekstu.

### Wybór modeli

| Model lub połączenie | Zastosowanie | Miejsce przetwarzania |
|---|---|---|
| **Jev / `vjev-vision`** | Podpisy, parafki i pieczątki; opcjonalnie eksperymentalne kategorie dokumentu i wycinki. | Przygotowany lokalny runtime CUDA albo zgodny serwer vjev. |
| **JevK5** | Kategoryzacja tekstu PDF z niezależnymi ocenami etykiet. | Lokalny proces PyTorch/CUDA. |
| **Jev przez Venice** | Kategoryzacja tekstu przez API Decisions. | Usługa zdalna; zobacz [konfigurację Venice](VENICE.pl.md). |
| **Ollama, w tym Gemma** | Kategoryzacja tekstu lub analiza podpisów, zależnie od możliwości modelu. | Lokalna Ollama albo wskazana usługa zdalna. |
| **Zgodne API / Anthropic** | Kategoryzacja tekstu, a z modelem obsługującym obrazy także analiza podpisów. | Skonfigurowana usługa. |

JevK5 i Jev przez Venice służą tutaj do tekstu; `vjev-vision` do obrazów.
Ich ustawienia są osobne. Nazwa dostawcy nie wystarcza do ustalenia, czy dane
pozostają na komputerze — znaczenie mają adres usługi i wybrany model.

## Kategoryzowanie dokumentów

1. Otwórz zakładkę **Kategoryzowanie dokumentów** i dodaj PDF-y lub folder.
   Menu **Więcej → Losuj 100 z folderu…** wybiera do 100 plików. **Otwórz zestaw lokalny…**
   otwiera PDF-y wskazane w zapisanym protokole testu na tym komputerze.
   Dokumenty testowe nie są dołączone do repozytorium ani instalatora.
2. W tabeli po lewej wpisz własne etykiety. Przycisk **Opisy** pokazuje dodatkową
   kolumnę z edytowalnymi wskazówkami dla modelu.
   Do dyspozycji jest 12 wierszy; puste wiersze są pomijane, wymagane są co najmniej
   dwie różne kategorie. Przycisk **Przykładowe** przywraca 12 rodzajów dokumentów
   i przykładową instrukcję. Kolor kategorii powtarza się przy jej wynikach.
   Przycisk **Instrukcja klasyfikacji** rozwija edytor promptu pod tabelą.
   Domyślna treść jest po angielsku.
   Zmiany zapisują się automatycznie, niezależnie od ustawień podpisów.
3. Otwórz **Ustawienia AI…**. Dodaj własne modele, w razie potrzeby duplikując
   konfigurację. Zaznacz modele do porównania albo wybierz pojedynczy model
   z listy na głównym ekranie. Liczba przejść wynosi od 1 do 10.
4. Kliknij **Kategoryzuj** lub **Porównaj modele** i potwierdź okno przed analizą.
   Przy usługach zdalnych okno wskazuje wybrane adresy API.
5. Tabela pokazuje etykietę, model i status każdej próby.
   Przycisk **Pomiary** rozwija czasy przygotowania tekstu, ładowania,
   działania modeli i całego porównania.
6. Dwukrotnie kliknij wiersz PDF-u, aby go otworzyć. Menu pod prawym przyciskiem
   umożliwia również otwarcie folderu. Działa przed analizą i w wynikach.
7. **Skopiuj do folderów…** lub **Przenieś do folderów…** układa kolekcję
   według etykiet — szczegóły poniżej.
8. **Zapisz wyniki…** eksportuje CSV lub pełny raport JSON, również po anulowaniu.
   Raport zawiera ścieżki PDF-ów, kategorie, czasy i skróty wejść; nie zawiera
   tekstów dokumentów ani kluczy API.

### Etykiety, oceny i ręczna weryfikacja

Wynik może zawierać do trzech etykiet o najwyższych ocenach osiągających próg
modelu. Szczegóły zachowują oceny wszystkich kategorii, także niewybranych.
**HITL (human-in-the-loop)** oznacza potrzebę ręcznej weryfikacji. Obejmuje wyniki
blisko progu, również odrzucone etykiety, jeśli wybrano mniej niż trzy.

Wbudowane profile dotyczą zgodnego modelu, domyślnego promptu i zestawu kategorii:

| Model kategoryzacji | Próg etykiety | Pasmo HITL | Źródło ocen |
|---|---|---|---|
| Jev przez Venice | 0,74 | ±0,03 | Oceny modelu decyzyjnego |
| Lokalny JevK5 | 0,83 | ±0,03 | Oceny modelu decyzyjnego |
| Gemma `gemma4:12b` | 0,65 | ±0,05 | Pewność deklarowana przez model |

Własny model, prompt lub kategorie bez pasującego profilu kalibracji wymagają
przeglądu wyników. Wysoka ocena nie gwarantuje poprawności. Wybierz dokument
i **Sprawdź etykiety…**, przejrzyj oceny, a następnie potwierdź lub popraw do
trzech etykiet. Ręczna korekta zachowuje pierwotny wynik modelu w danych kolekcji.
Starsze wyniki Gemmy bez ocen liczbowych wymagają nowego przebiegu, aby je uzyskać.

Lokalny JevK5 współdzieli obliczenie tekstu między pytaniami o etykiety.
Oceny pozostają niezależne; przy ograniczonej pamięci GPU partie są zmniejszane.

### Porządkowanie kolekcji w folderach

Po zakończeniu klasyfikacji wybierz **Skopiuj do folderów…** lub
**Przenieś do folderów…** na pasku poleceń. Operacja obejmuje zaznaczone dokumenty z wynikiem wybranego przebiegu.
Wskaż folder docelowy. Jeśli wykonywano kilka modeli lub przejść, wybierz jeden
wynik w polu **Etykiety z**. Etykiety pochodzą z wybranego przebiegu analizy;
zmiana listy kategorii po analizie nie zmienia istniejących wyników.

Przed operacją zaznacz wiersz i użyj **Sprawdź etykiety…** (lub **Zmień etykietę…**
w menu kontekstowym), aby zweryfikować przypisanie.
Odznaczenie pola obok nazwy pliku wyłącza go z porządkowania. Korekta jest zapisywana
jako ręczna; pierwotny wynik modelu pozostaje w danych sesji.

Kolekcja i jej wyniki zapisują się automatycznie i wracają po uruchomieniu programu.
Plik `%APPDATA%/Signum/collection.json` zawiera ścieżki, etykiety i identyfikatory plików,
a nie wyekstrahowaną treść PDF. **Wyczyść listę** usuwa bieżącą sesję. Historia operacji
jest dostępna przez **Więcej → Dziennik operacji**; nie oznacza automatycznego cofania.

Tabela pokazuje każdy dokument, docelową ścieżkę i pliki pomijane. Kliknięcie
**Skopiuj** lub **Przenieś** wykonuje wyświetlony plan, np.:

```text
Wybrany folder/
  Umowy i porozumienia/Umowa najmu.pdf
  Finanse i rozliczenia/Faktura.pdf
```

- Kopiowanie zachowuje oryginały i może umieścić PDF we wszystkich przypisanych
  kategoriach. Przenoszenie wymaga jednej kategorii docelowej; przy wielu etykietach
  użyj kopiowania albo ręcznie wybierz jedną etykietę.
- Przenoszenie usuwa źródło dopiero po sprawdzeniu
  kopii sumą SHA-256 i aktualizuje ścieżki w obu zakładkach oraz eksportach.
- Istniejące pliki nie są nadpisywane. Powtarzające się nazwy dostają przyrostki
  `(2)`, `(3)` itd.; dokładna nazwa jest widoczna w podglądzie.
- Znaki niedozwolone w nazwach folderów Windows są zastępowane `_`. Kolizje nazw
  etykiet po tej zmianie tworzą osobne numerowane foldery.
- Pliki z nierozstrzygniętym HITL lub bez etykiet są pomijane — najpierw sprawdź
  i zatwierdź ich etykiety.
- Pliki bez wyniku wybranego przebiegu, z błędem, brakujące albo już znajdujące się
  we właściwym folderze są pomijane. Dowiązania do plików i folderów kategorii
  nie są obsługiwane. Można uporządkować także częściowe wyniki anulowanej analizy.
- **Anuluj** zatrzymuje dalsze operacje. Zakończone kopie/przeniesienia pozostają;
  nieukończona kopia jest usuwana, a jej źródło pozostaje na miejscu.
- Błędy pojedynczego pliku nie zatrzymują reszty kolekcji. Wynik widać w kolumnie
  **Stan**; pełny komunikat pojawia się po najechaniu. **Otwórz folder** otwiera wynik
  w Eksploratorze. Jeśli plik zmienił się po klasyfikacji, powtórz jego analizę przed porządkowaniem.

### Ustawienia modeli kategoryzacji i porównywanie

W **Ustawienia AI…** możesz dodawać i duplikować konfiguracje, wybierać modele
do porównania oraz zmieniać ich adresy, nazwy i klucze. Dostępne połączenia:

- **Ollama** — adres serwera, dowolny model wpisany ręcznie lub wybrany
  przez **Odśwież listę**, opcjonalny klucz.
- **AI od dostawcy** — adres API, model, klucz i format: Chat Completions
  (OpenAI-compatible), Messages (Anthropic) lub Decisions (np. Jev przez Venice).
- **JevK5 — lokalnie, PyTorch** — przygotuj przez **Składniki AI → JevK5 → Instaluj / napraw**;
  ścieżki zostaną wpisane automatycznie. Możesz również wskazać własną instalację.

**Testuj połączenie** wysyła syntetyczny tekst i sprawdza odpowiedź wybranego
modelu, także przed zapisaniem konfiguracji. Klucze pozostają w systemowym
magazynie poświadczeń. Dotychczasowe konfiguracje są przenoszone do nowej listy;
zapisany własny prompt pozostaje bez zmian. Aplikacja nie pobiera modeli w tle.

Kategoryzacja korzysta z warstwy tekstowej PDF, bez OCR. Skan bez tekstu otrzyma
komunikat o braku warstwy tekstowej. Początek dokumentu (do 12 000 znaków)
jest skracany do wspólnego budżetu bajtów, a przy wybranym JevK5 również do
jego budżetu tokenów. Samo istnienie lokalnego JevK5 nie uruchamia jego tokenizera.
Wszystkie modele dostają identyczny przygotowany tekst.

Działanie modelu obejmuje żądanie API i ewentualne oczekiwanie na limit.
Ładowanie Ollamy i JevK5 odbywa się osobno, bez próbnej klasyfikacji do rozgrzewki.
Czas łączny obejmuje także obsługę połączenia i zwolnienie zasobów. Przy API
zarządzanym poza aplikacją czas ładowania po stronie serwera nie jest osobno dostępny.
Modele są uruchamiane kolejno; zakładka podpisów jest wtedy niedostępna.

## Sprawdzanie podpisów

Ta funkcja sprawdza, **czy dokumenty są podpisane**. Obsługuje PDF-y oraz skany
(JPG, PNG, TIFF, BMP, WEBP) i wykrywa:

- podpisy odręczne,
- parafki,
- pieczątki,
- pola podpisów cyfrowych (m.in. PAdES/CAdES, CMS/PKCS#7, X.509, znaczniki czasu
  RFC 3161 i podpisy certyfikujące/DocMDP).

Program **nie ocenia ważności prawnej ani poprawności kryptograficznej** podpisów —
wyszukuje oznaki ich obecności i, zależnie od trybu, udostępnia przybliżone wycinki
do ręcznej weryfikacji. Nie ustala, czy podpis jest kwalifikowany. Puste pola podpisu
nie są traktowane jako podpisane; pieczątka sama w sobie nie oznacza podpisu.

### TODO — poprawa lokalizacji podpisów na dokumencie

- [ ] Poprawić przestrzenną lokalizację podpisów przez **Gemmę i `vjev-vision`**,
  szczególnie na dokumentach z wieloma podpisami. Obecnie wskazywanie położenia,
  ramek i wycinków nie działa dostatecznie dobrze: może pomijać podpisy,
  obejmować kilka podpisów jednym obszarem lub wskazywać niewłaściwy fragment.
  Zadanie obejmuje dokładniejsze ramki i rozdzielanie poszczególnych podpisów
  oraz sprawdzenie wyników na dokumentach z jednym i wieloma podpisami.

To znane ograniczenie wymagające dalszej pracy. Wykrycie obecności podpisu
nie gwarantuje prawidłowego wskazania jego miejsca ani odnalezienia wszystkich
podpisów. Sprawdzaj pełną stronę dokumentu źródłowego; sama ramka lub wycinek
nie wystarcza. W vjev problem lokalizacji dotyczy eksperymentalnej **Dodatkowej
analizy** — tryb podstawowy nie zwraca wycinków i nie zlicza podpisów.

## Instalacja

Wymagany jest Windows 10 22H2 lub nowszy (w tym Windows 11); instalator odrzuca starsze wersje.

1. Uruchom `Signum-Setup-<wersja>.exe` i przejdź przez kreator (instalacja nie
   wymaga uprawnień administratora). Osobny ekran świadomości ryzyka wymaga
   czterech potwierdzeń: edukacyjnego charakteru programu i nieprzydatności do
   użytku komercyjnego, używania tylko dokumentów przykładowych bez danych osobowych
   lub wrażliwych, przetwarzania przez model lokalny oraz wysyłki przez internet
   do zewnętrznej usługi AI.
   Instalacja cicha wymaga parametru `/ACKNOWLEDGERISKS=1`.
   Instalator zawiera własny runtime Pythona i biblioteki — użytkownik nie musi
   osobno instalować Pythona dla samej aplikacji. Na ekranie składników możesz
   wybrać Ollamę i modele do lokalnej analizy albo pozostawić sam Signum.
   Suma SHA-256 instalatora znajduje się w pliku obok pakietu w repozytorium.
2. Dla lokalnego AI wybierz składniki. Instalator odczytuje dedykowaną pamięć
   GPU na tym samym ekranie i oznacza zalecany model: Gemma 4 E2B
   dla 8 GB albo Gemma 4 12B dla 16 GB. Jev (podpisy) i JevK5 (kategoryzacja) wymagają w tym pakiecie NVIDIA 16 GB.
   Przycisk **Zaznacz proponowane składniki** zaznacza zalecany model.
   Wykryta Ollama jest oznaczona na liście i nie jest instalowana ponownie.
   Wykrycie plików jest oznaczone osobno od testu działania bibliotek i modelu.
3. Wybierz katalog modeli i bibliotek. Jeśli istnieje dysk H:, propozycją jest
   `H:/Tools/SignumAI`; w przeciwnym razie `Dokumenty/SignumAI`. Można wybrać inny dysk.
   Pozostaw przynajmniej 20 GB dla Ollamy z modelem i po 35 GB dla Jev / JevK5.
4. Po skopiowaniu aplikacji otworzy się okno przygotowania AI. Pobiera zaznaczone
   zewnętrzne programy, biblioteki i modele, pokazuje postęp oraz ich źródła
   i licencje. Możesz anulować lub ponowić przygotowanie. Po udanym sprawdzeniu
   modelu ustawienia Signum zapisują się automatycznie.
   Działająca Ollama zachowuje własny katalog modeli, a posiadane modele nie
   są ponownie pobierane. Jev i JevK5 są wykorzystywane ponownie po udanym sprawdzeniu bibliotek i próbnej analizie.
   Biblioteki i modele pozostają oddzielnie od programu po jego odinstalowaniu.

## Doinstalowanie modeli i naprawa

**Składniki AI…** są dostępne w obu zakładkach i w Ustawieniach AI.
Zaznacz składnik i kliknij **Sprawdź**. Test nie pobiera plików; sprawdza biblioteki,
CUDA i przykładową odpowiedź modelu. „Wykryto pliki” samo w sobie nie oznacza gotowości.
Przycisk **Instaluj / napraw** uzupełnia brakującą instalację. Działające środowiska
są używane ponownie. Naprawa środowiska zewnętrznego przygotowuje osobną instalację
w wybranym folderze; nie usuwa globalnego Pythona użytkownika.

Aby pobrać inny model Ollamy, wpisz jego nazwę z biblioteki Ollamy w polu pod listą
składników. Modele tekstowe służą do kategoryzacji; do podpisów wybierz model obsługujący
obrazy. Nowe, sprawdzone modele trafiają do listy w Ustawieniach AI kategoryzacji.

Po błędzie odczytaj „Jak naprawić” w komunikacie lub kliknij dwukrotnie komórkę **Błąd**
w wynikach kategoryzacji. Szczegółowy log przygotowania: `setup.log` w wybranym folderze.

| Problem | Postępowanie |
|---|---|
| Brak Pythona, modułu, plików wag lub niezgodne biblioteki | Składniki AI → odpowiedni model → Instaluj / napraw, następnie Sprawdź. |
| CUDA / sterownik / karta bez 16 GB VRAM | Zaktualizuj sterownik NVIDIA z witryny producenta; bez odpowiedniej karty użyj Ollamy z mniejszym modelem albo API. |
| DLL / Visual C++ | Zainstaluj Microsoft Visual C++ Redistributable x64 z odnośnika w komunikacie i uruchom komputer ponownie. |
| Brak pamięci GPU | Zamknij pozostałe aplikacje używające GPU lub wybierz mniejszy model. |
| Brak miejsca lub praw zapisu | Wybierz inny folder w Składnikach AI; uruchomiona zewnętrzna Ollama zachowuje własny folder modeli. |
| Błąd API 401/403 lub 429 | Popraw klucz/uprawnienia albo sprawdź limit konta; ponów Testuj połączenie. |

Ollama, modele, biblioteki i Python są składnikami zewnętrznymi, które należy pobierać
ze sprawdzonych źródeł; autor Signum nie bierze za nie odpowiedzialności.

## Ustawienia AI do sprawdzania podpisów

Otwórz **Ustawienia AI…** i wybierz dostawcę:

- **Ollama** — jest lokalna tylko wtedy, gdy adres wskazuje pętlę zwrotną
  (`localhost`, `127.0.0.1` lub `::1`). W takim trybie dokumenty nie opuszczają
  komputera, ale ich treść
  nadal trafia do modelu i jest przez niego analizowana. Lokalne uruchomienie
  nie przesądza, czy przetwarzanie jest dozwolone. Kliknij „Odśwież listę",
  wybierz model obsługujący obrazy (np. `gemma4:12b`),
  Lista modeli i stan usługi są sprawdzane automatycznie po otwarciu ustawień.
  Możesz również kliknąć **Testuj połączenie**. Zdalna Ollama jest oznaczana jako
  tryb online i musi korzystać z HTTPS. Dodatkowo możesz ustawić **okno kontekstu
  (num_ctx)** — Signum domyślnie ustawia 8192 tokeny; większe okno zwiększa
  zużycie pamięci karty graficznej.
- **AI od dostawcy** — wybierz format API, podaj adres, model i klucz,
  następnie użyj **Testuj połączenie**.
- **vjev-vision (on-prem / API)** — domyślny adres to `http://localhost:8800/v1`,
  model **`vjev-vision`** (identyfikator serwera, a nie nazwa repozytorium Hugging Face).
  Przy **Testuj połączenie** lub rozpoczęciu analizy Signum uruchamia przygotowany
  lokalny model. Wagi, biblioteki i log znajdują się w folderze wybranym przy instalacji. Pierwsze ładowanie może potrwać kilkadziesiąt sekund;
  kolejne dokumenty korzystają z już załadowanego modelu. Klucz lokalnie jest zbędny.
  Przycisk **Zatrzymaj lokalny Jev / zwolnij GPU** zwalnia pamięć karty po testach.
  Po zakończeniu lub anulowaniu analizy program zwalnia ją automatycznie.
  Możesz też podać adres zdalnego serwera zgodnego z
  [vjev-serve](https://github.com/BubbleCal/vjev-serve) i opcjonalny klucz jego bramki API.
  Instalator GUI nie zawiera wag ani runtime CUDA. Automatyczny start wymaga kompletnego
  przygotowanego katalogu z `runtime.json`; nie pobiera nic podczas zwykłej pracy.

Każdy dostawca ma pola **Adres API**, **Model** i **Klucz API**. Wpisz adres bazowy,
bez końcówki `/systemone` czy `/messages`. Klucz możesz pokazać
lub wyczyścić; zmiany zatwierdza **Zapisz**. Przycisk **Testuj połączenie** dla Jev
sprawdza model i wysyła mały, syntetyczny obraz (API może naliczyć opłatę).
API na `localhost`, `127.0.0.1` i `::1` jest rozpoznawane jako lokalne także dla
vjev i serwerów zgodnych z pozostałymi API.

Jev analizuje pełną stronę i cztery zachodzące na siebie ćwiartki. Dziewięć pytań
typowanych dostarcza ocen do heurystyki z progiem 0,535. Program pokazuje
prawdopodobieństwo obecności podpisu lub parafki także przy wyniku ujemnym.
Kalibracja pochodzi z próby eksperymentalnej; nie gwarantuje jakości na innych dokumentach.
Wyniki w paśmie ±0,10 wokół progu 0,535 otrzymują HITL, także przy decyzji ujemnej.
Pieczątka jest osobnym znaleziskiem i sama nie oznacza podpisanego dokumentu.
**Podstawowy Jev nie zlicza podpisów i nie zwraca wycinków**. Podpisy cyfrowe są nadal
wykrywane niezależnie ze struktury PDF. Tytułem pozostaje nazwa pliku.
Przycisk **Otwórz dokument źródłowy** pozwala zweryfikować wynik.
Jeżeli limit stron pomija część PDF-a, brak podpisu dotyczy tylko badanej części.

### Dodatkowa analiza

W ustawieniach Ollamy (np. Gemmy) oraz Jev znajduje się osobny przełącznik
**Dodatkowa analiza**. Ustawienia obu dostawców są zapamiętywane niezależnie.

- **Ollama, wyłączona:** tylko obecność podpisu/parafki i pieczątki, bez opisu,
  liczenia oznaczeń i wycinków. W tym trybie używany jest stały, krótki prompt.
  Oceny liczbowe pochodzą bezpośrednio od modelu; nie są kalibrowane.
- **Ollama, włączona:** dotychczasowa pełna analiza z opisem i współrzędnymi
  do wycięcia oznaczeń. Ta opcja jest domyślnie włączona, aby zachować wcześniejsze działanie.
- **Jev, wyłączona:** dotychczasowy klasyfikator pięciu widoków bez zmian.
- **Jev, włączona:** dodatkowo maksymalnie dwie kategorie dokumentu z listy 48
  oraz przybliżone wycinki. Program sprawdza siatkę 4 × 5, łączy sąsiednie trafienia
  i ocenia scalone obszary. Wycinek może obejmować grupę podpisów. Jeśli lokalizacja
  się nie uda, pozostaje podstawowe wykrycie bez wycinka. Kategorie i wycinki są
  eksperymentalne; włączenie dodatków wydłuża pracę. Opcja jest domyślnie wyłączona.

Wynik obecności podpisu i jego prawdopodobieństwo w Jev pochodzą zawsze z tej samej
podstawowej reguły. Klasyfikacja rodzaju dokumentu nie wpływa na wykrywanie podpisu.
Podpisy cyfrowe są nadal sprawdzane niezależnie w obu trybach.

CLI obsługuje odpowiednio `--additional-analysis` oraz `--no-additional-analysis`.
Bez tych flag korzysta z zapisanych ustawień.

**Uwaga — konfiguracje zdalne:** przy przełączeniu z lokalnego API na zdalne
API program wyświetla ostrzeżenie, że analizowane dokumenty
**będą wysyłane przez sieć poza komputer** — przycisk „Rozumiem zagrożenie" odblokowuje się po
3 sekundach. Dopóki aktywny jest dostawca chmurowy, w pasku stanu okna głównego
widoczna jest czerwona plakietka **„Model online"**.

Klucze API są zapisywane w Menedżerze poświadczeń systemu Windows, nie w plikach.

Ustawienia przetwarzania:

| Opcja | Znaczenie |
|---|---|
| Limit stron na dokument | Liczba pierwszych stron analizowanych wizyjnie. Niezależny skan pól podpisów cyfrowych nie korzysta z tego limitu; błędy lub niepełny skan są raportowane. |
| Rozmiar obrazu dla modelu | Większy obraz może zwiększyć koszt i czas analizy; nie gwarantuje lepszej lokalizacji. Jev używa stałego rozmiaru 1120 px na widok. |
| Limit czasu odpowiedzi | maksymalny czas oczekiwania na model |
| Przeszukuj podfoldery | dotyczy dodawania folderów |

**Prompt programu** — w tej sekcji możesz edytować merytoryczną część polecenia
wysyłanego do modelu (np. dodać wskazówki specyficzne dla Twoich dokumentów:
„zwróć uwagę na pole przy napisie *czytelny podpis*"). Wymagany format
odpowiedzi program dokleja automatycznie — nie trzeba (i nie należy) go
opisywać. Przycisk **Przywróć domyślny** cofa zmiany.
LLM i Jev mają osobne instrukcje, zachowywane podczas przełączania dostawcy.
Do promptu Jev program dodaje pytania typowane, bez instrukcji generowania JSON.
Edycja promptu znajduje się w zwijanej sekcji zaawansowanej. Zmiana instrukcji Jev
oznacza odejście od przetestowanego wariantu i może zmienić jakość oraz kalibrację.

## Analiza podpisów krok po kroku

1. **Dodaj dokumenty**: przeciągnij pliki lub całe foldery do okna, albo użyj
   przycisków **Dodaj pliki…** / **Dodaj folder…**.
2. Kliknij **Przetwórz**, aby użyć wybranego dostawcy, albo **Porównaj Ollama + Jev**,
   aby uruchomić oba modele kolejno. Program pokaże ostrzeżenie dla całej kolejki —
   nie wyświetla go przy każdym dodawanym pliku. Aby rozpocząć, potwierdź prawo
   do przetwarzania dokumentów, sposób przekazania danych do modelu oraz
   konieczność ręcznej weryfikacji wyników. Przed pokazaniem ostrzeżenia Signum
   sprawdza, czy wybrana usługa oraz model są dostępne; brak Ollamy lub modelu
   zatrzymuje uruchomienie z instrukcją naprawy. Następnie pliki są analizowane po
   kolei — pasek postępu pokazuje bieżący plik i szacowany pozostały czas.
   Możesz kliknąć **Anuluj** (dokończy się bieżąca strona).
3. Wyniki pojawiają się w tabeli na bieżąco:
   - **Opis / nazwa** — opis wygenerowany przez model w odpowiednim trybie albo nazwa pliku,
   - **Podpisy** — decyzja o obecności podpisu z informacją o zakresie analizy;
     podstawowy Jev nie podaje liczby podpisów,
   - **Ocena** — najwyższa pewność wykrycia, a w trybach zwracających prawdopodobieństwo
     obecności podpisu — najwyższa taka wartość z analizowanych stron,
   - **Status** — m.in. OK, HITL, błąd lub anulowanie.
4. Kliknij wiersz, aby zobaczyć **szczegóły**: dostępne informacje o rodzaju
   znaleziska, stronie i ocenie oraz wycinki, jeśli dany tryb je zwrócił
   (kliknij miniaturę, aby powiększyć). **Otwórz dokument źródłowy** pozwala
   sprawdzić pełną stronę, także gdy wycinka brakuje lub jest nietrafny.
   Dla podpisów cyfrowych wyświetlane są podtyp i dostępne dane podpisującego oraz daty.
5. **Porównaj Ollama + Jev** uruchamia oba modele kolejno na tej samej kolejce,
   używając zapisanych ustawień każdego z nich, w tym dodatkowej analizy.
   **Wyniki przebiegu** pozwalają wrócić do wcześniejszego wyniku bez ponawiania analizy.
   Wyniki kolejnych uruchomień pozostają w pamięci do **Wyczyść** lub zamknięcia aplikacji.
6. **Zapisz raport…** eksportuje wszystkie zachowane przebiegi. HTML zawiera
   tabelę czasów przygotowania, ładowania, działania i całego przebiegu każdego modelu
   oraz porównanie dokument po dokumencie z zaznaczonymi różnicami i HITL.
   CSV zawiera osobny wiersz dla każdej pary dokument–przebieg, nazwę modelu,
   czasy dokumentu, czasy całego modelu i zgodność wyników. Błędy, brak wyniku
   i niepełna analiza nie oznaczają zgodności. Ustawienia analizy są zapisane przy
   każdym modelu; porównuj szybkość przy tym samym zakresie analizy.
   Raport to samowystarczalny HTML albo CSV (średniki, zgodny
   z polskim Excelem). Gdy dostępna jest lokalizacja, HTML pokazuje wycinek
   oraz **miniaturę całej strony z czerwoną ramką**. Ramka pokazuje wskazanie
   modelu, które również może być błędne — nie potwierdza rzeczywistego położenia
   podpisu. Przy wielu podpisach zweryfikuj każdy z nich w źródłowym dokumencie.
   Przed zapisem pojawia się ostrzeżenie o poufności. Raporty nie zapisują pełnych
   ścieżek lokalnych, ale zawierają nazwy plików i dane z dokumentów; HTML osadza
   również obrazy. Chroń raport tak samo jak dokumenty źródłowe.

Błąd jednego pliku (np. uszkodzony PDF, PDF z hasłem) nie przerywa pozostałych —
plik dostaje status „Błąd" z opisem w dymku. Utrata połączenia z modelem przerywa
partię z komunikatem.

Wynik Signum nie potwierdza tożsamości osoby podpisującej, autentyczności
podpisu, jego ważności prawnej lub kryptograficznej ani integralności dokumentu.
Signum jest narzędziem edukacyjnym i nie nadaje się do użytku w organizacjach.
Przed każdą partią należy zaznaczyć dwa potwierdzenia: edukacyjnego przeznaczenia
oraz przetwarzania treści dokumentów. Przy usłudze zdalnej drugie pole informuje
o przesyłaniu danych przez internet do usług stron trzecich. Dotyczy to także
modeli Ollamy z końcówką `cloud`, nawet przy lokalnym adresie API.

## Tryb wiersza poleceń

Do automatyzacji analizy podpisów służy `signum-cli` (w instalacji ze źródeł).
Kategoryzację i porządkowanie kolekcji obsługuje interfejs graficzny.

```
signum-cli C:\skany --html raport.html --csv raport.csv --acknowledge-risks
signum-cli umowa.pdf --provider ollama --model gemma4:12b --acknowledge-risks
```

Bez flagi `--acknowledge-risks` CLI wyświetla ostrzeżenie i kończy działanie bez
łączenia z usługą AI. Flaga jest jawnym potwierdzeniem wymaganym również w automatyzacji.

Kody zakończenia: `0` — partia ukończona bez błędów dokumentów; `1` — błąd dokumentu
lub przerwanie przez utratę połączenia; `2` — nieprawidłowe argumenty, brak wejść,
potwierdzenia albo nieudane sprawdzenie usługi przed analizą. Raporty są zapisywane
również dla partii z błędami dokumentów.

## Rozwiązywanie problemów

| Objaw | Rozwiązanie |
|---|---|
| „Brak połączenia z Ollamą" | uruchom Ollamę (`ollama serve` lub aplikacja); sprawdź adres w ustawieniach |
| „Model … nie jest zainstalowany" | `ollama pull <model>` |
| Bardzo długi czas analizy | mniejszy model, mniejszy „rozmiar obrazu dla modelu", mniejszy limit stron |
| PDF ze statusem „Błąd: … zaszyfrowany" | zdejmij hasło z pliku przed analizą |
| Brak wycinka przy wykrytym podpisie | Włącz „Dodatkową analizę” w ustawieniach Ollamy lub Jev. Także w tym trybie lokalizacja może się nie udać mimo wykrycia podpisu. Zweryfikuj w pliku |
| Wycinek pokazuje fragment bez podpisu albo pomija część podpisów | Znane ograniczenie Gemmy i vjev, szczególnie przy wielu podpisach. Otwórz źródło i sprawdź całą stronę; ramka w HTML pokazuje jedynie wskazanie modelu. Poprawa lokalizacji pozostaje zadaniem TODO. |
| Skan PDF nie daje się skategoryzować | Kategoryzacja wymaga warstwy tekstowej; przygotuj OCR poza Signum. Do samego sprawdzania podpisów warstwa tekstowa nie jest potrzebna. |
| Dokument jest pomijany podczas porządkowania | Sprawdź wynik wybranego modelu/przebiegu, etykiety i HITL. Przenoszenie wymaga jednej etykiety; kopiowanie obsługuje wiele. |


## Instalacja — stan AI i tryb cichy

Ekran końcowy rozróżnia zainstalowanie programu i gotowość AI. Przy błędzie użyj
**Składniki AI → Instaluj / napraw**. W otwartym oknie **Spróbuj ponownie** pomija
składniki już sprawdzone w tym podejściu. Log i licencje są pod **Szczegóły**.
Przerwane pobieranie jest wznawiane, jeśli serwer obsługuje zakresy; gotowy plik
z przypiętą sumą SHA-256 jest sprawdzany przed użyciem.

Przy istniejącej Ollamie program korzysta z jej magazynu modeli. Jeżeli usługa używa
niestandardowej lokalizacji, wskaż ją w **Składniki AI → Szczegóły instalacji**.
API Ollamy nie ujawnia tej ścieżki. Dla usługi uruchomionej poza bieżącą sesją Signum
pobranie brakującego modelu wymaga potwierdzonego folderu; program sprawdza na nim wolne
miejsce. Instalator interaktywny proponuje OLLAMA_MODELS lub domyślną lokalizację do
potwierdzenia. W trybie cichym podaj `/OLLAMAMODELDIR`, jeśli ścieżka nie była zapisana.

Przykład instalacji bez okien (PowerShell):

```powershell
.\Signum-Setup-1.1.8.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /ACKNOWLEDGERISKS=1 /COMPONENTS=app,gemma_small /AIDIR="H:\Tools\SignumAI"
```

Parametr `/OLLAMAMODELDIR="pełna ścieżka"` wskazuje magazyn istniejącej usługi.
Kod 0 oznacza sukces, 10 — program zainstalowany, ale przygotowanie AI nieudane.
Raport przygotowania instalatora znajduje się w `%APPDATA%/Signum/setup-result.json`.
Aktualizacja zachowuje wcześniej wybrany katalog; odinstalowanie pozostawia modele.

Instalator demo buduje się poleceniem `scripts/build_installer.ps1`.
