import test from 'node:test';
import assert from 'node:assert/strict';
import { irisShift } from '../renderer/lib/eye.js';

test('the iris turns towards the cursor, less when it is close, never out of the eye', () => {
  assert.deepEqual(irisShift(0, 0, 600), { x: 0, y: 0 });
  const far = irisShift(5000, 0, 600);
  assert.equal(Math.round(far.x), 46);
  assert.equal(far.y, 0);
  const near = irisShift(100, 0, 600);
  assert.ok(near.x > 0 && near.x < far.x);
  const up = irisShift(0, -5000, 600);
  assert.ok(up.y < 0 && Math.abs(up.y) < 46);   // the almond is lower than wide
});
