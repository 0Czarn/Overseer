Zatwierdzam metodę A jako pierwszy krok. Chcę jednak, aby była częścią docelowego HOI4 Debuggera, a nie końcem projektu.

1. Zaimplementuj odczyt rzeczywistych danych z plików zapisu HOI4, zaczynając od nagłówka i przypisań graczy do państw.
2. Zbadaj format binarny HOI4bin i wybierz sprawdzoną metodę parsowania. Nie zakładaj, że cały zapis jest zwykłym tekstem.
3. Jeśli pełne parsowanie wymaga dodatkowej biblioteki, najpierw wyjaśnij, dlaczego jest potrzebna.
4. W interfejsie wyraźnie oznacz źródło danych, datę zapisu i ich aktualność. Nie pokazuj danych z poprzedniego zapisu jako aktualnego stanu gry.
5. Dodaj obsługę błędnych, niekompletnych i nieobsługiwanych zapisów.
6. Przetestuj rozwiązanie na kopii zapisu, nie modyfikując oryginału.
7. Uzupełnij docs/PROGRESS.md i dodaj testy.
8. Zachowaj obecną aplikację i jej dziewięć zakładek.

Następnie przygotuj osobny raport o tym, jak przejść od odczytu save'a do odczytu aktywnej rozgrywki i bezpiecznej modyfikacji wartości.

Nie implementuj jeszcze zapisu do pamięci procesu ani modyfikacji save'a. Nie twierdź, że multiplayer jest zsynchronizowany bez testu.

Na końcu uruchom wszystkie testy i przedstaw podsumowanie: jakie pola faktycznie odczytujesz, z jakiego źródła pochodzą i jakie ograniczenia nadal pozostają.
