// Monthly trade advice (2026-10-20, user's request): when a new game month starts, the trade advisor of the player's
// country runs with the advisor's settings (Country Editor > Resources) and, if a deal should be made or cancelled,
// the app tells the player - the deals themselves are made in the game (Options > Notifications: Trade).
import { refreshMs } from './options.js';

export const TRADE_POLL_MS = 15000;
export const TRADE_KEY = 'hoi4dbg.tradeAdvisor';
export const MODES = { surplus: 'Small surplus (+2)', exact: 'Exactly (0)', tolerate: 'Tolerate shortage (-2)' };
const MONTH_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];   // the game has no leap years
const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October',
  'November', 'December'];

/** Settings of the trade advisor (balance target, factory limit in % of civilian factories). */
export function tradeSettings() {
  try {
    const v = JSON.parse(localStorage.getItem(TRADE_KEY)) ?? {};
    return { mode: MODES[v.mode] ? v.mode : 'surplus', limit: Math.min(100, Math.max(10, Number(v.limit) || 25)) };
  } catch {
    return { mode: 'surplus', limit: 25 };
  }
}

/** "1936.02" for a game date {year, day: 0-based day of the year}; null without one. */
export function monthKey(date) {
  if (!date || date.year == null || date.day == null) return null;
  let day = date.day;
  let m = 0;
  while (m < 11 && day >= MONTH_DAYS[m]) { day -= MONTH_DAYS[m]; m += 1; }
  return `${date.year}.${String(m + 1).padStart(2, '0')}`;
}

const amount = (v) => (Number.isInteger(v) ? String(v) : v.toFixed(1));

/** One line of what to do, or null when every resource is at its target: "February 1936: buy 16 Rubber from
 *  British Malaya (2 factories); cancel 8 Chromium from Philippines". Shortages without a seller are named last. */
export function tradeMessage(advice, month) {
  if (!advice?.resources) return null;
  const who = (t) => advice.country_names?.[t] ?? t;
  const f = (n) => `${n} ${n === 1 ? 'factory' : 'factories'}`;
  const parts = [];
  for (const r of advice.resources) {
    for (const b of r.buy ?? []) parts.push(`buy ${amount(b.amount)} ${r.name ?? r.resource} from ${who(b.seller)} (${f(b.factories)})`);
    for (const c of r.cancel ?? []) parts.push(`cancel ${amount(c.amount)} ${r.name ?? r.resource} from ${who(c.seller)}`);
  }
  const short = advice.resources.filter((r) => r.missing > 0).map((r) => `${r.name ?? r.resource} ${amount(r.missing)}`);
  if (short.length) parts.push(`still short: ${short.join(', ')}`);
  if (!parts.length) return null;
  const [year, m] = (month ?? '').split('.');
  const when = year && m ? `${MONTHS[Number(m) - 1]} ${year}: ` : '';
  return `${when}${parts.join('; ')}`;
}

/** Polls the game date; at each new month (not the first reading - that is only the baseline, and not after a
 *  jump back such as a loaded save) asks for the player's trade advice and calls notify(message) when there is
 *  something to do. Returns a stop function. */
export function startTradeWatch(api, notify, enabled = () => true) {
  let last = null;
  const tick = async () => {
    try {
      const { data } = await api.get('/api/live/date');
      const month = monthKey(data?.date);
      if (!month) return;
      const moved = last !== null && month > last;
      last = month;
      if (!moved || !enabled()) return;
      const s = tradeSettings();
      const res = await api.get(`/api/countries/${encodeURIComponent(data.tag)}/trade-advice?mode=${s.mode}&limit=${s.limit}`);
      const message = tradeMessage(res.data, month);
      if (message) notify(`${data.tag} - ${message}`);
    } catch {
      // game not running, main menu, loading: keep the last month
    }
  };
  tick();
  const timer = setInterval(tick, refreshMs(TRADE_POLL_MS));
  return () => clearInterval(timer);
}
