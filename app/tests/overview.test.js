import test from 'node:test';
import assert from 'node:assert/strict';
import { slicePath } from '../renderer/views/overview.js';

test('pie slices start at the top and go clockwise', () => {
  assert.equal(slicePath(50, 50, 40, 0, 0.25), 'M 50 50 L 50.000 10.000 A 40 40 0 0 1 90.000 50.000 Z');
  assert.match(slicePath(50, 50, 40, 0, 0.75), / 0 1 1 /);          // large-arc flag for more than half
  assert.match(slicePath(50, 50, 40, 0, 1), /^M 50 10 A 40 40 0 1 1/); // 100 % = full circle
});
