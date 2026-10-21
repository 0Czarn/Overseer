import test from 'node:test';
import assert from 'node:assert/strict';
import { KINDS, diffText } from '../renderer/views/compare.js';
import { cut } from '../renderer/views/military.js';

test('difference to the reference column in the row format', () => {
  const f = (v) => cut(v, 1);
  assert.equal(diffText(12.5, 10, f), '+2.5');
  assert.equal(diffText(8, 10, f), '−2.0');
  assert.equal(diffText(10, 10, f), '=');
  assert.equal(diffText(null, 10, f), '');
  assert.equal(diffText(0.81, 0.77, (v) => `${cut(v * 100, 1)}%`), '+4.0%');
});

test('items of each kind from a military response: templates with designer stats, current designs only', () => {
  const data = { army: { templates: [{ name: 'Inf', count: 3, designer: { stats: { soft_attack: 30 }, cost: { cost_max: 400, fuel_capacity: 0, fuel_usage: 0 } } },
    { name: 'Empty', count: 0 }],
  tank_designs: [{ id: 1, name: 'BT-7', type_name: 'Improved Light Tank', outdated: false, stats: { armor_value: 31 } }, { id: 2, name: 'Old', outdated: true, stats: {} }] },
  air: { designs: [{ id: 5, name: 'I-16', type_name: 'Fighter', outdated: false, stats: { air_attack: 20 } }] } };
  const div = KINDS.divisions.items(data);
  assert.deepEqual(div.map((x) => [x.name, x.note, x.stats.soft_attack, x.stats.cost_max]), [['Inf', '3 divisions', 30, 400]]);
  assert.deepEqual(KINDS.tanks.items(data).map((x) => x.name), ['BT-7']);
  assert.deepEqual(KINDS.planes.items(data).map((x) => x.id), ['5']);
});

test('every stat row of the compare tile has an icon file', async () => {
  const { DESIGNER_ICON_LABELS } = await import('../renderer/lib/icons.js');
  const fs = await import('node:fs');
  const labels = Object.values(KINDS).flatMap((k) => k.groups.flatMap(([, rows]) => rows.map(([, label]) => label)));
  const missing = [...new Set(labels)].filter((l) => !DESIGNER_ICON_LABELS.includes(l));
  assert.deepEqual(missing, []);
  const src = fs.readFileSync(new URL('../renderer/lib/icons.js', import.meta.url), 'utf8');
  for (const file of src.match(/[a-z_]+(?:_texticon)?\.png/g)) {
    assert.ok(fs.existsSync(new URL(`../renderer/assets/texticons/${file}`, import.meta.url)), file);
  }
});

test('a design note names its MIO; a design without one only its type', async () => {
  const { designNote } = await import('../renderer/views/compare.js');
  const d = { mios: { 6: { key: 'GER_henschel_organization', name: 'Henschel', icon: null } } };
  assert.equal(designNote({ type_name: 'Basic Heavy Tank Destroyer', mio: 6 }, d), 'Basic Heavy Tank Destroyer · Henschel');
  assert.equal(designNote({ type_name: 'Light Tank', mio: null }, d), 'Light Tank');
  assert.equal(designNote({ type_name: 'Light Tank', mio: 99 }, d), 'Light Tank');
});
