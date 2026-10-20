// Options: settings of the app itself - the style (1984 / classic), the Overseer's eye, the user's own background
// images (JPG / PNG, kept by the backend in <data dir>/backgrounds) with their transparency, the window and the tabs,
// Windows notifications, the pace of live reading, language and number format, the data folder (sizes, old
// recordings, export / import of these settings), text size and keyboard shortcuts. Texts in English or Polish (tt).
import { h, card, notice, toast, viewHeader } from '../lib/dom.js';
import { tt } from '../lib/i18n.js';
import { FITS, LANGS, NUMBERS, OVERLAY_FIELDS, PLAYERS_RAIL, REFRESH, TEXT_MAX, TEXT_MIN, THEMES, applyOptions, backgroundUri,
  loadOptions, saveOptions } from '../lib/options.js';
import { loadCountries } from './shared.js';
import { SHORTCUTS } from '../lib/shortcuts.js';

const MAX_MB = 12;
const SETTINGS_PREFIX = 'hoi4dbg.';   // every localStorage key of this app (exported / imported together)

function readFile(file, as = 'dataURL') {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error ?? new Error('The file could not be read'));
    if (as === 'text') reader.readAsText(file); else reader.readAsDataURL(file);
  });
}

/** "1.4 MB" / "820 KB" */
export function sizeText(bytes) {
  if (!Number.isFinite(bytes)) return '—';
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

/** The app's settings from localStorage as {key: value} (export). */
export function collectSettings(storage) {
  const out = {};
  for (let i = 0; i < storage.length; i += 1) {
    const key = storage.key(i);
    if (key?.startsWith(SETTINGS_PREFIX)) out[key] = storage.getItem(key);
  }
  return out;
}

/** Settings of an exported file checked: only this app's keys with text values. */
export function checkSettingsFile(data) {
  const settings = data?.app === 'The OVERSEER' ? data.settings : null;
  if (!settings || typeof settings !== 'object') throw new Error('Not a settings file of The OVERSEER');
  const entries = Object.entries(settings).filter(([k, v]) => k.startsWith(SETTINGS_PREFIX) && typeof v === 'string');
  if (!entries.length) throw new Error('The file holds no settings');
  return Object.fromEntries(entries);
}

function slider(value, min, max, onInput, unit = '%') {
  const out = h('output', { class: 'opt-value' }, `${value}${unit}`);
  const input = h('input', { type: 'range', min, max, step: 1, value, class: 'opt-range',
    oninput: (e) => { out.textContent = `${e.target.value}${unit}`; onInput(+e.target.value); } });
  return h('span', { class: 'opt-slider' }, input, out);
}

function row(label, hint, ...control) {
  return h('div', { class: 'opt-row' }, h('div', { class: 'opt-label' }, h('strong', null, label), hint ? h('span', { class: 'muted' }, hint) : null),
    h('div', { class: 'opt-control' }, ...control));
}

function check(checked, onChange, label) {
  return h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: checked || null, onchange: (e) => onChange(e.target.checked) }),
    h('span', null, label));
}

function seg(items, value, onPick) {
  return h('div', { class: 'gs-seg' }, items.map(([k, label]) => h('button', {
    class: `gs-seg-btn ${value === k ? 'gs-seg-on' : ''}`, 'aria-pressed': String(value === k), onclick: () => onPick(k) }, label)));
}

const fill = (el, items) => el.replaceChildren(...items.filter(Boolean));   // replaceChildren would print a null

export default {
  id: 'options',
  title: 'Options',
  short: 'OP',
  async render(root, ctx) {
    let o = loadOptions();
    let images = [];
    let busy = false;
    let usage = null;
    const set = (patch, rerender = false) => {
      o = { ...o, ...patch };
      saveOptions(o);
      applyOptions(o, ctx.api);
      if (rerender) draw();
    };
    const appearance = h('div');
    const gallery = h('div', { class: 'opt-gallery' });
    const layout = h('div');
    const notes = h('div');
    const reading = h('div');
    const mpBox = h('div');
    let mp = null;        // backend: local memory writes allowed in multiplayer (live/service.multiplayer_writes)
    const language = h('div');
    const data = h('div');
    const keyboard = h('div');
    const tabs = h('div');
    const desktopBox = h('div');
    const overlayBox = h('div');
    let desk = null;      // desktop integration state from the main process (desktop.cjs)
    let countries = [];

    async function setDesk(patch) {
      try { desk = await ctx.bridge.setDesktop(patch); } catch (err) { toast(err.message, 'error'); }
      draw();
    }

    async function loadImages() {
      try {
        images = (await ctx.api.get('/api/backgrounds')).data;
      } catch (err) {
        images = [];
        gallery.replaceChildren(notice('warn', `${tt('Background images unavailable', 'Tła niedostępne')}: ${err.message}`));
        return;
      }
      if (o.image && !images.some((b) => b.id === o.image)) set({ image: null });
      drawGallery();
    }

    async function addImages(files) {
      busy = true;
      drawGallery();
      for (const file of files) {
        if (!/\.(jpe?g|png)$/i.test(file.name) || !/^image\/(jpeg|png)$/.test(file.type)) {
          toast(`${file.name}: ${tt('only JPG and PNG images', 'tylko obrazy JPG i PNG')}`, 'error');
          continue;
        }
        if (file.size > MAX_MB * 1024 * 1024) {
          toast(`${file.name}: ${tt('larger than', 'większy niż')} ${MAX_MB} MB`, 'error');
          continue;
        }
        try {
          const item = (await ctx.api.post('/api/backgrounds', { name: file.name, data: await readFile(file) })).data;
          images.push(item);
          set({ image: item.id });
          toast(`${tt('Background added', 'Dodano tło')}: ${file.name}`, 'ok');
        } catch (err) {
          toast(`${file.name}: ${err.message}`, 'error');
        }
      }
      busy = false;
      drawGallery();
      loadUsage();
    }

    async function removeImage(b) {
      if (!window.confirm(`${tt('Delete the background', 'Usunąć tło')} ${b.name}?`)) return;
      try {
        images = (await ctx.api.post(`/api/backgrounds/${b.id}/delete`, {})).data;
        if (o.image === b.id) set({ image: null });
        drawGallery();
        loadUsage();
      } catch (err) {
        toast(`${tt('Not deleted', 'Nie usunięto')}: ${err.message}`, 'error');
      }
    }

    function thumb(b) {
      const box = h('button', { class: `opt-thumb ${o.image === b.id ? 'opt-thumb-on' : ''}`, title: b.name,
        'aria-pressed': String(o.image === b.id), onclick: () => { set({ image: b.id }, true); drawGallery(); } },
      h('span', { class: 'opt-thumb-name' }, b.name));
      backgroundUri(ctx.api, b.id).then((uri) => { box.style.backgroundImage = `url("${uri}")`; }, () => box.classList.add('opt-thumb-bad'));
      return h('div', { class: 'opt-thumb-wrap' }, box,
        h('button', { class: 'opt-thumb-del', title: `${tt('Delete', 'Usuń')} ${b.name}`, onclick: () => removeImage(b) }, '×'));
    }

    function drawGallery() {
      const input = h('input', { type: 'file', accept: '.jpg,.jpeg,.png,image/jpeg,image/png', multiple: true, hidden: true,
        onchange: (e) => { addImages([...e.target.files]); e.target.value = ''; } });
      gallery.replaceChildren(
        h('div', { class: 'opt-thumb-wrap' }, h('button', { class: `opt-thumb opt-thumb-none ${o.image ? '' : 'opt-thumb-on'}`,
          'aria-pressed': String(!o.image), onclick: () => { set({ image: null }, true); drawGallery(); } }, tt('No image', 'Bez obrazu'))),
        ...images.map(thumb),
        h('div', { class: 'opt-thumb-wrap' }, h('button', { class: 'opt-thumb opt-thumb-add', disabled: busy || null,
          onclick: () => input.click() }, busy ? tt('Adding…', 'Dodawanie…') : tt('+ Add image', '+ Dodaj obraz')), input));
    }

    async function loadUsage() {
      try {
        usage = (await ctx.api.get('/api/data/usage')).data;
      } catch (err) {
        usage = { error: err.message };
      }
      drawData();
    }

    async function deleteCampaign(g) {
      if (!window.confirm(`${tt('Delete the recorded campaign', 'Usunąć nagraną kampanię')} ${g.player} ${g.first ?? ''} → ${g.last ?? ''}?`)) return;
      try {
        await ctx.api.post(`/api/summary/games/${encodeURIComponent(g.id)}/delete`, {});
        toast(tt('Campaign deleted', 'Kampania usunięta'), 'ok');
      } catch (err) {
        toast(`${tt('Not deleted', 'Nie usunięto')}: ${err.message}`, 'error');
      }
      loadUsage();
    }

    function exportSettings() {
      const file = { app: 'The OVERSEER', exported: new Date().toISOString(), settings: collectSettings(localStorage) };
      const url = URL.createObjectURL(new Blob([JSON.stringify(file, null, 1)], { type: 'application/json' }));
      const a = h('a', { href: url, download: `overseer-settings-${new Date().toISOString().slice(0, 10)}.json` });
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 5000);
    }

    async function importSettings(file) {
      try {
        const settings = checkSettingsFile(JSON.parse(await readFile(file, 'text')));
        if (!window.confirm(tt(`Replace the settings of this app with ${Object.keys(settings).length} from ${file.name}? The app reloads.`,
          `Zastąpić ustawienia aplikacji ${Object.keys(settings).length} wpisami z ${file.name}? Aplikacja się przeładuje.`))) return;
        for (const [k, v] of Object.entries(settings)) localStorage.setItem(k, v);
        location.reload();
      } catch (err) {
        toast(`${tt('Settings not imported', 'Nie zaimportowano ustawień')}: ${err.message}`, 'error');
      }
    }

    function drawData() {
      const importInput = h('input', { type: 'file', accept: '.json,application/json', hidden: true,
        onchange: (e) => { if (e.target.files[0]) importSettings(e.target.files[0]); e.target.value = ''; } });
      fill(data, [
        row(tt('Data folder', 'Folder danych'), usage?.path ?? '', h('button', { class: 'btn btn-small', onclick: async () => {
          const res = await ctx.bridge.openDataFolder();
          if (!res.ok) toast(res.error, 'error');
        } }, tt('Open folder', 'Otwórz folder'))),
        usage?.error ? notice('warn', usage.error) : null,
        usage?.parts ? row(tt('Used space', 'Zajęte miejsce'), `${tt('Total', 'Razem')} ${sizeText(usage.total)}`,
          h('table', { class: 'opt-table' }, usage.parts.map((p) => h('tr', null, h('td', null, p.label),
            h('td', { class: 'num' }, sizeText(p.size)), h('td', { class: 'num muted' }, `${p.files} ${tt('files', 'plików')}`))))) : null,
        usage?.campaigns ? row(tt('Recorded campaigns', 'Nagrane kampanie'),
          tt('Delete the ones you no longer need (the one being recorded stays).', 'Usuń niepotrzebne (nagrywana zostaje).'),
          usage.campaigns.length ? h('table', { class: 'opt-table' }, usage.campaigns.map((g) => h('tr', null,
            h('td', null, h('strong', null, g.player ?? '?'), ` ${g.first ?? '-'} → ${g.last ?? '-'}`),
            h('td', { class: 'muted' }, `${tt('started', 'od')} ${(g.created ?? '').slice(0, 16)}`),
            h('td', { class: 'num' }, sizeText(g.size)),
            h('td', null, g.active ? h('span', { class: 'gs-camp-rec' }, tt('recording', 'nagrywana'))
              : h('button', { class: 'btn btn-small btn-ghost', onclick: () => deleteCampaign(g) }, tt('Delete', 'Usuń'))))))
            : h('span', { class: 'muted' }, tt('None yet.', 'Jeszcze brak.'))) : null,
        row(tt('Automatic clean-up', 'Automatyczne sprzątanie'), tt('At every start; 0 = off. The campaign being recorded stays.',
          'Przy każdym starcie; 0 = wyłączone. Nagrywana kampania zostaje.'),
          h('label', { class: 'opt-num' }, tt('Delete recordings older than', 'Usuń nagrania starsze niż'),
            h('input', { type: 'number', class: 'input', min: 0, max: 3650, value: o.cleanupDays, onchange: (e) => set({ cleanupDays: +e.target.value }) }),
            tt('days', 'dni')),
          h('label', { class: 'opt-num' }, tt('Keep the data folder under', 'Folder danych poniżej'),
            h('input', { type: 'number', class: 'input', min: 0, max: 100000, value: o.cleanupMB, onchange: (e) => set({ cleanupMB: +e.target.value }) }),
            'MB'),
          h('button', { class: 'btn btn-small', onclick: async () => {
            try {
              const res = (await ctx.api.post('/api/data/cleanup', { days: o.cleanupDays, limit_mb: o.cleanupMB })).data;
              toast(`${tt('Deleted', 'Usunięto')}: ${res.deleted.length}`, 'ok');
            } catch (err) { toast(err.message, 'error'); }
            loadUsage();
          } }, tt('Clean up now', 'Posprzątaj teraz'))),
        row(tt('These settings', 'Te ustawienia'), tt('Save them to a file or load them on another computer.', 'Zapisz do pliku albo wczytaj na innym komputerze.'),
          h('button', { class: 'btn btn-small', onclick: exportSettings }, tt('Export…', 'Eksportuj…')),
          h('button', { class: 'btn btn-small', onclick: () => importInput.click() }, tt('Import…', 'Importuj…')), importInput),
      ]);
    }

    async function loadMp() {
      try { mp = (await ctx.api.get('/api/live/multiplayer-writes')).data; } catch (err) { mp = { error: err.message }; }
      drawMp();
    }

    async function setMp(enabled) {
      if (enabled && !window.confirm(tt('Edits in multiplayer change the game memory of THIS computer only. The other players '
        + 'do not get them - the game may desync (out of sync / rehost). Allow?', 'Edycje w multiplayerze zmieniają pamięć gry '
        + 'tylko na TYM komputerze. Inni gracze ich nie dostaną - gra może się rozsynchronizować (desync / rehost). Zezwolić?'))) {
        drawMp();
        return;
      }
      try { mp = (await ctx.api.post('/api/live/multiplayer-writes', { enabled, confirm_desync: enabled })).data; }
      catch (err) { toast(err.message, 'error'); }
      drawMp();
    }

    async function setMpFog(fog) {
      if (fog && !window.confirm(tt('Without fog you see the other players\' units and moves, they do not see yours. '
        + 'It changes only what this computer shows (no desync). Use it only if the other players agree. Allow?',
        'Bez mgły widzisz wojska i ruchy innych graczy, a oni Twoich nie. Zmienia to tylko widok na tym komputerze '
        + '(bez desyncu). Używaj tylko za zgodą pozostałych graczy. Zezwolić?'))) {
        drawMp();
        return;
      }
      try { mp = (await ctx.api.post('/api/live/multiplayer-writes', { fog, confirm_fog: fog })).data; }
      catch (err) { toast(err.message, 'error'); }
      drawMp();
    }

    function drawMp() {
      fill(mpBox, [
        mp?.error ? notice('warn', mp.error) : null,
        row(tt('Edits in multiplayer', 'Edycja w multiplayerze'),
          tt('Value edits, stockpile, focus queue auto-start, factory auto-sort and fog of war also in a multiplayer game. '
            + 'Local to this computer - may cause a desync.', 'Edycja wartości, magazynu, auto-start celów z kolejki, sortowanie '
            + 'fabryk i mgła wojny także w grze multiplayer. Tylko na tym komputerze - może spowodować desync.'),
          check(mp?.enabled, setMp, tt('Allow (may desync)', 'Zezwól (możliwy desync)')),
          mp?.mode ? h('span', { class: 'muted' }, tt(`Game now: ${mp.mode}`, `Gra teraz: ${mp.mode}`)) : null),
        row(tt('Fog of war in multiplayer', 'Mgła wojny w multiplayerze'),
          tt('The "Map without fog" switch (Game Tools) also in a multiplayer game. Only this computer\'s view - '
            + 'no desync, but you see what the others cannot.', 'Przełącznik "Map without fog" (Game Tools) także w grze '
            + 'multiplayer. Tylko widok na tym komputerze - bez desyncu, ale widzisz to, czego inni nie widzą.'),
          check(mp?.fog, setMpFog, tt('Allow', 'Zezwól'))),
      ]);
    }

    function draw() {
      fill(tabs, [
        row(tt('Shown tabs', 'Widoczne zakładki'), tt('Hide the tabs you do not use (Options always stays).', 'Ukryj nieużywane zakładki (Ustawienia zostają zawsze).'),
          h('div', { class: 'opt-checks' }, ctx.views.filter((v) => v.id !== 'options').map((v) => check(!o.hiddenTabs.includes(v.id), (show) => {
            set({ hiddenTabs: show ? o.hiddenTabs.filter((t) => t !== v.id) : [...o.hiddenTabs, v.id] });
            ctx.renderNav?.();
          }, v.title)))),
        row(tt('Favourite country', 'Ulubione państwo'), tt('Pinned first (★) in every country picker.', 'Przypięte na górze (★) każdej listy państw.'),
          h('select', { class: 'input', onchange: (e) => set({ favCountry: e.target.value }) },
            h('option', { value: '' }, tt('None', 'Brak')),
            countries.map((c) => h('option', { value: c.tag, selected: o.favCountry === c.tag || null }, `${c.tag} - ${c.name}`)))),
        row(tt('Players list', 'Lista graczy'), tt('The players of the session left of the tabs.', 'Gracze sesji po lewej stronie zakładek.'),
          seg(Object.entries(PLAYERS_RAIL).map(([k, label]) => [k, tt(label, { mp: 'W multiplayerze', always: 'Zawsze', never: 'Nigdy' }[k])]),
            o.playersRail, (k) => { set({ playersRail: k }, true); ctx.playersRail?.redraw(); })),
      ]);
      fill(desktopBox, desk ? [
        row(tt('Start with Windows', 'Start z Windows'), null,
          check(desk.openAtLogin, (v) => setDesk({ openAtLogin: v }), tt('Enabled', 'Włączony')),
          check(desk.startHidden, (v) => setDesk({ startHidden: v }), tt('Start hidden in the tray', 'Start ukryty w zasobniku'))),
        row(tt('Tray', 'Zasobnik'), tt('The icon next to the clock: click shows the window, right click has a menu.', 'Ikona przy zegarze: kliknięcie pokazuje okno, prawy przycisk - menu.'),
          check(desk.closeToTray, (v) => setDesk({ closeToTray: v }), tt('Closing the window hides it in the tray', 'Zamknięcie okna chowa je do zasobnika')),
          check(desk.minimizeToTray, (v) => setDesk({ minimizeToTray: v }), tt('Minimising hides it in the tray', 'Minimalizacja chowa do zasobnika'))),
        row(tt('With the game', 'Razem z grą'), tt('With "start with Windows" in the tray: the app waits for the game.', 'Ze "startem z Windows" w zasobniku: aplikacja czeka na grę.'),
          check(o.showOnGame, (v) => set({ showOnGame: v }), tt('Show the window when the game starts', 'Pokaż okno, gdy gra się uruchomi'))),
      ] : [notice('warn', tt('Desktop settings are not available in this window.', 'Ustawienia pulpitu niedostępne w tym oknie.'))]);
      fill(overlayBox, [
        row(tt('Overlay over the game', 'Nakładka nad grą'), tt('A small window always on top. The game must run in "borderless" or windowed mode.',
          'Małe okno zawsze na wierzchu. Gra musi działać w trybie okna bez ramki albo w oknie.'),
          check(desk?.overlay, async (v) => { try { await ctx.bridge.setOverlay(v); desk = await ctx.bridge.desktop(); } catch (err) { toast(err.message, 'error'); } draw(); },
            tt('Show', 'Pokaż')),
          check(desk?.overlayLocked, (v) => setDesk({ overlayLocked: v }), tt('Lock (clicks pass through to the game)', 'Zablokuj (kliknięcia trafiają do gry)'))),
        row(tt('Values', 'Wartości'), tt('Of your country, read from game memory.', 'Twojego państwa, z pamięci gry.'),
          h('div', { class: 'opt-checks' }, Object.entries(OVERLAY_FIELDS).map(([k, label]) => check(o.overlayFields.includes(k),
            (v) => set({ overlayFields: v ? [...o.overlayFields, k] : o.overlayFields.filter((f) => f !== k) }), label)))),
        row(tt('Overlay transparency', 'Przezroczystość nakładki'), null, slider(o.overlayOpacity, 20, 100, (v) => set({ overlayOpacity: v }))),
      ]);
      fill(appearance, [
        row(tt('Style', 'Styl'), tt('Colours, fonts and the look of the panels.', 'Kolory, czcionki i wygląd paneli.'),
          seg(Object.entries(THEMES), o.theme, (k) => set(k === 'classic' ? { theme: k, eye: false } : { theme: k, eye: true }, true))),
        row(tt('The Overseer\'s eye', 'Oko Nadzorcy'), tt('The large eye behind the views.', 'Duże oko za widokami.'),
          check(o.eye, (v) => set({ eye: v }, true), tt('Show', 'Pokaż')),
          o.eye ? slider(o.eyeOpacity, 0, 100, (v) => set({ eyeOpacity: v })) : null),
        row(tt('Eye behaviour', 'Zachowanie oka'), tt('Also the eye of the logo.', 'Także oko w logo.'),
          check(o.eyeTrack, (v) => set({ eyeTrack: v }), tt('Follows the cursor', 'Śledzi kursor')),
          check(o.eyeBlink, (v) => set({ eyeBlink: v }), tt('Blinks', 'Mruga'))),
        row(tt('Background image', 'Obraz tła'), tt(`Your own JPG or PNG images (up to ${MAX_MB} MB each), kept in the app's data folder.`,
          `Własne obrazy JPG lub PNG (do ${MAX_MB} MB każdy), w folderze danych aplikacji.`), gallery),
        o.image ? row(tt('Image transparency', 'Przezroczystość obrazu'), tt('0% = invisible, 100% = full image.', '0% = niewidoczny, 100% = pełny obraz.'),
          slider(o.imageOpacity, 0, 100, (v) => set({ imageOpacity: v }))) : null,
        o.image ? row(tt('Image placement', 'Ułożenie obrazu'), null,
          h('select', { class: 'input', onchange: (e) => set({ imageFit: e.target.value }) },
            Object.entries(FITS).map(([k, label]) => h('option', { value: k, selected: o.imageFit === k || null }, label))),
          h('span', { class: 'muted' }, tt('Blur', 'Rozmycie')), slider(o.imageBlur, 0, 20, (v) => set({ imageBlur: v }), ' px')) : null,
        row('', null, h('button', { class: 'btn btn-small btn-ghost', onclick: () => {
          set({ theme: '1984', eye: true, eyeOpacity: 22, eyeTrack: true, eyeBlink: true, image: null, imageOpacity: 35,
            imageFit: 'cover', imageBlur: 0 }, true);
          drawGallery();
        } }, tt('Restore the default look', 'Przywróć domyślny wygląd'))),
      ]);
      fill(layout, [
        row(tt('Start tab', 'Zakładka startowa'), tt('The tab the app opens with.', 'Zakładka otwierana po starcie.'),
          h('select', { class: 'input', onchange: (e) => set({ startTab: e.target.value }) },
            h('option', { value: '' }, tt('Dashboard', 'Pulpit')),
            ctx.views.filter((v) => v.id !== 'dashboard').map((v) => h('option', { value: v.id, selected: o.startTab === v.id || null }, v.title)))),
        row(tt('Compact mode', 'Tryb kompaktowy'), tt('Denser layout for a small window next to the game.', 'Gęstszy układ dla małego okna obok gry.'),
          check(ctx.state.compact, (v) => ctx.setState({ compact: v }), tt('Enabled', 'Włączony'))),
        row(tt('Always on top', 'Zawsze na wierzchu'), tt('Keeps this window above the game window.', 'Okno aplikacji nad oknem gry.'),
          check(ctx.state.alwaysOnTop, (v) => ctx.setAlwaysOnTop(v), tt('Enabled', 'Włączone'))),
        row(tt('Tab order', 'Kolejność zakładek'), tt('Drag the tabs in the sidebar (or Alt+Up / Alt+Down).', 'Przeciągnij zakładki w pasku bocznym (albo Alt+Góra / Alt+Dół).'),
          h('button', { class: 'btn btn-small', onclick: () => { ctx.resetNavOrder(); toast(tt('Default tab order', 'Domyślna kolejność'), 'ok'); } },
            tt('Reset tab order', 'Przywróć kolejność'))),
      ]);
      fill(notes, [
        row(tt('Windows notifications', 'Powiadomienia Windows'), tt('Shown even while you play.', 'Widoczne także podczas gry.'),
          check(o.notifyFocus, (v) => set({ notifyFocus: v }), tt('National focus (next focus to pick, auto-start)', 'Narodowy cel (następny do wybrania, auto-start)')),
          check(o.notifyRecording, (v) => set({ notifyRecording: v }), tt('Campaign recording started or switched', 'Start lub zmiana nagrywanej kampanii')),
          check(o.notifyGame, (v) => set({ notifyGame: v }), tt('Game started / closed', 'Gra uruchomiona / zamknięta')),
          check(o.notifyTrade, (v) => set({ notifyTrade: v }), tt('Trade advice each game month (deals to make or cancel)',
            'Rada handlu co miesiąc gry (umowy do zawarcia lub anulowania)'))),
        row('', null, h('button', { class: 'btn btn-small btn-ghost', onclick: () => {
          try { new Notification('The OVERSEER', { body: tt('The Overseer is watching.', 'Nadzorca patrzy.') }); } catch (err) { toast(err.message, 'error'); }
        } }, tt('Send a test notification', 'Wyślij próbne powiadomienie'))),
      ]);
      fill(reading, [
        row(tt('Refresh rate', 'Częstotliwość odczytu'), tt('How often open tabs read the game memory again. Applies to tabs opened from now on.',
          'Jak często otwarte zakładki czytają pamięć gry. Działa dla zakładek otwieranych od teraz.'),
          seg(Object.entries(REFRESH).map(([k, [label, f]]) => [k, `${tt(label, { Fast: 'Szybko', Normal: 'Normalnie', 'Light on the CPU': 'Oszczędnie' }[label])} (×${1 / f})`]),
            o.refresh, (k) => set({ refresh: k }, true))),
      ]);
      fill(language, [
        row(tt('Language', 'Język'), tt('Tabs, headers and these options. Texts from the game keep the game\'s language.',
          'Zakładki, nagłówki i te ustawienia. Teksty z gry zostają w języku gry.'),
          seg(Object.entries(LANGS), o.lang, (k) => { set({ lang: k }); ctx.relabel(); })),
        row(tt('Number format', 'Format liczb'), null,
          seg(Object.entries(NUMBERS).map(([k, label]) => [k, k === 'system' ? tt(label, 'Jak w Windows') : label]), o.numbers, (k) => set({ numbers: k }, true))),
      ]);
      fill(keyboard, [
        row(tt('Text size', 'Rozmiar tekstu'), tt('The whole window (Ctrl+= / Ctrl+- / Ctrl+0).', 'Całe okno (Ctrl+= / Ctrl+- / Ctrl+0).'),
          slider(o.textSize, TEXT_MIN, TEXT_MAX, (v) => set({ textSize: v })),
          h('button', { class: 'btn btn-small btn-ghost', onclick: () => set({ textSize: 100 }, true) }, '100%')),
        row(tt('Keyboard shortcuts', 'Skróty klawiszowe'), null, check(o.shortcuts, (v) => set({ shortcuts: v }, true), tt('Enabled', 'Włączone')),
          h('table', { class: 'opt-table' }, SHORTCUTS.map(([keys, what]) => h('tr', null, h('td', null, h('kbd', null, keys)), h('td', { class: 'muted' }, what))))),
      ]);
    }

    draw();
    drawMp();
    loadMp();
    drawGallery();
    drawData();
    root.append(
      viewHeader('Options', 'Settings of this app - nothing here changes the game.'),
      card('Appearance', appearance),
      card('Window and tabs', layout),
      card('Tabs and countries', tabs),
      card('Desktop', desktopBox),
      card('Overlay', overlayBox),
      card('Notifications', notes),
      card('Live reading', reading),
      card('Multiplayer', mpBox),
      card('Language and numbers', language),
      card('Text and keyboard', keyboard),
      card('Data', data),
      card('More ideas', h('ul', { class: 'opt-ideas' },
        h('li', null, tt('Sound alerts (a short signal when a focus ends or a campaign starts recording).', 'Dźwięki alertów (krótki sygnał po zakończeniu celu albo starcie nagrywania).')),
        h('li', null, tt('Overlay: alerts in it (focus finished, war declared) and a second layout with resources.', 'Nakładka: alerty w niej (cel skończony, wypowiedziana wojna) i drugi układ z zasobami.')),
        h('li', null, tt('Notifications of Players actions (e.g. "GER declared war") for the watched countries.', 'Powiadomienia z Działań graczy (np. "GER wypowiedziała wojnę") dla obserwowanych państw.')),
        h('li', null, tt('Colour-blind friendly chart colours; own accent colour.', 'Kolory wykresów dla daltonistów; własny kolor akcentu.'))), { cls: 'opt-later' }),
    );
    await Promise.all([loadImages(), loadUsage(),
      ctx.bridge?.desktop?.().then((d) => { desk = d; }, () => {}),
      loadCountries(ctx).then((r) => { countries = r.data.filter((c) => c.exists !== false); }, () => {})]);
    draw();
  },
};
