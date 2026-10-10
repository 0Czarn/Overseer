import test from 'node:test';
import assert from 'node:assert/strict';
import { formatModifier, modifierClass } from '../renderer/views/spirits.js';

test('modifier values are shown like the game tooltip', () => {
  assert.equal(formatModifier('stability_factor', -0.2), '-20%');
  assert.equal(formatModifier('drift_defence_factor', 0.5), '+50%');
  assert.equal(formatModifier('recovery_rate', 0.05), '+5%');
  assert.equal(formatModifier('civilian_intel_to_others', -25), '-25');
  assert.equal(formatModifier('research_slot', 1), '+1');
});

test('higher costs and penalties are bad', () => {
  assert.equal(modifierClass('stability_factor', 0.1), 'hoi-pos');
  assert.equal(modifierClass('stability_factor', -0.1), 'hoi-neg');
  assert.equal(modifierClass('land_doctrine_cost_factor', 0.2), 'hoi-neg');
  assert.equal(modifierClass('civilian_intel_to_others', -25), 'hoi-pos');
  assert.equal(modifierClass('x', 0), '');
});
