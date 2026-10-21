import test from 'node:test';
import assert from 'node:assert/strict';
import { tankRows, tankSlotLabel, tankStatLines } from '../renderer/views/military.js';

test('tank designer rows: turret and gun, suspension armor engine, four specials; missing slots locked', () => {
  const slots = [{ slot: 'turret_type_slot', module: 't' }, { slot: 'main_armament_slot', module: null },
    { slot: 'engine_type_slot', module: 'e' }, { slot: 'special_type_slot_1', module: 'r' }];
  const [top, mid, special] = tankRows(slots);
  assert.deepEqual(top.map((s) => s?.module), ['t', null]);
  assert.deepEqual(mid.map((s) => s?.slot ?? null), [null, null, 'engine_type_slot']);
  assert.equal(special.length, 4);
  assert.equal(special[3], null);
  assert.equal(tankSlotLabel('main_armament_slot'), 'Main armament');
  assert.equal(tankSlotLabel('special_type_slot_3'), 'Special 3');
});

test('tank stats in the designer columns', () => {
  const lines = tankStatLines({ maximum_speed: 10.44, reliability: 0.77, soft_attack: 15, ap_attack: 50, hardness: 0.8, fuel_consumption: 2.5 });
  assert.deepEqual(lines.map(([t]) => t), ['Base Stats', 'Combat Stats', 'Misc. Stats']);
  assert.deepEqual(lines[0][1], [['Max Speed', '10.44 km/h'], ['Reliability', '77.0%']]);
  assert.deepEqual(lines[1][1].find(([l]) => l === 'Hardness'), ['Hardness', '80.0%']);
});
