import test from 'node:test';
import assert from 'node:assert/strict';
import { classifyLive, formatLiveValue, toValueUnits } from '../renderer/lib/live.js';

const okStatus = { process: { pid: 1 }, error: null };
const live = { status: 'live', value: 712.324, encoding: 'fixed32_1000', copies: 1, read_at: 100 };

test('a confirmed read is LIVE and carries the value', () => {
  const r = classifyLive({ status: okStatus, value: live, fetchedAt: 100, now: 101 });
  assert.equal(r.state, 'live');
  assert.equal(r.value, 712.324);
  assert.equal(formatLiveValue(r.value), '712.324');
});

test('unverified, uncalibrated and restarted states never carry a number', () => {
  for (const [code, state] of [['unverified', 'unverified'], ['not_calibrated', 'not_calibrated'],
    ['process_changed', 'process_changed'], ['inconsistent', 'read_error'], ['unreadable', 'read_error']]) {
    const r = classifyLive({ status: okStatus, value: { status: 'unavailable', code, message: 'x' }, fetchedAt: 1, now: 1 });
    assert.equal(r.state, state, code);
    assert.equal(r.value, undefined, code);
  }
  assert.equal(classifyLive({ status: okStatus, value: null }).state, 'not_calibrated');
});

test('missing game and access errors come from status or from the request', () => {
  assert.equal(classifyLive({ status: { error: { code: 'game_not_running', message: 'HOI4 is not running' } } }).state, 'no_game');
  assert.equal(classifyLive({ error: { code: 'no_access', message: '' } }).state, 'no_access');
  assert.match(classifyLive({ error: { code: 'no_access', message: '' } }).message, /access denied/);
  assert.equal(classifyLive({ error: { code: 'weird', message: 'boom' } }).state, 'error');
});

test('an old read turns STALE instead of looking live', () => {
  const fresh = classifyLive({ status: okStatus, value: live, error: { message: 'backend down' }, fetchedAt: 100, now: 105 });
  assert.equal(fresh.state, 'live');
  const stale = classifyLive({ status: okStatus, value: live, error: { message: 'backend down' }, fetchedAt: 100, now: 130 });
  assert.equal(stale.state, 'stale');
  assert.equal(stale.value, 712.324);
  assert.equal(classifyLive({ value: null, error: { message: 'backend down' } }).state, 'error');
});

test('stability and war support are shown and typed in percent', () => {
  assert.equal(formatLiveValue(0.71, 'stability'), '71%');
  assert.equal(formatLiveValue(0.355, 'war_support'), '35.5%');
  assert.equal(formatLiveValue(12.5, 'political_power'), '12.500');
  assert.equal(toValueUnits(80, 'stability'), 0.8);
  assert.equal(toValueUnits(5, 'command_power'), 5);
});
