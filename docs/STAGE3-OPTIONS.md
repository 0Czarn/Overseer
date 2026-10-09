# Etap 3 – metody odczytu danych rozgrywki (do zatwierdzenia)

Zgodnie z regułą 8 przed implementacją czegokolwiek bardziej inwazyjnego niż etap 2 przedstawiam metody,
ograniczenia i ryzyko. **Nic z poniższego nie jest jeszcze zaimplementowane.**

## Ustalenia z prawdziwej instalacji (2026-10-09, HOI4 1.19.3.0)

- Pliki `.hoi4` w `save games` zaczynają się od `HOI4bin` → **format binarny** (dotyczy zarówno `autosave.hoi4`,
  jak i zapisu MP z 1.16.10). Nie są to pliki tekstowe.
- Mimo binarności nagłówek zawiera czytelne ciągi: tag państwa gracza, ideologię, pełną wersję gry
  (`Operation Postern v1.19.3.0.c01a (ff0e)` – sufiks w nawiasie różni się od `(5632)` w `launcher-settings.json`;
  znaczenie nieustalone) oraz **listę par tag → nazwa gracza** (w zapisie MP: kilku graczy na różnych państwach).
- `game.log` dostaje wpisy tylko przy niektórych zdarzeniach (w bieżącej sesji ostatni wpis 09:48 mimo 3 h gry) –
  nie nadaje się jako źródło danych na żywo.
- `logs/` zawiera m.in. `executed_commands.log`, `posted_commands.log`, `sent_commands.log`, `received_commands.log`
  (w tej sesji SP puste). Ich zawartość w MP trzeba sprawdzić w etapie 7 – nie zakładam, co zawierają.

## Opcje

### A. Odczyt plików zapisu (autosave / zapis ręczny) – **nieinwazyjne**
- **Jak:** parser formatu binarnego `HOI4bin` (tylko odczyt kopii pliku), odświeżanie przy każdym nowym autosave.
- **Daje:** pełny stan gry z chwili zapisu: państwa, wartości z Country Editor, stany (właściciel/kontroler,
  budynki, rdzenie, roszczenia), cele narodowe, sprzęt i – co już widać w nagłówku – **przypisanie graczy do państw**.
- **Ograniczenia:** opóźnienie = interwał autosave (lub ręczny zapis przez testera). Format binarny używa
  numerycznych identyfikatorów pól; mapy identyfikator → nazwa gra nie publikuje. Trzeba ją ustalić i zweryfikować.
  Pierwszy krok to sprawdzić, czy gra potrafi zapisać ten sam stan w formie tekstowej, co pozwoliłoby porównać oba pliki.
  Do tego czasu nie zakładam, że taka opcja istnieje.
- **Ryzyko:** niskie – nie dotyka procesu gry ani oryginalnych plików (czytamy kopię). Mapa pól może się zmienić
  z wersją gry → testy na wersjach.

### B. Odczyt pamięci procesu (ReadProcessMemory) – **inwazyjne, tylko odczyt**
- **Jak:** otwarcie `hoi4.exe` z uprawnieniem `PROCESS_VM_READ`, odnalezienie struktur (wzorce/sygnatury), odczyt wartości.
- **Daje:** wartości na żywo bez moda i bez opóźnienia.
- **Ograniczenia:** układ pamięci nie jest udokumentowany; wymaga inżynierii wstecznej i będzie się psuł przy
  aktualizacjach gry (każda wersja do ponownej weryfikacji). Wymaga, by debugger działał na tym samym koncie/poziomie uprawnień co gra.
- **Ryzyko:** średnie/wysokie – kruchość przy patchach; zasady użytkowania gry/platformy wobec odczytu pamięci
  nie zostały przeze mnie zweryfikowane; programy antywirusowe mogą reagować na narzędzia czytające pamięć innego procesu.
  Odczyt nie zmienia stanu gry, ale **sam w sobie nie daje nic w MP poza lokalnym podglądem**.

### C. Mod pomocniczy (skrypt Clausewitz) – **zmienia zawartość gry**
- **Jak:** mały mod, który okresowo wypisuje potrzebne wartości do logu gry (do zweryfikowania, jakie mechanizmy
  wypisywania są dostępne w 1.19.3 – nie zakładam ich z góry).
- **Daje:** dane na żywo przez oficjalny mechanizm skryptowy; ten sam mechanizm jest naturalnym kandydatem
  do **zsynchronizowanych zmian w MP** (etap 7), bo efekty skryptowe wykonuje gra.
- **Ograniczenia:** specyfikacja preferuje wariant bez moda; mod zmienia sumę kontrolną → w MP wszyscy muszą go mieć.
- **Ryzyko:** niskie dla stabilności, ale wymaga dystrybucji moda do testerów.

## Rekomendacja

1. **Zacząć od A.** Jest bezpieczne, daje najwięcej danych, w tym przypisanie graczy, i od razu zasila wszystkie
   zakładki prawdziwymi danymi (z oznaczeniem czasu zapisu zamiast „na żywo”).
2. **B** rozważyć później, wyłącznie jako opcjonalny podgląd na żywo, po osobnej zgodzie.
3. **C** rozpatrzyć przy etapach 4–7. Zmiany wspólnego stanu w MP muszą przejść przez mechanizm gry,
   a lokalna zmiana pamięci tego nie zapewnia.

**Potrzebna decyzja:** którą metodę (lub kolejność) zatwierdzasz dla etapu 3?
