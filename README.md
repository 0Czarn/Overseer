# HOI4 Debugger

Desktopowa aplikacja do debugowania aktywnej rozgrywki Hearts of Iron IV (Windows, Steam).

> **Status:** wczesny prototyp. Dane rozgrywki (państwa, stany, cele, sprzęt, wywiad) są na razie
> **DEMO** i są tak oznaczone w interfejsie. Aplikacja **niczego nie zapisuje** do gry, jej pamięci,
> plików ani zapisów. Aktualny stan prac: [`docs/PROGRESS.md`](docs/PROGRESS.md).

## Wymagania

- Windows 10/11
- Python 3.12+ (testowane na 3.14.3) – tylko biblioteka standardowa, bez pakietów z pip
- Node.js 22.12+ (testowane na 24.14.1)

## Instalacja

```powershell
npm install
```

Instaluje jedyną zależność: `electron@44.4.5` (okno aplikacji desktopowej, ok. 100 MB).

## Uruchomienie

```powershell
npm start
```

Electron sam uruchamia backend Pythona (`py -3`, a gdy go brak – `python`). Inny interpreter można
wskazać zmienną `HOI4DBG_PYTHON`, np. `$env:HOI4DBG_PYTHON = "C:\Python314\python.exe"`.

Przydatne zmienne środowiskowe:

| Zmienna | Znaczenie |
|---|---|
| `HOI4DBG_PYTHON` | ścieżka do interpretera Pythona |
| `HOI4DBG_NO_GAME=1` | backend w ogóle nie dotyka gry (praca nad UI, testy) |
| `HOI4DBG_DATA_DIR` | katalog na logi i raporty aplikacji (domyślnie `%LOCALAPPDATA%\HOI4Debugger`) |

Backend można też uruchomić samodzielnie (wypisze port i token):

```powershell
cd backend
python -m hoi4dbg
```

## Testy

```powershell
npm test             # testy backendu (unittest) + testy JS (node --test)
npm run smoke        # test dymny UI: prawdziwy Electron, wszystkie zakładki, 2 rozmiary okna, zrzuty do smoke-output/
$env:HOI4DBG_NO_GAME=1; npm run smoke   # to samo bez wykrywania gry
```

## Struktura

```
backend/hoi4dbg/          Python: lokalne API JSON (127.0.0.1 + token)
  integration/            warstwa integracji z grą (jedyne miejsce, które dotyka HOI4)
  service.py              logika: łączy integrację, dane DEMO i raporty
  server.py               routing HTTP
  demo.py                 dane DEMO
  reports.py              raporty testerów (JSON + Markdown)
  applog.py               log aplikacji (plik + bufor dla UI)
backend/tests/            testy unittest
app/main.cjs              proces główny Electron (start backendu, okno, IPC)
app/preload.cjs           wąski most renderer <-> main
app/api-bridge.cjs        przekazywanie zapytań UI do backendu (walidacja ścieżek, token)
app/renderer/             interfejs (HTML/CSS/JS bez frameworka), 9 zakładek
app/tests/                testy node --test + test dymny UI
docs/                     PROGRESS.md, ARCHITECTURE.md
```

Gdzie aplikacja zapisuje swoje dane: `%LOCALAPPDATA%\HOI4Debugger\logs\app.log` i
`%LOCALAPPDATA%\HOI4Debugger\reports\*.json|*.md`.
