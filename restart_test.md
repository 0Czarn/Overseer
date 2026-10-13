# HOI4 DEBUGGER — KONTYNUACJA PROJEKTU I REALIZACJA PLANU

Kontynuuj istniejący projekt HOI4 Debugger w folderze:

`C:\NIBY DYSK\PROJEKT OVERSEER\HOI4-Debugger-Clean`

Nie twórz nowego projektu. Nie usuwaj istniejącej aplikacji ani jej dziewięciu zakładek. Twoim celem jest doprowadzenie projektu do stanu, w którym dostępne funkcje rzeczywiście odczytują i modyfikują grę Hearts of Iron IV, a ich działanie jest zweryfikowane testami.

Użytkownik chce, żebyś samodzielnie wykonywał pracę programistyczną, analizował problemy, dobierał narzędzia i kontynuował kolejne etapy bez pytania o zgodę na każdą decyzję techniczną. Pytaj tylko wtedy, gdy konieczna jest czynność użytkownika, której nie możesz bezpiecznie wykonać samodzielnie, albo gdy operacja wiąże się z istotnym ryzykiem utraty danych lub nieodwracalnej zmiany poza projektem.

## 1. Najpierw odzyskaj kontekst

Przed rozpoczęciem implementacji:

1. Sprawdź `git status`, aktualną gałąź i ostatnie commity.
2. Ustal, które funkcje są rzeczywiście zaimplementowane, a które jedynie opisane w dokumentacji.
3. Sprawdź, czy istnieją niezatwierdzone zmiany. Nie usuwaj ich i nie nadpisuj bez potrzeby.
4. Nie powtarzaj długich analiz, których wyniki są już zapisane w dokumentacji. Zweryfikuj tylko informacje niezbędne do podjęcia następnego kroku.

Jeśli `restart_test.md` nie istnieje, kontynuuj na podstawie pozostałych dokumentów. Nie przerywaj pracy z powodu braku opcjonalnego pliku.

## 2. Najważniejsza zasada: rzeczywiste działanie

Nie uznawaj funkcji za gotową tylko dlatego, że:

* przycisk istnieje;
* panel poprawnie się wyświetla;
* test jednostkowy przechodzi;
* wygenerowano komendę konsoli;
* odczytano stary zapis gry;
* kod nie zgłosił błędu.

Funkcja jest zweryfikowana dopiero wtedy, gdy wykonuje rzeczywistą operację, a jej rezultat został sprawdzony odpowiednią metodą.

W interfejsie nie mogą występować fikcyjne wartości oznaczone lub sugerujące, że pochodzą z bieżącej rozgrywki. Dane demonstracyjne muszą być jednoznacznie oznaczone jako DEMO. Nie pokazuj danych ze starego zapisu jako aktualnego stanu gry.

Każda funkcja musi mieć czytelny status:

* `DZIAŁA — ZWERYFIKOWANO`
* `DZIAŁA Z OGRANICZENIAMI`
* `W TRAKCIE IMPLEMENTACJI`
* `NIEZAIMPLEMENTOWANA`
* `NIEZWERYFIKOWANA`

## 3. Plan realizacji — pracuj etapami, bez zatrzymywania się na planach

### Etap A: uruchomienie i kontrola projektu

* Uruchom testy backendu, JavaScriptu i UI.
* Zapisz rzeczywiste wyniki.
* Napraw regresje, jeśli występują.
* Sprawdź, czy aplikację można uruchomić i czy wszystkie dziewięć zakładek nadal działa.
* Nie usuwaj testów ani nie zmieniaj ich tak, żeby jedynie uzyskać zielony wynik.

Po zakończeniu przejdź do kolejnego etapu.

### Etap B: prawdziwe dane z gry

W projekcie istnieje już parser zapisów binarnych oraz obsługa części danych zapisów tekstowych. Nie zaczynaj tych elementów od nowa, jeśli obecny kod działa.

* Ustal, które wartości można wiarygodnie odczytać z zapisów.
* Zbadaj, jak uzyskać aktualny stan rozgrywki.
* Sprawdź istniejące mechanizmy diagnostyczne, komendy debugowe i możliwości odczytu aktywnego procesu `hoi4.exe`.
* Odróżniaj migawkę z zapisu od danych na żywo.
* Wykrywaj nieaktualne dane i niezgodność wersji.
* Jeśli potrzebne jest ustawienie `save_as_binary=no` lub inne ustawienie gry, zachowaj kopię konfiguracji i możliwość przywrócenia pierwotnego stanu.
* Nie modyfikuj oryginalnych zapisów podczas eksperymentów.

Jeżeli brakuje narzędzia, sprawdź, czy jest rzeczywiście potrzebne. Możesz dobrać i wykorzystać odpowiednie narzędzia reverse engineeringu, analizę procesu oraz odczyt pamięci gry, jeśli to konieczne. Uzasadnij ich użycie konkretnym problemem technicznym.

Nie zgaduj adresów pamięci, offsetów ani znaczenia pól. Wykrywaj wersję gry i odrzucaj odczyty, których poprawności nie da się wiarygodnie potwierdzić.

### Etap C: pierwszy kompletny edytor — Political Power

To najważniejszy najbliższy cel.

Wcześniej przeprowadzono test `pp 10` przez konsolę gry i sprawdzono rezultat w zapisie. To potwierdza możliwość testowania zmiany, ale nie oznacza, że edytor aplikacji jest już gotowy.

Zaimplementuj następujący przepływ:

1. Aplikacja rozpoznaje działający proces gry i sprawdza jego wersję.
2. Odczytuje rzeczywistą wartość Political Power z jasno określonego źródła.
3. UI pokazuje wartość, źródło, czas odczytu oraz informację, czy wartość jest bieżąca, czy pochodzi z migawki.
4. Użytkownik może określić docelową wartość lub wielkość zmiany.
5. Aplikacja wykonuje operację przez zweryfikowany mechanizm gry, bez wymagania ręcznego przepisywania komendy, jeśli automatyzacja jest technicznie możliwa.
6. Aplikacja niezależnie odczytuje wartość po zmianie.
7. UI pokazuje wynik i informuje o sukcesie albo konkretnym błędzie.

Zacznij od trybu jednoosobowego.

Najpierw wybierz najbezpieczniejszy wiarygodny mechanizm. Jeśli można wykorzystać mechanizm konsoli gry, nie komplikuj rozwiązania odczytem i zapisem pamięci bez potrzeby. Jeżeli jednak automatyzacja konsoli nie jest możliwa lub niezawodna, zbadaj alternatywy.

Nie wpisuj wartości na sztywno i nie uznawaj samego wysłania komendy za potwierdzenie zmiany.

Jeśli nie możesz jeszcze wdrożyć automatycznej modyfikacji, wykonaj rzeczywisty odczyt i przygotuj dokładny test kolejnego kroku. Wyjaśnij konkretną przeszkodę, ale kontynuuj inne możliwe zadania.

### Etap D: pozostałe funkcje

Po zweryfikowaniu Political Power kontynuuj implementację kolejnych funkcji.

**Countries & Players**

* Odczyt państw, tagów i nazw.
* Przypisania graczy do państw.
* Rozpoznawanie trybu obserwatora, jeśli możliwe.
* Zmiana kontrolowanego państwa, jeśli można ją wykonać i zweryfikować.

**Country Editor**

* Political Power.
* Stability.
* War Support.
* Manpower.
* Fuel.
* Convoys.
* Command Power.
* Army XP, Air XP i Navy XP.

**State Editor**

* Lista stanów.
* Owner i Controller jako odrębne pola.
* Fabryki wojskowe i cywilne.
* Rafinerie syntetyczne, infrastruktura, lotniska, AA i radar.
* Zasoby: oil, aluminium, rubber, tungsten, steel, chromium oraz zasoby dodawane przez mody.
* Cores i claims.

**National Focus Manager**

* Aktualny, ukończony, dostępny i zablokowany focus.
* Kolejka przyszłych focusów.
* Wybór kolejnego focusa po ukończeniu bieżącego.
* Nie kończ natychmiast focusa, jeżeli wymagana jest wyłącznie kolejka.

**Equipment Manager**

* Odczyt zapasów i wariantów wyposażenia.
* Dodawanie i odejmowanie ilości.
* Weryfikacja wyniku.

**Game Tools**

* Lokalne FOW.
* Tryb debugowania.
* Rozróżnienie zmian lokalnych od zmian wspólnych dla sesji.

**Intelligence Lab**

* Wyraźne rozdzielenie rzeczywistego stanu gry od dodatkowych informacji dostępnych wyłącznie debuggerowi.

Nie implementuj fikcyjnych wartości, jeśli dana funkcja jest trudna. Zamiast tego ustal rzeczywisty sposób jej realizacji, wdrażaj i testuj kolejne funkcje w małych etapach.

### Etap E: multiplayer

Docelowo uczestnik sesji multiplayer korzystający z debuggera powinien móc inicjować obsługiwane zmiany wspólnego stanu gry bez ręcznego zatwierdzania każdej operacji przez hosta.

Nie zakładaj jednak, że każda zmiana pamięci jednego klienta zostanie zsynchronizowana.

* Rozróżnij stan lokalnego klienta od stanu wspólnej sesji.
* Ustal, które mechanizmy gry synchronizują zmiany.
* Najpierw przygotuj prywatne środowisko testowe.
* Zweryfikuj zmianę wykonaną przez hosta.
* Następnie zweryfikuj zmianę zainicjowaną przez klienta niebędącego hostem.
* Odczytaj wynik na obu klientach i sprawdź, czy zmiana utrzymuje się po upływie czasu w grze.
* Zbadaj desynchronizację, zgodność wersji i wpływ modów.
* Jeśli konieczny jest pomocniczy mod, przygotuj go jako osobny komponent i udokumentuj wymagania instalacyjne.

Nie deklaruj obsługi multiplayera, dopóki test nie zakończy się powodzeniem na dwóch klientach.

## 4. Testowanie i jakość

Każda nowa funkcja musi mieć odpowiednie testy:

* prawidłowy odczyt;
* poprawna zmiana;
* niezależne potwierdzenie wyniku;
* błędne dane wejściowe;
* brak dostępu do procesu;
* brak uruchomionej gry;
* nieobsługiwana wersja;
* nieaktualne dane;
* obsługa błędów bez uszkadzania gry i zapisów.

Rozdziel testy jednostkowe, testy integracyjne i testy rzeczywistej rozgrywki. Nie twierdź, że test integracyjny lub UI potwierdza zmianę w grze, jeśli nie została ona wykonana.

Po każdym istotnym etapie:

1. Uruchom odpowiednie testy.
2. Napraw regresje.
3. Zaktualizuj `docs/PROGRESS.md`.
4. Zapisz ograniczenia.
5. Utwórz mały, opisowy commit, jeśli testy przechodzą i repozytorium nie ma niezamierzonych zmian.

## 5. Zarządzanie tokenami i czasem pracy

Limit tokenów jest ograniczony. Dlatego:

* Nie powtarzaj przeczytanych raportów w długiej formie.
* Nie twórz kolejnych dokumentów zamiast implementacji.
* Nie wykonuj szerokiego, nieukierunkowanego researchu.
* Wybierz jeden najważniejszy kolejny krok, wykonaj go, przetestuj i dopiero wtedy przejdź dalej.
* Nie przerywaj pracy po samym planie.
* Nie próbuj implementować wszystkich funkcji jednocześnie kosztem jakości.
* Jeśli kończy się kontekst lub limit, zapisz dokładnie aktualny stan pracy, zmienione pliki, wyniki testów i konkretny następny krok w `docs/PROGRESS.md`, aby kolejna sesja mogła bezproblemowo kontynuować.

## 6. Oczekiwane podsumowanie

Na końcu pracy przedstaw krótko:

* Co rzeczywiście zaimplementowano.
* Jakie rzeczywiste operacje na grze wykonano.
* Jak niezależnie zweryfikowano wyniki.
* Jakie testy uruchomiono i jakie były ich wyniki.
* Które funkcje są już zweryfikowane, a które nadal są ograniczone lub niezaimplementowane.
* Czy zmiany zapisano w Git.
* Jaki jest następny konkretny krok.

Zacznij od sprawdzenia repozytorium i aktualnych testów, następnie kontynuuj od pierwszego niezakończonego etapu. Nie proś mnie o wybór między kolejnymi raportami. Samodzielnie podejmuj bezpieczne decyzje techniczne i wykonuj pracę.

**Cel końcowy: działający HOI4 Debugger, nie tylko ładny interfejs. Każdy feature musi być rzeczywiście zaimplementowany, przetestowany i uczciwie opisany.**

