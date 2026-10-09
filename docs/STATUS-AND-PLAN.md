# Stan projektu i plan do ukończenia (aktualizacja 2026-10-09, wieczór)

Porównanie ze specyfikacją `Jak_ma_wygladac_aplikacja.txt`. Szczegóły i dowody: `PROGRESS.md`.
Legenda: ✅ zrobione · 🟡 częściowo · ⏳ nie rozpoczęte (DEMO w UI)

## 1. Stan

| Etap | Zakres | Stan |
|---|---|---|
| 1 | Aplikacja, UI, logi, testy, dokumentacja | ✅ |
| 2 | Proces i wersja gry | ✅ |
| 3 | Wiarygodny odczyt danych | 🟡 Państwa: 8 pól **dowolnego państwa na żywo bez kalibracji** (tablica państw gry). Brakuje: manpower/konwoje na żywo, gracz na żywo, stany/sprzęt/cele |
| 4 | Zmiana wartości w SP + weryfikacja | ✅ PP, stabilność, poparcie wojny, CP, paliwo (komenda konsoli + odczyt pamięci) |
| 5 | Edytory państw, stanów, sprzętu | 🟡 Country Editor ✅ (poza konwojami); State Editor, Equipment – DEMO |
| 6 | Cele narodowe, narzędzia | ⏳ |
| 7 | MP (także nie-host) | ⏳ nietestowane – **największe ryzyko** |
| 8 | Poprawki, kompatybilność, instrukcja | ⏳ |

**Kluczowa zmiana dzisiaj:** odczyt na żywo nie wymaga już kalibracji ani komend – gra jest czytana przez jej
własną tablicę państw. Ta sama metoda (znajdź obiekt po wartościach z zapisu → znajdź ścieżkę z `hoi4.exe`
→ sprawdź po restarcie) da się powtórzyć dla stanów, sprzętu i celów. To zamyka „kręcenie się w kółko”:
koniec z kalibracją przy każdym uruchomieniu gry.

## 2. Co zostało – plan do ukończenia (w kolejności)

Zasada pracy: **jedna sesja w grze na krok**, wynik od razu w kodzie, testach, `PROGRESS.md` i commicie.
Każdy krok ma kryterium „zrobione”.

| # | Krok | Twoja rola w grze | Kryterium „zrobione” |
|---|---|---|---|
| A | **Countries & Players z tablicy państw**: lista istniejących państw, tagi, nazwy (lokalizacja gry), gracz z zapisu. Usuwa DEMO z 2 zakładek | brak (gra uruchomiona) | lista = państwa z zapisu; zero DEMO |
| B | **Automatyczny „mapper” pól**: porównanie zapisu z pamięcią dla 440 państw naraz → odstępy dla manpower, konwojów i kolejnych pól bez komend | 1 zapis | manpower i konwoje LIVE, zgodne z zapisem dla wszystkich państw |
| C | **Gracz na żywo** (bez zapisu): szukanie w obiektach gry, nie w pamięci statycznej | 2× wczytanie zapisu innym państwem | po wczytaniu innego państwa aplikacja sama przełącza gracza |
| D | **State Editor (odczyt)**: stany z zapisu (właściciel, kontroler, budynki, zasoby, rdzenie/roszczenia) + nazwy z plików gry/modów; potem tablica stanów jak państw | 1 zapis | zakładka bez DEMO, zgodna z zapisem |
| E | **Equipment Manager**: zapasy i warianty z zapisu → zmiana przez `add_equipment` z weryfikacją | 1 runda komend | zmiana potwierdzona w grze |
| F | **National Focus Manager (odczyt)**: aktualny/ukończone/postęp z zapisu, drzewo z plików gry; kolejkowanie tylko jeśli gra to umożliwia; bez natychmiastowego kończenia | 1 zapis | zakładka bez DEMO |
| G | **Intelligence Lab + Game Tools**: poziomy wywiadu z zapisu (jeśli są), narzędzia lokalne vs wspólne | brak / 1 zapis | zakładki bez DEMO |
| H | **Test MP** na 2 klientach: czy konsola u nie-hosta działa i synchronizuje; jeśli nie → decyzja o modzie pomocniczym | drugi komputer/konto | raport: działa / co zamiast |
| I | **Etap 8**: raport kompatybilności (wersja gry, mody), instrukcja użytkownika, narzędzie do ponownego znalezienia ścieżek po aktualizacji gry | brak | dokumenty + działająca instrukcja |

Szacunek: A–C to 1–2 sesje, D–G po ~1 sesji każda, H zależy od dostępności drugiego klienta, I – 1 sesja.

## 3. Ryzyka

- **Aktualizacja gry** psuje ścieżki wskaźników (stałe miejsca w `hoi4.exe`). Zabezpieczenie: odczyt tylko dla
  zweryfikowanej wersji, zapasowo kalibracja; narzędzie do ponownego znalezienia ścieżek (krok I).
- **Mody** zmieniające listę tagów – indeksy czytane z plików gry, ale bez testu z modami.
- **MP**: zmiany wspólnego stanu tylko przez mechanizmy gry; synchronizacja niesprawdzona (krok H).

## 4. Decyzje potrzebne od Ciebie

1. Czy kolejność A → I Ci odpowiada (MP na końcu, bo wymaga drugiego klienta)? Jeśli drugi klient jest dostępny
   wcześniej – H można przesunąć, bo jego wynik może zmienić sposób zmian w krokach E–G.
2. Czy dopuszczasz mod pomocniczy, jeśli test MP wykaże, że konsola nie wystarcza?
