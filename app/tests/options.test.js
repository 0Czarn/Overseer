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

test('data sizes, settings files and shortcuts', async () => {
  const { sizeText, collectSettings, checkSettingsFile } = await import('../renderer/views/options.js');
  const { shortcutAction } = await import('../renderer/lib/shortcuts.js');
  assert.equal(sizeText(1536), '2 KB');
  assert.equal(sizeText(5 * 1024 * 1024), '5.0 MB');
  const store = { k: ['hoi4dbg.options', 'other'], v: { 'hoi4dbg.options': '{}', other: 'x' },
    get length() { return this.k.length; }, key(i) { return this.k[i]; }, getItem(k) { return this.v[k]; } };
  assert.deepEqual(collectSettings(store), { 'hoi4dbg.options': '{}' });
  assert.deepEqual(checkSettingsFile({ app: 'The OVERSEER', settings: { 'hoi4dbg.a': '1', evil: '2', 'hoi4dbg.b': 3 } }), { 'hoi4dbg.a': '1' });
  assert.throws(() => checkSettingsFile({ app: 'Other', settings: {} }));
  assert.deepEqual(shortcutAction({ key: '3', ctrlKey: true }), { type: 'tab', index: 2 });
  assert.deepEqual(shortcutAction({ key: 'Tab', ctrlKey: true, shiftKey: true }), { type: 'step', by: -1 });
  assert.deepEqual(shortcutAction({ key: 'F5' }), { type: 'reload' });
  assert.deepEqual(shortcutAction({ key: '0', ctrlKey: true }), { type: 'text', reset: true });
  assert.equal(shortcutAction({ key: 'a', ctrlKey: true }), null);
  assert.equal(shortcutAction({ key: '3' }), null);
});
