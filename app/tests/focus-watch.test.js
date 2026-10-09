import test from 'node:test';
import assert from 'node:assert/strict';
import { focusAlert } from '../renderer/lib/focus-watch.js';

const running = { idle: false, current: 'SOV_heavy_industry', next: { name: 'Infrastructure Effort', days: 35 } };

test('no alert while a focus is running', () => {
  assert.equal(focusAlert({ idle: false, current: 'SOV_heavy_industry' }, running).message, null);
});

test('completion with nothing selected names the next planned focus', () => {
  const data = { ...running, idle: true, current: null, event: { id: 'e0', completed: 'SOV_heavy_industry', name: 'Heavy Industry' } };
  assert.equal(focusAlert({ idle: false }, data).message,
    'Completed: Heavy Industry. Start next: Infrastructure Effort (35 days).');
});

test('idle alert only once, and an empty plan is said so', () => {
  const idle = { idle: true, current: null, next: null };
  const first = focusAlert({ idle: false }, idle);
  assert.equal(first.message, 'No focus selected - your plan is empty.');
  assert.equal(focusAlert(first.next, idle).message, null);
});

test('completion followed by an immediately chosen focus still reports the completion', () => {
  const data = { idle: false, current: 'SOV_x', event: { id: 'e1', completed: 'SOV_heavy_industry', name: 'Heavy Industry' } };
  assert.equal(focusAlert({ idle: false }, data).message, 'Completed: Heavy Industry.');
});

test('a kept event is announced once (backend keeps it for all pollers)', () => {
  const data = { ...running, idle: true, current: null, event: { id: 'e1', completed: 'SOV_heavy_industry', name: 'Heavy Industry' } };
  const first = focusAlert({ idle: false }, data);
  assert.ok(first.message);
  assert.equal(focusAlert(first.next, data).message, null);
});
