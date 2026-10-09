// Tiny DOM builder. Never uses innerHTML, so game/mod-provided text can't inject markup.
import { sourceInfo, scopeInfo } from './format.js';

export function h(tag, props, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props ?? {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') el.className = value;
    else if (key === 'dataset') Object.assign(el.dataset, value);
    else if (key === 'style') Object.assign(el.style, value); // CSSOM is allowed by the CSP
    else if (key.startsWith('on') && typeof value === 'function') el.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === 'value') el.value = value;
    else if (value === true) el.setAttribute(key, '');
    else el.setAttribute(key, String(value));
  }
  append(el, children);
  return el;
}

function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

export function clear(el) {
  while (el.firstChild) el.firstChild.remove();
  return el;
}

export function sourceBadge(source, note) {
  const info = sourceInfo(source);
  return h('span', { class: `badge ${info.cls}`, title: note || info.title }, info.label);
}

export function scopeBadge(scope) {
  const info = scopeInfo(scope);
  return h('span', { class: `badge ${info.cls}`, title: info.title }, info.label);
}

export function viewHeader(title, subtitle, ...extras) {
  return h('div', { class: 'view-header' },
    h('div', { class: 'view-title' }, h('h1', null, title), subtitle ? h('p', null, subtitle) : null),
    h('div', { class: 'view-extras' }, extras));
}

export function card(title, body, { extra, cls } = {}) {
  return h('section', { class: `card ${cls ?? ''}` },
    title ? h('div', { class: 'card-head' }, h('h2', null, title), extra ?? null) : null,
    h('div', { class: 'card-body' }, body));
}

/** Banner shown on every view that displays DEMO data. */
export function demoBanner(note) {
  return h('div', { class: 'demo-banner', role: 'note' },
    h('span', { class: 'badge badge-demo' }, 'DEMO'),
    h('span', null, note || 'Sample data - not read from the game.'));
}

export function notice(kind, text) {
  return h('div', { class: `notice notice-${kind}` }, text);
}

export function errorBox(message) {
  return h('div', { class: 'error-box', role: 'alert' }, message);
}

export function keyValues(pairs) {
  return h('dl', { class: 'kv' }, pairs.filter(Boolean).map(([k, v]) => [h('dt', null, k), h('dd', null, v ?? '—')]));
}

/**
 * columns: [{ key, label, render?(row), cls? }]
 * options: { onRowClick?(row), rowClass?(row), selectedKey?, keyField? }
 */
export function table(columns, rows, options = {}) {
  const { onRowClick, rowClass, selectedKey, keyField = 'id', empty = 'No data' } = options;
  const body = rows.length
    ? rows.map((row) => h('tr', {
      class: [onRowClick ? 'clickable' : '', rowClass?.(row) ?? '',
        selectedKey !== undefined && row[keyField] === selectedKey ? 'selected' : ''].join(' ').trim() || null,
      onClick: onRowClick ? () => onRowClick(row) : null,
      tabindex: onRowClick ? 0 : null,
      onKeydown: onRowClick ? (e) => { if (e.key === 'Enter') onRowClick(row); } : null,
    }, columns.map((c) => h('td', { class: c.cls ?? null, 'data-label': c.label },
      c.render ? c.render(row) : (row[c.key] ?? '—')))))
    : [h('tr', null, h('td', { colspan: columns.length, class: 'empty' }, empty))];
  return h('div', { class: 'table-wrap' },
    h('table', { class: 'table' },
      h('thead', null, h('tr', null, columns.map((c) => h('th', { class: c.cls ?? null }, c.label)))),
      h('tbody', null, body)));
}

export function select(options, value, onChange, attrs = {}) {
  return h('select', { ...attrs, onChange: (e) => onChange(e.target.value) },
    options.map((o) => h('option', { value: o.value, selected: o.value === value }, o.label)));
}

export function meter(ratio, cls = '') {
  const pct = Math.max(0, Math.min(1, ratio)) * 100;
  return h('div', { class: `meter ${cls}` }, h('div', { class: 'meter-fill', style: { width: `${pct}%` } }));
}

export function toast(message, kind = 'info') {
  const host = document.getElementById('toasts');
  if (!host) return;
  const el = h('div', { class: `toast toast-${kind}` }, message);
  host.append(el);
  setTimeout(() => el.remove(), 4000);
}
