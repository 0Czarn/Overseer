import test from 'node:test';
import assert from 'node:assert/strict';
import { DEFAULTS, fitStyle, normalizeOptions } from '../renderer/lib/options.js';

test('stored options are checked and completed with the defaults', () => {
  assert.deepEqual(normalizeOptions(null), DEFAULTS);
  const o = normalizeOptions({ theme: 'pink', eyeOpacity: 250, imageOpacity: '40', image: '../x', imageFit: 'tile', imageBlur: -3 });
  assert.equal(o.theme, '1984');
  assert.equal(o.eyeOpacity, 100);
  assert.equal(o.imageOpacity, 40);
  assert.equal(o.image, null);
  assert.equal(o.imageFit, 'tile');
  assert.equal(o.imageBlur, 0);
  assert.equal(normalizeOptions({ theme: 'classic', image: '0123456789abcdef' }).image, '0123456789abcdef');
});

test('image placement', () => {
  assert.equal(fitStyle('cover').backgroundSize, 'cover');
  assert.equal(fitStyle('tile').backgroundRepeat, 'repeat');
});
