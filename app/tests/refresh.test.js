import test from 'node:test';
import assert from 'node:assert/strict';
import { dataKey, saveSource } from '../renderer/lib/refresh.js';

test('change detection ignores read time stamps', () => {
  assert.equal(dataKey({ a: 1, read_at: 5, b: { read_at: 9, c: 2 } }), dataKey({ a: 1, read_at: 7, b: { c: 2, read_at: 1 } }));
  assert.notEqual(dataKey({ a: 1 }), dataKey({ a: 2 }));
});

test('source line names the live parts', () => {
  const res = { data: { file: { name: 'x.hoi4' }, in_game_date: { text: '1936.3.12.1' } } };
  assert.equal(saveSource(res), 'save x.hoi4 · 1936.3.12.1');
  assert.equal(saveSource(res, ['parties']), 'LIVE: parties · save x.hoi4 · 1936.3.12.1');
});
