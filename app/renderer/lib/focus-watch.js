// Watches the player's national focus in game memory and notifies when the next one has to be started.
// The game has no command that starts a focus, so the app only tells the player what to click next.

export const FOCUS_POLL_MS = 4000;

/** Pure transition logic (unit-tested): returns { message, next } - message is null when nothing to say. */
export function focusAlert(prev, data) {
  if (!data || data.loading) return { message: null, next: prev }; // focus tree still being read
  const next = { idle: data.idle, current: data.current };
  const parts = [];
  if (data.event?.completed) parts.push(`Completed: ${data.event.name}.`);
  const becameIdle = data.idle && !(prev?.idle);
  if (becameIdle || (data.event?.completed && data.idle)) {
    parts.push(data.next ? `Start next: ${data.next.name} (${data.next.days} days).`
      : 'No focus selected - your plan is empty.');
  }
  if (!parts.length || (!becameIdle && !data.event)) return { message: null, next };
  return { message: parts.join(' '), next };
}

/** Polls /api/live/focus while the app runs; silently stops talking when live reading is unavailable. */
export function startFocusWatch(api, notify) {
  let prev = null;
  const tick = async () => {
    try {
      const { data } = await api.get('/api/live/focus');
      const { message, next } = focusAlert(prev, data);
      // the first reading only sets the baseline (no alert for a state that existed before the app started)
      if (prev !== null && message) notify(message);
      prev = next;
    } catch {
      prev = null; // game not running / unsupported version / no save yet
    }
  };
  tick();
  const timer = setInterval(tick, FOCUS_POLL_MS);
  return () => clearInterval(timer);
}
