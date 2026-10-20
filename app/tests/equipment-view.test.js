import test from 'node:test';
import assert from 'node:assert/strict';
import { archetypeTotals, coverage, totalChanges } from '../renderer/views/equipment.js';

test('live stockpile summed per archetype, changes between two readings', () => {
  const t1 = archetypeTotals([{ id: '1', archetype: 'infantry_equipment', amount: 100 },
    { id: '2', archetype: 'infantry_equipment', amount: 50 }, { id: '3', type: 'train_equipment_1', amount: 4 }]);
  assert.deepEqual(t1, { infantry_equipment: 150, train_equipment_1: 4 });
  const t2 = archetypeTotals([{ id: '1', archetype: 'infantry_equipment', amount: 120 }, { id: '4', archetype: 'support_equipment', amount: 10 }]);
  assert.deepEqual(totalChanges(t1, t2), { infantry_equipment: -30, train_equipment_1: -4, support_equipment: 10 });
});

test('coverage of the need by divisions and the stockpile', () => {
  assert.equal(coverage({ need: 100, held: 60, stockpile: 20 }), 0.8);
  assert.equal(coverage({ need: 100, held: 60 }, 100), 1);
  assert.equal(coverage({ need: 0, held: 0, stockpile: 5 }), null);
});
