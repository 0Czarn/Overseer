import test from 'node:test';
import assert from 'node:assert/strict';
import { moveTab, orderTabs } from '../renderer/lib/nav-order.js';

test('the saved tab order is kept and new tabs go after their default predecessor', () => {
  const ids = ['a', 'b', 'c', 'd'];
  assert.deepEqual(orderTabs(ids, null), ids);
  assert.deepEqual(orderTabs(ids, ['c', 'a', 'b', 'd']), ['c', 'a', 'b', 'd']);
  assert.deepEqual(orderTabs(ids, ['d', 'gone', 'b', 'd']), ['a', 'd', 'b', 'c']);   // a first (no predecessor), c after b
});

test('a tab moves to the place of the target', () => {
  assert.deepEqual(moveTab(['a', 'b', 'c', 'd'], 'a', 'c'), ['b', 'c', 'a', 'd']);
  assert.deepEqual(moveTab(['a', 'b', 'c', 'd'], 'd', 'b'), ['a', 'd', 'b', 'c']);
  assert.deepEqual(moveTab(['a', 'b'], 'x', 'b'), ['a', 'b']);
});
