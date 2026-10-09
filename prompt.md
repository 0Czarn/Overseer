# HOI4 Debugger — główna specyfikacja projektu

## Twoja rola

Jesteś głównym programistą projektu. Pracujesz w aktualnym folderze VS Code, samodzielnie tworzysz kod, uruchamiasz testy, naprawiasz błędy i dokumentujesz postęp.

Nie ograniczaj projektu do analizowania plików modów. Celem jest aplikacja desktopowa do debugowania aktywnej rozgrywki Hearts of Iron IV.

## Środowisko

* Windows 10
* Hearts of Iron IV na Steamie
* Python 3.14 jest dostępny
* Node.js jest dostępny
* VS Code i Claude Code są zainstalowane

## Główny cel

Stwórz nowoczesną aplikację desktopową, która podczas działania HOI4 potrafi wykrywać grę, odczytywać dostępne dane i docelowo pozwalać testerom modyfikować wartości w trakcie rozgrywki.

Preferowany jest wariant bez dodatkowego moda pomocniczego. Nie zakładaj jednak, że wszystkie funkcje da się zrealizować bez niego.

W multiplayerze każdy tester posiadający aplikację ma móc inicjować operacje bez ręcznej zgody hosta. Operacje zmieniające wspólny stan muszą być rzeczywiście zsynchronizowane przez mechanizm zgodny z działaniem gry. Nie uznawaj lokalnej zmiany pamięci za zmianę wspólną.

## Wymagane zakładki

1. Dashboard
2. Countries & Players
3. Country Editor
4. State Editor
5. National Focus Manager
6. Equipment Manager
7. Game Tools
8. Intelligence Lab
9. Logs & Test Reports

Interfejs ma być nowoczesny, przejrzysty, responsywny i wygodny podczas gry.

## Docelowe funkcje

### Countries & Players

* Wykrywanie państw, tagów i nazw.
* Wykrywanie graczy i przypisanych państw, jeśli technicznie dostępne.
* Wybór państwa niezależnie od państwa kontrolowanego przez użytkownika.

### Country Editor

* Political Power
* Stability
* War Support
* Manpower
* Fuel
* Convoys
* Command Power
* Army, Air i Navy Experience

### State Editor

* Lista stanów.
* Rozróżnienie właściciela i kontrolującego państwa.
* Budynki, zasoby, claims i cores.
* Obsługa zawartości dodanej przez mody, jeśli zostanie potwierdzona.

### National Focus Manager

* Podgląd aktualnych, ukończonych, dostępnych i zablokowanych celów.
* Kolejkowanie następnych celów, jeśli jest to technicznie możliwe.
* Nie kończ celów natychmiast.

### Equipment Manager

* Odczyt zapasów sprzętu i wariantów.
* Dodawanie i odejmowanie ilości po wdrożeniu i przetestowaniu bezpiecznej metody.

### Game Tools

* Lokalne narzędzia debugowania i widoczności.
* Wyraźne odróżnienie efektów lokalnych od wspólnego stanu gry.

### Intelligence Lab

* Porównywanie widoczności informacji i dostępnego wywiadu.
* Odróżnienie rzeczywistego stanu gry od dodatkowego podglądu debuggera.

## Zasady techniczne

1. Najpierw sprawdź środowisko i przedstaw krótki plan.
2. Następnie od razu rozpocznij budowę działającej aplikacji.
3. Nie wymyślaj API, komend ani możliwości gry.
4. Oznaczaj przykładowe dane jako DEMO.
5. Oddziel interfejs od warstwy integracji z grą.
6. Zacznij od wykrywania procesu, wersji gry i wiarygodnego odczytu danych.
7. Testuj na prawdziwej grze tam, gdzie to konieczne.
8. Zanim dodasz odczyt pamięci lub inne bardziej inwazyjne techniki, przedstaw metodę, ograniczenia i ryzyko do zatwierdzenia.
9. Nie modyfikuj oryginalnych plików gry ani zapisów bez osobnej decyzji.
10. Nie obiecuj synchronizacji multiplayera bez testu na dwóch klientach.
11. Używaj Git i wykonuj małe, opisowe commity po ukończonych etapach.
12. Zapisuj postęp w `docs/PROGRESS.md`, a nie tylko w historii rozmowy.
13. Po każdym etapie uruchom testy i podaj ich wyniki.
14. Nie instaluj nieznanych zależności ani narzędzi bez wyjaśnienia ich celu.

## Plan realizacji

Etap 1: działająca aplikacja desktopowa, UI, logi, testy i dokumentacja.

Etap 2: wykrywanie procesu HOI4 i odczyt informacji o wersji.

Etap 3: wiarygodny odczyt dostępnych danych z aktywnej rozgrywki.

Etap 4: prototyp modyfikacji pojedynczej wartości w singleplayerze i weryfikacja wyniku.

Etap 5: edytory państw, stanów i wyposażenia.

Etap 6: cele narodowe i narzędzia debugowania.

Etap 7: testy synchronizacji prywatnego multiplayera, w tym inicjowanie zmian przez uczestnika niebędącego hostem.

Etap 8: poprawki, raport kompatybilności i instrukcja użytkownika.

## Pierwsze zadanie

Przeczytaj całą specyfikację. Sprawdź, czy folder projektu jest pusty. Przedstaw krótki plan technologiczny i rozpocznij implementację pierwszego etapu.

Dostarcz działający prototyp, instrukcję uruchomienia i testy. Nie twórz na razie mechanizmu zapisu do pamięci gry. Nie zatrzymuj się na samym planie.
