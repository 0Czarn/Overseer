import test from 'node:test';
import assert from 'node:assert/strict';
import { focusTitle } from '../renderer/views/focus.js';

test('focus tooltip: name, description, time, needs, exclusions, plan', () => {
  const byId = new Map([['USA_a', { name: 'Alpha' }], ['USA_b', { name: 'Beta' }], ['USA_c', { name: 'Gamma' }]]);
  const f = { id: 'USA_x', name: 'Next Deal', status: 'blocked', desc: 'From the game.', days: 70,
    missing: [['USA_a', 'USA_b']], exclusive: ['USA_c'], has_conditions: true };
  assert.equal(focusTitle(f, { n: 2, ok: true }, byId), ['Next Deal (Blocked)', 'From the game.', '70 days',
    'Needs: Alpha or Beta', 'Mutually exclusive with: Gamma', 'Has game conditions the app cannot check', 'Plan #2', 'USA_x'].join('\n'));
  assert.equal(focusTitle({ id: 'X', name: 'X', status: 'completed', days: 35 }, null), 'X (Completed)\n35 days\nX');
});

test('focus auto-start messages: started each time, manual once per focus', async () => {
  const { autostartMessage } = await import('../renderer/lib/focus-autostart.js');
  const seen = new Set();
  assert.deepEqual(autostartMessage({ state: 'started', name: 'WPA', days: 70 }, seen), { text: 'Focus started: WPA (70 days)', kind: 'ok' });
  const manual = { state: 'manual', focus: 'USA_neutrality_act', name: 'Neutrality Act', reason: 'has conditions the app cannot check - start it in the game' };
  assert.equal(autostartMessage(manual, seen).kind, 'warn');
  assert.equal(autostartMessage(manual, seen), null);
  assert.equal(autostartMessage({ state: 'busy' }, seen), null);
});

test('plan timeline: each focus starts when the one before ends; dates like the game (no leap years)', async () => {
  const { planTimeline, gameDateText } = await import('../renderer/views/focus.js');
  const byId = new Map([['CUR', { days: 70 }], ['A', { days: 70 }], ['B', { days: 35, start_conditions: true }], ['C', { days: 70 }]]);
  const { items, total } = planTimeline([{ id: 'A', ok: true }, { id: 'X', ok: false, reason: 'needs A' },
    { id: 'B', ok: true }, { id: 'C', ok: true }], byId, 'CUR', 20);
  assert.deepEqual(items.map((x) => [x.n, x.start, x.end, x.next, x.manual]),
    [[1, 50, 120, true, false], [2, null, null, false, false], [3, 120, 155, false, true], [4, 155, 225, false, false]]);
  assert.equal(total, 225);
  assert.equal(gameDateText({ year: 1936, day: 103 }, 0), '14 Apr 1936');
  assert.equal(gameDateText({ year: 1936, day: 360 }, 10), '6 Jan 1937');
});

test('zoom: limits, fit and the point under the cursor stays put', async () => {
  const { clampZoom, fitZoom, anchoredScroll } = await import('../renderer/lib/zoom.js');
  assert.equal(clampZoom(5), 2);
  assert.equal(clampZoom(0.01), 0.25);
  assert.equal(fitZoom(7148, 1206, 1000, 600), 0.25);   // USA tree: very wide - smallest level
  assert.equal(fitZoom(800, 400, 1000, 600), 1.25);
  // content point under the cursor: (scroll + cursor) / zoom stays the same
  const after = anchoredScroll(300, 200, 1, 2);
  assert.equal((after + 200) / 2, (300 + 200) / 1);
});
