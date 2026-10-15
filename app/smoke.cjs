'use strict';
// Smoke test driver (HOI4DBG_SMOKE_DIR set): visits every tab, captures screenshots,
// records renderer console errors, writes result.json and quits.

const fs = require('node:fs');
const path = require('node:path');

const TABS = ['dashboard', 'summary', 'countries', 'country-editor', 'research', 'construction', 'doctrines', 'state-editor', 'focus', 'equipment', 'tools',
  'logs'];
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
    try {
      if (!(await waitFor(wc, "document.body.dataset.ready === '1'"))) result.failures.push('app never became ready');
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
          if (tab === 'summary') {
            await waitFor(wc, `!!document.querySelector('.lc-svg, .gs-charts .notice')`, 20000);
            info.summary = await wc.executeJavaScript(`({ charts: document.querySelectorAll('.lc-svg').length,
              lines: document.querySelectorAll('.lc-line').length, countries: document.querySelectorAll('.gs-country').length,
              notice: document.querySelector('.gs-charts .notice')?.textContent ?? null })`);
            if (!info.summary.charts && !info.summary.notice) result.failures.push(`${size.name}/summary: shows nothing`);
            if (info.summary.charts === 2) {   // hover one chart: the values of the day show in both
              info.summary.hover = await wc.executeJavaScript(`(() => {
                const hit = document.querySelector('.lc-hit'); const r = hit.getBoundingClientRect();
                hit.dispatchEvent(new MouseEvent('mousemove', { clientX: r.left + r.width / 2, clientY: r.top + 10, bubbles: true }));
                return [...document.querySelectorAll('.lc-tip')].map((t) => (t.hidden ? null : [...t.querySelectorAll('.lc-tip-row')].length));
              })()`);
              if (!info.summary.hover.every((n) => n > 0)) result.failures.push(`${size.name}/summary: hover shows no values in both charts`);
              info.summary.search = await wc.executeJavaScript(`(() => { const i = document.querySelector('.gs-search');
                i.value = 'sov'; i.dispatchEvent(new Event('input'));
                const n = [...document.querySelectorAll('.gs-country-tag')].map((e) => e.textContent);
                i.value = ''; i.dispatchEvent(new Event('input')); return n; })()`);
              if (!info.summary.search.includes('SOV') || info.summary.search.length > 3) result.failures.push(`${size.name}/summary: search does not filter`);
              await wc.executeJavaScript(`(() => { const c = document.querySelector('.gs-color'); c.value = '#ffffff';
                c.dispatchEvent(new Event('change')); })()`);
              await waitFor(wc, `[...document.querySelectorAll('.lc-line')].some((l) => l.getAttribute('stroke') === '#ffffff')`, 10000);
            }
            if (info.summary.charts) {   // factory counts: one chart (a level, no cumulative)
              await wc.executeJavaScript(`document.querySelectorAll('.gs-seg')[1].querySelectorAll('.gs-seg-btn')[1].click()`);
              await waitFor(wc, `document.querySelector('.lc-title')?.textContent === 'Military factories'`, 10000);
              info.summary.factoryCharts = await wc.executeJavaScript(`document.querySelectorAll('.lc-svg').length`);
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
          if (tab === 'doctrines') {
            await waitFor(wc, `!!document.querySelector('.doc-tab, .live-panel-body .notice')`, 20000);
            await waitFor(wc, `!!document.querySelector('.mil-bigs, .live-panel-body .notice')`, 20000);
            info.military = await wc.executeJavaScript(`[...document.querySelectorAll('.mil-big-value')].map((e) => e.textContent)`);
            info.doctrines = await wc.executeJavaScript(`({ tabs: document.querySelectorAll('.doc-tab').length,
              tracks: document.querySelectorAll('.doc-track').length,
              notice: document.querySelector('.live-panel-body .notice')?.textContent ?? null })`);
            if (!info.doctrines.tabs && !info.doctrines.notice) result.failures.push(`${size.name}/doctrines: shows nothing`);
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
    if (consoleErrors.length) result.failures.push(`console errors: ${consoleErrors.length}`);
    fs.writeFileSync(path.join(outDir, 'result.json'), JSON.stringify(result, null, 2));
    quit(result.failures.length ? 1 : 0);
  });
}

module.exports = { runSmoke, TABS };
