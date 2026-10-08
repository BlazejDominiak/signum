# Signum — instrukcja użytkownika

Signum ma dwie niezależne zakładki: **Kategoryzowanie dokumentów**
oraz **Sprawdzanie podpisów**. Każda ma własną kolejkę i wyniki.

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

### Porządkowanie kolekcji w folderach

Po zakończeniu klasyfikacji wybierz **Skopiuj do folderów…** lub
**Przenieś do folderów…** na pasku poleceń. Operacja obejmuje zaznaczone dokumenty z wynikiem wybranego przebiegu.
Wskaż folder docelowy. Jeśli wykonywano kilka modeli lub przejść, wybierz jeden
wynik w polu **Etykiety z**. Etykiety pochodzą z wybranego przebiegu analizy;
zmiana listy kategorii po analizie nie zmienia istniejących wyników.

Przed operacją zaznacz wiersz i użyj **Zmień etykietę…**, aby poprawić kategorię.
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

- Kopiowanie zachowuje oryginały. Przenoszenie usuwa źródło dopiero po sprawdzeniu
  kopii sumą SHA-256 i aktualizuje ścieżki w obu zakładkach oraz eksportach.
- Istniejące pliki nie są nadpisywane. Powtarzające się nazwy dostają przyrostki
  `(2)`, `(3)` itd.; dokładna nazwa jest widoczna w podglądzie.
- Znaki niedozwolone w nazwach folderów Windows są zastępowane `_`. Kolizje nazw
  etykiet po tej zmianie tworzą osobne numerowane foldery.
- Pliki bez wyniku wybranego przebiegu, z błędem, brakujące albo już znajdujące się
  we właściwym folderze są pomijane. Dowiązania do plików i folderów kategorii
  nie są obsługiwane. Można uporządkować także częściowe wyniki anulowanej analizy.
- **Anuluj** zatrzymuje dalsze operacje. Zakończone kopie/przeniesienia pozostają;
  nieukończona kopia jest usuwana, a jej źródło pozostaje na miejscu.
- Błędy pojedynczego pliku nie zatrzymują reszty kolekcji. Wynik widać w kolumnie
  **Stan**; pełny komunikat pojawia się po najechaniu. **Otwórz folder** otwiera wynik
  w Eksploratorze. Jeśli plik zmienił się po klasyfikacji, powtórz jego analizę przed porządkowaniem.

**Ustawienia AI…** oferują:
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
- podpisy cyfrowe (kwalifikowane i zwykłe: PAdES, PKCS#7, X.509, znaczniki czasu,
  podpisy certyfikujące).

Program **nie ocenia ważności prawnej ani poprawności kryptograficznej** podpisów —
stwierdza wyłącznie ich obecność i pokazuje wycinki do ręcznej weryfikacji.

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

## Pierwsze uruchomienie — ustawienia AI

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
  (num_ctx)** — Ollama sama z siebie używa tylko 4096 tokenów; Signum domyślnie
  ustawia 8192 (większe okno = większe zużycie pamięci karty graficznej).
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
| Limit stron na dokument | ile pierwszych stron PDF-a jest analizowanych wizyjnie (podpisy cyfrowe są wykrywane zawsze, w całym pliku) |
| Rozmiar obrazu dla modelu | większy = dokładniej, wolniej. Dla `gemma4` Ollama zmniejsza obraz do ~0,65 Mpx. Dla Jev rozmiar jest stały: 1120 px na widok, zgodnie ze sprawdzoną metodą |
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

## Praca z programem

1. **Dodaj dokumenty**: przeciągnij pliki lub całe foldery do okna, albo użyj
   przycisków **Dodaj pliki…** / **Dodaj folder…**.
2. Kliknij **Przetwórz**. Program pokaże jedno ostrzeżenie dla całej kolejki —
   nie wyświetla go przy każdym dodawanym pliku. Aby rozpocząć, potwierdź prawo
   do przetwarzania dokumentów, sposób przekazania danych do modelu oraz
   konieczność ręcznej weryfikacji wyników. Przed pokazaniem ostrzeżenia Signum
   sprawdza, czy wybrana usługa oraz model są dostępne; brak Ollamy lub modelu
   zatrzymuje uruchomienie z instrukcją naprawy. Następnie pliki są analizowane po
   kolei — pasek postępu pokazuje bieżący plik i szacowany pozostały czas.
   Możesz kliknąć **Anuluj** (dokończy się bieżąca strona).
3. Wyniki pojawiają się w tabeli na bieżąco:
   - **Tytuł (AI)** — kilkuwyrazowy opis dokumentu nadany przez model,
   - **Podpisy** — `PODPISANY (n)` albo `BRAK PODPISU`,
   - **Pewność** — najwyższa pewność wykrycia w pliku.
4. Kliknij wiersz, aby zobaczyć **szczegóły**: rodzaj każdego podpisu, stronę,
   pewność oraz **wycinek podpisu** (kliknij miniaturę, aby powiększyć).
   Dla podpisów cyfrowych wyświetlane są podtyp, podpisujący i data.
5. **Zapisz raport…** — samowystarczalny HTML albo CSV (średniki, zgodny
   z polskim Excelem). W raporcie HTML przy każdym znalezisku jest wycinek
   oraz **miniatura całej strony z czerwoną ramką** w miejscu wskazanym przez
   model — nawet gdy wycinek chybił, miniatura pokazuje, gdzie szukać podpisu.
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

Do automatyzacji służy `signum-cli` (w instalacji ze źródeł):

```
signum-cli C:\skany --html raport.html --csv raport.csv --acknowledge-risks
signum-cli umowa.pdf --provider ollama --model gemma4:12b --acknowledge-risks
```

Bez flagi `--acknowledge-risks` CLI wyświetla ostrzeżenie i kończy działanie bez
łączenia z usługą AI. Flaga jest jawnym potwierdzeniem wymaganym również w automatyzacji.

## Rozwiązywanie problemów

| Objaw | Rozwiązanie |
|---|---|
| „Brak połączenia z Ollamą" | uruchom Ollamę (`ollama serve` lub aplikacja); sprawdź adres w ustawieniach |
| „Model … nie jest zainstalowany" | `ollama pull <model>` |
| Bardzo długi czas analizy | mniejszy model, mniejszy „rozmiar obrazu dla modelu", mniejszy limit stron |
| PDF ze statusem „Błąd: … zaszyfrowany" | zdejmij hasło z pliku przed analizą |
| Brak wycinka przy wykrytym podpisie | Włącz „Dodatkową analizę” w ustawieniach Ollamy lub Jev. Także w tym trybie lokalizacja może się nie udać mimo wykrycia podpisu. Zweryfikuj w pliku |
| Wycinek pokazuje fragment bez podpisu | lokalizacja z modelu bywa przybliżona — spójrz na miniaturę strony z czerwoną ramką w raporcie HTML |


### Instalacja 1.1.4 — stan AI i tryb cichy

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
.\Signum-Setup-1.1.4.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /ACKNOWLEDGERISKS=1 /COMPONENTS=app,gemma_small /AIDIR="H:\Tools\SignumAI"
```

Parametr `/OLLAMAMODELDIR="pełna ścieżka"` wskazuje magazyn istniejącej usługi.
Kod 0 oznacza sukces, 10 — program zainstalowany, ale przygotowanie AI nieudane.
Raport przygotowania instalatora znajduje się w `%APPDATA%/Signum/setup-result.json`.
Aktualizacja zachowuje wcześniej wybrany katalog; odinstalowanie pozostawia modele.

Instalator demo buduje się poleceniem `scripts/build_installer.ps1`; certyfikat nie jest potrzebny.
