import test from 'node:test';
import assert from 'node:assert/strict';
import { tipPosition } from '../renderer/lib/tooltips.js';

const rect = (left, top, w = 50, hgt = 50) => ({ left, top, right: left + w, bottom: top + hgt });

test('tooltip below its tile when it fits', () => {
  assert.deepEqual(tipPosition(rect(100, 100), 300, 200, 1920, 1080), { left: 100, top: 156 });
});

test('tooltip above a tile at the bottom of the window (Military Staff)', () => {
  assert.deepEqual(tipPosition(rect(530, 835), 340, 260, 1920, 1040), { left: 530, top: 569 });
});

test('a tall tooltip that fits neither below nor above stays inside the window; moved left at the right edge', () => {
  assert.deepEqual(tipPosition(rect(1800, 300), 340, 900, 1920, 1000), { left: 1576, top: 96 });
  assert.equal(tipPosition(rect(10, 10), 300, 2000, 800, 600).top, 4);
});
