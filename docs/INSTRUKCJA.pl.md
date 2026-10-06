# Signum — instrukcja użytkownika

Signum sprawdza, **czy dokumenty są podpisane**. Obsługuje PDF-y oraz skany
(JPG, PNG, TIFF, BMP, WEBP) i wykrywa:

- podpisy odręczne,
- parafki,
- pieczątki,
- podpisy cyfrowe (kwalifikowane i zwykłe: PAdES, PKCS#7, X.509, znaczniki czasu,
  podpisy certyfikujące).

Program **nie ocenia ważności prawnej ani poprawności kryptograficznej** podpisów —
stwierdza wyłącznie ich obecność i pokazuje wycinki do ręcznej weryfikacji.

## Instalacja

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
   Przed uruchomieniem instalatora pobranego spoza oficjalnego źródła sprawdź
   jego podpis Authenticode lub sumę SHA-256 podaną przez wydawcę.
2. Dla lokalnego AI wybierz składniki. Instalator odczytuje dedykowaną pamięć
   GPU na tym samym ekranie i oznacza zalecany model: Gemma 4 E2B
   dla 8 GB albo Gemma 4 12B dla 16 GB. Jev wymaga w tym pakiecie NVIDIA 16 GB.
   Przycisk **Zaznacz proponowane składniki** zaznacza zalecany model.
   Wykryta Ollama jest oznaczona na liście i nie jest instalowana ponownie.
   Zainstalowane modele i przygotowany Jev mają oznaczenie stanu instalacji.
3. Wybierz katalog modeli i bibliotek. Na tym komputerze domyślnie jest to
   `H:/Tools/SignumAI`. Pozostaw przynajmniej 20 GB dla Ollamy z jednym modelem
   i 35 GB dla Jev; przy obu pakietach dodaj te wartości.
4. Po skopiowaniu aplikacji otworzy się okno przygotowania AI. Pobiera zaznaczone
   zewnętrzne programy, biblioteki i modele, pokazuje postęp oraz ich źródła
   i licencje. Możesz anulować lub ponowić przygotowanie. Po udanym sprawdzeniu
   modelu ustawienia Signum zapisują się automatycznie.
   Działająca Ollama zachowuje własny katalog modeli, a posiadane modele nie
   są ponownie pobierane. Przygotowany Jev także jest wykorzystywany ponownie.
   Biblioteki i modele pozostają oddzielnie od programu po jego odinstalowaniu.

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
- **OpenAI / API zgodne z OpenAI** — podaj adres API, nazwę modelu i klucz API.
- **Claude (Anthropic)** — podaj adres API (domyślnie
  `https://api.anthropic.com/v1`), nazwę modelu i klucz API.
- **vjev-vision (on-prem / API)** — domyślny adres to `http://localhost:8800/v1`,
  model **`vjev-vision`** (identyfikator serwera, a nie nazwa repozytorium Hugging Face).
  Przy **Testuj połączenie** lub rozpoczęciu analizy Signum uruchamia przygotowany
  lokalny model. Wagi, dodatkowe biblioteki i log znajdują się osobno na H:,
  w `H:/Tools/SignumJev`. Pierwsze ładowanie może potrwać kilkadziesiąt sekund;
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
**Jev nie zlicza podpisów i nie zwraca wycinków**. Podpisy cyfrowe są nadal
wykrywane niezależnie ze struktury PDF. Tytułem pozostaje nazwa pliku.
Przycisk **Otwórz dokument źródłowy** pozwala zweryfikować wynik.
Jeżeli limit stron pomija część PDF-a, brak podpisu dotyczy tylko badanej części.

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
   przycisków **Dodaj pliki…** / **Pracuj na folderze…**.
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
| Brak wycinka przy wykrytym podpisie | Jev raportuje tylko obecność na stronie; dla LLM model mógł nie podać wiarygodnej ramki. Zweryfikuj w pliku |
| Wycinek pokazuje fragment bez podpisu | lokalizacja z modelu bywa przybliżona — spójrz na miniaturę strony z czerwoną ramką w raporcie HTML |
