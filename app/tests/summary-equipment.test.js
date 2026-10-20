import test from 'node:test';
import assert from 'node:assert/strict';
import { EQUIPMENT_LINES, equipmentSets } from '../renderer/views/summary-equipment.js';

test('needed / in divisions / stockpile become three chart series over the recorded days', () => {
  const data = { t: [10, 11], series: { needed: [100, 100], held: [80, 90], stockpile: [5, 0], produced: [3, 3] } };
  const sets = equipmentSets(data);
  assert.deepEqual(sets.map((s) => s.label), EQUIPMENT_LINES.map(([, label]) => label));
  assert.deepEqual(sets[1].points, [[10, 80], [11, 90]]);
  assert.equal(new Set(sets.map((s) => s.color)).size, 3);
});
