import test from 'node:test';
import assert from 'node:assert/strict';
import { ppCommand, verifyChange } from '../renderer/lib/verify.js';

const base = { value: 2.324, file: 'PROJEKT-OVERSEER.hoi4', mtime: 100, date: '1936.1.1.12' };

test('ppCommand builds the documented console command', () => {
  assert.equal(ppCommand('10'), 'pp 10');
  assert.equal(ppCommand(-5), 'pp -5');
  assert.equal(ppCommand('2.5'), 'pp 2.500');
  assert.equal(ppCommand('0'), null);
  assert.equal(ppCommand('abc'), null);
});

test('verifyChange passes only for a newer save with the exact expected value', () => {
  const after = { value: 12.324, file: 'x.hoi4', mtime: 200, date: '1936.1.1.12' };
  assert.equal(verifyChange(base, after, 10).status, 'pass');
  assert.equal(verifyChange(base, { ...after, value: 7.324 }, 10).status, 'fail');
});

test('verifyChange refuses stale or ambiguous evidence', () => {
  assert.equal(verifyChange(null, base, 10).status, 'waiting');
  assert.equal(verifyChange(base, { ...base, value: 12.324 }, 10).status, 'waiting'); // same file / not newer
  assert.equal(verifyChange(base, { ...base, mtime: 200, value: null }, 10).status, 'waiting');
  assert.equal(verifyChange(base, { value: 12.9, file: 'x', mtime: 200, date: '1936.1.2.12' }, 10).status, 'inconclusive');
});
