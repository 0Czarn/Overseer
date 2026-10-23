'use strict';
// Smoke test driver (HOI4DBG_SMOKE_DIR set): visits every tab, captures screenshots,
// records renderer console errors, writes result.json and quits.

const fs = require('node:fs');
const path = require('node:path');

const TABS = ['dashboard', 'summary', 'time-machine', 'actions', 'countries', 'country-editor', 'research', 'construction', 'doctrines', 'state-editor', 'focus', 'equipment', 'tools',
  'logs', 'options'];
// HOI4DBG_SMOKE_TABS=focus,construction checks only these tabs
const ONLY = (process.env.HOI4DBG_SMOKE_TABS || '').split(',').filter(Boolean);
const SIZES = [{ name: 'wide', width: 1320, height: 860 }, { name: 'narrow', width: 480, height: 820 }];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function waitFor(webContents, expression, timeoutMs = 8000) {
  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    if (await webContents.executeJavaScript(expression)) return true;
    await sleep(100);
  }
  return false;
}

function runSmoke(win, outDir, quit) {
  fs.mkdirSync(outDir, { recursive: true });
  const consoleErrors = [];
  const wc = win.webContents;
  wc.on('console-message', (event, legacyLevel, legacyMessage) => {
    const level = event.level ?? (legacyLevel === 3 ? 'error' : String(legacyLevel));
    const message = event.message ?? legacyMessage;
    if (level === 'error') consoleErrors.push(message);
  });

  wc.once('did-finish-load', async () => {
    const result = { tabs: [], consoleErrors, failures: [] };
    let folded = null;
    try {
      if (!(await waitFor(wc, "document.body.dataset.ready === '1'"))) result.failures.push('app never became ready');
      // the user's folded tiles would hide what the checks look for: unfold everything for the run, restored at the end
      folded = await wc.executeJavaScript(`(() => { const v = localStorage.getItem('hoi4dbg.collapsed'); localStorage.removeItem('hoi4dbg.collapsed'); return v; })()`);
      for (const size of SIZES) {
        win.setContentSize(size.width, size.height);
        await sleep(300);
        for (const tab of TABS.filter((t) => !ONLY.length || ONLY.includes(t))) {
          // a tab already shown is not rendered again by a hash change: show another one first (tab filter)
          if (await wc.executeJavaScript(`location.hash === '#/${tab}'`)) {
            const other = tab === 'dashboard' ? 'logs' : 'dashboard';
            await wc.executeJavaScript(`location.hash = '#/${other}'`);
            await waitFor(wc, `document.body.dataset.rendered === '${other}'`, 20000);
          }
          if (tab === 'time-machine' && process.env.HOI4DBG_SMOKE_CAMPAIGN) {   // a recorded campaign and its division 1
            await wc.executeJavaScript(`localStorage.setItem('hoi4dbg.timeMachine', JSON.stringify({ game: ${JSON.stringify(process.env.HOI4DBG_SMOKE_CAMPAIGN)}, division: 1 }))`);
          }
          await wc.executeJavaScript(`location.hash = '#/${tab}'`);
          // the first read of a new 40 MB binary save takes a few seconds per view (pure Python parser)
          const ok = await waitFor(wc,
            `document.body.dataset.rendered === '${tab}' && document.body.dataset.loading === '0'`, 20000);
          // the window is hidden: large views (focus tree: hundreds of nodes) need time to be painted, otherwise
          // capturePage() returns the previous frame
          await sleep(900);
          const info = await wc.executeJavaScript(`({
            heading: document.querySelector('.view-header h1')?.textContent ?? null,
            demoBadges: document.querySelectorAll('.badge-demo').length,
            errors: [...document.querySelectorAll('.view .error-box')].map((e) => e.textContent),
            hScroll: document.documentElement.scrollWidth > document.documentElement.clientWidth,
            // focus tree checked in the DOM (a hidden window may not repaint a very large tree for the screenshot)
            focusNodes: Object.fromEntries(['completed', 'in_progress', 'available', 'blocked', 'excluded'].map(
              (s) => [s, document.querySelectorAll('.fnode.fnode-' + s).length])),
          })`);
          if (tab === 'countries') {
            // Live tab: switch, wait for the memory read (countries table or a reason), switch back
            await wc.executeJavaScript(`document.querySelector('[data-tab="live"]').click()`);
            await waitFor(wc, `!!document.querySelector('[data-panel="live"] .card-body-inner > :not(p.muted)')`, 15000);
            info.live = await wc.executeJavaScript(`({
              rows: document.querySelectorAll('[data-panel="live"] .table tbody tr').length,
              notice: document.querySelector('[data-panel="live"] .notice')?.textContent ?? null,
            })`);
            await wc.executeJavaScript(`document.querySelector('[data-tab="saves"]').click()`);
            if (!info.live.rows && !info.live.notice) result.failures.push(`${size.name}/countries: Live tab shows nothing`);
          }
          if (tab === 'country-editor') {
            // stability / war support: wait until the modifiers from the save are in (first read takes seconds)
            await waitFor(wc, `[...document.querySelectorAll('.hoi-source')].some((e) => /Modifiers from|unavailable/.test(e.textContent))`, 30000);
            info.gauges = await wc.executeJavaScript(`[...document.querySelectorAll('.hoi-gauge')].map((g) => ({
              value: g.querySelector('.hoi-gauge-value').textContent,
              lines: g.querySelectorAll('.hoi-lines .hoi-line').length }))`);
            if (info.gauges.length !== 2) result.failures.push(`${size.name}/country-editor: stability/war support gauges missing`);
            await waitFor(wc, `document.querySelectorAll('.live-panel-body').length >= 4 && ![...document.querySelectorAll('.live-panel-body > .muted')].some((e) => e.textContent.startsWith('Reading'))`, 30000);
            // factories tile: military, dockyards, civilian and energy boxes, or the reason
            await waitFor(wc, `!!document.querySelector('.fac-kind, .fac-grid ~ .notice, .live-panel-body .notice')`, 20000);
            info.factories = await wc.executeJavaScript(`[...document.querySelectorAll('.fac-total')].map((e) => e.textContent)`);
            if (info.factories.length && info.factories.length !== 3) result.failures.push(`${size.name}/country-editor: factories tile shows ${info.factories.length} types`);
            // trade advisor in the resources tile: six resource rows, or the reason (game not running)
            await waitFor(wc, `!!document.querySelector('.trade-row, .trade-out .notice')`, 20000);
            info.trade = await wc.executeJavaScript(`({ rows: document.querySelectorAll('.trade-row').length,
              advice: [...document.querySelectorAll('.trade-advice')].map((e) => e.textContent),
              notice: document.querySelector('.trade-out .notice')?.textContent ?? null })`);
            if (info.trade.rows !== 6 && !info.trade.notice) result.failures.push(`${size.name}/country-editor: trade advisor shows ${info.trade.rows} rows`);
            info.modeSwitches = await wc.executeJavaScript(`document.querySelectorAll('.hoi-mode').length`);
            if (info.modeSwitches < 5) result.failures.push(`${size.name}/country-editor: ${info.modeSwitches} Live/On refresh switches`);
            info.spirits = await wc.executeJavaScript(`document.querySelectorAll('.hoi-panel:not(.gov-panel) .spirit-row .spirit').length`);
            if (!info.spirits) result.failures.push(`${size.name}/country-editor: no national spirits shown`);
            info.government = await wc.executeJavaScript(`[...document.querySelectorAll('.gov-row')].map((r) => r.querySelectorAll('.spirit').length)`);
            if (info.government.length !== 3 || info.government.some((n) => n < 6)) result.failures.push(`${size.name}/country-editor: government slots ${info.government}`);
            info.mios = await wc.executeJavaScript(`(() => { const t = document.querySelector('.mio-slot'); if (!t) return -1;
              t.click(); const n = document.querySelectorAll('.mio-list:not([hidden]) .mio').length; t.click(); return n; })()`);
            if (info.mios === 0) result.failures.push(`${size.name}/country-editor: MIO list did not open`);
            // a tooltip of a tile at the bottom of the window opens above it, inside the window (apl_display_bug.jpg)
            info.tipInside = await wc.executeJavaScript(`(async () => { const tiles = [...document.querySelectorAll('.gov-panel .spirit')];
              const t = tiles[tiles.length - 1]; if (!t) return null;
              t.scrollIntoView({ block: 'end' }); window.scrollBy(0, 0); t.focus();
              await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
              const r = t.querySelector('.spirit-tip').getBoundingClientRect();
              const ok = r.top >= 0 && r.bottom <= window.innerHeight + 1 && r.left >= 0 && r.right <= window.innerWidth + 1;
              t.blur(); return ok; })()`);
            if (info.tipInside === false) result.failures.push(`${size.name}/country-editor: a tooltip leaves the window`);
            if (info.mios > 0) {   // a MIO: its trait tree as the game's MIO window
              await wc.executeJavaScript(`(() => { document.querySelector('.mio-slot').click(); document.querySelector('.mio-list:not([hidden]) .mio-open').click(); })()`);
              await waitFor(wc, `document.querySelectorAll('.mio-trait').length > 0`, 15000);
              info.mioTree = await wc.executeJavaScript(`(() => { const w = document.querySelector('.mio-window'); w?.scrollIntoView();
                return { traits: document.querySelectorAll('.mio-trait').length, lines: document.querySelectorAll('.mio-tree-lines polyline').length,
                  heads: document.querySelectorAll('.mio-tree-head').length, frames: document.querySelectorAll('.mio-trait-frame[src]').length,
                  overlap: (() => { const r = [...document.querySelectorAll('.mio-trait')].map((t) => t.getBoundingClientRect());
                    return r.some((a, i) => r.some((b, j) => j > i && Math.abs(a.left - b.left) < 20 && Math.abs(a.top - b.top) < 20)); })() }; })()`);
              if (!info.mioTree.traits || !info.mioTree.frames) result.failures.push(`${size.name}/country-editor: the MIO tree shows no traits`);
              if (info.mioTree.overlap) result.failures.push(`${size.name}/country-editor: MIO traits on top of each other`);
              info.mioZoom = await wc.executeJavaScript(`(() => { const v = document.querySelector('.mio-tree-scroll'); const t = v.querySelector('.mio-tree');
                const r = v.getBoundingClientRect(); const before = t.style.transform;
                v.dispatchEvent(new WheelEvent('wheel', { deltaY: -100, clientX: r.left + 50, clientY: r.top + 50, bubbles: true, cancelable: true }));
                const after = t.style.transform;
                v.dispatchEvent(new WheelEvent('wheel', { deltaY: 100, clientX: r.left + 50, clientY: r.top + 50, bubbles: true, cancelable: true }));
                return { before, after, icons: document.querySelectorAll('.mio-side .tx-icon').length }; })()`);
              if (info.mioZoom.before === info.mioZoom.after) result.failures.push(`${size.name}/country-editor: the MIO tree does not zoom`);
              if (!info.mioZoom.icons) result.failures.push(`${size.name}/country-editor: no modifier icons in the MIO window`);
              await sleep(500);
              wc.invalidate();
              await sleep(1500);
              fs.writeFileSync(path.join(outDir, `${size.name}-mio-tree.png`), (await wc.capturePage()).toPNG());
              await wc.executeJavaScript(`document.querySelector('.mio-slot').click()`);   // closed again
            }
            await waitFor(wc, `!!document.querySelector('.ov-body .pie, .ov-body .notice')`, 20000);
            info.pieSlices = await wc.executeJavaScript(`document.querySelectorAll('.ov-body .pie-slice').length`);
            if (!info.pieSlices) result.failures.push(`${size.name}/country-editor: no party popularity pie`);
            await waitFor(wc, `!!document.querySelector('.res-table, .res-body .notice')`, 20000);
            info.resources = await wc.executeJavaScript(`document.querySelectorAll('.res-row:not(.res-head)').length`);
            if (!info.resources) result.failures.push(`${size.name}/country-editor: no resources`);
            info.editableChips = await wc.executeJavaScript(`document.querySelectorAll('.hoi-chip .hoi-chip-input').length`);
            if (info.editableChips !== 6) result.failures.push(`${size.name}/country-editor: ${info.editableChips}/6 editable live values`);
          }
          if (tab === 'focus') {
            // the tree's own Live / On refresh switch and the state read after it (game memory or save)
            await waitFor(wc, `/read|not read/.test(document.querySelector('.card .hoi-status')?.textContent ?? '')`, 20000);
            info.focusState = await wc.executeJavaScript(`({ switches: document.querySelectorAll('.card .hoi-mode').length,
              status: document.querySelector('.card .hoi-status')?.textContent ?? null })`);
            if (info.focusState.switches !== 1) result.failures.push(`${size.name}/focus: tree has no Live / On refresh switch`);
            // a click on an available focus adds it to the plan, a second click removes it again (the user's plan stays)
            const target = await wc.executeJavaScript(`document.querySelector('.fnode-available:not(.fnode-queued)')?.dataset.focus ?? null`);
            if (target) {
              const count = `document.querySelectorAll('.focus-queue li').length`;
              const before = await wc.executeJavaScript(count);
              await wc.executeJavaScript(`document.querySelector('[data-focus="${target}"]').click()`);
              await waitFor(wc, `${count} === ${before + 1}`, 10000);
              info.focusQueueAdd = (await wc.executeJavaScript(count)) - before;
              await wc.executeJavaScript(`document.querySelector('[data-focus="${target}"]').click()`);
              await waitFor(wc, `${count} === ${before}`, 10000);
              if (info.focusQueueAdd !== 1) result.failures.push(`${size.name}/focus: clicking a focus does not add it to the plan`);
            }
          }
          if (tab === 'state-editor' && size.name === 'wide') {   // Save / Live switch: both list states (the user's choice restored)
            info.states = await wc.executeJavaScript(`(async () => {
              const btn = (label) => [...document.querySelectorAll('.view-header .gs-seg-btn')].find((b) => b.textContent === label);
              const before = document.querySelector('.view-header .gs-seg-on')?.textContent;
              const rows = async (label) => { btn(label)?.click(); for (let i = 0; i < 60; i += 1) {
                await new Promise((r) => setTimeout(r, 250));
                if (btn(label)?.classList.contains('gs-seg-on') && document.querySelectorAll('#view table tbody tr').length) break; }
                return document.querySelectorAll('#view table tbody tr').length; };
              const live = await rows('Live');
              const save = await rows('Save');
              const icons = document.querySelectorAll('.amounts .tx-icon').length;
              if (before) btn(before)?.click();
              return { live, save, icons };
            })()`);
            if (!info.states.save) result.failures.push(`${size.name}/state-editor: the save view lists no states`);
            if (!info.states.icons) result.failures.push(`${size.name}/state-editor: no building icons`);
          }
          if (tab === 'state-editor') {   // the map: provinces and states drawn, a click chooses the state under it
            const drawn = await waitFor(wc, `!!document.querySelector('.se-map-card .map-canvas')`, 30000);
            info.stateMap = drawn ? await wc.executeJavaScript(`(async () => {
              const c = document.querySelector('.se-map-card .map-canvas');
              const g = c.getContext('2d');
              const colours = new Set(); for (let i = 0; i < 400; i++) colours.add([...g.getImageData((i * 97) % c.width, (i * 53) % c.height, 1, 1).data.slice(0, 3)].join());
              const before = document.querySelector('.detail h3')?.textContent;
              const r = c.getBoundingClientRect();
              const ev = (type) => new MouseEvent(type, { clientX: r.left + r.width * 0.535, clientY: r.top + r.height * 0.2, bubbles: true });
              c.dispatchEvent(ev('mousedown')); c.dispatchEvent(ev('click')); c.dispatchEvent(ev('mousemove'));
              await new Promise((res) => setTimeout(res, 200));
              const tip = document.querySelector('.se-map-card .map-tip');
              for (let i = 0; i < 6; i++) document.querySelector('.se-map-card .zoom-btn[aria-label="Zoom in"]').click();
              const v = document.querySelector('.se-map-card .map-scroll');
              v.scrollLeft = v.scrollWidth * 0.5 - v.clientWidth / 2; v.scrollTop = v.scrollHeight * 0.19 - v.clientHeight / 2;
              document.querySelector('.se-map-card').scrollIntoView({ block: 'start' });
              return { colours: colours.size, before, after: document.querySelector('.detail h3')?.textContent,
                tip: tip.hidden ? null : tip.innerText };
            })()`) : null;
            if (!info.stateMap || info.stateMap.colours < 5) result.failures.push(`${size.name}/state-editor: the map is not drawn`);
            else if (!info.stateMap.after) result.failures.push(`${size.name}/state-editor: a click on the map chooses no state`);
            wc.invalidate(); await sleep(1500); wc.invalidate(); await sleep(800);
            fs.writeFileSync(path.join(outDir, `${size.name}-state-map.png`), (await wc.capturePage()).toPNG());
            await wc.executeJavaScript(`(() => { for (let i = 0; i < 6; i++) document.querySelector('.se-map-card .zoom-btn[aria-label="Zoom out"]').click(); window.scrollTo(0, 0); })()`);
          }
          if (tab === 'construction') {   // forecast with the queue, where to build
            await waitFor(wc, `!!document.querySelector('.cons-advice table, .cons-advice .notice')`, 20000);
            info.constructionAdvice = await wc.executeJavaScript(`({ rows: document.querySelectorAll('.cons-advice-table tbody tr').length,
              forecast: document.querySelectorAll('.cons-forecast-table tbody tr').length,
              notice: document.querySelector('.cons-advice .notice')?.textContent ?? null })`);
            if (!info.constructionAdvice.rows && !info.constructionAdvice.notice) result.failures.push(`${size.name}/construction: where to build shows nothing`);
          }
          if (tab === 'options') {   // style, eye, background images; no stray "null" text
            info.options = await wc.executeJavaScript(`({ rows: document.querySelectorAll('.opt-row').length,
              gallery: !!document.querySelector('.opt-gallery .opt-thumb-add'),
              nulls: /null/.test(document.querySelector('#view').innerText) })`);
            if (!info.options.rows || !info.options.gallery) result.failures.push(`${size.name}/options: settings missing`);
            if (info.options.nulls) result.failures.push(`${size.name}/options: shows "null"`);
          }
          if (tab === 'actions') {   // the log, its filters and the watched countries
            await waitFor(wc, `!!document.querySelector('.pa-kinds, .pa-list .notice')`, 20000);
            info.actions = await wc.executeJavaScript(`({ kinds: document.querySelectorAll('.pa-kind').length,
              events: document.querySelectorAll('.pa-event').length, chips: document.querySelectorAll('.pa-chip').length,
              notice: document.querySelector('.pa-list .notice')?.textContent ?? null })`);
            if (!info.actions.kinds && !info.actions.notice) result.failures.push(`${size.name}/actions: shows nothing`);
          }
          if (tab === 'summary') {
            await waitFor(wc, `!!document.querySelector('.lc-svg, .gs-charts .notice')`, 20000);
            info.summary = await wc.executeJavaScript(`({ charts: document.querySelectorAll('.lc-svg').length,
              lines: document.querySelectorAll('.lc-line').length, countries: document.querySelectorAll('.gs-country').length,
              notice: document.querySelector('.gs-charts .notice')?.textContent ?? null })`);
            if (!info.summary.charts && !info.summary.notice) result.failures.push(`${size.name}/summary: shows nothing`);
            info.summary.recording = await wc.executeJavaScript(`document.querySelector('.gs-rec-head')?.textContent ?? null`);
            if (!info.summary.recording) result.failures.push(`${size.name}/summary: no recording panel`);
            if (info.summary.charts === 2) {   // hover one chart: the values of the day show in both
              info.summary.hover = await wc.executeJavaScript(`(() => {
                const hit = document.querySelector('.lc-hit'); const r = hit.getBoundingClientRect();
                hit.dispatchEvent(new MouseEvent('mousemove', { clientX: r.left + r.width / 2, clientY: r.top + 10, bubbles: true }));
                return [...document.querySelectorAll('.lc-tip')].map((t) => (t.hidden ? null : [...t.querySelectorAll('.lc-tip-row')].length));
              })()`);
              if (!info.summary.hover.every((n) => n > 0)) result.failures.push(`${size.name}/summary: hover shows no values in both charts`);
              // the country list (the user's own preference may be the factions view)
              await wc.executeJavaScript(`[...document.querySelectorAll('.gs-seg-btn')].find((b) => b.textContent === 'Countries')?.click()`);
              await waitFor(wc, `!!document.querySelector('.gs-country')`, 10000);
              // search for a tag the campaign has (the first country listed), it alone should be left
              info.summary.search = await wc.executeJavaScript(`(() => { const i = document.querySelector('.gs-search');
                const want = document.querySelector('.gs-group .gs-country-tag')?.firstChild?.textContent ?? '';
                i.value = want.toLowerCase(); i.dispatchEvent(new Event('input'));
                const n = [...document.querySelectorAll('.gs-country-tag')].map((e) => e.firstChild?.textContent);
                i.value = ''; i.dispatchEvent(new Event('input')); return { want, n }; })()`);
              const { want, n } = info.summary.search;
              if (!want || !n.includes(want) || n.length > 3) result.failures.push(`${size.name}/summary: search does not filter`);
              await wc.executeJavaScript(`(() => { const c = document.querySelector('.gs-color'); c.value = '#ffffff';
                c.dispatchEvent(new Event('change')); })()`);
              await waitFor(wc, `[...document.querySelectorAll('.lc-line')].some((l) => l.getAttribute('stroke') === '#ffffff')`, 10000);
            }
            if (info.summary.charts) {   // factory counts: one chart (a level, no cumulative)
              await wc.executeJavaScript(`(() => { const b = document.querySelectorAll('.gs-seg')[1].querySelectorAll('.gs-seg-btn')[1]; b.focus(); b.click(); })()`);
              await waitFor(wc, `document.querySelector('.lc-title')?.textContent === 'Military factories'`, 10000);
              info.summary.factoryCharts = await wc.executeJavaScript(`document.querySelectorAll('.gs-charts .lc-svg').length`);
              // the clicked button is the highlighted one, even while it keeps the focus
              info.summary.highlight = await wc.executeJavaScript(`[...document.querySelectorAll('.gs-field')]
                .filter((f) => f.querySelector('.gs-seg-on')).map((f) => f.firstChild.textContent + ':' + f.querySelector('.gs-seg-on').textContent)`);
              if (!info.summary.highlight.some((t) => t.startsWith('Factories:'))) result.failures.push(`${size.name}/summary: the chosen metric is not highlighted`);
              if (info.summary.factoryCharts !== 1) result.failures.push(`${size.name}/summary: factory view should show one chart`);
            }
            if (info.summary.charts && size.name === 'wide') {   // factions: a new group, a country moved into it
              await wc.executeJavaScript(`[...document.querySelectorAll('.gs-seg-btn')].find((b) => b.textContent === 'Factions').click()`);
              await waitFor(wc, `!!document.querySelector('.gs-new-group')`, 10000);
              await wc.executeJavaScript(`(() => { const i = document.querySelector('.gs-new-group'); i.value = 'Smoke bloc';
                i.dispatchEvent(new Event('input')); document.querySelector('.gs-new button').click(); })()`);
              await waitFor(wc, `[...document.querySelectorAll('.gs-group-name')].some((e) => e.textContent.startsWith('Smoke bloc'))`, 10000);
              await wc.executeJavaScript(`(() => { const s = document.querySelector('.gs-move'); s.value = 'Smoke bloc';
                s.dispatchEvent(new Event('change')); })()`);
              await waitFor(wc, `[...document.querySelectorAll('.gs-group-name')].some((e) => e.textContent === 'Smoke bloc (1)')`, 10000);
              info.summary.groups = await wc.executeJavaScript(`({ groups: document.querySelectorAll('.gs-group').length,
                legend: [...document.querySelectorAll('.lc-legend-item')].map((e) => e.textContent) })`);
              if (!info.summary.groups.legend.includes('Smoke bloc')) result.failures.push('wide/summary: a new group is not on the chart');
              // the campaign is the user's own: delete the test group (its country goes back to its faction)
              await wc.executeJavaScript(`[...document.querySelectorAll('.gs-group summary')].find((s) => s.textContent.includes('Smoke bloc'))
                ?.querySelector('.gs-del')?.click()`);
              await waitFor(wc, `![...document.querySelectorAll('.gs-group-name')].some((e) => e.textContent.startsWith('Smoke bloc'))`, 10000);
            }
          }
          if (tab === 'summary') {   // campaign analysis (2026-10-21): notes, sessions and map cards on every campaign
            info.analysis = await wc.executeJavaScript(`({ notes: !!document.querySelector('.gs-notes-card'),
              sessions: !!document.querySelector('.gs-sessions-card'), map: !!document.querySelector('.gs-map-card'),
              groups: [...document.querySelectorAll('.gs-seg-label')].map((e) => e.textContent) })`);
            if (!info.analysis.notes || !info.analysis.sessions || !info.analysis.map) result.failures.push(`${size.name}/summary: analysis cards missing`);
            if (!['Politics', 'Army', 'Territory', 'Research', 'Manpower'].every((g) => info.analysis.groups.includes(g))) {
              result.failures.push(`${size.name}/summary: new metric groups missing`);
            }
            // HOI4DBG_SMOKE_CAMPAIGN: a recorded test campaign with map rows - the map is drawn, played back and hovered,
            // a click on a chart picks the note day, the ranking shows; the user's choice is restored after
            const smokeGame = process.env.HOI4DBG_SMOKE_CAMPAIGN;
            if (smokeGame) {
              const saved = await wc.executeJavaScript(`localStorage.getItem('hoi4dbg.summary')`);
              await wc.executeJavaScript(`(() => { const p = JSON.parse(localStorage.getItem('hoi4dbg.summary') || '{}');
                Object.assign(p, { game: ${JSON.stringify(smokeGame)}, compare: null, players: true, factions: false, metric: 'sctl', hiddenPlayers: [] });
                localStorage.setItem('hoi4dbg.summary', JSON.stringify(p)); location.hash = '#/dashboard'; })()`);
              await waitFor(wc, `document.body.dataset.rendered === 'dashboard'`, 20000);
              await wc.executeJavaScript(`location.hash = '#/summary'`);
              const drawn = await waitFor(wc, `!!document.querySelector('.map-canvas') && document.querySelector('.gs-map-date')?.textContent.length > 4`, 30000);
              await waitFor(wc, `document.querySelectorAll('.gs-rank-cat').length > 0`, 10000);
              if (!drawn) {
                info.campaignText = await wc.executeJavaScript(`(async () => { const t = Date.now();
                  const r = await window.hoi4dbg.request('GET', '/api/summary/games/${smokeGame}/map?raster=1');
                  return { ms: Date.now() - t, ok: r.ok, status: r.status, error: r.body?.error, len: JSON.stringify(r.body).length }; })()`);
                result.failures.push(`${size.name}/summary: direct map request ${JSON.stringify(info.campaignText)}`);
                info.campaignText = await wc.executeJavaScript(`({ map: document.querySelector('.gs-map-card')?.innerText,
                  charts: document.querySelector('.gs-charts')?.innerText?.slice(0, 300), game: JSON.parse(localStorage.getItem('hoi4dbg.summary')).game })`);
                result.failures.push(`${size.name}/summary: the campaign map is not drawn: ${JSON.stringify(info.campaignText)}`);
              }
              if (drawn) info.campaign = await wc.executeJavaScript(`(async () => {
                const c = document.querySelector('.map-canvas');
                const g = c.getContext('2d');
                const px = (x, y) => [...g.getImageData(x, y, 1, 1).data.slice(0, 3)];
                const colours = new Set(); for (let i = 0; i < 400; i++) colours.add(px((i * 97) % c.width, (i * 53) % c.height).join());
                const lastDate = document.querySelector('.gs-map-date').textContent;
                const s = document.querySelector('.gs-map-slider'); s.value = '0'; s.dispatchEvent(new Event('input'));
                const firstDate = document.querySelector('.gs-map-date').textContent;
                document.querySelector('.gs-map-card .map-scroll, .gs-map-main > *')
                  .dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));
                const keyDate = document.querySelector('.gs-map-date').textContent;   // → : the next recorded step
                s.value = s.max; s.dispatchEvent(new Event('input'));
                const r = c.getBoundingClientRect();
                c.dispatchEvent(new MouseEvent('mousemove', { clientX: r.left + r.width * 0.52, clientY: r.top + r.height * 0.22, bubbles: true }));
                const tip = document.querySelector('.map-tip');
                const hit = document.querySelector('.lc-hit'); const hr = hit.getBoundingClientRect();
                hit.dispatchEvent(new MouseEvent('click', { clientX: hr.left + hr.width / 2, clientY: hr.top + 10, bubbles: true }));
                await new Promise((res) => setTimeout(res, 300));
                // names on the overlay; each mode button redraws the whole map (time of the slowest one)
                const sc = document.querySelector('.gs-map-card .map-screen');
                const o = sc.getContext('2d').getImageData(0, 0, sc.width, sc.height).data;
                let named = 0; for (let i = 3; i < o.length; i += 4 * 7) if (o[i]) named += 1;
                const buttons = [...document.querySelectorAll('.gs-map-options .gs-seg-btn')];
                let slowest = 0;
                for (const label of ['Factions', 'Players', 'Chart lines', 'Provinces', 'Countries', 'Game', 'Provinces']) {
                  const b = buttons.find((x) => x.textContent === label) ?? [...document.querySelectorAll('.gs-map-options .gs-seg-btn')].find((x) => x.textContent === label);
                  const t0 = performance.now(); b?.click(); slowest = Math.max(slowest, performance.now() - t0);
                }
                return { width: c.width, colours: colours.size, firstDate, keyDate, lastDate, tip: tip.hidden ? null : tip.textContent,
                  named, options: document.querySelectorAll('.gs-map-options .gs-seg-btn').length, drawMs: Math.round(slowest),
                  noteDay: document.querySelector('.gs-note-day')?.textContent, markers: document.querySelectorAll('.lc-note').length,
                  ranking: document.querySelectorAll('.gs-rank-cat').length, sessions: document.querySelectorAll('.gs-sess-table tbody tr').length,
                  legend: document.querySelectorAll('.gs-map-legend-item').length };
              })()`);
              if (drawn && info.campaign.colours < 5) result.failures.push(`${size.name}/summary: the campaign map is not drawn`);
              if (drawn && !info.campaign.named) result.failures.push(`${size.name}/summary: no names on the campaign map`);
              if (drawn && info.campaign.firstDate === info.campaign.lastDate) result.failures.push(`${size.name}/summary: the map slider does not change the day`);
              if (drawn && info.campaign.keyDate === info.campaign.firstDate) result.failures.push(`${size.name}/summary: the arrow key does not step to the next day`);
              if (drawn && !info.campaign.markers) result.failures.push(`${size.name}/summary: notes are not on the charts`);
              if (drawn && !info.campaign.ranking) result.failures.push(`${size.name}/summary: no players ranking`);
              await wc.executeJavaScript(`document.querySelector('.gs-map-card').scrollIntoView({ block: 'start' })`);
              wc.invalidate(); await sleep(1500); wc.invalidate(); await sleep(800);
              fs.writeFileSync(path.join(outDir, `${size.name}-campaign-map.png`), (await wc.capturePage()).toPNG());
              if (drawn) {   // Europe at 100%: the full-size map and the city names
                await wc.executeJavaScript(`(() => { const bar = document.querySelector('.gs-map-card .zoom-bar');
                  [...bar.querySelectorAll('button')].find((b) => b.textContent === '100%').click();
                  const v = document.querySelector('.gs-map-card .map-scroll'); v.scrollLeft = 2650; v.scrollTop = 380; })()`);
                wc.invalidate(); await sleep(1200);
                fs.writeFileSync(path.join(outDir, `${size.name}-campaign-map-zoom.png`), (await wc.capturePage()).toPNG());
                await wc.executeJavaScript(`(() => { const bar = document.querySelector('.gs-map-card .zoom-bar');   // ~300% at Berlin: the outlines
                  const plus = [...bar.querySelectorAll('button')].find((b) => b.textContent === '+');
                  for (let i = 0; i < 8; i++) plus.click();
                  const v = document.querySelector('.gs-map-card .map-scroll'); v.scrollLeft = 8690; v.scrollTop = 1265; })()`);
                wc.invalidate(); await sleep(1500);
                fs.writeFileSync(path.join(outDir, `${size.name}-campaign-map-close.png`), (await wc.capturePage()).toPNG());
                // state borders on and their strength x3 (input events: nothing else turned on), then both as they were
                const statesBtn = `[...document.querySelectorAll('.gs-map-options .gs-seg-btn')].find((x) => x.textContent === 'States')`;
                const before = await wc.executeJavaScript(`(() => { const r = document.querySelector('.gs-border-slider');
                  if (!r) return null; const on = ${statesBtn}.getAttribute('aria-pressed') === 'true';
                  if (!on) ${statesBtn}.click();
                  const s = document.querySelector('.gs-border-slider'); const v = s.value;
                  s.value = '3'; s.dispatchEvent(new Event('input')); return { v, on }; })()`);
                if (before === null) result.failures.push(`${size.name}/summary: no border strength slider`);
                wc.invalidate(); await sleep(1000);
                fs.writeFileSync(path.join(outDir, `${size.name}-campaign-map-borders.png`), (await wc.capturePage()).toPNG());
                if (before !== null) await wc.executeJavaScript(`(() => { const s = document.querySelector('.gs-border-slider');
                  s.value = ${JSON.stringify(before?.v)}; s.dispatchEvent(new Event('input'));
                  if (!${before?.on}) ${statesBtn}.click(); })()`);
                // the slowest of 4 frames while moving the map (drawn from the outlines)
                const frames = `(async () => {
                  const v = document.querySelector('.gs-map-card .map-scroll'); let slowest = 0;
                  for (let i = 0; i < 4; i++) {   // the time render() took (rAF is slow in a hidden window)
                    v.scrollLeft += 40;
                    await new Promise((res) => setTimeout(res, 1100));
                    slowest = Math.max(slowest, Number(document.querySelector('.gs-map-card .map-wrap').dataset.frameMs));
                  }
                  return slowest; })()`;
                info.campaignFrameMs = { close: await wc.executeJavaScript(frames) };
                await wc.executeJavaScript(`[...document.querySelectorAll('.gs-map-card .zoom-bar button')].find((b) => b.textContent === '100%').click()`);
                info.campaignFrameMs.full = await wc.executeJavaScript(frames);
                await wc.executeJavaScript(`(() => { const f = document.querySelector('.gs-map-fog'); f.value = 'GER'; f.dispatchEvent(new Event('change')); })()`);
                wc.invalidate(); await sleep(1500);
                fs.writeFileSync(path.join(outDir, `${size.name}-campaign-map-fog.png`), (await wc.capturePage()).toPNG());
                await wc.executeJavaScript(`(() => { const f = document.querySelector('.gs-map-fog'); f.value = ''; f.dispatchEvent(new Event('change')); })()`);
                await sleep(800);
                // a click on a province with divisions: their list beside the map, then one division's card
                info.campaignDivision = await wc.executeJavaScript(`(async () => {
                  const c = document.querySelector('.gs-map-card .map-canvas'); const v = document.querySelector('.gs-map-card .map-scroll');
                  const r = v.getBoundingClientRect();
                  for (let y = 20; y < r.height - 20; y += 24) for (let x = 20; x < r.width - 20; x += 24) {
                    const at = { clientX: r.left + x, clientY: r.top + y, bubbles: true };
                    c.dispatchEvent(new MouseEvent('mousedown', at)); c.dispatchEvent(new MouseEvent('click', at));
                    const item = document.querySelector('.gs-div-item');
                    if (item) {
                      const n = document.querySelectorAll('.gs-div-item').length; item.click();
                      for (let i = 0; i < 60 && !document.querySelector('.gs-map-panel .dc-name'); i++) await new Promise((res) => setTimeout(res, 100));
                      return { items: n, name: document.querySelector('.gs-map-panel .dc-name')?.textContent ?? null,
                        open: !!document.querySelector('.gs-map-panel .dc-open') };
                    }
                  }
                  return null; })()`);
                if (!info.campaignDivision?.name) result.failures.push(`${size.name}/summary: no division card from a map click ${JSON.stringify(info.campaignDivision)}`);
                await wc.executeJavaScript(`document.querySelector('.gs-map-panel')?.scrollIntoView({ block: 'start' })`);
                wc.invalidate(); await sleep(1500);
                fs.writeFileSync(path.join(outDir, `${size.name}-campaign-map-division.png`), (await wc.capturePage()).toPNG());
                await wc.executeJavaScript(`[...document.querySelectorAll('.gs-map-card .zoom-bar button')].find((b) => b.textContent === 'Fit').click()`);
              }
              await wc.executeJavaScript(`document.querySelector('.gs-ranking-card').scrollIntoView()`);
              await sleep(400);
              wc.invalidate(); await sleep(500);
              fs.writeFileSync(path.join(outDir, `${size.name}-ranking.png`), (await wc.capturePage()).toPNG());
              await wc.executeJavaScript(`document.querySelector('.gs-main').scrollIntoView()`);
              await sleep(400);
              wc.invalidate(); await sleep(500);
              fs.writeFileSync(path.join(outDir, `${size.name}-summary-notes.png`), (await wc.capturePage()).toPNG());
              await wc.executeJavaScript(`document.querySelector('.gs-sessions-card').scrollIntoView()`);
              await sleep(400);
              wc.invalidate(); await sleep(500);
              fs.writeFileSync(path.join(outDir, `${size.name}-sessions.png`), (await wc.capturePage()).toPNG());
              // the report: the download is caught instead of the save dialog
              info.report = await wc.executeJavaScript(`(async () => {
                const click = HTMLAnchorElement.prototype.click;
                const make = URL.createObjectURL;
                let got = null;
                let blob = null;
                URL.createObjectURL = (b) => { blob = b; return make.call(URL, b); };
                HTMLAnchorElement.prototype.click = function () { got = { name: this.download }; };
                try {
                  [...document.querySelectorAll('.gs-report-btn')][0].click();
                  for (let i = 0; i < 100 && !got; i++) await new Promise((r) => setTimeout(r, 200));
                } finally { HTMLAnchorElement.prototype.click = click; URL.createObjectURL = make; }
                if (!got || !blob) return null;
                const html = await blob.text();
                return { name: got.name, size: html.length, charts: (html.match(/class="lc-svg"/g) || []).length,
                  map: html.includes('data:image/png'), ranking: html.includes('Players ranking'), notes: html.includes('Soviet invasion') };
              })()`);
              if (!info.report || info.report.charts < 5 || !info.report.map || !info.report.ranking || !info.report.notes) {
                result.failures.push(`${size.name}/summary: report ${JSON.stringify(info.report)}`);
              }
              await wc.executeJavaScript(`localStorage.setItem('hoi4dbg.summary', ${JSON.stringify(saved ?? '{}')})`);
            }
          }
          if (tab === 'time-machine' && process.env.HOI4DBG_SMOKE_CAMPAIGN) {   // game state, the division list, one division
            await waitFor(wc, `!!document.querySelector('.tm-table tbody tr') && !!document.querySelector('.tm-division .dc-name')`, 20000);
            info.timeMachine = await wc.executeJavaScript(`({ metrics: document.querySelectorAll('.tm-metrics .hoi-line').length,
              rows: document.querySelectorAll('.tm-table tbody tr').length, division: document.querySelector('.tm-division .dc-name')?.textContent,
              grid: document.querySelectorAll('.tm-division .mil-slot:not(.mil-slot-empty)').length })`);
            if (!info.timeMachine.rows || !info.timeMachine.division) result.failures.push(`${size.name}/time-machine: ${JSON.stringify(info.timeMachine)}`);
            await wc.executeJavaScript(`document.querySelector('.tm-division').scrollIntoView()`);
            wc.invalidate(); await sleep(1200);
            fs.writeFileSync(path.join(outDir, `${size.name}-time-machine-division.png`), (await wc.capturePage()).toPNG());
          }
          if (tab === 'doctrines') {
            await waitFor(wc, `!!document.querySelector('.doc-tab, .live-panel-body .notice')`, 20000);
            await waitFor(wc, `!!document.querySelector('.mil-bigs, .live-panel-body .notice')`, 20000);
            info.military = await wc.executeJavaScript(`[...document.querySelectorAll('.mil-big-value')].map((e) => e.textContent)`);
            info.doctrines = await wc.executeJavaScript(`({ tabs: document.querySelectorAll('.doc-tab').length,
              tracks: document.querySelectorAll('.doc-track').length,
              notice: document.querySelector('.live-panel-body .notice')?.textContent ?? null })`);
            if (!info.doctrines.tabs && !info.doctrines.notice) result.failures.push(`${size.name}/doctrines: shows nothing`);
            if (await waitFor(wc, `!!document.querySelector('.mil-tpl-head')`, 15000)) {   // a template unfolds into the designer
              await wc.executeJavaScript(`(() => { localStorage.removeItem('hoi4dbg.armyView'); document.querySelector('.mil-tpl-head').click(); })()`);
              await waitFor(wc, `!!document.querySelector('.mil-dd')`, 10000);
              await waitFor(wc, `!!document.querySelector('.mil-slot-img[src]')`, 10000).catch(() => {});
              info.designer = await wc.executeJavaScript(`(() => { document.querySelector('.mil-tpl-open').scrollIntoView();
                return { slots: document.querySelectorAll('.mil-dd-cols .mil-slot').length,
                  units: document.querySelectorAll('.mil-dd-cols .mil-slot:not(.mil-slot-empty)').length,
                  icons: document.querySelectorAll('.mil-slot-img[src]').length }; })()`);
              if (info.designer.slots !== 25) result.failures.push(`${size.name}/army: the designer grid is not 5 x 5`);
              await wc.executeJavaScript(`[...document.querySelectorAll('.mil-view-btn')].find((b) => b.textContent === 'Text').click()`);
              await waitFor(wc, `!!document.querySelector('.mil-dd-text')`, 10000);
              await wc.executeJavaScript(`[...document.querySelectorAll('.mil-view-btn')].find((b) => b.textContent === 'Graphic').click()`);
              await waitFor(wc, `!!document.querySelector('.mil-dd')`, 10000);
              await wc.executeJavaScript(`document.querySelector('.mil-tpl-open').scrollIntoView()`);
              await sleep(500);
              wc.invalidate();   // a hidden window: repaint before the screenshot
              await sleep(1500);
              fs.writeFileSync(path.join(outDir, `${size.name}-army-designer.png`), (await wc.capturePage()).toPNG());
            }
            // the tiles by their title (Tank designs comes before Air Force)
            const panel = (title) => `[...document.querySelectorAll('.hoi-panel')].find((p) => p.querySelector('.hoi-head-title')?.textContent === '${title}')`;
            if (await waitFor(wc, `!!${panel('Tank designs')}?.querySelector('.mil-design-head')`, 15000)) {   // a tank design: the tank designer
              await wc.executeJavaScript(`(() => { localStorage.removeItem('hoi4dbg.tankView'); ${panel('Tank designs')}.querySelector('.mil-design-head').click(); })()`);
              await waitFor(wc, `!!document.querySelector('.mil-tdg .mil-td-tank')`, 15000);
              info.tankDesign = await wc.executeJavaScript(`(() => { const d = document.querySelector('.mil-tdg'); d.scrollIntoView();
                return { slots: d.querySelectorAll('.mil-pd-slot').length, drawing: !!d.querySelector('.mil-td-tank'),
                  modules: d.querySelectorAll('.mil-pd-img').length, mios: document.querySelectorAll('.mil-design-type').length,
                  mio: d.querySelector('.mil-mio')?.textContent ?? null }; })()`);
              if (info.tankDesign.slots !== 9) result.failures.push(`${size.name}/army: the tank designer should show 2 + 3 + 4 slots`);
              if (!info.tankDesign.drawing) result.failures.push(`${size.name}/army: the tank designer shows no chassis drawing`);
              await sleep(500);
              wc.invalidate();
              await sleep(1500);
              fs.writeFileSync(path.join(outDir, `${size.name}-tank-designer.png`), (await wc.capturePage()).toPNG());
              await wc.executeJavaScript(`${panel('Tank designs')}.querySelector('.mil-design-head').click()`);   // folded again
            }
            // the compare tile at the bottom: a table of stats; a second column can be added and removed again
            if (await waitFor(wc, `!!document.querySelector('.cmp-panel .cmp-table tbody tr th.cmp-label')`, 20000)) {
              info.compare = await wc.executeJavaScript(`(async () => {
                const rows = () => document.querySelectorAll('.cmp-panel .cmp-table tbody tr').length;
                const cols = () => document.querySelectorAll('.cmp-panel th.cmp-col').length;
                const before = cols();
                [...document.querySelectorAll('.cmp-panel .cmp-actions button')].find((b) => b.textContent.includes('Add column'))?.click();
                for (let i = 0; i < 40 && cols() === before; i += 1) await new Promise((r) => setTimeout(r, 250));
                const added = cols();
                const sel = document.querySelector('.cmp-panel th.cmp-col:last-child select');   // another country in the new column
                const other = [...(sel?.options ?? [])].find((o) => o.value !== sel.value && ['SOV', 'GER', 'FRA'].includes(o.value));
                if (other) { sel.value = other.value; sel.dispatchEvent(new Event('change')); await new Promise((r) => setTimeout(r, 3000)); }
                document.querySelector('.cmp-panel').scrollIntoView();
                return { rows: rows(), before, added, other: other?.value ?? null }; })()`);
              await wc.executeJavaScript(`document.querySelector('.cmp-panel .cmp-table').scrollIntoView({ block: 'start' })`);
              await sleep(500);
              wc.invalidate();
              await sleep(1500);
              fs.writeFileSync(path.join(outDir, `${size.name}-compare.png`), (await wc.capturePage()).toPNG());
              info.compare.after = await wc.executeJavaScript(`(async () => {
                const cols = () => document.querySelectorAll('.cmp-panel th.cmp-col').length;
                const before = cols();
                document.querySelector('.cmp-panel th.cmp-col:last-child button')?.click();
                for (let i = 0; i < 40 && cols() === before; i += 1) await new Promise((r) => setTimeout(r, 250));
                return cols(); })()`);
              if (!(info.compare.rows > 5 && info.compare.added === info.compare.before + 1 && info.compare.after === info.compare.before)) {
                result.failures.push(`${size.name}/compare: ${JSON.stringify(info.compare)}`);
              }
            } else result.failures.push(`${size.name}/compare: no stats table`);
            if (await waitFor(wc, `!!${panel('Air Force')}?.querySelector('.mil-design-head')`, 15000)) {   // a plane design unfolds into its modules
              await wc.executeJavaScript(`(() => { localStorage.removeItem('hoi4dbg.planeView'); ${panel('Air Force')}.querySelector('.mil-design-head').click(); })()`);
              await waitFor(wc, `!!document.querySelector('.mil-pdg')`, 10000);
              await waitFor(wc, `!!document.querySelector('.mil-pdg-plane')`, 15000);
              info.planeDesign = await wc.executeJavaScript(`(() => { document.querySelector('.mil-design-open').scrollIntoView();
                return { designs: document.querySelectorAll('.mil-design').length, slots: document.querySelectorAll('.mil-pdg .mil-pd-slot').length,
                  locked: document.querySelectorAll('.mil-pd-locked').length, blueprint: !!document.querySelector('.mil-pdg-plane') }; })()`);
              if (info.planeDesign.slots !== 12) result.failures.push(`${size.name}/air: the plane designer should show 5 + 7 slots`);
              await wc.executeJavaScript(`[...document.querySelectorAll('.mil-design-view .mil-view-btn')].find((b) => b.textContent === 'Text').click()`);
              await waitFor(wc, `!document.querySelector('.mil-pdg')`, 10000);
              await wc.executeJavaScript(`[...document.querySelectorAll('.mil-design-view .mil-view-btn')].find((b) => b.textContent === 'Graphic').click()`);
              await waitFor(wc, `!!document.querySelector('.mil-pdg-plane')`, 10000);
              await wc.executeJavaScript(`document.querySelector('.mil-design-open').scrollIntoView()`);
              await sleep(500);
              wc.invalidate();   // a hidden window keeps the old frame until it repaints
              await sleep(1500);
              fs.writeFileSync(path.join(outDir, `${size.name}-air-designer.png`), (await wc.capturePage()).toPNG());
              wc.invalidate();
              await sleep(1200);
            }
          }
          if (tab === 'equipment') {   // the needs of the divisions: Live / On refresh, read from game memory (or the save without a game)
            await waitFor(wc, `/game memory|live not read/.test([...document.querySelectorAll('.card')].find((c) => /Needs of the divisions/.test(c.querySelector('h2')?.textContent ?? ''))?.querySelector('.hoi-status')?.textContent ?? '')`, 30000);
            info.needs = await wc.executeJavaScript(`(() => { const c = [...document.querySelectorAll('.card')].find((x) => /Needs of the divisions/.test(x.querySelector('h2')?.textContent ?? ''));
              return c ? { switch: !!c.querySelector('.hoi-mode'), status: c.querySelector('.hoi-status')?.textContent ?? null,
                rows: c.querySelectorAll('tr.eq-group').length, produced: [...c.querySelectorAll('th')].some((t) => t.textContent === 'Produced / day') } : null; })()`);
            if (!info.needs?.switch || !info.needs.rows) result.failures.push(`${size.name}/equipment: needs table ${JSON.stringify(info.needs)}`);
            await wc.executeJavaScript(`[...document.querySelectorAll('.card')].find((c) => /Needs of the divisions/.test(c.querySelector('h2')?.textContent ?? ''))?.scrollIntoView()`);
            await sleep(500);
            wc.invalidate();
            await sleep(1200);
            fs.writeFileSync(path.join(outDir, `${size.name}-equipment-needs.png`), (await wc.capturePage()).toPNG());
          }
          if (tab === 'construction') {
            // queue rows, the empty-queue line, or the reason (game not running)
            await waitFor(wc, `!!document.querySelector('.construction-line, .research-summary, .live-panel-body .notice')`, 20000);
            info.construction = await wc.executeJavaScript(`({
              lines: document.querySelectorAll('.construction-line').length,
              text: document.querySelector('.research-summary, .live-panel-body .notice')?.textContent ?? null })`);
            if (!info.construction.lines && !info.construction.text) result.failures.push(`${size.name}/construction: shows nothing`);
          }
          if (tab === 'research') {
            await waitFor(wc, `!!document.querySelector('.research-slot, .live-panel-body .notice')`, 20000);
            info.researchSlots = await wc.executeJavaScript(`document.querySelectorAll('.research-slot').length`);
            info.researchSwitch = await wc.executeJavaScript(`document.querySelectorAll('.hoi-mode').length`);
            if (!info.researchSlots) result.failures.push(`${size.name}/research: no research slots shown`);
            if (info.researchSwitch !== 2) result.failures.push(`${size.name}/research: ${info.researchSwitch}/2 Live/On refresh switches (slots, tabs & tree)`);
            await waitFor(wc, `!!document.querySelector('.research-tab')`, 20000);
            info.researchTabs = await wc.executeJavaScript(`document.querySelectorAll('.research-tab').length`);
            if (!info.researchTabs) result.failures.push(`${size.name}/research: no research tabs shown`);
            info.researchTabImages = await wc.executeJavaScript(`[...document.querySelectorAll('.research-tab')].filter((b) => b.style.backgroundImage).length`);
            if (info.researchTabImages !== info.researchTabs) result.failures.push(`${size.name}/research: ${info.researchTabImages}/${info.researchTabs} tabs with the game image`);
            await waitFor(wc, `!!document.querySelector('.tech-item, .tech-tree-scroll + .notice')`, 60000);
            info.techItems = await wc.executeJavaScript(`document.querySelectorAll('.tech-item').length`);
            if (!info.techItems) result.failures.push(`${size.name}/research: technology tree empty`);
            await wc.executeJavaScript(`document.querySelector('.research-tab-strip').scrollIntoView()`);
            await sleep(300);
            await wc.executeJavaScript(`document.querySelector('.tech-tree-scroll')?.scrollIntoView({ block: 'start' })`);
            wc.invalidate();
            await sleep(1200);
          }
          // every tile with a title can be folded: the first one folds to its head and unfolds again (state restored)
          info.tiles = await wc.executeJavaScript(`(async () => {
            const tiles = [...document.querySelectorAll('#view .card, #view .hoi-panel')].filter((t) =>
              [...t.children].some((c) => c.classList.contains('card-head') || c.classList.contains('hoi-head')));
            const headOf = (t) => [...t.children].find((c) => c.classList.contains('card-head') || c.classList.contains('hoi-head'));
            const toggles = tiles.filter((t) => headOf(t).querySelector('.tile-toggle')).length;
            const t = tiles.find((x) => !x.classList.contains('tile-collapsed'));
            let folded = null;
            if (t) {
              const btn = headOf(t).querySelector('.tile-toggle');
              btn.click();
              folded = [...t.children].filter((c) => !c.classList.contains('card-head') && !c.classList.contains('hoi-head'))
                .every((c) => getComputedStyle(c).display === 'none');
              btn.click();
            }
            // head layout: title at the left, the tile's controls next to the fold button at the right edge
            const head = document.querySelector('#view .hoi-head:has(> .hoi-head-right .tile-toggle)');
            let layout = null;
            if (head) {
              const r = (el) => el.getBoundingClientRect();
              const hb = r(head), tb = r(head.querySelector('.tile-toggle'));
              layout = tb.right > hb.right - 20;   // the fold button at the right edge (a narrow head may wrap to a second line)
            }
            return { tiles: tiles.length, toggles, folded, layout, all: !!document.querySelector('#view .view-header .tile-all') };
          })()`);
          if (info.tiles.toggles !== info.tiles.tiles || info.tiles.folded === false || info.tiles.layout === false) {
            result.failures.push(`${size.name}/${tab}: tiles not collapsible ${JSON.stringify(info.tiles)}`);
          }
          const image = await wc.capturePage();
          const file = path.join(outDir, `${size.name}-${tab}.png`);
          fs.writeFileSync(file, image.toPNG());
          result.tabs.push({ size: size.name, tab, loaded: ok, ...info, screenshot: file });
          if (!ok) result.failures.push(`${size.name}/${tab}: view did not finish loading`);
          if (info.errors.length) result.failures.push(`${size.name}/${tab}: ${info.errors.join('; ')}`);
          if (info.hScroll) result.failures.push(`${size.name}/${tab}: horizontal page scroll`);
        }
      }
    } catch (err) {
      result.failures.push(`smoke crashed: ${err.stack || err}`);
    }
    if (folded !== null) {
      await wc.executeJavaScript(`localStorage.setItem('hoi4dbg.collapsed', ${JSON.stringify(folded)})`).catch(() => {});
    }
    if (consoleErrors.length) result.failures.push(`console errors: ${consoleErrors.length}`);
    fs.writeFileSync(path.join(outDir, 'result.json'), JSON.stringify(result, null, 2));
    quit(result.failures.length ? 1 : 0);
  });
}

module.exports = { runSmoke, TABS };
