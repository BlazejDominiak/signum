# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/), wersjonowanie: [SemVer](https://semver.org/).

## [1.1.3] — 2026-10-07

### Added
- „Składniki AI” w obu widokach oraz ustawieniach: sprawdzanie, instalacja i naprawa,
  wybór folderu i pobieranie dowolnego nazwanego modelu Ollamy.
- Instalacja JevK5 z osobnym Pythonem, bibliotekami CUDA, przypiętą wersją źródeł
  i wagami sprawdzanymi sumą SHA-256. Osobne opisy Jev do podpisów i JevK5 do tekstu.
- Testy rzeczywistych importów bibliotek, operacji CUDA, tokenizera, plików wag
  i przykładowej odpowiedzi modelu przed uznaniem składnika za gotowy.
- Instrukcje naprawy błędów bibliotek, sterownika, pamięci, dysku i API oraz
  informacja o odpowiedzialności za zewnętrzne składniki w instalatorze PL/EN.

### Fixed
- Usunięto domyślne ścieżki Pythona, bibliotek, JevK5 i pliku .env konkretnego komputera.
  Bez H: program korzysta z wybranego folderu lub Dokumenty/SignumAI.
- Modele przygotowane w instalatorze trafiają do konfiguracji kategoryzacji;
  wybór E2B nie pozostawia niepobranego 12B jako jedynego modelu.
- Embedded Python otrzymuje jawne ścieżki bibliotek; nie zależy od PYTHONPATH.
  Tryb sprawdzania nie pobiera ani nie instaluje składników.

### Validation
- Testy automatyczne obejmują brak dysku H:, niekompletne instalacje, ponowne
  użycie środowisk i publikowanie konfiguracji dopiero po udanym teście modelu.
- Pakiet wymaga osobnego odbioru na czystym Windows przed publikacją;
  lokalny test bibliotek/GPU nie zastępuje instalacji na drugim komputerze.

## [1.1.2] — 2026-10-07

### Changed
- Wspólny układ pasków dokumentów, ustawień AI i przycisków uruchamiania.
- Własne konfiguracje modeli do porównania: Ollama, dowolne obsługiwane API
  i lokalny runtime JevK5; dodawanie, duplikowanie, wybór oraz test połączenia.
- Jedna opcja „AI od dostawcy” z adresem, modelem, kluczem i formatem API.
- Angielski prompt kategoryzacji widoczny od razu; usunięto zbędne opisy z UI.
- Osobne czasy przygotowania, ładowania i działania modeli oraz czas całkowity,
  również w eksportach. Bez dodatkowych rozgrzewkowych zapytań do chmury.

### Added
- Otwieranie PDF-ów dwukrotnym kliknięciem i folderów z menu kontekstowego.
- Wspólne potwierdzenie przed analizą dla obu zakładek.

## [1.1.1] — 2026-10-07

### Changed
- Uporządkowany interfejs, stałe kolory kategorii w edytorze i wynikach,
  osobne kafelki pomiarów trzech modeli oraz zwijana edycja promptu.
- Pasek postępu i czytelny pusty stan; zmiana kolejki usuwa poprzednie pomiary.
- Testowe PDF-y pozostają lokalne. Git ignoruje wszystkie wejściowe PDF-y,
  a CI i budowanie instalatora kontrolują brak dokumentów i plików `.env`.

## [1.1.0] — 2026-10-07

### Added
- Dwie osobne zakładki: sprawdzanie podpisów i kategoryzowanie dokumentów.
- Kategoryzowanie tekstu PDF do 2–12 własnych kategorii, z edytowalnymi opisami
  i promptem, zapisywanymi niezależnie od ustawień podpisów.
- Jev przez Venice, lokalny JevK5 i Gemma przez Ollamę; porównanie trzech modeli
  na identycznych wejściach, od 1 do 10 przejść, oddzielne czasy przygotowania i modeli.
- Wczytanie zestawu 100 PDF-ów z benchmarku, losowanie do 100 PDF-ów z folderu,
  własne pliki, anulowanie oraz eksport CSV/JSON bez tekstów źródłowych.
- Kontrola limitu API Venice z oczekiwaniem wliczonym w czas i anulowaniem przerwy.
- JevK5 w osobnym procesie istniejącego Pythona CUDA; pakiet GUI nie zawiera wag
  ani dodatkowej kopii bibliotek Torch.

## [1.0.10] — 2026-10-07

### Added
- Osobne przełączniki „Dodatkowa analiza” dla Ollamy i vjev-vision.
  Ollama może ograniczyć odpowiedź do obecności podpisu i pieczątki,
  bez generowania opisu dokumentu i współrzędnych.
- Eksperymentalna analiza dodatkowa Jev: 48 niezależnych kategorii,
  siatka 4 × 5, łączenie sąsiednich trafień i weryfikacja scalonych obszarów.
  Podstawowa reguła pięciu widoków i jej wynik pozostają bez zmian.
- CLI: `--additional-analysis` i `--no-additional-analysis`.
- Powtarzalny eksperyment lokalny zapisujący surowe odpowiedzi, czasy obliczeń
  i ładowania modeli oraz podglądy przybliżonych wycinków.

## [1.0.9] — 2026-10-07

### Fixed
- Nieprawidłowy schemat odpowiedzi AI powoduje ponowienie i ewentualny błąd,
  zamiast fałszywego wyniku „brak podpisu”.
- Skan PDF uwzględnia dziedziczenie typu pola podpisu; wycinki uwzględniają
  obrót strony i przesunięcie jej widocznego obszaru.
- Błędy i ograniczenia skanu struktury PDF docierają do wyniku i raportów.
- CLI zwraca kod błędu również przy niepowodzeniu pojedynczych dokumentów;
  sprawdzenie połączenia OpenAI odrzuca błędy usługi, w tym HTTP 503.
- Konfiguracja JSON o nieprawidłowym typie nie przerywa uruchamiania aplikacji.
- Test metadanych pomija lokalny katalog roboczy `scratch`.

### Changed
- Analiza renderuje strony PDF i klatki TIFF pojedynczo, zwalniając obrazy
  także po błędzie lub anulowaniu, zamiast przechowywać wszystkie strony w pamięci.
- Dodano testy regresji problemów wykrytych podczas audytu kodu.

## [1.0.4] — 2026-07-22

### Added
- Diagnostyka Ollamy w ustawieniach oraz asynchroniczny preflight usługi i modelu
  przed uruchomieniem każdej partii; instalator wyjaśnia, że Python jest wbudowany,
  a Ollama jest opcjonalnym, osobno instalowanym składnikiem.
- Jawne potwierdzenie ryzyka w CLI (`--acknowledge-risks`) i ostrzeżenie o
  poufności przed eksportem raportu.
- Audyt zależności w CI, przypięte wersje zależności i akcji oraz Dependabot.

### Security
- Zdalne endpointy wymagają HTTPS, przekierowania HTTP są wyłączone, a Ollama
  na pętli zwrotnej nie dziedziczy proxy z otoczenia procesu.
- Raporty nie zawierają pełnych ścieżek; komórki CSV są chronione przed formula
  injection, a raport HTML ma restrykcyjną politykę CSP.
- Limity rozmiaru pliku, liczby pikseli, stron i złożoności hierarchii pól PDF
  ograniczają ryzyko wyczerpania pamięci lub czasu przez złośliwy dokument.
- Konfiguracja jest walidowana i zapisywana atomowo; treści pochodzące z modelu
  i dokumentu są wyświetlane w GUI jako tekst jawny.

### Changed
- Metadane autora zastąpiono neutralnym `Signum contributors`; pozostawiono
  wyłącznie wskazany wyjątek wydawcy w instalatorze.
- Usunięto screenshoty zawierające lokalne ścieżki i rozszerzono reguły ignorowania
  sekretów, artefaktów instalatora oraz lokalnych ustawień narzędzi.

## [1.0.3] — 2026-07-22

### Added
- Instalator: osobny polsko- i anglojęzyczny ekran świadomości ryzyka z czterema
  wymaganymi potwierdzeniami; instalacja cicha wymaga `/ACKNOWLEDGERISKS=1`.
- GUI: jedno ostrzeżenie przed uruchomieniem całej partii dokumentów, obejmujące
  uprawnienia do przetwarzania, sposób pracy modelu i ręczną weryfikację wyników.

### Changed
- Raport HTML i okno „O programie" wyraźniej opisują ograniczenia wyniku oraz
  obowiązek niezależnej weryfikacji.

## [1.0.2] — 2026-07-20

### Fixed
- Ollama: znacząco lepszy recall detekcji — structured outputs (`format` =
  schemat JSON) potrafił tłumić znaleziska (model zamykał listę po pieczątce
  i gubił podpis odręczny obok niej). Pierwsze zapytanie idzie teraz bez
  wymuszania schematu; `format` jest używany tylko jako jednorazowe ponowienie,
  gdy odpowiedź nie zawiera poprawnego obiektu JSON. Zweryfikowane na
  dokumencie z pieczątką i podpisem (wcześniej wykrywana tylko pieczątka)
  oraz na przykładach z repo (bez nowych fałszywych pozytywów).

## [1.0.1] — 2026-07-17

### Added
- Raport HTML: obok wycinka każdego znaleziska miniatura całej strony
  z czerwoną ramką w miejscu wskazanym przez model — nawet niedokładna
  ramka pokazuje, gdzie na stronie model widzi podpis (miniatura powstaje
  także wtedy, gdy sam wycinek został odrzucony jako nieprawdopodobny).
- Ustawienia AI: sekcja „Prompt programu" — edytowalna część merytoryczna
  promptu (stały format odpowiedzi JSON program dokleja automatycznie),
  z przyciskiem „Przywróć domyślny".
- Ustawienia AI (Ollama): konfigurowalne okno kontekstu `num_ctx`
  (domyślnie 8192; Ollama sama z siebie używa zaledwie 4096).
- Ostrzeżenie przy przełączeniu dostawcy z lokalnego na chmurowy: modal
  „Dane opuszczą ten komputer" z przyciskiem „Rozumiem zagrożenie"
  odblokowywanym po 3 s; czerwone ostrzeżenie na stronach dostawców
  chmurowych; plakietka „Model online" w pasku stanu okna głównego.
- Większe opcje rozmiaru obrazu dla modelu (1600, 2048 px) — z adnotacją,
  że dla gemma4 Ollama i tak ogranicza obraz do ~0,65 Mpx (280 tokenów
  wizyjnych), więc większe rozmiary wykorzystają głównie modele chmurowe.

## [1.0.0] — 2026-07-13

### Added
- GUI (PySide6): drag & drop plików i folderów, kolejka, sekwencyjne przetwarzanie
  z paskiem postępu i ETA, anulowanie, tabela wyników + panel szczegółów
  z wycinkami podpisów (klik = powiększenie).
- Detekcja wizyjna (vision LLM): podpisy odręczne, parafki, pieczątki —
  z pewnością 0–100 i ramkami `box_2d` walidowanymi przed wycięciem.
- Detekcja strukturalna podpisów cyfrowych w PDF (pypdf): PAdES/CAdES,
  CMS/PKCS#7, X.509, znaczniki czasu RFC 3161, podpisy certyfikujące (DocMDP),
  podpisy praw użycia (UR3); wycinki widocznych widgetów podpisu; raportowanie
  pustych pól podpisu.
- Dostawcy AI: Ollama (structured outputs, lista modeli), API zgodne z OpenAI,
  Claude (Anthropic). Klucze API w Windows Credential Manager (keyring).
- Raporty: samowystarczalny HTML z osadzonymi wycinkami oraz CSV (`;`, BOM,
  CRLF — zgodny z polskim Excelem).
- Tryb `signum-cli` do automatyzacji (te same wyniki co GUI).
- Fabryka dokumentów testowych (w tym PDF-y naprawdę podpisane cyfrowo przez
  pyhanko) + 80 testów jednostkowych i GUI (pytest, pytest-qt), ruff, mypy.
- Instalator Windows (PyInstaller + Inno Setup 6, per-user, PL/EN).
