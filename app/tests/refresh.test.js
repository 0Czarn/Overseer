import test from 'node:test';
import assert from 'node:assert/strict';
import { dataKey, readMode, saveSource, writeMode } from '../renderer/lib/refresh.js';

test('change detection ignores read time stamps', () => {
  assert.equal(dataKey({ a: 1, read_at: 5, b: { read_at: 9, c: 2 } }), dataKey({ a: 1, read_at: 7, b: { c: 2, read_at: 1 } }));
  assert.notEqual(dataKey({ a: 1 }), dataKey({ a: 2 }));
});

test('source line names the live parts', () => {
  const res = { data: { file: { name: 'x.hoi4' }, in_game_date: { text: '1936.3.12.1' } } };
  assert.equal(saveSource(res), 'save x.hoi4 · 1936.3.12.1');
  assert.equal(saveSource(res, ['parties']), 'LIVE: parties · save x.hoi4 · 1936.3.12.1');
});

test('tile mode: Live by default, On refresh remembered per tile', () => {
  const store = new Map();
  const storage = { getItem: (k) => store.get(k) ?? null, setItem: (k, v) => store.set(k, v) };
  assert.equal(readMode(storage, 'Resources'), 'live');
  writeMode(storage, 'Resources', 'manual');
  assert.equal(readMode(storage, 'Resources'), 'manual');
  assert.equal(readMode(storage, 'National spirits'), 'live');
  writeMode(storage, 'Resources', 'live');
  assert.equal(readMode(storage, 'Resources'), 'live');
});

test('tile mode survives a broken storage', () => {
  const broken = { getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); } };
  assert.equal(readMode(broken, 'x'), 'live');
  assert.doesNotThrow(() => writeMode(broken, 'x', 'manual'));
  assert.equal(readMode(null, 'x'), 'live');
});
