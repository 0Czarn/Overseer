# Format zapisu HOI4 (`.hoi4`): ustalenia i metoda odczytu

Badanie z 2026-10-09 na **kopiach** zapisów z tej maszyny. Objęło 158 plików z wersji 1.16.10–1.19.3
(nagłówki wszystkich plików, pełna struktura 11 plików, po co najmniej jednym z każdej wersji). Oryginały nie były
modyfikowane: do analizy kopiowano je do katalogu tymczasowego, a aplikacja kopiuje je do własnego cache.

## 1. Rozpoznawanie pliku

| Początek pliku | Znaczenie | Obsługa |
|---|---|---|
| `HOI4bin` | zapis binarny (domyślny; `settings.txt`: `save_as_binary=yes`) | ✅ odczyt |
| `HOI4txt` | zapis tekstowy (gra uruchomiona z `-force_text_save`) | ✅ nagłówek + wartości Country Editor (sekcja 8) |
| `PK\x03\x04` | archiwum zip | rozpoznawany, nieobsługiwany |
| pusty / inny | – | błąd `empty` / `unknown_format` |

Wszystkie 158 zapisów na tej maszynie to `HOI4bin`.

## 2. Struktura binarna (zweryfikowana)

Po 7 bajtach `HOI4bin` następuje ciąg 16-bitowych tokenów little-endian:

| Token | Znaczenie | Ładunek |
|---|---|---|
| `0x0001` | `=` | – |
| `0x0003` / `0x0004` | `{` / `}` | – |
| `0x000c` | i32 | 4 B |
| `0x0014` | u32 | 4 B |
| `0x000e` | bool | 1 B |
| `0x000f` / `0x0017` | łańcuch w cudzysłowie / bez | u16 długość + bajty UTF-8 |
| `0x0167`, `0x029c`, `0x0317` | wartości 64-bitowe | 8 B |
| `0x000d` | wartość liczbowa | **4 B w 1.16.x, 8 B od 1.17.0** |
| każdy inny | identyfikator nazwy pola | – |

**Jak to zweryfikowano.** Lekser przechodzi cały plik i sprawdza gramatykę: plik musi kończyć się dokładnie na granicy
tokenu, nawiasy muszą się bilansować, `=` musi następować po kluczu i poprzedzać wartość. Jeden zły rozmiar ładunku
rozsynchronizowuje strumień, a ta kontrola to wykrywa.
- **Wszystkie testowane wersje:** pełna walidacja przechodzi przy podanych rozmiarach.
- **1.16.10:** `0x000d` = 4 B; wariant 8 B daje błąd.
- **1.17.0, 1.17.3, 1.17.5, 1.19.0, 1.19.1, 1.19.3:** `0x000d` = 8 B; wariant 4 B daje niezbilansowane nawiasy.
- **1.18.2, 1.18.3, 1.19.2:** oba warianty przechodzą (przypadkiem). Rozstrzyga reguła wersji (≥ 1.17 → 8 B),
  co UI pokazuje w komunikacie walidacji.

**Algorytm w aplikacji.** Najpierw próbowana jest szerokość wynikająca z wersji w nagłówku. Jeśli cały plik się waliduje,
jest akceptowana. Jeśli nie, próbowana jest druga szerokość. Przy niejednoznaczności bez wersji wynik to `ambiguous`.

**Skala liczb niezweryfikowana.** Skala wartości `0x000d`, `0x0167` i `0x0317` (np. czy to stały przecinek)
**nie została ustalona**. Takie wartości są przechowywane jako surowe bajty i nigdzie nie są prezentowane jako liczby.

## 3. Znaczenie pól (nagłówek)

Gra nie publikuje mapy *identyfikator tokenu → nazwa pola*. Interpretowane są wyłącznie poniższe tokeny
(`backend/hoi4dbg/saves/fields.py`):

| Token | Pole | Status | Dowód |
|---|---|---|---|
| `0x2a35` | kraj gracza zapisującego | verified | = prefiks TAG nazwy pliku w 121/121 zapisach |
| `0x284a` | data w grze | verified | = data z nazwy pliku w 121/121 (godzina w nagłówku 0–6 h późniejsza: gra liczy dalej przed zapisem) |
| `0x00ee` | wersja gry | verified | wartość to pełny ciąg wersji |
| `0x3567` → `0x00e2` | gracze: tag → nazwa konta | verified | klucze to tagi, wartości to nazwy kont; zapisy MP mają wielu graczy (np. 31) |
| `0x3769` | włączone mody | verified | 14/14 nazw = `name=` zainstalowanych plików `.mod` |
| `0x2e3e` | ideologia | inferred | wartości we wszystkich zapisach to nazwy ideologii |
| `0x299f` | poziom trudności | inferred | wartości: easy / normal / hard / very_hard |

**Kodowanie daty** (`i32`): liczba godzin od 1 stycznia 5000 p.n.e., lata 365-dniowe, `godzina = wartość % 24 + 1`.
Na przykład `60769537` → 1937.3.1.2.

**Pola nieustalone** w bloku gracza: `#3035` (bool) i `#000b` (i32). `#000b` **nie** jest unikalnym ID, bo ta sama wartość
występuje u dwóch graczy. Są pokazywane jako `unidentified_fields` i nie są interpretowane.

## 4. Czy potrzebna jest dodatkowa biblioteka?

**Nie.** Do parsowania struktury wystarcza biblioteka standardowa Pythona (`struct`), a format jest prosty i w pełni
zweryfikowany powyżej. Ograniczeniem nie jest parser, tylko brak **nazw pól**. Te trzeba ustalić dla danej wersji gry,
niezależnie od użytej biblioteki. Zalecana metoda: kalibracja na parze zapis binarny / tekstowy tego samego stanu
(`save_as_binary=no`), opisana w raporcie [REPORT-LIVE-AND-WRITE.md](REPORT-LIVE-AND-WRITE.md).

## 5. Wydajność (Python 3.14, Ryzen 5 7600X3D)

- Nagłówek: < 10 ms po skopiowaniu pliku.
- Pełna walidacja struktury: 1,5–6 s dla 30–57 MB. Działa w tle; UI pokazuje „Checking whole-file structure…”.

## 6. Bezpieczeństwo odczytu

- Oryginał jest tylko kopiowany (`shutil.copyfile`) do `%LOCALAPPDATA%\HOI4Debugger\save-cache`. Wszystkie odczyty idą z kopii.
  Cache trzyma 3 ostatnie kopie.
- Plik zmodyfikowany < 3 s temu albo zmieniony w trakcie kopiowania → `in_progress` (gra może jeszcze pisać), ponowna próba później.
- Nazwa zapisu z UI jest akceptowana tylko wtedy, gdy dokładnie odpowiada plikowi z listingu folderu (ochrona przed path traversal).
- Twardy limit rozmiaru bloków nagłówka chroni przed nieoczekiwanie dużymi lub złośliwymi plikami.

## 7. Aktualność danych w UI

Zapis to zawsze **migawka** (`is_live: false`). UI przy każdym panelu SAVE pokazuje nazwę pliku, datę w grze,
czas zapisania pliku z wiekiem oraz kategorię:
- `current_session`: plik zapisany po starcie bieżącego procesu gry, ale gra od tego czasu poszła dalej;
- `previous_session`: **wcześniejsza sesja, NIE jest to obecny stan gry** (czerwony);
- `game_not_running` / `unknown_session`.

Dodatkowo UI sprawdza zgodność wersji zapisu z uruchomioną grą (porównanie bez sufiksu w nawiasie,
który różni się między zapisami tego samego buildu) i oznacza zapis, który nie jest najnowszy.

## 8. Zapisy tekstowe (`-force_text_save`), potwierdzone 2026-10-09

**Jak uzyskane.** W `hoi4.exe` ciąg `force_text_save` leży na liście parametrów linii poleceń (obok `debug`, `nofilewatcher`,
`start_save`). Użytkownik uruchomił grę z `-force_text_save` i wykonał `savegame`. Powstał `PROJEKT-OVERSEER.hoi4`
(62,6 MB, zaczyna się od `HOI4txt`). `settings.txt` nie był zmieniany. Gra zapisuje ten plik przy starcie i wyjściu,
więc jego edycja przy działającej grze byłaby zawodna.

**Nagłówek w formie tekstowej** potwierdza znaczenia ustalone wcześniej dla tokenów binarnych:
`player` (0x2a35), `ideology` (0x2e3e), `date` (0x284a), `difficulty` (0x299f), `version` (0x00ee),
`player_countries` (0x3567) → `user` (0x00e2), `country_leader` (#3035), `id` (#000b), `mods` (0x3769).

**Pola Country Editor** (blok `countries={ TAG={ ... } }`, odczytane z prawdziwego pliku):

| Pole | Ścieżka w bloku państwa | GER w PROJEKT-OVERSEER |
|---|---|---|
| Political Power | `politics.political_power` | 2.324 |
| Stability | `stability` (0–1) | 0.7 |
| War Support | `war_support` (0–1) | 0.3 |
| Command Power | `command_power` | 0.286 |
| Fuel | `fuel_status.fuel` | 297201.86508 |
| Army Experience | `experience_status.army_experience` | 30.0 |
| Air / Navy Experience | `experience_status.air_experience` / `navy_experience` | brak w pliku (gra pomija wartości, prawdopodobnie zerowe) |
| Manpower | **nie zlokalizowano**. W bloku jest tylko `manpower.ratio`. | – |
| Convoys | **niepotwierdzone**. `convoys.equipment` zawiera ilości dla ID sprzętu. | – |

Kontrola: SOV PP 1.5856, ENG PP 2.3182. Wartości różnią się między państwami, a bloki są poprawnie rozgraniczone.

**Parser** (`saves/text.py`) wycina tylko potrzebne fragmenty (nagłówek, jeden blok państwa). Czas: nagłówek ~1 ms,
blok państwa ~0,05 s.

**Zapisy binarne.** Te same wartości są w nich zakodowane, ale identyfikatorów tokenów dla `politics`, `political_power`
itd. nie ustalono, a skala wartości liczbowych jest niezweryfikowana. Odczyt wartości państw działa więc tylko dla zapisów tekstowych.
