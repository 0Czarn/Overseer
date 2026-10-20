import test from 'node:test';
import assert from 'node:assert/strict';
import { monthKey, startTradeWatch, tradeMessage } from '../renderer/lib/trade-watch.js';

test('the month of a game date (365-day years)', () => {
  assert.equal(monthKey({ year: 1936, day: 0 }), '1936.01');
  assert.equal(monthKey({ year: 1936, day: 31 }), '1936.02');
  assert.equal(monthKey({ year: 1936, day: 364 }), '1936.12');
  assert.equal(monthKey(null), null);
});

test('the message names deals to make and cancel, and shortages; nothing when all is at the target', () => {
  const advice = { country_names: { MAL: 'British Malaya', PHI: 'Philippines' }, resources: [
    { resource: 'rubber', name: 'Rubber', buy: [{ seller: 'MAL', amount: 16, factories: 2 }], cancel: [], missing: 0 },
    { resource: 'chromium', name: 'Chromium', buy: [], cancel: [{ seller: 'PHI', amount: 8 }], missing: 0 },
    { resource: 'oil', name: 'Oil', buy: [], cancel: [], missing: 2.5 }] };
  assert.equal(tradeMessage(advice, '1936.02'), 'February 1936: buy 16 Rubber from British Malaya (2 factories); '
    + 'cancel 8 Chromium from Philippines; still short: Oil 2.5');
  assert.equal(tradeMessage({ resources: [{ resource: 'oil', buy: [], cancel: [], missing: 0 }] }, '1936.02'), null);
});

test('advice only when a new month starts - the first reading is the baseline', async () => {
  let date = { year: 1936, day: 5 };
  const asked = [];
  const api = { get: async (url) => {
    if (url === '/api/live/date') return { data: { tag: 'SOV', date } };
    asked.push(url);
    return { data: { resources: [{ resource: 'rubber', name: 'Rubber', buy: [{ seller: 'MAL', amount: 8, factories: 1 }], cancel: [] }] } };
  } };
  const said = [];
  globalThis.setInterval = () => 0;
  globalThis.clearInterval = () => {};
  const stop = startTradeWatch(api, (m) => said.push(m));
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(asked.length, 0);
  stop();
  // a second watcher reading another month after its baseline
  let tick;
  globalThis.setInterval = (fn) => { tick = fn; return 0; };
  startTradeWatch(api, (m) => said.push(m));
  await new Promise((r) => setTimeout(r, 0));
  date = { year: 1936, day: 33 };
  await tick();
  assert.equal(asked.length, 1);
  assert.match(asked[0], /^\/api\/countries\/SOV\/trade-advice\?mode=surplus&limit=25$/);
  assert.deepEqual(said, ['SOV - February 1936: buy 8 Rubber from MAL (1 factory)']);
  await tick();   // same month: nothing more
  assert.equal(said.length, 1);
});
