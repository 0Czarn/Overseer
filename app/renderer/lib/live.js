// Classification of the live memory read (pure, unit tested). The UI shows a number only for
// state 'live'; every other state shows a reason, never a guessed value.

export const STALE_AFTER_S = 10;

const ERROR_STATES = {
  game_not_running: ['no_game', 'Hearts of Iron IV is not running.'],
  no_access: ['no_access', 'The game process cannot be read (access denied - is HOI4 running as administrator?).'],
  process_changed: ['process_changed', 'The game was restarted - the previous calibration was discarded.'],
  not_calibrated: ['not_calibrated', 'Not calibrated for this game process yet.'],
  unverified: ['unverified', 'Memory location not verified yet.'],
  unreadable: ['read_error', 'The calibrated address is no longer readable (save loaded or game restarted?).'],
  inconsistent: ['read_error', 'Calibrated copies disagree - calibrate again.'],
  disabled: ['disabled', 'Live access is disabled (--no-game).'],
};

export const LIVE_LABELS = {
  live: 'LIVE',
  stale: 'STALE',
  unverified: 'UNVERIFIED',
  no_game: 'NO GAME',
  no_access: 'NO ACCESS',
  process_changed: 'RESTARTED',
  not_calibrated: 'NOT CALIBRATED',
  read_error: 'READ ERROR',
  disabled: 'DISABLED',
  error: 'ERROR',
};

/**
 * status: GET /api/live body (or null), value: entry of GET /api/live/values data (or null),
 * fetchedAt / now: seconds (time of the last SUCCESSFUL read). error: { code?, message } when the last
 * request failed; a failure without a code (backend unreachable) keeps the old value, which turns STALE.
 * Returns { state, label, message, value? }.
 */
export function classifyLive({ status, value, error, fetchedAt, now }) {
  const out = (state, message, extra = {}) => ({ state, label: LIVE_LABELS[state], message, ...extra });
  if (error?.code || (error && value?.status !== 'live')) {
    const [state, text] = ERROR_STATES[error.code] ?? ['error', null];
    return out(state, error.message || text);
  }
  if (status?.error) {
    const [state, text] = ERROR_STATES[status.error.code] ?? ['error', null];
    return out(state, status.error.message || text);
  }
  if (!value) return out('not_calibrated', ERROR_STATES.not_calibrated[1]);
  if (value.status !== 'live') {
    const [state, text] = ERROR_STATES[value.code] ?? ['error', null];
    return out(state, value.message || text);
  }
  if (!Number.isFinite(value.value)) return out('read_error', 'The backend returned no number.');
  if (Number.isFinite(now) && Number.isFinite(fetchedAt) && now - fetchedAt > STALE_AFTER_S) {
    return out('stale', `Last successful read ${Math.round(now - fetchedAt)} s ago.`, { value: value.value });
  }
  return out('live', `Read from game memory (${value.encoding}, ${value.copies} cop${value.copies === 1 ? 'y' : 'ies'}).`,
    { value: value.value });
}

// Stored as 0..1 in game memory; the game shows them as percent.
export const PERCENT_FIELDS = new Set(['stability', 'war_support']);

export function formatLiveValue(value, field) {
  if (!Number.isFinite(value)) return '—';
  if (PERCENT_FIELDS.has(field)) return `${(value * 100).toFixed(1).replace(/\.0$/, '')}%`;
  return value.toFixed(3);
}

/** Amount typed by the user (percent for stability/war support) -> value units used by the backend. */
export function toValueUnits(amount, field) {
  return PERCENT_FIELDS.has(field) ? amount / 100 : amount;
}
