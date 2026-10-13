import test from 'node:test';
import assert from 'node:assert/strict';
import { sortMessage } from '../renderer/lib/construction-sort.js';
import { actionText, completeText, factoriesHead, placeText, pointsText, progressPct, queueSummary } from '../renderer/views/construction.js';

test('construction progress cut like the game tooltip (SOV Krasnoyarsk: 6309/7200 (87%))', () => {
  assert.equal(progressPct(6309.79 / 7200), '87%');
  assert.equal(progressPct(0), '0%');
  assert.equal(progressPct(null), '');
  assert.equal(pointsText({ produced: 6309.79, cost: 7200 }), '6309 / 7200');
});

test('construction queue summary (FRA 1936: 12 lines, 2 being built with 15 + 4 factories)', () => {
  const lines = [{ factories: 15, action: 'build' }, { factories: 4, action: 'build' }, ...Array(10).fill({ factories: 0, action: 'build' })];
  assert.equal(queueSummary(lines), '12 in queue · 2 being built · 19 factories working');
  assert.equal(queueSummary([]), 'Nothing in the construction queue');
});

test('next level complete like the game tooltip (SOV 27 Sep 1941: 2 Oct, 1941)', () => {
  assert.equal(completeText({ days_left: 5, speed: 183.75, next_complete: { text: '2 Oct, 1941' } }),
    '5 days · 2 Oct, 1941 · 183.75 a day');
  assert.equal(completeText({ days_left: null, speed: 0 }), 'Not being built');
});

test('repair or construction (SOV 1941: rail_way 0 levels to build, 1 to repair)', () => {
  assert.equal(actionText({ action: 'repair', levels: 0, repair: 2 }), 'Repair: 2 damaged levels');
  assert.equal(actionText({ action: 'build', levels: 1, repair: 0 }), '1 level to build');
  assert.equal(actionText({ action: 'build_repair', levels: 1, repair: 1 }), '1 new level to build, 1 damaged level to repair');
  const lines = [{ factories: 15, action: 'build' }, { factories: 0, action: 'repair' }, { factories: 0, action: 'repair' }];
  assert.equal(queueSummary(lines), '3 in queue · 2 repairs · 1 being built · 15 factories working');
});

test('place of a line: state, railway from state to state', () => {
  assert.equal(placeText({ state_name: 'Bryansk' }), 'Bryansk');
  assert.equal(placeText({ place: 'Bizerte - Tunis', state_name: 'Tunisia' }), 'Bizerte - Tunis');
  assert.equal(placeText({ state_name: 'Bryansk', end_state_name: 'Kharkov' }), 'Bryansk → Kharkov');
  assert.equal(placeText({ state: 288, state_name: null }), 'State 288');
});

test('railway line like the game tooltip (FRA Constantine - Algiers)', () => {
  assert.equal(actionText({ action: 'build', levels: 4, repair: 0, railway_levels: [2, 3] }),
    'upgrading level 2 railways to level 3 · 4 railways needed');
  assert.equal(actionText({ action: 'build', levels: 1, repair: 0, railway_levels: [0, 1] }), 'new railways to level 1 · 1 railway needed');
});

test('civilian factories header like the game (SOV 1941: 161/161, from trade 38, owned 123)', () => {
  assert.equal(factoriesHead({ total: 161, from_trade: 38, owned: 123 }), '161/161 · From trade: 38 · Owned: 123');
});

test('auto-sort message only when the queue was changed', () => {
  assert.equal(sortMessage({ applied: false, moved: [] }), null);
  assert.equal(sortMessage({ applied: true, moved: [
    { building: 'industrial_complex', location: 568, state_name: 'Krasnoyarsk', progress: 0.876, to: 1 },
    { building: 'arms_factory', location: 400, progress: 0.5, to: 2 }] }),
  'Construction queue sorted (2 moved): Krasnoyarsk 87% → 1');
});
