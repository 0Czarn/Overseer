// Interface language (Options > Language). The app is written in English; tr() gives the Polish text of the
// sidebar, view headers, card and tile titles, the top bar and the Options tab. Names read from the game stay as the
// game has them.
import { loadOptions } from './options.js';

const PL = {
  // tabs and view headers
  Dashboard: 'Pulpit', 'Game summary': 'Podsumowanie gry', 'Players actions': 'Działania graczy',
  'Countries & Players': 'Państwa i gracze', 'Country Editor': 'Edytor państwa', Research: 'Badania',
  Construction: 'Budowa', 'Army/Air/Navy': 'Armia/Lotnictwo/Flota', 'State Editor': 'Edytor regionów',
  'National Focus Manager': 'Menedżer narodowych celów', 'Equipment Manager': 'Menedżer sprzętu', 'Game Tools': 'Narzędzia gry',
  'Logs & Test Reports': 'Logi i raporty testów', Options: 'Ustawienia',
  'Divisions, air wings, ships and doctrines of the selected country (game memory).':
    'Dywizje, skrzydła lotnicze, okręty i doktryny wybranego państwa (pamięć gry).',
  'What the selected country builds and has queued, with the progress of each line (game memory).':
    'Co buduje wybrane państwo i co ma w kolejce, z postępem każdej linii (pamięć gry).',
  'Pick any country to inspect - independent of the country you control.':
    'Wybierz dowolne państwo do podglądu - niezależnie od tego, którym grasz.',
  'Political, military and logistic values of the selected country.': 'Wartości polityczne, wojskowe i logistyczne wybranego państwa.',
  'Stockpiles and variants of the selected country.': 'Magazyny i warianty sprzętu wybranego państwa.',
  'IC a day per country over the campaign, recorded from game memory while the app runs.':
    'IC dziennie dla każdego państwa w czasie kampanii, nagrywane z pamięci gry, gdy aplikacja działa.',
  'Local debugging and visibility helpers.': 'Lokalne narzędzia diagnostyczne i podglądu.',
  'Focus tree of the selected country, its state and your planned order.': 'Drzewko celów wybranego państwa, jego stan i Twoja planowana kolejność.',
  'Settings of this app - nothing here changes the game.': 'Ustawienia aplikacji - nic tutaj nie zmienia gry.',
  'What the player and the watched countries did, day by day - read from game memory while the app runs.':
    'Co robił gracz i obserwowane państwa, dzień po dniu - z pamięci gry, gdy aplikacja działa.',
  'Research slots of the selected country and what each one researches.': 'Sloty badań wybranego państwa i co jest w nich badane.',
  'Owner vs controller, buildings, resources, cores and claims.': 'Właściciel i kontroler, budynki, zasoby, rdzenie i roszczenia.',
  // card and tile titles
  'Add equipment (verified)': 'Dodaj sprzęt (weryfikowane)', Appearance: 'Wygląd', 'Application log': 'Log aplikacji',
  Countries: 'Państwa', 'Current focus': 'Obecny cel', 'Data sources': 'Źródła danych', Details: 'Szczegóły',
  'Game process': 'Proces gry', 'Game version': 'Wersja gry', 'HOI4 logs': 'Logi HOI4', 'HOI4 logs (read-only)': 'Logi HOI4 (tylko odczyt)',
  'Live session': 'Sesja na żywo', 'Local tools': 'Narzędzia lokalne', 'New test report': 'Nowy raport testu',
  'Newest save file': 'Najnowszy zapis', Paths: 'Ścieżki', 'Planned order': 'Planowana kolejność',
  'Players (from save file)': 'Gracze (z zapisu)', 'Political Power - change test (diagnostic)': 'Political Power - test zmiany (diagnostyka)',
  'Recent warnings': 'Ostatnie ostrzeżenia', 'Saved reports': 'Zapisane raporty', 'Session hints': 'Wskazówki sesji',
  'Shared-state tools': 'Narzędzia stanu wspólnego', States: 'Regiony', 'Technical data': 'Dane techniczne',
  'Window and tabs': 'Okno i zakładki', Leadership: 'Przywództwo', 'National spirits': 'Duchy narodowe',
  'Government & staff': 'Rząd i sztab', Factories: 'Fabryki', 'Resources (per day)': 'Zasoby (dziennie)',
  'Research slots': 'Sloty badań', 'Research tabs & technology tree': 'Karty badań i drzewko technologii',
  'Construction queue': 'Kolejka budowy', Army: 'Armia', 'Air Force': 'Lotnictwo', Navy: 'Flota', Doctrines: 'Doktryny',
  Notifications: 'Powiadomienia', 'Live reading': 'Odczyt na żywo', 'Language and numbers': 'Język i liczby',
  Data: 'Dane', 'Text and keyboard': 'Tekst i klawiatura', 'More ideas': 'Więcej pomysłów',
  // top bar
  'On top': 'Na wierzchu', Compact: 'Kompaktowy', 'Reset tab order': 'Przywróć kolejność zakładek',
};

/** The text in the chosen language (English when there is no translation). */
export function tr(text) {
  return loadOptions().lang === 'pl' ? PL[text] ?? text : text;
}

/** For the Options tab: English and Polish side by side - tt('Show', 'Pokaż'). */
export function tt(en, pl) {
  return loadOptions().lang === 'pl' ? pl : en;
}
