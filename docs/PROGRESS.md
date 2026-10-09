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
| Uwagi | `zalozenia.md` w katalogu projektu jest pusty (0 bajtów) – praca wg `prompt.md` |

## Etapy

| Etap | Zakres | Status |
|---|---|---|
| 1 | Aplikacja desktopowa, UI (9 zakładek), logi, testy, dokumentacja | ✅ |
| 2 | Wykrywanie procesu HOI4 i wersji gry | ✅ |
| 3 | Wiarygodny odczyt danych z aktywnej rozgrywki | 🟡 zapisy: nagłówek, gracze, mody ✅; wartości Country Editor z zapisów tekstowych ✅; odczyt procesu ❌ |
| 4 | Prototyp modyfikacji pojedynczej wartości (SP) + weryfikacja | 🟡 PP: metoda diagnostyczna + niezależna weryfikacja gotowe; test w grze niewykonany |
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

**Czego brakuje (uczciwie)**
- **Modyfikacja PP nie została jeszcze wykonana ani zweryfikowana w grze.** Metoda i weryfikacja są gotowe, ale wymagają
  wpisania `pp 10` i `savegame` w grze uruchomionej z `-force_text_save`. Gra była zamknięta w chwili implementacji.
- **Odczyt aktywnego procesu nie istnieje.** Statyczna analiza `hoi4.exe` (mapa tokenów) została zablokowana przez
  system uprawnień Claude Code, a analiza pamięci procesu nie była prowadzona. Wymaga wyraźnego dopuszczenia przez użytkownika.
- Manpower i Convoys: lokalizacja w zapisie nieustalona.
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
- ⛔ Analiza `hoi4.exe` / pamięci procesu: zablokowana przez uprawnienia Claude Code; wymaga wyraźnej zgody użytkownika.
- Generator komend: tylko narzędzie diagnostyczne (decyzja z prompt4.md), nie docelowa implementacja edytorów.
- `zalozenia.md` jest pusty – jeśli miał zawierać dodatkowe wymagania, trzeba go uzupełnić.
