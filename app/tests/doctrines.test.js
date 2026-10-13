import test from 'node:test';
import assert from 'node:assert/strict';
import { doctrineTitle, nextRewardText } from '../renderer/views/doctrines.js';

test('doctrine tooltip: name, description, effects, tactics', () => {
  assert.equal(doctrineTitle({ name: 'Grand Battleplan', desc: 'Plan.', modifiers: [{ key: 'command_power_gain', label: 'Command Power gain', value: 0.25 }],
    tactics: ['Planned Attack'] }), 'Grand Battleplan\nPlan.\nCommand Power gain: +25%\nEnables tactic: Planned Attack');
});

test('next reward like the game ladder (SOV infantry 221.8 mastery, +0.70 a day)', () => {
  const sub = { rewards: [{ threshold: 100, unlocked: true }, { threshold: 200, unlocked: true }, { threshold: 300, unlocked: false }] };
  assert.equal(nextRewardText({ sub, mastery: 221.823, daily: 0.7036 }), 'Next reward in 112 days (~0.70 a day)');
  assert.equal(nextRewardText({ sub, mastery: 221.823, daily: 0 }), 'Next reward at 300 - no mastery gained now');
  assert.equal(nextRewardText({ sub: { rewards: [{ threshold: 100, unlocked: true }] }, mastery: 100, daily: 1 }), 'All rewards unlocked');
  assert.equal(nextRewardText({ sub: null, mastery: 0, daily: 1 }), '');
});
