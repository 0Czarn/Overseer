// Pure formatting helpers (no DOM) - unit tested with node --test.

import { numberLocale } from './options.js';

// number formats of the locale chosen in Options (en-US by default)
const formats = new Map();
const nf = (opts) => {
  const key = `${numberLocale() ?? ''}|${JSON.stringify(opts)}`;
  if (!formats.has(key)) formats.set(key, new Intl.NumberFormat(numberLocale(), opts));
  return formats.get(key);
};
const grouped = { format: (v) => nf({ maximumFractionDigits: 0 }).format(v) };
const oneDecimal = { format: (v) => nf({ minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(v) };

export function formatValue(value, unit = 'number') {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  if (typeof value !== 'number') return String(value);
  switch (unit) {
    case 'percent':
      return `${Math.round(value * 100)}%`;
    case 'integer':
      return grouped.format(Math.round(value));
    default:
      return oneDecimal.format(value);
  }
}

export const SOURCES = {
  live: { label: 'LIVE', cls: 'badge-live', title: 'Read from the running game or your system' },
  demo: { label: 'DEMO', cls: 'badge-demo', title: 'Sample data - not read from the game' },
  unavailable: { label: 'N/A', cls: 'badge-na', title: 'Not available right now' },
  save: { label: 'SAVE', cls: 'badge-save', title: 'Read from a copy of a save file - a snapshot, never live' },
};

export const FRESHNESS = {
  current_session: { cls: 'fresh-current', short: 'Current session (snapshot)' },
  previous_session: { cls: 'fresh-stale', short: 'Earlier session - not current' },
  game_not_running: { cls: 'fresh-offline', short: 'Game not running' },
  unknown_session: { cls: 'fresh-offline', short: 'Session unknown' },
};

export function freshnessInfo(category) {
  return FRESHNESS[category] ?? { cls: 'fresh-offline', short: String(category ?? 'unknown') };
}

export function formatAge(seconds) {
  return Number.isFinite(seconds) ? `${formatDuration(seconds)} ago` : '—';
}

export function formatBytes(bytes) {
  if (!Number.isFinite(bytes)) return '—';
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function sourceInfo(source) {
  return SOURCES[source] ?? { label: String(source ?? '?').toUpperCase(), cls: 'badge-na', title: '' };
}

export const SCOPES = {
  local: { label: 'LOCAL', cls: 'badge-local', title: 'Affects only this app / this client' },
  shared: { label: 'SHARED STATE', cls: 'badge-shared', title: 'Would change the common game state' },
};

export function scopeInfo(scope) {
  return SCOPES[scope] ?? { label: String(scope).toUpperCase(), cls: 'badge-na', title: '' };
}

export function formatDuration(totalSeconds) {
  if (!Number.isFinite(totalSeconds) || totalSeconds < 0) return '—';
  const s = Math.floor(totalSeconds);
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m ${s % 60}s`;
  return `${s}s`;
}

/** Humanises snake_case keys from the game/backend: "industrial_complex" -> "Industrial complex". */
export function humanize(key) {
  const text = String(key ?? '').replace(/_/g, ' ').trim();
  return text ? text[0].toUpperCase() + text.slice(1) : '';
}

export function filterByText(items, text, fields) {
  const needle = String(text ?? '').trim().toLowerCase();
  if (!needle) return items;
  return items.filter((item) => fields.some((f) => String(item[f] ?? '').toLowerCase().includes(needle)));
}

/** Stockpile vs requirement for the Equipment Manager: ratio clamped to [0, 1] plus surplus/deficit. */
export function stockBalance(stockpile, required) {
  const stock = Number(stockpile) || 0;
  const need = Number(required) || 0;
  return { ratio: need > 0 ? Math.min(1, stock / need) : 1, delta: stock - need };
}

export const FOCUS_COLUMNS = [
  { status: 'in_progress', label: 'In progress' },
  { status: 'available', label: 'Available' },
  { status: 'completed', label: 'Completed' },
  { status: 'blocked', label: 'Blocked' },
];

export function groupFocuses(focuses) {
  const groups = Object.fromEntries(FOCUS_COLUMNS.map((c) => [c.status, []]));
  for (const focus of focuses ?? []) (groups[focus.status] ??= []).push(focus);
  return groups;
}
