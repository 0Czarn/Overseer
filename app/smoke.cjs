'use strict';
// Smoke test driver (HOI4DBG_SMOKE_DIR set): visits every tab, captures screenshots,
// records renderer console errors, writes result.json and quits.

const fs = require('node:fs');
const path = require('node:path');

const TABS = ['dashboard', 'countries', 'country-editor', 'state-editor', 'focus', 'equipment', 'tools',
  'intel', 'logs'];
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
        for (const tab of TABS) {
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
              (s) => [s, document.querySelectorAll('.focus-node.focus-' + s).length])),
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
            info.editableChips = await wc.executeJavaScript(`document.querySelectorAll('.hoi-chip .hoi-chip-input').length`);
            if (info.editableChips !== 6) result.failures.push(`${size.name}/country-editor: ${info.editableChips}/6 editable live values`);
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
