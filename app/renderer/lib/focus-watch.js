// Watches the player's national focus in game memory and notifies when the next one has to be started.
// The game has no command that starts a focus, so the app only tells the player what to click next.
import { refreshMs } from './options.js';

export const FOCUS_POLL_MS = 4000;

/** Pure transition logic (unit-tested): returns { message, next } - message is null when nothing to say.
 *  The backend keeps the last completion event for a while (several pollers read it); `prev.eventId` makes
 *  sure each completion is announced once. */
export function focusAlert(prev, data) {
  if (!data || data.loading) return { message: null, next: prev }; // focus tree still being read
  const freshEvent = data.event?.completed && data.event.id !== prev?.eventId ? data.event : null;
  const next = { idle: data.idle, current: data.current, eventId: data.event?.id ?? prev?.eventId ?? null };
  const parts = [];
  if (freshEvent) parts.push(`Completed: ${freshEvent.name}.`);
  const becameIdle = data.idle && !(prev?.idle);
  if (becameIdle || (freshEvent && data.idle)) {
    parts.push(data.next ? `Start next: ${data.next.name} (${data.next.days} days).`
      : 'No focus selected - your plan is empty.');
  }
  return { message: parts.length ? parts.join(' ') : null, next };
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
      // transient (save being written, game loading): keep the previous state - regression: resetting it made
      // the next reading a new baseline and the completion that happened meanwhile was never announced
    }
  };
  tick();
  const timer = setInterval(tick, refreshMs(FOCUS_POLL_MS));
  return () => clearInterval(timer);
}
