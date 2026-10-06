# Signum 1.0.8 — instalator i Ollama

Gotowy plik: `H:/podpisy/installer/output/Signum-Setup-1.0.8.exe`.
SHA-256: `B54AB5DADEE47C3AC194F24C45C3F9AF668C5455EFD237921A3683231DF4B08A`.

Aktualizacja tekstów instalatora: potwierdzenia dotyczą edukacyjnego charakteru,
braku zastosowania komercyjnego, dokumentów przykładowych bez danych osobowych
i wrażliwych oraz wysyłki treści przez internet do zewnętrznej usługi AI.
Długie etykiety zawijają tekst; kliknięcie etykiety przełącza pole wyboru.
Sześć istniejących testów instalatora przeszło, a kreator został ponownie skompilowany.

Okno przed analizą ma dwa wymagane potwierdzenia: edukacyjnego przeznaczenia
i nieprzydatności do użytku w organizacjach oraz przetwarzania treści dokumentów.
Przy usłudze zdalnej drugie pole informuje o przesyłaniu treści przez internet
do usług stron trzecich. Modele Ollamy z końcówką `cloud` także pokazują tę treść.
Usunięto wcześniejsze potwierdzenia uprawnień i zasad organizacji.
Etykiety zawijają się i można je kliknąć; przycisk anulowania ma polską nazwę.
32 testy GUI przeszły. Sprawdzono renderowanie trybu lokalnego, zdalnego,
lokalnego Jev i Ollamy cloud przy skalowaniu 100% oraz 150%, wraz z klikaniem
etykiet i blokadą uruchomienia do czasu obu potwierdzeń.

Panel wyników nie zawiera komentarzy o Jev, kalibracji ani braku wycinka.
Pozostawiono znaleziska, strony i pewność; przy wyniku negatywnym także ocenę
obecności podpisu. Usunięto objaśnienia działania modelu z danych znalezisk
i raportu HTML. Sprawdzono render panelu z podpisem (98%) i pieczątką (69%).

Wykrywanie GPU i wybór składników są na wspólnym ekranie. Model zalecany dla
8/16 GB jest oznaczony na liście. Wykryta Ollama nie ma aktywnego pola instalacji;
modele i Jev pokazują stan instalacji. Nie sprawdza się numeru wersji Ollamy.
Wyszukiwanie obejmuje konfigurację Signum, PATH, procesy, rejestr instalacji
i typowe katalogi oraz lokalną usługę API. Modele są sprawdzane przez API lub
manifesty i obecność plików wag; nieznany stan jest opisany jako niezweryfikowany.
Jev jest rozpoznawany po konfiguracji runtime i kompletności plików.
Wykryta, zatrzymana Ollama jest uruchamiana z istniejącej lokalizacji;
nie pobiera się drugiej kopii i nie zmienia jej katalogu modeli.

Na tej maszynie wykryto Ollamę, Gemma 4 12B i Jev. Osobna kontrola wyszukiwania
wykryła atrapę Ollamy z niestandardowej lokalizacji PATH, bez kontroli wersji.
221 testów przeszło, w tym ponowne użycie zatrzymanej Ollamy bez pobrań oraz
zachowanie istniejącego katalogu modeli. Ruff i mypy przeszły; przebudowana
aplikacja przeszła test `--self-test`, a instalator skompilował się poprawnie.
Log: `scratch/build-ux-components-final.log`; testy: `scratch/ux-components-tests.log`.

## Zmiany

- Instalator wyjaśnia wymagania lokalnego AI i udostępnia wybór składników:
  Ollama, Gemma 4 E2B dla 8 GB, Gemma 4 12B dla 16 GB i Jev dla NVIDIA 16 GB.
  DXGI odczytuje dedykowaną pamięć w 64 bitach, bez ograniczenia WMI do 4 GB.
  Rekomendacja nie zaznacza pobierania bez działania użytkownika.
- Wybrane składniki są przygotowywane w osobnym oknie z postępem, anulowaniem,
  ponowieniem, logiem i linkami do źródeł/licencji. Użytkownik wybiera katalog.
  Działająca Ollama zachowuje swój magazyn modeli. Przygotowany Jev jest
  wykorzystywany ponownie. Nowy Jev otrzymuje osobny Python oraz biblioteki CUDA.
  Udane sprawdzenie obrazu poprzedza zapis ustawień gotowego AI.
- Teksty ryzyka mają UTF-8 z BOM, aby natywne pole tekstowe zachowało polskie znaki.
- Ollama nie generuje rozumowania przy analizie podpisów. Instrukcja i kara za
  powtórzenia ograniczają zapętlenie na tej samej ramce. Puste, ucięte i niepełne
  odpowiedzi są ponawiane ze schematem; nie są przedstawiane jako brak podpisu.
  Po partii lokalny model Ollamy jest zwalniany z pamięci GPU.

## Sprawdzenia

218 testów przeszło; Ruff i mypy nie zgłosiły błędów. Zbudowany runtime przeszedł
test podstawowych zależności, a Inno Setup skompilował instalator 1.0.8.
Testy obejmują przygotowanie świeżego Jev z atrapami pobrań, sumy kontrolne,
brak ponownych pobrań zweryfikowanych plików, błąd dysku, anulowanie i zwalnianie GPU.

Na rzeczywistej RTX 5060 Ti odczytano 16051 MB VRAM. Sprawdzono przygotowanie
posiadanej Ollamy i Jev, bez nowych pobrań i bez zapisu konfiguracji użytkownika.
Okno przygotowania sprawdzono poprzez renderowanie Qt przy skalowaniu 150%.
Oficjalny pakiet Ollamy 0.35.1 udostępnia sumę SHA-256 w metadanych wydania.

W istniejącym poligonie znaleziono 12 wcześniejszych stron z błędem JSON Gemmy.
Po końcowej poprawce wszystkie 12 zwróciło poprawny wynik analizy. Na d010_p004
odtworzono wielokrotne powtarzanie tych samych współrzędnych aż do limitu tokenów;
po zmianie odpowiedź kończy się poprawnie. To kontrola działania parsera i transportu,
nie nowy pomiar jakości zliczania podpisów. Próba badawcza pozostaje zamknięta na 120 stronach.

Nie wykonano pełnego pobierania i instalacji na czystym komputerze ani próby na
fizycznej karcie 8 GB. Odczyt kontrolek natywnego kreatora działał, lecz przechwytywanie
obrazu i sterowanie jego oknem zawodziły; nie przeklikano całego kreatora.

Logi: `scratch/tests-1.0.8-final.log`, `scratch/build-1.0.8-final.log`,
`scratch/ollama-regressions-fixed.log`, `scratch/ollama-fix/`, `scratch/gpu-info.txt`.
