# Postęp prac

Legenda: ✅ zrobione · 🟡 w toku / częściowo · ⏳ zaplanowane · ⛔ wymaga decyzji

## Środowisko (sprawdzone 2026-10-09)

| Element | Wynik |
|---|---|
| System | Windows 10 Home 10.0.19045 |
| Python / Node / npm / git | 3.14.3 / 24.14.1 / 11.11.0 / 2.56 |
| HOI4 | Steam, `C:\NIBY DYSK\Steam\steamapps\common\Hearts of Iron IV` |
| Wersja gry | `Operation Postern v1.19.3.0.c01a (5632)` (`launcher-settings.json`), build `c01a3d507` (`logs/code_revisions.log`) |
| Dane użytkownika | `%USERPROFILE%\Documents\Paradox Interactive\Hearts of Iron IV` |
| Uwagi | `zalozenia.md` był pusty (0 bajtów) i został usunięty; praca wg `prompt.md` (usunięty z katalogu, dostępny w historii git) |

## Etapy

| Etap | Zakres | Status |
|---|---|---|
| 1 | Aplikacja desktopowa, UI (9 zakładek), logi, testy, dokumentacja | ✅ |
| 2 | Wykrywanie procesu HOI4 i wersji gry | ✅ |
| 3 | Wiarygodny odczyt danych z aktywnej rozgrywki | 🟡 zapisy ✅; **PP z pamięci procesu ✅ (tylko odczyt, po kalibracji)**; pozostałe pola z pamięci ❌ |
| 4 | Prototyp modyfikacji pojedynczej wartości (SP) + weryfikacja | 🟡 PP +10 zweryfikowane w grze (komenda diagnostyczna + odczyt zapisu); brak docelowej metody edycji |
| 5 | Edytory państw, stanów, sprzętu | ⏳ |
| 6 | Cele narodowe, narzędzia debugowania | ⏳ |
| 7 | Testy synchronizacji MP (w tym inicjowanie przez nie-hosta) | ⏳ |
| 8 | Poprawki, raport kompatybilności, instrukcja użytkownika | ⏳ |

---

## Etap 1 – szkielet aplikacji ✅

**Zrobione**
- Backend Python (tylko stdlib): lokalne API JSON na `127.0.0.1` z tokenem, routing, obsługa błędów.
- Warstwa integracji z grą jako osobny pakiet (`integration/`) z interfejsem `GameIntegration`;
  w etapie 1 tylko `NullIntegration`.
- Dane DEMO dla wszystkich obszarów; każda odpowiedź ma `source` (`live`/`demo`/`unavailable`),
  UI pokazuje plakietki i banery DEMO.
- Electron 44.4.5: sandbox, CSP, `contextIsolation`, renderer bez Node, własny protokół `app://`,
  most IPC z walidacją ścieżek; backend uruchamiany i zamykany przez Electron.
- 9 zakładek: Dashboard, Countries & Players, Country Editor, State Editor, National Focus Manager,
  Equipment Manager, Game Tools, Intelligence Lab, Logs & Test Reports.
- Responsywność: pełny sidebar → pasek ikon (<1000 px) → górna nawigacja i tabele jako karty (<640 px).
  Tryb kompaktowy i „zawsze na wierzchu” do pracy obok gry.
- Log aplikacji (plik rotowany + podgląd na żywo w UI, błędy renderera trafiają do logu).
- Raporty testerów (JSON + Markdown) z automatycznie dołączonym środowiskiem (wersja aplikacji, wykrycie gry).
- Edycja wszędzie wyłączona; brak jakiegokolwiek zapisu do gry.

**Testy (2026-10-09)**
- `npm run test:py` – 22 testy, OK
- `npm run test:js` – 14 testów, OK (w tym start prawdziwego backendu przez `startBackend`)
- `HOI4DBG_NO_GAME=1 npm run smoke` – 18/18 widoków (9 zakładek × 2 rozmiary okna), 0 błędów konsoli,
  brak poziomego przewijania

---

## Etap 2 – wykrywanie procesu i wersji ✅

**Zrobione** (wszystko tylko do odczytu, bez dostępu do pamięci gry)
- `integration/winproc.py`: lista procesów i metadane przez WinAPI (`CreateToolhelp32Snapshot`,
  `QueryFullProcessImageNameW`, `GetProcessTimes`), uprawnienie `PROCESS_QUERY_LIMITED_INFORMATION` – bez `PROCESS_VM_READ`.
- `integration/install.py`: Steam z rejestru → `libraryfolders.vdf` (nowy i stary format) → `appmanifest_394360.acf`
  (build id) → katalog gry; wersja z `launcher-settings.json`; hash buildu z `hoi4_rev.txt`.
- `integration/userdata.py`: folder użytkownika z `gameDataPath` (+ `SHGetKnownFolderPath` dla przekierowanych Dokumentów),
  ostatni zapis z `continue_game.json`, bezpieczny podgląd końcówki logów gry (walidacja nazw, limit 2 MB).
- `integration/session.py`: wskazówki z `game.log` (typ uruchomienia, data startu, ostatnia zalogowana data gry).
- `integration/hoi4.py` (`Hoi4Integration`): łączy powyższe; katalog gry preferencyjnie ze ścieżki **działającego** procesu;
  kontrola spójności: hash buildu z instalacji vs `code_revisions.log` bieżącego uruchomienia; logi starsze niż proces
  są ignorowane; ostrzeżenia (wiele procesów, brak dostępu, gra spoza biblioteki Steam itd.) trafiają do UI.
- UI: Dashboard pokazuje proces, wersję, sprawdzenie buildu, Steam build id, ścieżki, ostrzeżenia; zakładka Logs
  pokazuje logi gry (tylko odczyt); Game Tools: „Re-detect” i „Open HOI4 logs folder”.

**Test na prawdziwej grze (2026-10-09, HOI4 uruchomione, sesja SP)**
- Wykryto `hoi4.exe` PID 15144, start 09:47:31, ścieżka `C:\NIBY DYSK\Steam\steamapps\common\Hearts of Iron IV\hoi4.exe`.
- Wersja `Operation Postern v1.19.3.0.c01a (5632)`, raw `1.19.3.0`, build `c01a3d507` (instalacja = działający build),
  Steam build id `25205862`.
- Sesja z `game.log`: SINGLEPLAYER, start 1936.1.1.12. Ostatni wpis 09:48:16 mimo ok. 3 h gry, co potwierdza,
  że `game.log` nie nadaje się do danych na żywo.
- Czas detekcji: ~12 ms (pierwsza), ~6 ms (kolejne, cache instalacji 30 s).

**Testy (2026-10-09)**
- `npm run test:py` – 48 testów, OK (w tym fikstury o kształcie prawdziwych plików 1.19.3 oraz test prawdziwego WinAPI)
- `npm run test:js` – 14 testów, OK
- `npm run smoke` (z wykrywaniem gry) – 18/18 widoków, 0 błędów konsoli

---

## Etap 3 (część 1) – odczyt zapisów, metoda A 🟡

Decyzja użytkownika (prompt2.md, 2026-10-09): metoda A jako pierwszy krok docelowego debuggera; bez zapisu do pamięci
i bez modyfikacji save'ów.

**Badanie formatu** (szczegóły i dowody: [SAVE-FORMAT.md](SAVE-FORMAT.md))
- Wszystkie 158 zapisów na maszynie to `HOI4bin`: binarny strumień 16-bitowych tokenów. Struktura została zweryfikowana
  pełną walidacją gramatyki na 11 plikach z wersji 1.16.10–1.19.3.
- Ustalono, że token `0x000d` ma 4 B w 1.16.x i 8 B od 1.17.0. Parser wybiera wariant po walidacji całego pliku.
- Znaczenie 7 pól nagłówka potwierdzono krzyżowo:
  - tag = nazwa pliku 121/121;
  - data = nazwa pliku 121/121;
  - mody = zainstalowane mody 14/14.
- Ideologia i poziom trudności są oznaczone jako „inferred”.
- Dodatkowa biblioteka nie jest potrzebna (stdlib `struct`). Brakuje mapy nazw pól, a nie parsera.

**Zrobione**
- `backend/hoi4dbg/saves/`:
  - `binary.py`: lekser, walidator gramatyki, wybór szerokości, parser nagłówka z limitem rozmiaru;
  - `fields.py`: tabela znaczeń pól z dowodami, dekodowanie daty;
  - `reader.py`: lista zapisów, bezpieczna kopia do cache (wykrywanie pliku w trakcie zapisu), analiza nagłówka,
    walidacja w tle, cache wyników.
- Obsługa błędów z kodami: `empty`, `unknown_format`, `compressed`, `text_unsupported`, `truncated`, `corrupt`,
  `unsupported`, `in_progress`, `io_error`. Uszkodzone ciało pliku daje nagłówek z ostrzeżeniem `corrupt`.
- Aktualność: nowe źródło `save` (plakietka SAVE) i kategorie `current_session` / `previous_session` / `game_not_running`
  (`is_live` zawsze `false`). Do tego kontrola zgodności wersji zapisu z uruchomioną grą i flaga „nie najnowszy zapis”.
- API: `GET /api/saves`, `GET /api/saves/analysis?name=`, `GET /api/saves/fields`.
- UI (9 zakładek zachowanych):
  - Countries & Players: panel „Players (from save file)” z wyborem zapisu, bannerem źródła, daty i aktualności,
    graczami, nagłówkiem i modami; lista państw nadal DEMO, w osobnej, wyraźnie oznaczonej karcie;
  - Dashboard: karta „Newest save file”;
  - Game Tools: „Save inspector”.
- Raport: [REPORT-LIVE-AND-WRITE.md](REPORT-LIVE-AND-WRITE.md) opisuje drogę od zapisu do odczytu na żywo i bezpiecznej
  modyfikacji, na podstawie dokumentacji komend i efektów dostarczanej z grą.

**Weryfikacja na prawdziwych danych (kopie)**
- Najnowszy zapis `autosave.hoi4` (1.19.3, 54,6 MB):
  - GER, 1937.3.1.2, gracz „Czarny”, 14 modów, struktura poprawna;
  - UI oznacza go na czerwono jako „From an EARLIER session – NOT the current game state” (zapis z 3.10, gra uruchomiona 9.10).
- Zapis MP `AUS_1943_02_01_01.hoi4` (1.16.10): 31 graczy, szerokość 4, flaga niezgodności wersji.
- SHA-1 i mtime oryginałów bez zmian po analizie.

**Testy (2026-10-09)**
- `npm run test:py`: 74 testy, OK. W tym 26 nowych dla zapisów:
  - syntetyczne zapisy o strukturze prawdziwych;
  - pliki uszkodzone, ucięte, puste, zip i tekstowe;
  - path traversal i kategorie aktualności;
  - test na kopii najnowszego prawdziwego zapisu z kontrolą niezmienności oryginału.
- `npm run test:js`: 17 testów, OK.
- `npm run smoke` (z grą): 18/18 widoków, 0 błędów konsoli.

**Ograniczenia, które zostają**
- Wartości państw (PP, stabilność itd.), stany, cele, sprzęt i wywiad nadal są DEMO. Wymagają mapy nazw pól
  (kalibracja binarny ↔ tekst, raport §2.2).
- Skala liczb `0x000d` / `0x0167` / `0x0317` nie została ustalona, więc nie są prezentowane.
- Zapisy tekstowe i zip są rozpoznawane, ale nieczytane.
- Pola `#3035` i `#000b` w bloku gracza mają nieznane znaczenie.
- Zapis jest migawką. Odczyt aktywnej rozgrywki nie istnieje.

---

## Etap 3 (część 2) + etap 4 (przygotowanie): Political Power z prawdziwego zapisu 🟡

Instrukcje: `prompt4.md` (2026-10-09).

**Zrobione i sprawdzone na prawdziwych danych**
- Zapis tekstowy uzyskany przez parametr startowy `-force_text_save` (bez zmiany `settings.txt`). Gracz wykonał
  `savegame` → `PROJEKT-OVERSEER.hoi4`.
- `saves/text.py`: parser Clausewitz-text (nagłówek i pojedyncze bloki państw), wartości Country Editor z pochodzeniem
  każdego pola (`read` / `absent` / `unmapped`). Ścieżki pól ustalone na prawdziwym pliku (SAVE-FORMAT §8).
- API `GET /api/countries/<TAG>/save-values` zwraca wartości, plik, datę w grze, czas odczytu, aktualność (`is_live: false`)
  i tag gracza z zapisu.
- Country Editor pokazuje prawdziwe wartości z zapisu: plakietka SAVE, data w grze, czas zapisu pliku, czas odczytu i
  „SNAPSHOT – …”. Pola niezmapowane są puste z opisem, a nie wartościami DEMO. Gdy zapis jest binarny lub niedostępny,
  widok wraca do DEMO z wyjaśnieniem.
- Diagnostyczny test zmiany PP: debugger przygotowuje udokumentowaną komendę `pp <n>`, zapisuje wartość bazową z zapisu,
  a po `savegame` niezależnie czyta nowszy zapis i porównuje (pass / fail / inconclusive przy zmianie daty w grze / waiting).
  Wynik trafia do logu aplikacji.

**Wartości odczytane z prawdziwego zapisu (GER, 1936.1.1.12):** PP 2.324, stabilność 0.7, poparcie wojny 0.3,
CP 0.286, paliwo 297201.87, doświadczenie armii 30.

**Test w grze (2026-10-09, SP, GER, gra na pauzie 1936.1.1.12): ✅ PASS**
- Wartość bazowa: `PROJEKT-OVERSEER.hoi4` (14:02:46): `politics.political_power = 2.324`.
- Gracz wpisał `pp 10` i `savegame` → `pp save 2.hoi4` (14:12:02).
- Niezależny odczyt kopii nowego zapisu: `political_power = 12.324`, ta sama data w grze. Zmiana dokładnie +10.000.
  Stabilność, poparcie wojny, CP, paliwo i doświadczenie armii bez zmian.
- `verifyChange` (logika przycisku Verify): `pass`. SHA-1 oryginałów bez zmian.
- Utrwalone jako test regresyjny `RealPpChangeTests` (pomijany, gdy pliki nie istnieją).

**Czego brakuje (uczciwie)**
- Zmiana działa przez komendę konsoli wpisaną ręcznie przez gracza (narzędzie diagnostyczne), a nie przez edytor.
  Docelowa metoda edycji z poziomu debuggera nie istnieje. Komenda działa tylko na kraj gracza.
- **Odczyt aktywnego procesu nie istnieje.** Statyczna analiza `hoi4.exe` (mapa tokenów) została zablokowana przez
  system uprawnień Claude Code, a analiza pamięci procesu nie była prowadzona. Wymaga wyraźnego dopuszczenia przez użytkownika.
- ~~Manpower i Convoys~~: zmapowane 2026-10-09 (patrz niżej). Zgodność z wartościami w UI gry niepotwierdzona.
- Zapisy binarne: brak mapy tokenów dla pól państwa.
- MP: komendy konsoli działają na kraj gracza wydającego komendę („to player”). Działanie dla klienta niebędącego hostem
  oraz synchronizacja **nie były testowane** (wymaga dwóch klientów).

**Testy (2026-10-09)**
- `npm run test:py`: 85 OK. Nowe: 11 testów zapisów tekstowych (parser, bloki państw, uszkodzone pliki, usługa,
  zapis binarny jako „unmapped”) plus test na kopii prawdziwego `PROJEKT-OVERSEER.hoi4` z kontrolą SHA-1 oryginału.
- `npm run test:js`: 20 OK (nowe: komenda `pp`, logika weryfikacji).
- `npm run smoke`: 18/18 widoków.

## Decyzje i założenia
- **Electron + Python zamiast jednego języka:** UI w Electronie jest nowoczesne i przenośne, a Python z `ctypes`
  pozwala w przyszłości dostać się do WinAPI bez kompilowania natywnych modułów Node.
- **Brak frameworka UI i bundlera:** mniej zależności (reguła 14). Moduły ES ładowane bezpośrednio.
- **Brak zapisu do pamięci w tym etapie** – zgodnie z poleceniem.

## Otwarte kwestie / do decyzji
- ✅ Metoda etapu 3: A (zapisy) – zatwierdzona 2026-10-09.
- ✅ Zapis tekstowy: uzyskany przez `-force_text_save` (bez zmiany `settings.txt`).
- Generator komend: tylko narzędzie diagnostyczne (decyzja z prompt4.md), nie docelowa implementacja edytorów.
- ✅ Odczyt pamięci procesu (tylko odczyt): dopuszczony przez użytkownika (test.txt, 2026-10-09).
- `zalozenia.md` był pusty i został usunięty – bez wpływu na projekt.

---

## Manpower i konwoje z zapisów tekstowych (2026-10-09) ✅/🟡

- `manpower.current` = dostępna pula siły ludzkiej (pole pomijane przez grę, gdy wynosi 0).
- Konwoje = suma `convoys.equipment` dla sprzętu typu `convoy*`. Nazwy z top-level `equipments={}` (4504 definicje w zapisie).
- Weryfikacja na parze zapisów `pp save 2` → `Manpower 203.3, convoy 10` (komendy z `console_history.txt`):
  - manpower: brak → 201 692 736 (komendy dodały 202 000 000; różnica niewyjaśniona);
  - konwoje: 200 → 15 (bez komendy dotyczącej konwojów).
- **Otwarte:** nazwa pliku sugeruje 203.3 i 10 w UI gry. Jak UI przelicza wartości z zapisu, niepotwierdzone.
- Poprawka: zapisy tekstowe mają końce linii CRLF (wcześniej nieobsłużone w tabeli sprzętu).
- Testy: backend 89 OK (nowe: CRLF, konwoje, test na prawdziwej parze zapisów), JS 20 OK, smoke 18/18.

---

## Odczyt Political Power z pamięci gry (2026-10-09) ✅

Decyzja użytkownika (test.txt): opcja 1 – dokończyć odczyt pamięci, wyłącznie odczyt.

**Metoda** (`integration/memory.py`, `live/calibration.py`, `live/service.py`)
- Proces otwierany tylko z `PROCESS_QUERY_INFORMATION | PROCESS_VM_READ`; w module nie ma ścieżki zapisu (test pilnuje).
- Kalibracja bez zgadywania adresów: skan pamięci na dokładną wartość z niezależnego źródła (świeży zapis tekstowy)
  w 5 kandydujących kodowaniach → zawężanie po każdej udokumentowanej komendzie `pp N` (wykrywanej w
  `console_history.txt`) lub nowym zapisie → „confirmed” dopiero po ≥ 3 różnych wartościach, ≤ 8 adresach, jednym kodowaniu.
- Adresy są ważne tylko dla procesu (PID + czas startu), w którym je znaleziono. Kalibracja innego procesu albo
  po zamknięciu gry jest odrzucana (także z `calibrations.json`); odczyt zwraca wtedy `process_changed`.
- Niepotwierdzona lokalizacja nigdy nie daje liczby (`unverified`).

**Wynik na prawdziwej grze (SP, GER, PID 28728, 1.19.3)**
- Skan (68 s): 3 kandydatów w 2 kodowaniach dla PP 700.324.
- `pp 7` → 707.324, `pp 5` → 712.324: zostaje **1 adres, kodowanie `fixed64_100000`** (int64, wartość × 100 000).
- Nowy zapis `claude_save_pp.hoi4`: 712.324 = pamięć.
- Po odpauzowaniu (`python -m hoi4dbg.live check`): zapis `3.hoi4` 1936.1.30 – zapis 751.3 / pamięć 751.3 (PASS).
  Zapisy `1.hoi4` i `2.hoi4`: pamięć wyższa o dokładnie 2 × i 4 × dzienny przyrost PP (1.344) – pamięć odczytana
  2–4 dni gry po zapisie (gra nie była na pauzie). Adres śledzi PP przez 18 dni gry.
- Pamięć ma 5 miejsc po przecinku, zapis 3 – porównanie z zapisem w tolerancji 0.0005.

**UI**: karta „Live game memory (read-only)” na Dashboardzie (z kalibracją) i w Country Editorze. Stany:
LIVE / STALE (>10 s bez udanego odczytu) / UNVERIFIED / NO GAME / NO ACCESS / RESTARTED / NOT CALIBRATED / READ ERROR.
Liczba tylko w stanie LIVE (i przekreślona jako STALE).

**Naprawy**: `python -m unittest tests.<moduł>` działa (pakiet `tests/__init__.py`); usunięte odwołanie do nieistniejącego
`livecal.py`; komunikat o zapisie w trakcie zapisywania (`save_in_progress`).

**Ograniczenia**
- Po każdym uruchomieniu gry kalibrację trzeba powtórzyć (adres sterty zmienia się); powtarzalność w nowym procesie
  niesprawdzona. Wczytanie innego zapisu w tym samym procesie prawdopodobnie unieważnia adres (wykrywane jako
  `unreadable`/zmiana wartości dopiero przy weryfikacji – niesprawdzone).
- Tylko PP i tylko kraj gracza. Wymaga zapisu tekstowego (`-force_text_save`) jako źródła wartości bazowej.
- MP: nietestowane. Odczyt pamięci pokazuje stan lokalnego klienta.

**Testy (2026-10-09)**: backend 117 OK, JS 24 OK, smoke 18/18.
