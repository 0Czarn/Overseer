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
| 3 | Wiarygodny odczyt danych z aktywnej rozgrywki | ⛔ czeka na wybór metody ([STAGE3-OPTIONS.md](STAGE3-OPTIONS.md)) |
| 4 | Prototyp modyfikacji pojedynczej wartości (SP) + weryfikacja | ⏳ |
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

## Decyzje i założenia
- **Electron + Python zamiast jednego języka:** UI w Electronie jest nowoczesne i przenośne, a Python z `ctypes`
  pozwala w przyszłości dostać się do WinAPI bez kompilowania natywnych modułów Node.
- **Brak frameworka UI i bundlera:** mniej zależności (reguła 14). Moduły ES ładowane bezpośrednio.
- **Brak zapisu do pamięci w tym etapie** – zgodnie z poleceniem.

## Otwarte kwestie / do decyzji
- ⛔ Metoda odczytu danych rozgrywki (etap 3) – opcje, ograniczenia i ryzyko: [STAGE3-OPTIONS.md](STAGE3-OPTIONS.md).
  Rekomendacja: zacząć od parsera plików zapisu (nieinwazyjny).
- Zapisy gry są binarne (`HOI4bin`), ale nagłówek zawiera listę tag → gracz – kandydat na wykrywanie graczy.
- `zalozenia.md` jest pusty – jeśli miał zawierać dodatkowe wymagania, trzeba go uzupełnić.
