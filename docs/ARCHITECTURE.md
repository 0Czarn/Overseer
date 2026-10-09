# Architektura

```
┌──────────────── Electron ────────────────┐        ┌──────────── Python backend ────────────┐
│ renderer (sandbox, CSP, brak Node)       │        │ server.py   HTTP 127.0.0.1, token      │
│   views/*.js  ── window.hoi4dbg (IPC) ─┐ │        │ service.py  DEMO / LIVE / UNAVAILABLE  │
│ preload.cjs                            │ │  HTTP  │ integration/  ◄── jedyny dostęp do gry │
│ main.cjs + api-bridge.cjs ─────────────┴─┼───────►│ reports.py, applog.py                  │
└──────────────────────────────────────────┘        └────────────────────────────────────────┘
```

## Zasady

1. **Oddzielenie UI od integracji z grą.** UI zna wyłącznie API JSON. Kod, który dotyka HOI4
   (procesy, pliki gry, w przyszłości ewentualnie pamięć), znajduje się tylko w `backend/hoi4dbg/integration/`
   i implementuje interfejs `GameIntegration`.
2. **Każda odpowiedź mówi, skąd pochodzą dane:** `source` = `live` (odczyt z gry/systemu),
   `save` (kopia pliku zapisu – migawka, z oceną aktualności), `demo` (dane przykładowe), `unavailable`. UI pokazuje to plakietką, a dla DEMO dodatkowo banerem.
   Lista obszarów i ich źródeł jest w `service.CAPABILITIES` (jedno źródło prawdy, widoczne na Dashboardzie).
3. **Lokalne vs wspólne.** Narzędzia mają `scope`: `local` (tylko ta aplikacja / ten klient) albo
   `shared` (zmiana wspólnego stanu gry). Narzędzia `shared` pozostają `planned`, dopóki nie zostaną
   zsynchronizowane mechanizmem zgodnym z grą i przetestowane na dwóch klientach.
4. **Brak zapisu.** Edycja jest wyłączona (`write: false` wszędzie). Zapis do pamięci nie istnieje.
5. **Bezpieczeństwo lokalne.** API słucha tylko na `127.0.0.1`, wymaga losowego tokenu z nagłówka
   `X-HOI4DBG-Token` (generowanego przez Electron przy każdym starcie). Renderer nie zna portu ani tokenu,
   a `api-bridge.cjs` przepuszcza tylko `GET/POST` na `/api/...`. Backend kończy działanie,
   gdy proces nadrzędny zamknie stdin.

## Kontrakt widoku (renderer)

`views/<nazwa>.js` eksportuje `{ id, title, short, render(root, ctx) }`. `render` może zwrócić funkcję
sprzątającą (np. zatrzymanie pollingu). `ctx` udostępnia `api`, `state` (m.in. `selectedCountry`, czyli państwo
wybrane niezależnie od kontrolowanego przez gracza), `setState`, `navigate`, `onStatus`, `refreshStatus`.

## Zapisy gry (`backend/hoi4dbg/saves/`)

`reader.SaveSnapshotter` kopiuje oryginał do cache (nigdy nie czyta go w miejscu). `reader.SaveAnalyzer` czyta nagłówek
od razu, a pełną walidację struktury uruchamia w tle. `binary.py` to format, a `fields.py` to znaczenia pól z dowodami.
Szczegóły: [SAVE-FORMAT.md](SAVE-FORMAT.md).
