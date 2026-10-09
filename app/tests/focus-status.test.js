import test from 'node:test';
import assert from 'node:assert/strict';
import { focusStatuses } from '../renderer/lib/focus-status.js';

const tree = [
  { id: 'a', prerequisites: [] },
  { id: 'b', prerequisites: [['a']], exclusive: ['c'] },
  { id: 'c', prerequisites: [['a']], exclusive: ['b'] },
  { id: 'd', prerequisites: [['b', 'c']] },
];

test('statuses follow completed focuses, the current one and exclusions', () => {
  const s = focusStatuses(tree, new Set(['a']), 'b');
  assert.deepEqual(Object.fromEntries(s), { a: 'completed', b: 'in_progress', c: 'excluded', d: 'blocked' });
  const later = focusStatuses(tree, new Set(['a', 'b']), null);
  assert.equal(later.get('d'), 'available'); // one of b/c is enough
});
