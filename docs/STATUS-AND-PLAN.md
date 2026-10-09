# Stan projektu i plan dalszych prac (2026-10-09)

Porównanie ze specyfikacją `Jak_ma_wygladac_aplikacja.txt`. Szczegóły i dowody: `PROGRESS.md`.
Legenda: ✅ zrobione · 🟡 częściowo · ⏳ nie rozpoczęte (DEMO w UI)

## 1. Etapy specyfikacji

| Etap | Zakres | Stan | Co konkretnie |
|---|---|---|---|
| 1 | Aplikacja, UI, logi, testy, dokumentacja | ✅ | Electron + backend Python, 9 zakładek, logi aplikacji i gry, raporty testera, smoke test 18 widoków |
| 2 | Proces i wersja gry | ✅ | PID, ścieżka, wersja (1.19.3), czas działania; wykrywanie restartu |
| 3 | Wiarygodny odczyt danych | 🟡 | Zapisy: nagłówek, gracze, wartości państwa (tekstowe wszystkie wersje, binarne 1.19.3). Pamięć: 9 pól kraju gracza, potwierdzone niezależnie zapisem (9/9, różnica 0) |
| 4 | Zmiana jednej wartości w SP + weryfikacja | ✅ | Komenda konsoli przygotowana przez aplikację → wykrycie w `console_history.txt` → weryfikacja w pamięci. W grze: PP, stabilność, poparcie wojny, CP, paliwo |
| 5 | Edytory państw, stanów, sprzętu | 🟡 | Country Editor prawie kompletny; State Editor i Equipment Manager – DEMO |
| 6 | Cele narodowe, narzędzia debugowania | ⏳ | Focus – DEMO; Game Tools – tylko narzędzia lokalne aplikacji |
| 7 | Synchronizacja MP (także nie-host) | ⏳ | Nic nie testowano. **Największe ryzyko projektu** (pkt 4) |
| 8 | Poprawki, kompatybilność, instrukcja | ⏳ | – |

## 2. Zakładki

| Zakładka | Stan | Dane prawdziwe | Brakuje |
|---|---|---|---|
| Dashboard | ✅ | proces, wersja, data z `game.log`, ostrzeżenia | – |
| Countries & Players | 🟡 | gracze i ich kraje z nagłówka zapisu | lista wszystkich państw (tagi, nazwy) – DEMO |
| Country Editor | 🟡 | wartości z zapisu dla dowolnego kraju; LIVE z pamięci dla kraju gracza (PP, stab., WS, CP, manpower, paliwo, 3× XP); zmiana z weryfikacją | LIVE i zmiana dla innych krajów; konwoje (tylko zapis tekstowy, brak komendy w dokumentacji); zmiana manpower/XP z aplikacji nie testowana w grze |
| State Editor | ⏳ | – | wszystko: lista stanów, właściciel/kontroler, budynki, zasoby, cores/claims, treść modów |
| National Focus Manager | ⏳ | – | stan celów, kolejkowanie (do zbadania, czy możliwe) |
| Equipment Manager | ⏳ | (tabela sprzętu z zapisu tekstowego istnieje w backendzie – używana dla konwojów) | zapasy, warianty, zmiana ilości (`add_equipment`) |
| Game Tools | 🟡 | narzędzia lokalne: on top, compact, ponowne wykrycie, logi, inspektor zapisów | podgląd debugowy, narzędzia wspólnego stanu |
| Intelligence Lab | ⏳ | – | poziomy wywiadu, porównanie widoczne vs rzeczywiste |
| Logs & Test Reports | ✅ | logi aplikacji i gry, raporty | – |

Testy (2026-10-09): backend 122 OK, JS 24 OK, smoke 18/18 (z uruchomioną grą: karta LIVE).

## 3. Ograniczenia obecnego rozwiązania

- **Kalibracja po każdym uruchomieniu gry**: skan ~6 min + zapis + 2 rundy komend (≈ 10 min pracy testera).
  Wczytanie zapisu w tym samym procesie adresów nie psuje (sprawdzone).
- **Tylko kraj gracza**: komendy konsoli działają na gracza; pamięć skalibrowana tylko dla jego obiektu.
- **Mapa tokenów zapisu binarnego tylko dla 1.19.3** – po aktualizacji gry trzeba ją potwierdzić od nowa (para zapisów tekst/binarny).
- Tester sam wpisuje komendę w konsoli (aplikacja jej nie wstrzykuje) – zgodnie z dotychczasowymi decyzjami.
- Zero testów MP.

## 4. Plan działania (proponowana kolejność)

### Krok 1 – wczesny test wykonalności MP ⛔ wymaga drugiego klienta
Specyfikacja wymaga, by **nie-host** zmieniał wspólny stan bez zgody hosta. Cała dotychczasowa metoda zmian opiera
się na konsoli. Jeśli w MP konsola u nie-hosta nie działa albo zmiana się nie synchronizuje, potrzebny będzie mod
pomocniczy – to zmienia architekturę etapów 5–6, więc lepiej wiedzieć to **teraz**, a nie na etapie 7.
Test (~30 min, prywatna gra, 2 klientów): u nie-hosta `pp 5`, `st 3` → na obu `savegame` → porównanie wartości
(+ odczyt pamięci u obu) → gra kilka miesięcy bez desynchronizacji. Plan szczegółowy: `REPORT-LIVE-AND-WRITE.md` §4.5.
Wynik decyduje: konsola wystarcza / potrzebny mod pomocniczy (osobna zgoda).

### Krok 2 – szybsza kalibracja po restarcie gry
- Stabilność, poparcie wojny i CP leżą w jednym obiekcie państwa w stałych odstępach. Hipoteza: po znalezieniu PP
  pozostałe pola można wyznaczyć z przesunięć i tylko potwierdzić jednym zapisem, bez rund komend.
  Do weryfikacji na 2–3 uruchomieniach gry.
- Przycisk „Kalibruj” w Country Editorze z instrukcją krok po kroku (dziś kalibracja jest z wiersza poleceń).
- Test zmiany manpower i XP z aplikacji w grze.

### Krok 3 – Countries & Players z zapisu
Lista państw z bloku `countries` zapisu (tekst + binarny 1.19.3), nazwy z plików lokalizacji gry/modów.
Usuwa DEMO z dwóch zakładek (Countries, wybór kraju w pozostałych).

### Krok 4 – State Editor (odczyt)
Blok `states` zapisu: właściciel, kontroler, budynki, zasoby, cores/claims. Metoda jak dla państw: para zapisów
tekst/binarny → mapa tokenów. Nazwy stanów i zawartość modów – z plików gry/modu (tylko odczyt).
Zmiany stanów – dopiero po kroku 1 (komendy/efekty działające na stan, do zbadania w dokumentacji).

### Krok 5 – Equipment Manager
Odczyt zapasów i wariantów z zapisu (istniejąca tabela sprzętu) → zmiana przez `add_equipment` z tą samą pętlą
weryfikacji co Country Editor (weryfikacja zapisem, bo sprzętu nie ma w kalibracji pamięci).

### Krok 6 – National Focus Manager
Odczyt stanu celów z zapisu (aktualny, ukończone, postęp); dostępne/zablokowane wymagają drzewa celów z plików
gry/modu. Kolejkowanie – najpierw ustalić, czy gra udostępnia mechanizm; **bez natychmiastowego kończenia celów**.

### Krok 7 – Intelligence Lab i Game Tools
Poziomy wywiadu z zapisu (do potwierdzenia, czy są zapisywane), porównanie z wartościami rzeczywistymi.
Game Tools: narzędzia lokalne (np. podgląd debugowy) wyraźnie oddzielone od wspólnego stanu.

### Krok 8 – zmiany dla innych krajów niż gracz
Do zbadania: `tag` (przełącza kraj gracza – skutki uboczne) albo `effect`/`eval_effect` na wybranym zakresie,
albo mod pomocniczy. Zależy od wyniku kroku 1.

### Krok 9 – pełny test MP (etap 7) i domknięcie (etap 8)
Wszystkie operacje wspólnego stanu na dwóch klientach, raport kompatybilności (wersje gry, mody), instrukcja użytkownika.

## 5. Decyzje potrzebne od Ciebie

1. Czy masz drugi komputer/konto do testu MP (krok 1)? Jeśli nie teraz – zaczynam od kroków 2–5, które od MP nie zależą.
2. Czy dopuszczasz mod pomocniczy, jeśli test MP pokaże, że konsola nie wystarcza?
