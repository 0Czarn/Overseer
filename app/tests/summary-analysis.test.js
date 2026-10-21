import test from 'node:test';
import assert from 'node:assert/strict';
import { extraNote, isLevelMetric, metricFormat } from '../renderer/views/summary.js';
import { forecast } from '../renderer/views/summary-equipment.js';
import { rgb, rowAt, standings, statesAt } from '../renderer/views/summary-map.js';
import { minutesText, rankMove } from '../renderer/views/summary-extra.js';
import { esc, reportName } from '../renderer/views/summary-report.js';

test('values recorded from 2026-10-21 are levels with their own format', () => {
  for (const m of ['pp', 'stab', 'divs', 'vp', 'tech', 'mpall', 'kd']) assert.equal(isLevelMetric(m), true, m);
  assert.equal(metricFormat('stab')(55.25), '55.3%');
  assert.equal(metricFormat('divs')(41.6), '42');
  assert.equal(metricFormat('kd')(1.234), '1.23');
  assert.match(extraNote('kd'), /above 1/);
});

test('production forecast: days to fill the missing equipment at today\'s production', () => {
  const rows = forecast({ inf: [1000, 600, 100, 50], art: [100, 100, 20, 5], tank: [50, 0, 0, 0] },
    [{ key: 'inf', name: 'Infantry' }], 1941 * 365);
  assert.deepEqual(rows.map((r) => [r.key, r.missing, r.days]), [['tank', 50, null], ['inf', 300, 6], ['art', 0, 0]]);
  assert.equal(rows[1].ready, '1941.01.07');
  assert.equal(rows[1].name, 'Infantry');
});

test('campaign map: states of a day from the last full row and the changes after it', () => {
  const rows = [{ t: 1, full: 1, s: { 1: ['GER', 'GER'], 2: ['POL', 'POL'] } }, { t: 5, s: { 2: ['POL', 'GER'] } },
    { t: 9, full: 1, s: { 1: ['GER', 'GER'], 2: ['GER', 'GER'] } }];
  assert.deepEqual(statesAt(rows, 1), { 1: ['GER', 'GER'], 2: ['POL', 'GER'] });
  assert.deepEqual(statesAt(rows, 2)[2], ['GER', 'GER']);
  assert.equal(rowAt(rows, 6), 1);
  assert.equal(rowAt(rows, 0), -1);
  const top = standings(statesAt(rows, 1), { 2: 10 });
  assert.deepEqual(top.map((s) => [s.tag, s.owned, s.controlled, s.vp]), [['GER', 1, 2, 10], ['POL', 1, 0, 0]]);
  assert.deepEqual(rgb('#ff8000'), [255, 128, 0]);
});

test('ranking moves, session times and report text', () => {
  assert.deepEqual(rankMove(1, 3), { text: '▲2', cls: 'gs-up' });
  assert.deepEqual(rankMove(2, 1), { text: '▼1', cls: 'gs-down' });
  assert.equal(rankMove(1, null).text, '');
  assert.equal(minutesText(125), '2 h 05 min');
  assert.equal(minutesText(45), '45 min');
  assert.equal(esc('<b>"Axis" & co</b>'), '&lt;b&gt;&quot;Axis&quot; &amp; co&lt;/b&gt;');
  assert.equal(reportName('GER_1936-01-01_x'), 'overseer-GER_1936-01-01_x.html');
});
