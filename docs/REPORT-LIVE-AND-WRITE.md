# Raport: od odczytu zapisu do odczytu aktywnej rozgrywki i bezpiecznej modyfikacji wartości

Data: 2026-10-09 · Wersja gry: 1.19.3.0 · Stan projektu: etap 3 (metoda A, część 1)

Raport opiera się na faktach sprawdzonych na tej maszynie oraz na **dokumentacji dostarczanej z grą**
(`Hearts of Iron IV\documentation\console_commands_documentation.md` i `effects_documentation.md`). Wszystko, czego nie
sprawdzono, jest oznaczone jako *do weryfikacji*.

## 1. Gdzie jesteśmy

| Obszar | Stan |
|---|---|
| Wykrywanie procesu i wersji | ✅ na żywo, bez dostępu do pamięci |
| Zapisy: format binarny | ✅ w pełni rozpoznany i walidowany (1.16.10–1.19.3) |
| Zapisy: nagłówek, gracze → państwa, mody | ✅ odczyt z kopii, z oznaczeniem aktualności |
| Zapisy: wartości Country Editor | ✅ z zapisów tekstowych (`-force_text_save`); manpower/convoys nieustalone |
| Zapisy: stany, cele, sprzęt | ❌ jeszcze nie mapowane |
| Odczyt na żywo | ❌ |
| Modyfikacja | 🟡 PP: komenda diagnostyczna + niezależna weryfikacja przez zapis; test w grze niewykonany |

## 2. Etap pośredni: zapis jako źródło „prawie na żywo”

### 2.1 Krótszy cykl zapis → odczyt
- **Automatyczne odświeżanie:** debugger może obserwować folder `save games` i czytać nowy autosave zaraz po jego
  ustabilizowaniu się. Mechanizm kopiowania i wykrywania pliku w trakcie zapisu już istnieje.
- **Zapis na żądanie testera:** komenda konsoli `savegame` (alias `save`) jest udokumentowana jako „Creates a save file”.
  Tester wpisuje ją w konsoli, a debugger po kilku sekundach pokazuje stan z tego momentu.
- **Interwał autosave:** `settings.txt` ma `autosave="MONTHLY"`. Dostępnych wartości nie sprawdzałem (*do weryfikacji*).
- **Ograniczenie:** to nadal migawka. W MP *do weryfikacji* jest, kto może zapisywać i gdzie trafia plik u klienta
  niebędącego hostem.

### 2.2 Pełne nazwy pól: kalibracja binarny ↔ tekst (rekomendowane, wymaga decyzji)
`settings.txt` zawiera `save_as_binary=yes`, a w pliku wykonywalnym gry występują ciągi `save_as_binary`
i `force_text_save`. Gra potrafi więc zapisywać tekstowo. Procedura:
1. Zamknąć grę i ustawić `save_as_binary=no`. To zmiana pliku ustawień użytkownika, więc wymaga Twojej decyzji (reguła 9).
   Można to zrobić ręcznie.
2. Wczytać istniejący zapis binarny X i od razu, na pauzie, zapisać go jako tekst Y. Przywrócić ustawienie.
3. Debugger równolegle parsuje X i Y i przypisuje identyfikatory tokenów do nazw tam, gdzie struktury się pokrywają.
   Wynik to mapa `token → nazwa` dla tej wersji gry, weryfikowana na drugiej parze plików.
4. Z mapą odczyt wartości z Country Editor, stanów (właściciel/kontroler/budynki/rdzenie), celów i sprzętu
   staje się zwykłą ekstrakcją. Te same dane można też czytać bezpośrednio z zapisów tekstowych.

Pomocna przy tym komenda `savecheck` („Makes a savegame (Test_01), loads the savegame, makes a new savegame (Test_02).
Those savegames should look the same.”) pozwala sprawdzić determinizm zapisu.

## 3. Odczyt aktywnej rozgrywki: opcje

| Opcja | Co daje | Koszt / ryzyko | Rekomendacja |
|---|---|---|---|
| **A+ zapis na żądanie** (2.1) | stan z chwili `savegame`, bez moda, bez dostępu do pamięci | opóźnienie kilku sekund, tester musi wpisać komendę | **najpierw** |
| **C mod pomocniczy z efektem `log`** | wartości wypisywane okresowo do `game.log` (efekt `log`: „Print message to game.log, console (if visible) and history logger”); debugger już czyta `game.log` | zmienia sumę kontrolną, więc w MP każdy musi mieć mod; okresowy wyzwalacz *do ustalenia* | jeśli potrzebny ciągły podgląd |
| **B odczyt pamięci** (`ReadProcessMemory`) | prawdziwe „na żywo”, bez moda | układ pamięci nieudokumentowany, psuje się przy aktualizacjach; wymaga zgody (reguła 8); pokazuje tylko lokalny stan klienta | na końcu, tylko odczyt, tylko po osobnej zgodzie |

## 4. Bezpieczna modyfikacja wartości

### 4.1 Zasada
Wspólny stan gry wolno zmieniać **wyłącznie mechanizmami samej gry** (komendy konsoli albo efekty skryptowe), bo tylko
one mają szansę przejść przez synchronizację MP. **Zapis do pamięci procesu jest wykluczony** jako metoda zmiany
wspólnego stanu: zmienia stan jednego klienta i prowadzi do rozjechania się stanów graczy. Zgodnie z decyzją nie jest
i nie będzie implementowany bez osobnej zgody.

### 4.2 Udokumentowane mechanizmy dla pól Country Editor / Equipment Manager

| Pole | Komenda konsoli (dokumentacja gry) | Efekt skryptowy (dokumentacja gry) |
|---|---|---|
| Political Power | `pp` / `political_power` – „Gives political power to player” | `add_political_power`, `set_political_power` |
| Stability | `add_stability` / `st` | `add_stability`, `set_stability` |
| War Support | `add_war_support` / `ws` | `add_war_support`, `set_war_support` |
| Manpower | `manpower` – „Adds manpower to player” | `add_manpower` |
| Fuel | `fuel` / `army_juice` | `add_fuel`, `set_fuel` |
| Command Power | `cp` | `add_command_power` |
| Army/Air/Navy XP | `xp` – wszystkie trzy naraz | `army_experience`, `air_experience`, `navy_experience` |
| Sprzęt | `add_equipment` / `ae` | `add_equipment_to_stockpile` |
| Convoys | **nie znaleziono** w dokumentacji komend ani efektów | – |
| Cele narodowe | `Focus.AutoComplete` itp. (zmienne) – **nie używać** (spec: nie kończyć natychmiast) | `complete_national_focus` – j.w.; kolejkowanie: *do ustalenia* |

Ważne ograniczenia z dokumentacji:
- Komendy działają na **kraj gracza** („to player”). Zmiana innego kraju wymagałaby `tag` (przełącza kraj gracza,
  ma skutki uboczne) albo `effect` / `eval_effect` („Runs … on selected scope”). Sposób wyboru zakresu jest *do weryfikacji*.
- Działanie komend w Ironmanie i dostęp do konsoli dla klienta MP niebędącego hostem: *do weryfikacji*.

### 4.3 Jak debugger miałby wydawać polecenia (od najbezpieczniejszego)
1. **Generator komend.** Debugger buduje gotową komendę (np. `pp 50`) i kopiuje ją do schowka, a tester wkleja ją w konsoli gry.
   Nie wymaga ingerencji w grę, moda ani wstrzykiwania wejścia. **Proponowany prototyp etapu 4.**
2. **Mod pomocniczy z akcjami (decyzje / scripted GUI) wywołującymi efekty.** Akcje gracza w grze są rozsyłane do
   wszystkich klientów, więc to naturalny kandydat na zmiany inicjowane przez nie-hosta bez zgody hosta.
   *Do weryfikacji testem na dwóch klientach.*
3. Automatyczne wpisywanie do konsoli (symulacja klawiatury) jest kruche i inwazyjne. Tylko po osobnej zgodzie.

### 4.4 Pętla weryfikacji (bez czytania pamięci)
`odczyt przed` (zapis + parser) → polecenie (np. `pp 10`) → `savegame` → `odczyt po` → porównanie z oczekiwaną zmianą.
Warunek wstępny: mapa nazw pól z 2.2 (żeby znaleźć wartość PP w zapisie). Wynik trafia do raportu testera.

### 4.5 Multiplayer: test, zanim cokolwiek zostanie uznane za zsynchronizowane
**Synchronizacja MP NIE jest zweryfikowana.** Plan testu (etap 7, dwóch klientów, prywatna gra):
1. Klient B (nie-host) wykonuje zmianę metodą z 4.3.
2. Na obu klientach: `savegame`, porównanie wartości z zapisów. Dodatkowo udokumentowane narzędzia diagnostyczne:
   `PrintSynchStuff` („Prints random count and seed”), `dump_synchronized_members` („Dump the synchronized game
   state”), `compare_to_last_checksum`. Komenda `oos` nie jest dostępna w wersji release.
3. Sprawdzenie logów `sent_commands.log`, `received_commands.log` i `posted_commands.log` w folderze `logs`.
   W SP były puste; ich zawartość w MP jest *do weryfikacji*.
4. Kryterium: identyczna wartość u obu klientów, brak desynchronizacji, gra trwa dalej co najmniej kilka miesięcy gry.

## 5. Proponowana kolejność i potrzebne decyzje

| # | Krok | Decyzja |
|---|---|---|
| 1 | Auto-odświeżanie po nowym zapisie + instrukcja `savegame` | nie wymaga |
| 2 | Kalibracja nazw pól (2.2) → odczyt wartości państw, stanów, celów i sprzętu z zapisów | **zgoda na tymczasowe `save_as_binary=no`** (wykonujesz Ty) |
| 3 | Etap 4: generator komend (4.3.1) + pętla weryfikacji (4.4) w SP, jedno pole (PP) | **zgoda na metodę** |
| 4 | Mod pomocniczy (podgląd przez `log` i/lub akcje MP) | **zgoda na mod** (spec preferuje wariant bez moda) |
| 5 | Test MP na dwóch klientach (4.5) | potrzebny drugi klient / tester |
| 6 | Odczyt pamięci (tylko odczyt) | osobna zgoda; najniższy priorytet |
