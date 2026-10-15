import test from 'node:test';
import assert from 'node:assert/strict';
import { assignColors, cumulative, gameLabel, isFactoryMetric, MAX_SERIES, startedText } from '../renderer/views/summary.js';
import { dayText, dayTicks, niceTicks } from '../renderer/lib/linechart.js';

test('cumulative IC counts skipped days at the last value (high game speed)', () => {
  assert.deepEqual(cumulative([10, 11, 14], [100, 120, 150]), [100, 220, 670]);
});

test('a colour follows its series: survivors keep their slot, new ones take the first free slot', () => {
  const first = assignColors(['SOV', 'GER', 'USA']);
  assert.deepEqual(first, { SOV: 0, GER: 1, USA: 2 });
  assert.deepEqual(assignColors(['USA', 'JAP'], first), { USA: 2, JAP: 0 });
  assert.equal(MAX_SERIES, 8);
});

test('game days: no leap years, month ticks and round value ticks', () => {
  assert.equal(dayText(1941 * 365 + 305), '1941.11.02');
  assert.equal(dayText(1940 * 365 + 59), '1940.03.01');
  assert.deepEqual(dayTicks(1941 * 365, 1941 * 365 + 120).map(dayText), ['1941.01.01', '1941.02.01', '1941.03.01', '1941.04.01', '1941.05.01']);
  assert.deepEqual(niceTicks(1550), [0, 500, 1000, 1500, 2000]);
});

test('factory counts are a level: no cumulative chart', () => {
  assert.equal(isFactoryMetric('fmil'), true);
  assert.equal(isFactoryMetric('fall'), true);
  assert.equal(isFactoryMetric('mil'), false);
});

test('groups: moves keep only changes against the game, deleted groups send countries home', async () => {
  const { addGroup, deleteGroup, moveCountry, NO_FACTION } = await import('../renderer/views/summary.js');
  let g = { custom: [], assign: {} };
  g = addGroup(g, ' Nordic ');
  assert.deepEqual(g.custom, ['Nordic']);
  assert.equal(addGroup(g, 'Nordic'), g);            // no duplicates
  assert.equal(addGroup(g, NO_FACTION), g);
  g = moveCountry(g, { tag: 'SWE', game_faction: null }, 'Nordic');
  g = moveCountry(g, { tag: 'ITA', game_faction: 'Axis' }, NO_FACTION);
  assert.deepEqual(g.assign, { SWE: 'Nordic', ITA: '' });
  g = moveCountry(g, { tag: 'ITA', game_faction: 'Axis' }, 'Axis');   // back home: no override
  assert.deepEqual(g.assign, { SWE: 'Nordic' });
  assert.deepEqual(deleteGroup(g, 'Nordic'), { custom: [], assign: {} });
});

test('search by tag or name, case-insensitive', async () => {
  const { matches } = await import('../renderer/views/summary.js');
  const sov = { tag: 'SOV', name: 'Soviet Union' };
  assert.equal(matches(sov, ''), true);
  assert.equal(matches(sov, 'so'), true);
  assert.equal(matches(sov, 'union'), true);
  assert.equal(matches(sov, 'GER'), false);
});

test('cumulative losses start at the first known day and skip unknown ones', () => {
  assert.deepEqual(cumulative([1, 2, 3, 6], [null, 3, null, 2]), [null, 3, 3, 9]);
});

test('campaign labels: game dates and the real date the recording began', () => {
  const g = { player: 'POL', first: '1936.01.02', last: '1936.05.15', days: 114, created: '2026-10-15 09:53:17' };
  assert.equal(gameLabel(g), 'POL · 1936.01.02 → 1936.05.15 (114 days)');
  assert.equal(gameLabel({ ...g, days: 1 }), 'POL · 1936.01.02 → 1936.05.15 (1 day)');
  assert.equal(startedText(g.created), '2026-10-15 09:53');
  assert.equal(startedText(undefined), 'unknown');
});
