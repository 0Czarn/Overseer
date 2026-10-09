import test from 'node:test';
import assert from 'node:assert/strict';
import {
  filterByText, formatDuration, formatValue, groupFocuses, humanize, scopeInfo, sourceInfo, stockBalance,
} from '../renderer/lib/format.js';

test('formatValue handles every unit and missing values', () => {
  assert.equal(formatValue(0.625, 'percent'), '63%');
  assert.equal(formatValue(1250000, 'integer'), '1,250,000');
  assert.equal(formatValue(112.44), '112.4');
  assert.equal(formatValue(null), '—');
  assert.equal(formatValue(undefined, 'percent'), '—');
  assert.equal(formatValue('text'), 'text');
});

test('sourceInfo labels DEMO data distinctly from live data', () => {
  assert.equal(sourceInfo('demo').label, 'DEMO');
  assert.equal(sourceInfo('live').label, 'LIVE');
  assert.equal(sourceInfo('unavailable').label, 'N/A');
  assert.notEqual(sourceInfo('demo').cls, sourceInfo('live').cls);
  assert.equal(sourceInfo('weird').label, 'WEIRD');
});

test('scopeInfo separates local from shared state', () => {
  assert.equal(scopeInfo('local').label, 'LOCAL');
  assert.equal(scopeInfo('shared').label, 'SHARED STATE');
});

test('formatDuration', () => {
  assert.equal(formatDuration(5), '5s');
  assert.equal(formatDuration(125), '2m 5s');
  assert.equal(formatDuration(3 * 3600 + 120), '3h 2m');
  assert.equal(formatDuration(2 * 86400 + 3600), '2d 1h');
  assert.equal(formatDuration(-1), '—');
  assert.equal(formatDuration(undefined), '—');
});

test('humanize', () => {
  assert.equal(humanize('industrial_complex'), 'Industrial complex');
  assert.equal(humanize(''), '');
  assert.equal(humanize(null), '');
});

test('filterByText is case-insensitive over chosen fields', () => {
  const rows = [{ tag: 'GER', name: 'Germany' }, { tag: 'SOV', name: 'Soviet Union' }];
  assert.deepEqual(filterByText(rows, 'sov', ['tag', 'name']).map((r) => r.tag), ['SOV']);
  assert.deepEqual(filterByText(rows, 'many', ['name']).map((r) => r.tag), ['GER']);
  assert.equal(filterByText(rows, '  ', ['tag']).length, 2);
});

test('stockBalance', () => {
  assert.deepEqual(stockBalance(50, 100), { ratio: 0.5, delta: -50 });
  assert.deepEqual(stockBalance(150, 100), { ratio: 1, delta: 50 });
  assert.deepEqual(stockBalance(10, 0), { ratio: 1, delta: 10 });
});

test('groupFocuses keeps all known columns and unknown statuses', () => {
  const groups = groupFocuses([
    { id: 'a', status: 'completed' }, { id: 'b', status: 'available' }, { id: 'c', status: 'mystery' },
  ]);
  assert.equal(groups.completed.length, 1);
  assert.equal(groups.in_progress.length, 0);
  assert.equal(groups.mystery.length, 1);
});
