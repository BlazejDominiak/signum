# Poligon Jev / Gemma — obecność podpisów

Data: 2026-10-05. Sprzęt: RTX 5060 Ti 16 GB. Wszystkie dokumenty i inferencje lokalnie na H:.

Pierwotna próba: **50 podpisanych publicznych PDF-ów + 50 stron kontrolnych z 50 innych PDF-ów**. W każdym dokumencie oceniono jedną wybraną kompletną stronę. Etykiety pochodzą z oględzin Codex przed inferencją, nie z odpowiedzi Jev ani Gemmy. Nie weryfikowano autentyczności podpisów.

## Wynik końcowy: 120 stron, próg sukcesu 98%

Zgodnie z ustaleniem próba kończy się na 120 stronach: 60 z widocznym podpisem i 60 kontrolnych z innych PDF-ów. Nie dodawano dalszych dokumentów.

| Metoda | Poprawne / 120 | Trafność | Podpisy wykryte / 60 | Fałszywe alarmy / 60 |
|---|---:|---:|---:|---:|
| Jev — dwa widoki | 117/120 | 97.50% | 58/60 | 1/60 |
| Jev — pięć widoków | 120/120 | 100.00% | 60/60 | 0/60 |
| Gemma — binarna | 118/120 | 98.33% | 58/60 | 0/60 |

**Jev z pięcioma widokami spełnia ustalony próg sukcesu.** Wynik 120 stron obejmuje jednak 60 stron strojenia, 40 stron użytych do wyboru wariantu w analizie dodatkowej oraz 20 nowych stron potwierdzających. Nie należy przedstawiać całych 120 jako niezależnego testu generalizacji.

## Dokładniejszy kalkulator i dodatkowa próba: 20 nowych stron

Po pierwotnej ocenie porównano dodatkowo 39 wcześniej zdefiniowanych reguł, z progami dopasowanymi wyłącznie na 60 stronach do strojenia. Wariant pięciu widoków osiągnął 40/40 w pierwotnym teście, ale został wybrany po obejrzeniu tego wyniku. To **analiza eksploracyjna**, a nie niezależne potwierdzenie wybranego wariantu.

Następnie znaleziono i obejrzano 20 stron z 20 kolejnych PDF-ów: 10 podpisanych i 10 kontrolnych. Wydawcy i SHA256 nie pokrywają się z pierwotnymi 100. Parametry wariantu pięciu widoków zamrożono przed wyborem tej próby; etykiety zapisano przed inferencją. **Nie dostrajano parametrów po nowym teście**. Łącznie sprawdzono 60 podpisanych dokumentów i 60 stron kontrolnych z innych PDF-ów.

| Nowa próba | Poprawne | Pominięcia | Fałszywe alarmy | Błędy odpowiedzi | Mediana / strona |
|---|---:|---:|---:|---:|---:|
| Jev — dwa widoki | 19/20 | 1 | 0 | 0 | 0.893 s |
| Jev — pięć widoków | 20/20 | 0 | 0 | 0 | 2.221 s |
| Gemma — binarna | 20/20 | 0 | 0 | 0 | 0.973 s |

W tej nowej próbie dokładniejszy Jev dorównał Gemmie binarnej, lecz był około 2,3 razy wolniejszy. 20/20 to mała próba; nie dowodzi uniwersalnej przewagi ani statystycznej równoważności. Nie potwierdzono przewagi ceny API czy energii.

Reguła: dla całej strony i czterech nakładających się fragmentów po 60% oblicz `mean(handwritten, execution, pen_strokes, choice.present)`, a następnie `s = max(pięć średnich)`. Podpis, gdy `s ≥ 0.535`. W każdym zapytaniu pozostaje ten sam zamrożony zestaw 9 pytań. Pozostałe odpowiedzi służą audytowi. Średnia jest heurystyką, nie połączonym niezależnym prawdopodobieństwem.

Kalibracja wyłącznie na pierwotnych 60 stronach do strojenia: `p = sigmoid(-1.2752369584469005 + 4.525887113758848 × 4 × (s - 0.5))`. Brier w nowym teście wynosi 0.000602. Mała, zbilansowana próba nie potwierdza wiarygodności procentów na dowolnych nowych dokumentach.

[Kalkulator pięciu widoków](quality-calculator.html), `calculator_quality.py` do analizy własnego PDF-u, [20 dodatkowych źródeł](sources_confirmation.csv), [etykiety](labels_confirmation.json), [blokada protokołu](confirmation_protocol.json), [komplet wyników](confirmation_results.json). Podglądy i surowe logi: `H:/podpisy/scratch/jev50/fresh`. Wariant pięciu widoków poprawił obie błędne decyzje pierwotnej reguły Jev; wynik pierwszych 40 stron nadal pozostaje eksploracyjny dla tego wariantu.

### Każda strona nowej próby

| Źródło / strona | Oględziny | Jev 2 | Jev 5 | Gemma binarna |
|---|---|---|---|---|
| [n002_p001](https://bji.ac.in/image-uploads/019c6b1a-9e84-72f4-a86a-97a9d8bc1c58-MOU%20BJSOA%20&%20MS-IDPT_13022026.pdf) | podpis | podpis | podpis | podpis |
| [n003_p002](https://hr.sfsu.edu/sites/default/files/documents/APC-%20Out%20of%20State%20Employment%20%20Policy%20MOU%20%28Final%29%20-%20signed.pdf) | podpis | podpis | podpis | podpis |
| [n005_p011](https://hr.sfsu.edu/sites/default/files/documents/TeleworkSigned%20%20Agreement%20SFSU%20APC%20%28R04%29-%20signed.pdf) | podpis | brak | podpis | podpis |
| [n006_p001](https://hr.sfsu.edu/sites/default/files/documents/CSUEU%20-%20Out%20of%20State%20Employment%20MOU%2012-3-21%20-%20signed.pdf) | podpis | podpis | podpis | podpis |
| [n011_p005](https://nsarchive.gwu.edu/sites/default/files/documents/2700117/Document-37.pdf) | podpis | podpis | podpis | podpis |
| [n013_p009](https://iqac1.sgtuniversity.ac.in/assets/files/MoU/131.pdf) | podpis | podpis | podpis | podpis |
| [n015_p001](https://iqac1.sgtuniversity.ac.in/assets/files/MoU/238.pdf) | podpis | podpis | podpis | podpis |
| [n018_p001](https://bji.ac.in/image-uploads/019c602c-7457-732e-a89b-e9dea8e6b8e1-BJI%20with%20Nirmithi%20Kendra_Apr2025-1.pdf) | podpis | podpis | podpis | podpis |
| [n023_p005](https://bji.ac.in/image-uploads/01997a7b-6eaa-704a-ad9f-183edd0c5980-MOU_BJI%20and_TECHGENTSIA_25092025.pdf) | podpis | podpis | podpis | podpis |
| [n025_p025](https://kimskarad.in/documents/1046/236.pdf) | podpis | podpis | podpis | podpis |
| [n001_p001](https://bji.ac.in/image-uploads/019c6009-97c7-7063-819a-e103692cf515-CSE%20with%20PhiScape_Aug%202024-1.pdf) | brak | brak | brak | brak |
| [n007_p003](https://www.toronto.ca/wp-content/uploads/2025/07/95e7-CRCResidentialCollectiveAgreement.pdf) | brak | brak | brak | brak |
| [n008_p001](https://bip.aotm.gov.pl/assets/files/zamowienia_publiczne/zapytania_ofertowe/2026/9/projekt%20umowy%20na%20depozytory%20kluczy%202026_03_03.pdf) | brak | brak | brak | brak |
| [n009_p001](https://janikowo.com.pl/wiadomosci/80332/ogloszenie-konkursu-na-stanowisko-dyrektora-szkoly-podstawowej--.pdf) | brak | brak | brak | brak |
| [n010_p001](https://hr.sfsu.edu/sites/default/files/documents/SFSU--CSUEU%20Draft%20Telecommuting%20Agreement%20FINAL%20-%20signed.pdf) | brak | brak | brak | brak |
| [n012_p002](https://hr.sfsu.edu/sites/default/files/documents/HR2021-04.pdf) | brak | brak | brak | brak |
| [n014_p001](https://kalpataruprojects.com/api/view-file/Annual-Return-2021-22-MGT-7.pdf) | brak | brak | brak | brak |
| [n016_p013](https://www.disabilityrightsnc.org/wp-content/uploads/2022/03/work-report-v4-edited-FINAL.pdf) | brak | brak | brak | brak |
| [n017_p007](https://kcpolice.org/media/1888/ppbm-312-05.pdf) | brak | brak | brak | brak |
| [n024_p001](https://bsmedia.business-standard.com/_media/bs/data/announcements/bse/12022025/1b187647-1d08-4476-b71b-3b0751476dd6.pdf) | brak | brak | brak | brak |
## Oddzielny test: 40 stron

20 z podpisem, 20 bez. Wszystkie strony danego wydawcy pozostają w jednym zbiorze; 60 pozostałych stron służyło wyłącznie do wyboru reguły, progu i kalibracji.

| Metoda | Poprawne | Trafność | Pominięcia FN | Fałszywe alarmy FP | Błędy¹ | Mediana | Średnia |
|---|---:|---:|---:|---:|---:|---:|---:|
| Jev — dotychczasowy klient | 37/40 | 92.5% | 2 | 1 | 0 | 0.363 s | 0.364 s |
| Jev — zamrożony kalkulator | 38/40 | 95.0% | 1 | 1 | 0 | 0.911 s | 0.908 s |
| Gemma — dotychczasowy Signum | 33/40 | 82.5% | 1 | 0 | 6 | 14.855 s | 65.089 s |
| Gemma — tylko klasyfikacja | 38/40 | 95.0% | 2 | 0 | 0 | 0.956 s | 0.956 s |

¹ Błąd inferencji lub parsowania liczy się jako niepoprawna decyzja w trafności. FN/FP w tabeli dotyczą poprawnie odczytanych odpowiedzi i nie zawierają tych błędów. Nie usuwano trudnych przykładów po odpowiedziach modeli.

Gemma — dotychczasowy Signum: pokrycie poprawnymi odpowiedziami 34/40; trafność wśród tych odpowiedzi 97.1%. Brak odpowiedzi: 6 stron podpisanych i 0 kontrolnych.

Gemma — tylko klasyfikacja: pokrycie poprawnymi odpowiedziami 40/40; trafność wśród tych odpowiedzi 95.0%. Brak odpowiedzi: 0 stron podpisanych i 0 kontrolnych.

Przy traktowaniu stron jako niezależnych 95% przedział Wilsona dla trafności kalkulatora wynosi 83.5%–98.6%. Dokumenty od tego samego wydawcy mogą być podobne, więc ten prosty przedział może przeceniać precyzję.

Porównanie par z Gemma — dotychczasowy Signum: tylko Jev poprawny 7, tylko Gemma poprawna 2; dokładny dwustronny test McNemara p=0.1797. To opis małej próby, nie dowód równoważności ani uniwersalnej przewagi modelu.

Porównanie par z Gemma — tylko klasyfikacja: tylko Jev poprawny 2, tylko Gemma poprawna 2; dokładny dwustronny test McNemara p=1.0000. To opis małej próby, nie dowód równoważności ani uniwersalnej przewagi modelu.

## Całość: 100 stron (łącznie ze strojeniem)

| Metoda | Poprawne | Trafność | Pominięcia FN | Fałszywe alarmy FP | Błędy¹ | Mediana | Średnia |
|---|---:|---:|---:|---:|---:|---:|---:|
| Jev — dotychczasowy klient | 93/100 | 93.0% | 5 | 2 | 0 | 0.364 s | 0.364 s |
| Jev — zamrożony kalkulator | 98/100 | 98.0% | 1 | 1 | 0 | 0.911 s | 0.911 s |
| Gemma — dotychczasowy Signum | 87/100 | 87.0% | 1 | 0 | 12 | 14.454 s | 61.900 s |
| Gemma — tylko klasyfikacja | 98/100 | 98.0% | 2 | 0 | 0 | 0.957 s | 1.061 s |

Ten wynik obejmuje dane użyte do strojenia. Głównym wynikiem generalizacji jest osobny test powyżej.

## Co wygrało na zbiorze do strojenia

800 zapytań Jev, 8 wariantów obrazu/kontekstu dla każdej strony, 9 pytań na wariant. Trzy instrukcje kontekstu: domyślna angielska, krótka angielska, polska. Widoki: cała strona, dolne 55%, cztery nakładające się ćwiartki po 60% szerokości i wysokości. Fragmenty są stałe, niezależne od oględzin.

Porównano 39 heurystyk, każdą z progami 0,10–0,90 co 0,005. Kryterium: największa zbilansowana trafność, potem mniej fałszywych alarmów, mniej zapytań, próg bliżej 0,5 i porządek nazwy. Bez mnożenia skorelowanych prawdopodobieństw i bez założenia niezależności pytań.

Wybrano **max(choice.present całej strony, choice.present dolnych 55%) ≥ 0,455**. Dwa zapytania; 60/60 na zbiorze do strojenia. Regułę zamrożono przed oceną testu. W kalkulatorze zachowano identyczne 9 pytań, mimo że decyzja używa tylko pytania binarnego, aby zachować przebadany protokół.

## Prawdopodobieństwo

Surowy wynik s = max(p_cała, p_dół). Kalibracja logistyczna na 60 stronach do strojenia z regularyzacją 0,1:

`p = sigmoid(0.8835469095897316 + 4.074756987698717 × 4 × (s - 0.5))`

Decyzję wyznacza próg surowego wyniku, nie p=0,5. Kalibracja pochodzi z próby 50/50; przy innej częstości podpisów lub innym rodzaju skanów może być nadmiernie pewna. Nie należy traktować procentu jako potwierdzonej częstości poprawnych odpowiedzi dla nowych prywatnych dokumentów.

Brier na osobnym teście (mniej = lepiej): wcześniejsze surowe Jev 0.1110; kalibracja kalkulatora 0.0461.

## Dwa błędy zamrożonej reguły w teście

`d016_p001`: duży odręczny podpis w górnej części nagłówka pisma. Kalkulator otrzymał s=0,1029 i pominął podpis. Podgląd: [pełna strona](../../scratch/jev50/pages/d016_p001.jpg).

`d019_p001`: formularz z tekstową adnotacją o podpisie cyfrowym i bladym znakiem graficznym w tle tego pola, bez odręcznego podpisu. Kalkulator otrzymał s=0,5893 i zgłosił fałszywy alarm. Podgląd: [pełna strona](../../scratch/jev50/pages/d019_p001.jpg). Podpis kryptograficzny jest odrębną cechą dokumentu.

Te przykłady są częścią odłożonego testu; ocena reguły nadal wynosi 38/40. Diagnostyka błędów służy projektowaniu kolejnego eksperymentu, który potrzebowałby nowego niezależnego testu.

## Modele i uczciwość porównania

Jev: `yah01/vjev-vision@2fa8b58e40e5bc351a7d6dd39b953469a8f3ded2`, vjev-serve `37e2ffb2695b9bf278374fdefec24611c3b710c1`. Gemma: lokalne `gemma4:12b`, 11,9B, Q4_K_M, digest `4eb23ef187e2c5462566d6a1d3bbbc2f1346d0b4327cbb66d58fffbcc9b2b05c`.

Oba modele otrzymują identyczny JPEG kompletnej strony (150 DPI, maksymalny dłuższy bok 1120 px, jakość 85). Serwer Jev wewnętrznie redukuje obraz do 512 px. Kalkulator dodatkowo wysyła dolną część jako osobny obraz. SHA256 wejść sprawdza `build_report.py`. Modele działały kolejno na tym samym GPU.

Gemma Signum: temperatura 0, num_ctx 8192, dotychczasowy polski prompt opisujący dokument, podpisy, parafki, pieczątki i ich współrzędne; retry strukturalny tylko gdy pierwszy JSON jest niepoprawny. Gemma binarna: jedno pole boolean, ten sam zakres definicji podpisu, temperatura 0, num_ctx 8192, think=false, limit 64 tokenów, schemat JSON; jeden przebieg, bez strojenia promptu po ocenie.

Czasy to zmierzony czas żądań lokalnego klienta, bez pobierania, renderowania i startu serwera Jev. Dla Gemmy pierwsze żądanie może obejmować ładowanie modelu; surowy log je zachowuje. Mediana ogranicza wpływ zimnego startu i błędów. W trybie binarnym zapisano też czasy ładowania i generacji z API. Czasy Jev pochodzą z ciepłego przebiegu wariantów eksperymentalnych; suma obu wymaganych zapytań jest podana dla kalkulatora. To nie pomiar przepustowości wielu dokumentów ani kosztu energii. Nie mierzono cen chmurowych API.

Samo przyspieszenie wobec pełnej analizy Gemmy nie dowodzi przyspieszenia jednakowego zadania — dlatego pokazano również kontrolę binarną. Nie mierzono jakości współrzędnych Gemmy ani wycinków podpisów.

Dokumentacja protokołu: [Ollama /api/chat](https://docs.ollama.com/api/chat), [vjev-serve](https://github.com/BubbleCal/vjev-serve). Dokładne instrukcje użyte w próbie zapisano w `protocol.json` i `gemma_binary_protocol.json`.

## Dobór i ograniczenia

Przejrzano pulę 161 PDF-ów odnalezionych w wyszukiwarce i na stronach źródłowych, przetasowaną z ziarnem 20261005. Wybrano podpisane strony i kontrolki po oględzinach miniatur, powiększeń oraz kompletnych stron. To próba dogodna administracji/uczelni, nie reprezentatywna losowa próba internetu. Przypadek niejednoznaczny wykluczono przed inferencją. Korekty etykiet zapisano w manifeście.

Strona kontrolna bez podpisu nie oznacza, że cały wielostronicowy PDF jest niepodpisany. Nie oceniono całych PDF-ów ani trudnego rozróżniania podpisów od zwykłych notatek na reprezentatywnym zbiorze rękopisów. Ręczna adnotacja jest pojedynczym przeglądem Codex, bez drugiego niezależnego annotatora. Publiczne dokumenty mogły występować w danych treningowych modeli.

Najpierw parser eksperymentalny odczytywał błędny klucz `probs`, mimo że API zwracało `probabilities`. Wszystkie surowe odpowiedzi zostały zachowane; odtworzono wyniki z poprawnego klucza bez ponownej inferencji ani podmiany odpowiedzi. Usunięto z analizy wyłącznie ten dokładny błąd klienta; inne błędy liczą się jako błędne decyzje.

## Artefakty i uruchomienie

`calculator.html` — interaktywny przegląd wyników i kalkulator liczbowy. `calculator.py` — lokalna analiza nowego PDF/obrazu. `results.json` — komplet decyzji i surowe odpowiedzi porównań. `audit.json` — skróty wyników i surowych logów. `sources.csv` / `labels.json` — wszystkie źródła i etykiety. Dane PDF, podglądy i 800 surowych odpowiedzi Jev: `H:/podpisy/scratch/jev50`. Instrukcje w `README.md`. Domyślny klient GUI pozostaje osobną metodą bazową.

## Wyniki każdego dokumentu

| Strona / źródło | Zbiór | Oględziny | Jev wcześniej | Jev kalkulator | Gemma Signum | Gemma binarna |
|---|---|---|---|---|---|---|
| [d151_p006](https://www.epa.gov/system/files/documents/2023-04/EPA%20KLHK%20MOU%20English.pdf) | dev | podpis | jest | jest | jest | jest |
| [d068_p011](https://rcf-wb6.org/wp-content/uploads/2021/02/RCF-EoI-form-.pdf) | dev | brak | brak | brak | brak | brak |
| [d086_p007](https://www.epa.gov/system/files/documents/2023-12/2023-decentralized-mou-agreement.pdf) | dev | podpis | jest | jest | jest | jest |
| [d083_p001](https://bip.umb.edu.pl/pl/attachments/download/14228) | dev | brak | brak | brak | brak | brak |
| [d047_p001](https://bip.powiatrypinski.pl/download/attachment/10263/1zarzadzenie-52-2025-regulamin-zamowien-ponizej-170-tys-31-12-2025.pdf?v=1767949503) | test | brak | brak | brak | brak | brak |
| [d074_p005](https://wns.ug.edu.pl/sites/wns.ug.edu.pl/files/_nodes/strona/114461/files/zarzadzenie-05-2023_1.pdf) | dev | brak | brak | brak | brak | brak |
| [d071_p002](https://arpc.gov.au/wp-content/uploads/2026/03/Senate-Continuing-Order-no12-for-period-1Jan-to-30Jun2025-To-Treasury.pdf) | dev | brak | brak | brak | brak | brak |
| [d024_p002](https://bip.gogolin.pl/download/attachment/99396/zarzadzenie-burmistrza-gogolina-nr-ori0050412017-w-sprawie-zmiany-regulaminu-organizacyjnego-urzedu-miejskiego-w-gogolinie.pdf?v=1602661639) | test | brak | brak | brak | brak | brak |
| [d041_p001](https://bip.strzeleczki.pl/download/attachment/45821/nr-rm00503622026-z-17072026-r-w-sprawie-zmiany-zarzadzenia-nr-rm00503462026-burmistrza-strzeleczek-z-dnia-30-czerwca-2026-r-powolania-komisji-rekrutacyjnej.pdf?v=1785841424) | dev | brak | jest | brak | brak | brak |
| [d017_p008](https://www.abhi.org.uk/media/2768/diagnostics-a-future-roadmap.pdf) | test | brak | brak | brak | brak | brak |
| [d036_p005](https://www.epa.gov/system/files/documents/2022-08/2011%20Signed%20Agreement.pdf) | dev | podpis | jest | jest | błąd odpowiedzi | jest |
| [d016_p001](https://www.energy.gov/sites/default/files/2016/04/f30/Final-HRP-Memo-712-Clarifications-Under-the-Existing-Rule-Signed-8-20-13.pdf) | test | podpis | brak | brak | jest | jest |
| [d159_p001](https://bip.strzeleczki.pl/download/attachment/46337/nr-rm00503812026-z-07092026-r-w-sprawie-powolania-komisji-rekrutacyjnej-skan.pdf?v=1790244787) | dev | podpis | jest | jest | jest | jest |
| [d149_p008](https://www.epa.gov/system/files/documents/2025-11/npdes-erule-mou-il_0.pdf) | dev | podpis | jest | jest | jest | jest |
| [d028_p014](https://19january2021snapshot.epa.gov/sites/static/files/2020-03/documents/adi-ais_-pia-npp_final-2020_0.pdf) | dev | brak | brak | brak | brak | brak |
| [d056_p001](https://lomza-api.bip.net.pl/api/attachments/7883) | test | brak | brak | brak | brak | brak |
| [d084_p022](https://www.uis.edu/sites/default/files/2025-11/NTT-UIS%202024-2027%20Agreement%20Updated.pdf) | test | podpis | jest | jest | jest | jest |
| [d077_p001](https://bip.lesnica.pl/download/attachment/28764/zarzadzenie-nr-00504232026-burmistrza-lesnicy-z-dnia-13-sierpnia-2026-r-zmieniajace-zarzadzenie-w-sprawie-powolania-komisji-przetargowej-skan.pdf?v=1787122031) | dev | podpis | jest | jest | jest | jest |
| [d080_p008](https://www.epa.gov/system/files/documents/2025-05/npdes-erule-mou-nj.pdf) | dev | podpis | jest | jest | jest | jest |
| [d018_p006](https://bip.lesnica.pl/download/attachment/27791/zarzadzenie-nr-00503412026-burmistrza-lesnicy-z-dnia-4-lutego-2026-r-w-sprawie-ogloszenia-naboru-uzupelniajacego-na-czlonka-komitetu-rewitalizacji-skan.pdf?v=1770286831) | dev | brak | brak | brak | brak | brak |
| [d043_p005](https://www.epa.gov/system/files/documents/2022-08/Flanders%20-%208.23.22.pdf) | dev | podpis | jest | jest | jest | jest |
| [d048_p001](https://bip.pans.krosno.pl/attachments/3438/download) | test | brak | brak | brak | brak | brak |
| [d087_p001](https://bip.pans.krosno.pl/attachments/3835/download) | test | podpis | jest | jest | jest | jest |
| [d104_p001](https://bip.lesnica.pl/download/attachment/28934/zarzadzenie-nr-00504422026-burmistrza-lesnicy-z-dnia-22-wrzesnia-2026-r-w-sprawie-powolania-komisji-przetargowej-skan.pdf?v=1790075976) | dev | podpis | brak | jest | jest | jest |
| [d010_p004](https://www.epa.gov/system/files/documents/2022-08/2005%20Signed%20Agreement.pdf) | dev | podpis | jest | jest | błąd odpowiedzi | jest |
| [d097_p009](https://www.epa.gov/system/files/documents/2023-11/npdes-erule-mou-ct.pdf) | dev | podpis | jest | jest | jest | jest |
| [d009_p001](https://edit.doi.gov/sites/default/files/elips/documents/personnel-bulletin-20-04-standard-position-description-it-specialist-customer-supportmemo-and-pb-signed-4.15.2020-v3.pdf) | test | brak | brak | brak | brak | brak |
| [d012_p009](https://www.gov.scot/binaries/content/documents/govscot/publications/foi-eir-release/2018/03/foi-18-00534/documents/e-mails-pdf/e-mails-pdf/govscot%3Adocument/E-mails.pdf) | dev | brak | brak | brak | brak | brak |
| [d023_p001](https://bip.strzeleczki.pl/download/attachment/46375/nr-rm00503892026-z-25092026-r-w-sprawie-ustalenia-oplat-za-wynajem-sali-biesiadnej-w-raclawiczkach-skan.pdf?v=1790587458) | dev | podpis | jest | jest | jest | jest |
| [d050_p007](https://repository.library.noaa.gov/view/noaa/13334/noaa_13334_DS1.pdf) | test | podpis | jest | jest | jest | jest |
| [d027_p002](https://www.london.gov.uk/sites/default/files/the_prime_minister_0.pdf) | test | podpis | jest | jest | jest | jest |
| [d073_p016](https://lomza-api.bip.net.pl/api/attachments/7884) | test | brak | brak | brak | brak | brak |
| [d025_p026](https://wimim.zut.edu.pl/fileadmin/pliki/users/246/wydzial-jakosc/sprawozdania/WIMiM_sprawozdanie_WSZJK_2021_2022.pdf) | dev | brak | brak | brak | brak | brak |
| [d039_p001](https://lomza-api.bip.net.pl/api/attachments/6984) | test | brak | brak | brak | brak | brak |
| [d122_p002](https://www.london.gov.uk/sites/default/files/business_letter_to_the_prime_minister.pdf) | test | podpis | jest | jest | jest | jest |
| [d109_p006](https://www.epa.gov/sites/default/files/2016-09/documents/final_mou.pdf) | dev | podpis | jest | jest | jest | jest |
| [d103_p006](https://www.epa.gov/sites/default/files/2017-11/documents/2017_decentralized_mou_agreement_app_a_final.pdf) | dev | podpis | jest | jest | jest | jest |
| [d019_p001](https://www.doi.gov/sites/default/files/elips/documents/512-dm-4-5-ts.pdf) | test | brak | brak | jest | brak | brak |
| [d128_p001](https://bip.powiatrypinski.pl/download/attachment/10260/1zarzadzenie-52-2025-scan.pdf?v=1767949503) | test | podpis | jest | jest | jest | jest |
| [d130_p003](https://repository.library.noaa.gov/view/noaa/13384/noaa_13384_DS1.pdf) | test | podpis | jest | jest | błąd odpowiedzi | jest |
| [d143_p001](https://bip.strzeleczki.pl/download/attachment/43677/nr-rm00502922026-z-16022026-r-w-sprawie-ustalenia-stawki-czynszu-za-lokal-uzytkowy-polozony-w-zielinie-przy-ul-prudnickiej-6-skan.pdf?v=1771411754) | dev | podpis | jest | jest | jest | jest |
| [d021_p005](https://bip-v1-files.idcom-jst.pl/sites/3137/wiadomosci/699926/files/zarzadzenie_nr_140.pdf) | dev | brak | brak | brak | brak | brak |
| [d011_p001](https://lomza-api.bip.net.pl/api/attachments/6985) | test | brak | brak | brak | brak | brak |
| [d006_p007](https://bip.powiatrypinski.pl/download/attachment/10266/1aregulamin-do-zarzadzenia-52-2025-skan.pdf?v=1767949504) | test | podpis | jest | jest | jest | brak |
| [d126_p008](https://www.epa.gov/system/files/documents/2022-03/npdes-erule-mou-vi.pdf) | dev | podpis | brak | jest | jest | jest |
| [d051_p002](https://www.epa.gov/system/files/documents/2022-02/updated-wa_epa-ec_feb-2-2022-final.pdf) | dev | brak | brak | brak | brak | brak |
| [d058_p006](https://www.epa.gov/system/files/documents/2022-07/npdes-erule-mou-r07.pdf) | dev | brak | brak | brak | brak | brak |
| [d007_p006](https://hau.ac.in/storage/app/uploads/Qw3MLhT650UkCkd58ymo9Z90LSA9g6F6Owrc3sAa.pdf) | test | podpis | jest | jest | jest | jest |
| [d042_p001](https://assets.publishing.service.gov.uk/media/5e56856986650c53b2cefbb4/iicsa-response-letter-to-alexis-jay-obe.pdf) | dev | podpis | jest | jest | błąd odpowiedzi | jest |
| [d040_p009](https://www.doi.gov/sites/default/files/signed-mou-with-department-of-labor-on-gji.pdf) | test | podpis | jest | jest | błąd odpowiedzi | jest |
| [d082_p003](https://bip.strzeleczki.pl/download/attachment/45290/nr-rm00503412026-z-25062026-r-w-sprawie-zmian-planow-finansowych-jednostek-organizacyjnych-gminy-strzeleczki-na-2026-r-do-uchwaly-nr-xxxiv-203-26-skan.pdf?v=1783068648) | dev | podpis | jest | jest | jest | jest |
| [d032_p007](https://www.epa.gov/system/files/documents/2022-05/npdes-erule-mou-r09.pdf) | dev | brak | brak | brak | brak | brak |
| [d059_p003](https://www.epa.gov/system/files/documents/2024-08/castnet-factsheet-2024_final_0.pdf) | dev | brak | brak | brak | brak | brak |
| [d002_p011](https://bip.ug.edu.pl/sites/default/files/nodes/akty_normatywne/109928/files/zalacznik_nr_7.pdf) | dev | brak | brak | brak | brak | brak |
| [d063_p010](https://www.gov.pl/attachment/2ae6040c-b61a-48b4-86e3-35c5e7c0e7ad) | dev | brak | brak | brak | brak | brak |
| [d022_p005](https://www.epa.gov/system/files/documents/2023-11/mou_us-epa_and_peru_oefa_english.pdf) | dev | podpis | jest | jest | jest | jest |
| [d029_p010](https://bip.ideis.pl/attachments/1264/download) | test | brak | brak | brak | brak | brak |
| [d100_p001](https://bip.bialystok.pl/resource/104820/Zarz%25C4%2585dzenie+466+%2528skan%2529.pdf) | dev | podpis | jest | jest | jest | jest |
| [d072_p002](https://arpc.gov.au/wp-content/uploads/2024/03/Senate-Continuing-Order-no.-12-for-period-1-Jul-to-31-Dec-2023_To-Publish.pdf) | dev | brak | brak | brak | brak | brak |
| [d070_p001](https://bip.pans.krosno.pl/attachments/4611/download) | test | brak | jest | brak | brak | brak |
| [d057_p001](https://bip.bialystok.pl/akty_prawne/zarzadzenia_prezydenta/zarzadzenia-prezydenta-20242029/zarzadzenie-nr-88524.html?format=pdf&pagespeed=noscript) | dev | brak | brak | brak | brak | brak |
| [d044_p007](https://www.monitor.uw.edu.pl/Lists/Uchway/Attachments/4220/M.2017.256.Zarz.66.pdf) | test | brak | brak | brak | brak | brak |
| [d001_p009](https://www.epa.gov/system/files/documents/2022-06/npdes-erule-mou-me.pdf) | dev | podpis | jest | jest | błąd odpowiedzi | jest |
| [d052_p001](https://lomza-api.bip.net.pl/api/attachments/6983) | test | brak | brak | brak | brak | brak |
| [d026_p001](https://www.epa.gov/system/files/documents/2022-02/application-form-4.pdf) | dev | brak | brak | brak | brak | brak |
| [d123_p005](https://www.epa.gov/system/files/documents/2023-11/usepaxdenr-mou-14nov2023.pdf) | dev | podpis | jest | jest | jest | jest |
| [d108_p024](https://manuu.edu.in/sites/default/files/2022-06/annexure-14-MoUs.pdf) | dev | podpis | jest | jest | jest | jest |
| [d069_p002](https://bip.powiatrypinski.pl/download/attachment/10272/1bzalacznik-nr-1-do-regulamninu-ponizej-170-tys-12-2025-skan.pdf?v=1767949505) | test | podpis | jest | jest | brak | brak |
| [d090_p008](https://www.epa.gov/system/files/documents/2025-11/npdes-erule-mou-ga.pdf) | dev | podpis | jest | jest | jest | jest |
| [d015_p009](https://repository.library.noaa.gov/view/noaa/11884/noaa_11884_DS1.pdf) | test | podpis | jest | jest | jest | jest |
| [d049_p012](https://wfp.uniwersytetradom.pl/wp-content/uploads/sites/21/2022/11/5_2020_Dziekana-WFP_Procedura-przeprowadzenia-zdalnego-egzaminudyplomowego.pdf) | dev | brak | brak | brak | brak | brak |
| [d045_p008](https://apps.fas.usda.gov/newgainapi/api/Report/DownloadReportByFileName?fileName=April+Rice+Update_Hanoi_Vietnam_04-18-2002.pdf) | dev | brak | brak | brak | brak | brak |
| [d065_p016](https://repository.library.noaa.gov/view/noaa/11902/noaa_11902_DS1.pdf) | test | brak | brak | brak | brak | brak |
| [d054_p004](https://www.doi.gov/sites/default/files/doi-pathways-mou-fy23-signed.pdf) | test | brak | brak | brak | brak | brak |
| [d081_p001](https://assets.publishing.service.gov.uk/media/5e56861186650c53b8b5d929/ministerial-letter-iicsa.pdf) | dev | brak | brak | brak | brak | brak |
| [d157_p006](https://bip.gogolin.pl/download/attachment/99401/zarzadzenie-burmistrza-gogolina-nr-ori00501562018-w-sprawie-zmiany-regulaminu-organizacyjnego-urzedu-miejskiego-w-gogolinie-skan.pdf?v=1602663935) | test | podpis | brak | jest | jest | jest |
| [d079_p001](https://bip.bialystok.pl/akty_prawne/zarzadzenia_prezydenta/zarzadzenia-prezydenta-20242029/zarzadzenie-nr-4226.html?format=pdf&pagespeed=noscript) | dev | brak | brak | brak | brak | brak |
| [d152_p003](https://www.uach.cl/uach/_file/an_usa_26-642339375f9e9.pdf) | dev | podpis | jest | jest | jest | jest |
| [d078_p007](https://www.gov.pl/attachment/85c04970-5ca5-4998-81f1-cf901ff238a5) | dev | brak | brak | brak | brak | brak |
| [d003_p007](https://www.epa.gov/sites/default/files/2021-03/documents/npdes-erule-mou-id.pdf) | dev | podpis | jest | jest | błąd odpowiedzi | jest |
| [d098_p005](https://www.epa.gov/sites/production/files/2014-04/documents/indonesia-mou-eng.pdf) | dev | podpis | jest | jest | jest | jest |
| [d160_p005](https://pu.edu.pk/del/MOU/18-Int.pdf) | test | podpis | jest | jest | jest | jest |
| [d046_p001](https://bip.bialystok.pl/akty_prawne/zarzadzenia_prezydenta/zarzadzenia-prezydenta-20242029/zarzadzenie-nr-10826.html?format=pdf&pagespeed=noscript) | dev | brak | brak | brak | brak | brak |
| [d008_p004](https://bip.ug.edu.pl/sites/default/files/nodes/akty_normatywne/109928/files/zalacznik_nr_8.pdf) | dev | brak | brak | brak | brak | brak |
| [d055_p001](https://bip.lesnica.pl/download/attachment/27794/zal-3-regulamin-losowania.pdf?v=1770286832) | dev | brak | brak | brak | brak | brak |
| [d014_p023](https://assets.publishing.service.gov.uk/media/5e56675d86650c53a184c0d5/govt-response-iicsa-recommendation-17.pdf) | dev | brak | brak | brak | brak | brak |
| [d064_p007](https://www.monitor.uw.edu.pl/Lists/Uchway/Attachments/2207/M.2015.22.Zarz.8.pdf) | test | brak | brak | brak | brak | brak |
| [d033_p005](https://bip.gogolin.pl/download/attachment/125678/62-zarzadzenie-burmistrza-gogolina-nr-or0050622025-z-dnia-31-marca-2025-r-sprawie-zmiany-regulaminu-organizacyjnego-urzedu-miejskiego-w-gogolinie.pdf?v=1744279509) | test | brak | brak | brak | brak | brak |
| [d120_p001](https://lomza-api.bip.net.pl/api/attachments/6981) | test | podpis | jest | jest | błąd odpowiedzi | jest |
| [d037_p003](https://bip.amuz.wroc.pl/download/attachment/2243/zarzadzenie-nr-46-2020-rektora-akademii-muzycznej-im-karola-lipinskiego-we-wroclawiu-z-dnia-14-pazdziernika-2020-w-sprawie-wdrozenia-zdalnego-trybu-prowadzenia-zajec-dydaktycznych-oraz-okreslenia-zasad-prowadzenia-zajec-dydaktycznych-w-trybie.pdf?v=1602774050) | test | podpis | jest | jest | jest | jest |
| [d030_p001](https://www.bip.bialystok.pl/resource/106568/zarz%25C4%2585dzenie+Nr+743+%2528skan%2529.pdf) | dev | podpis | brak | jest | jest | jest |
| [d005_p001](https://bip.lesnica.pl/download/attachment/28582/zarzadzenie-nr-00504032026-skan.pdf?v=1782291426) | dev | podpis | jest | jest | jest | jest |
| [d031_p026](https://bip.gogolin.pl/download/attachment/123218/143-zarzadzenie-nr-ori00501432024-z-dnia-1-lipca-2024-r-w-sprawie-regulaminu-organizacyjnego-urzedu-miejskiego-w-gogolinie.pdf?v=1728036541) | test | brak | brak | brak | brak | brak |
| [d038_p002](https://bip.powiatrypinski.pl/download/attachment/10278/1bzalacznik-nr-2-do-regulamninu-ponizej-170-tys-12-2025.pdf?v=1767949505) | test | brak | brak | brak | brak | brak |
| [d035_p004](https://repository.library.noaa.gov/view/noaa/11925/noaa_11925_DS1.pdf) | test | podpis | jest | jest | błąd odpowiedzi | jest |
| [d062_p006](https://www.epa.gov/sites/default/files/2020-09/documents/2020_mou_agreement.pdf) | dev | podpis | jest | jest | błąd odpowiedzi | jest |
| [d004_p002](https://bip.ug.edu.pl/sites/default/files/nodes/akty_normatywne/109928/files/zalacznik_nr_2.pdf) | dev | brak | brak | brak | brak | brak |
| [d121_p001](https://bip.pans.krosno.pl/attachments/4610/download) | test | podpis | jest | jest | błąd odpowiedzi | jest |
| [d034_p006](https://wiskitki.pl/wp-content/uploads/2022/09/Zarzadzenie-Nr-97-Burmistrza-Miasta-i-Gminy-Wiskitki-z-dn.-19.09.2022r.-konsultacje-proj.-uchwal-zm.-Statutow-Solectw.pdf) | dev | brak | brak | brak | brak | brak |
| [d116_p008](https://repository.library.noaa.gov/view/noaa/13354/noaa_13354_DS1.pdf) | test | podpis | jest | jest | błąd odpowiedzi | jest |
