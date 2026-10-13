Kontynuujemy rozwój istniejącego HOI4 Debuggera. Przeczytaj , `docs/PROGRESS.md` i `docs/REPORT-LIVE-AND-WRITE.md`. Nie przepisuj raportów od nowa i nie zatrzymuj się na planowaniu.

### Decyzje

* Nie twórz teraz kolejnego raportu wykonalności, chyba że jest niezbędny do udokumentowania nowych ustaleń.
* Usunięcie pustego `zalozenia.md` bylo specjalnie, nie jest potrzebny.
* Zachowaj dotychczasowe commity i wszystkie dziewięć zakładek.
* Możesz przeprowadzić analizę pamięci procesu HOI4 oraz użyć odpowiednich narzędzi reverse engineeringu. Najpierw sprawdź uprawnienia, wersję gry i wymagane narzędzia. Nie zmieniaj pamięci procesu, dopóki nie rozpoznasz wiarygodnie struktury danych i nie przygotujesz testu bezpieczeństwa.

### Zadanie A — uruchom testy ponownie

Uruchom rzeczywiste testy backendu, JS i UI. Podaj aktualne wyniki, a nie tylko liczby skopiowane z dokumentacji. Sprawdź również `git status`.

### Zadanie B — ustal źródło danych aktywnej gry

Zbadaj, jak odczytać aktualny Political Power i pozostałe wartości z działającego `hoi4.exe`.
Sprawdź kolejno:

1. istniejące mechanizmy gry i źródła diagnostyczne;
2. odczyt pamięci procesu;
3. narzędzia reverse engineeringu, jeśli są rzeczywiście potrzebne.

Nie zakładaj, że odczyt zapisu jest odczytem na żywo. Nie zgaduj adresów ani offsetów. Sprawdź, czy odczyt zgadza się z grą i czy pozostaje poprawny po zmianie dnia w grze.

Jeśli analiza jest zablokowana przez uprawnienia, ustal dokładnie, które uprawnienie jest wymagane, dlaczego i do jakiej operacji. Nie omijaj zabezpieczeń systemu.

### Zadanie C — pierwszy edytor obsługiwany przez aplikację

Użyj Political Power jako pierwszego pełnego przykładu:

* pokaż aktualną, rzeczywistą wartość;
* pozwól użytkownikowi wybrać docelową wartość lub zmianę;
* wykonaj operację przez udokumentowaną komendę gry lub inną zweryfikowaną metodę;
* odczytaj wartość ponownie niezależną metodą;
* pokaż potwierdzony rezultat albo konkretny błąd.

Nie wymagaj ręcznego przepisywania komendy przez użytkownika, jeśli aplikacja może bezpiecznie wykonać obsługiwaną operację. Nie twierdź, że edycja pamięci jest konieczna, dopóki tego nie wykażesz.

Zacznij od gry jednoosobowej i zastosuj bezpieczne ograniczenia. Nie modyfikuj zapisów ani pamięci w sposób eksperymentalny bez kopii, kontroli zakresu i możliwości przerwania.

### Zadanie D — dalsze funkcje

Po ukończeniu Political Power przejdź do pozostałych pól Country Editor, następnie State Editor, Equipment Manager, National Focus Manager, Countries & Players, Game Tools i Intelligence Lab. W pierwszej kolejności implementuj funkcje, dla których da się wykazać prawdziwy odczyt i zweryfikowaną zmianę.

Każda funkcja ma być oznaczona jako działająca, ograniczona lub niezaimplementowana. Usuń dane DEMO z miejsc, w których mogą być mylone z rzeczywistym stanem gry.

### Zadanie E — multiplayer

Nie deklaruj synchronizacji, dopóki nie przeprowadzisz testu na dwóch klientach. Zbadaj osobno zmianę inicjowaną przez klienta niebędącego hostem. Jeśli będzie potrzebny pomocniczy mod, uzasadnij to i przygotuj go jako osobny etap.

### Raport końcowy

Podaj:

* pliki zmienione w tej sesji;
* rzeczywiście wykonane operacje;
* aktualne wyniki wszystkich testów;
* co działa w aplikacji, a co nadal wymaga ręcznej czynności;
* czego nie udało się zrobić i dlaczego;
* konkretny następny krok.

Nie kończ po samym sporządzeniu raportu. Wykonaj tyle implementacji i testów, ile rzeczywiście możesz bezpiecznie przeprowadzić w tej sesji.
