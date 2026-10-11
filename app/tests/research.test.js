import test from 'node:test';
import assert from 'node:assert/strict';
import { aheadText, progressText, slotSummary, speedText } from '../renderer/views/research.js';

test('research speed bonus as the game shows it', () => {
  assert.equal(speedText(1.13), '+13%');
  assert.equal(speedText(0.9), '-10%');
  assert.equal(speedText(1), '');
  assert.equal(speedText(null), '');   // from a save: not known
});

test('slot summary counts researching slots', () => {
  assert.equal(slotSummary([{ technology: 'excavation1' }, { technology: null }, { technology: 'interwar_artillery' }]),
    '2 of 3 slots researching');
  assert.equal(slotSummary([{ technology: null }]), '0 of 1 slot researching');
});

test('progress like the game: 18.7% finished, 146 days left', () => {
  assert.equal(progressText({ progress: 41.28 / 220, days_left: 146, estimate: false }), '18.7% finished · 146 days left');
  assert.equal(progressText({ progress: 0.2465, days_left: 159, estimate: true }), '24.6% finished · ~159 days left');
  assert.equal(progressText({ progress: null }), '');
});

test('ahead of time penalty shown apart from the slot speed', () => {
  // antiair1 2.28 years ahead: 0.20327 points/day of a 1.13 slot (the game showed 5.5 %, 401 days)
  const s = { speed: 0.20327, base_speed: 1.13, ahead_years: 2.2795 };
  assert.equal(speedText(s.base_speed), '+13%');
  assert.equal(aheadText(s), '2.3 years ahead of time: -82% speed');
  assert.equal(aheadText({ speed: 1.13, base_speed: 1.13, ahead_years: null }), '');
});
