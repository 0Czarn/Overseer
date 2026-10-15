import test from 'node:test';
import assert from 'node:assert/strict';
import { groupByDay, KINDS } from '../renderer/views/actions.js';

test('players actions: newest day first, filters by kind, country and text', () => {
  const ev = (date, tag, kind, name) => ({ date, tag, kind, action: 'added', name });
  const events = [ev('1936.05.01', 'POL', 'focus', 'Polish Militarism'), ev('1936.05.01', 'GER', 'ideas', 'Partial Mobilization'),
    ev('1936.05.02', 'POL', 'research', 'Infantry Weapons I')];
  assert.deepEqual(groupByDay(events).map(([d, list]) => [d, list.length]), [['1936.05.02', 1], ['1936.05.01', 2]]);
  assert.deepEqual(groupByDay(events, { hidden: ['research'] }).map(([d]) => d), ['1936.05.01']);
  assert.equal(groupByDay(events, { tag: 'GER' })[0][1][0].name, 'Partial Mobilization');
  assert.equal(groupByDay(events, { search: 'militarism' })[0][1][0].tag, 'POL');
  assert.equal(Object.keys(KINDS).length, 12);   // every kind of the backend (hoi4dbg/actions.py KINDS)
});
