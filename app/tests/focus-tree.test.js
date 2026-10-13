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
