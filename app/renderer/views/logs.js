import { h, card, clear, errorBox, keyValues, notice, select, sourceBadge, toast, viewHeader } from '../lib/dom.js';
import { refreshMs } from '../lib/options.js';

const SEVERITIES = ['info', 'minor', 'major', 'critical'];
const AREAS = ['Dashboard', 'Countries & Players', 'Country Editor', 'State Editor', 'National Focus Manager',
  'Equipment Manager', 'Game Tools', 'Logs & Test Reports', 'Game / multiplayer'];

function appLogPanel(ctx) {
  let level = 'debug';
  let lastSeq = 0;
  const list = h('ol', { class: 'log-list' });
  const reload = async () => {
    lastSeq = 0;
    clear(list);
    await poll();
  };
  const poll = async () => {
    const res = await ctx.api.get(`/api/logs/app?limit=500&level=${level}&after=${lastSeq}`);
    const atBottom = list.scrollTop + list.clientHeight >= list.scrollHeight - 8;
    for (const e of res.data) {
      list.append(h('li', { class: `lvl-${e.level}` }, h('time', null, e.time.replace('T', ' ')),
        h('span', { class: 'lvl' }, e.level.toUpperCase()), h('span', { class: 'origin' }, e.origin), h('span', null, e.message)));
      lastSeq = e.seq;
    }
    while (list.childElementCount > 1000) list.firstChild.remove();
    if (atBottom) list.scrollTop = list.scrollHeight;
  };
  const timer = setInterval(() => poll().catch(() => {}), refreshMs(2000));
  const el = card('Application log', [
    h('div', { class: 'toolbar' }, select(['debug', 'info', 'warning', 'error'].map((v) => ({ value: v, label: `≥ ${v}` })),
      level, (v) => { level = v; reload(); }, { class: 'input', 'aria-label': 'Minimum level' })),
    list,
  ], { extra: sourceBadge('live') });
  return { el, start: poll, stop: () => clearInterval(timer) };
}

async function gameLogPanel(ctx) {
  const names = await ctx.api.get('/api/logs/game');
  if (!names.data?.length) {
    return card('HOI4 logs', notice('muted', 'Game log folder not detected.'), { extra: sourceBadge(names.source) });
  }
  let current = names.data.includes('error.log') ? 'error.log' : names.data[0];
  const pre = h('pre', { class: 'log-pre' });
  const meta = h('div', { class: 'muted' });
  const load = async () => {
    const res = await ctx.api.get(`/api/logs/game/${encodeURIComponent(current)}?lines=300`);
    if (!res.data) {
      pre.textContent = res.note ?? 'Not available';
      return;
    }
    pre.textContent = res.data.lines.join('\n') || '(empty file)';
    meta.textContent = `${res.data.path} - ${res.data.size} bytes - modified ${new Date(res.data.modified).toLocaleString()}`;
    pre.scrollTop = pre.scrollHeight;
  };
  await load();
  return card('HOI4 logs (read-only)', [
    h('div', { class: 'toolbar' },
      select(names.data.map((n) => ({ value: n, label: n })), current, (v) => { current = v; load(); },
        { class: 'input', 'aria-label': 'Log file' }),
      h('button', { class: 'btn btn-small', onClick: load }, 'Reload')),
    meta, pre,
  ], { extra: sourceBadge('live') });
}

function reportsPanel(ctx) {
  const listHost = h('div', { class: 'report-list' });
  const viewer = h('div', { class: 'report-view' });

  const showReport = async (id) => {
    const { data } = await ctx.api.get(`/api/reports/${encodeURIComponent(id)}`);
    viewer.replaceChildren(h('h3', null, data.title), keyValues([
      ['Severity', h('span', { class: `sev sev-${data.severity}` }, data.severity)],
      ['Area', data.area], ['Created', data.created],
      ['Game detected', String(data.environment?.game?.detected ?? false)],
      ['Game version', data.environment?.game?.install?.version?.display],
      ['Steps', h('pre', { class: 'pre-wrap' }, data.steps || '—')],
      ['Expected', h('pre', { class: 'pre-wrap' }, data.expected || '—')],
      ['Actual', h('pre', { class: 'pre-wrap' }, data.actual || '—')],
      ['Notes', h('pre', { class: 'pre-wrap' }, data.notes || '—')],
    ]));
  };
  const loadList = async () => {
    const { data } = await ctx.api.get('/api/reports');
    listHost.replaceChildren(...(data.length ? data.map((r) => h('button', { class: 'report-item', onClick: () => showReport(r.id) },
      h('span', { class: `sev sev-${r.severity}` }, r.severity), h('span', null, r.title),
      h('time', { class: 'muted' }, r.created?.replace('T', ' ')))) : [h('p', { class: 'muted' }, 'No reports yet.')]));
  };

  const form = h('form', { class: 'form', onSubmit: async (e) => {
    e.preventDefault();
    const payload = Object.fromEntries(new FormData(form).entries());
    try {
      const { data } = await ctx.api.post('/api/reports', payload);
      toast(`Report saved: ${data.id}`, 'ok');
      form.reset();
      await loadList();
      await showReport(data.id);
    } catch (err) {
      toast(err.message, 'error');
    }
  } },
  h('label', null, 'Title', h('input', { class: 'input', name: 'title', required: true, maxlength: 200 })),
  h('div', { class: 'form-row' },
    h('label', null, 'Severity', select(SEVERITIES.map((s) => ({ value: s, label: s })), 'minor', () => {}, { class: 'input', name: 'severity' })),
    h('label', null, 'Area', select(AREAS.map((a) => ({ value: a, label: a })), AREAS[0], () => {}, { class: 'input', name: 'area' }))),
  h('label', null, 'Steps to reproduce', h('textarea', { class: 'input', name: 'steps', rows: 3 })),
  h('div', { class: 'form-row' },
    h('label', null, 'Expected', h('textarea', { class: 'input', name: 'expected', rows: 2 })),
    h('label', null, 'Actual', h('textarea', { class: 'input', name: 'actual', rows: 2 }))),
  h('label', null, 'Notes', h('textarea', { class: 'input', name: 'notes', rows: 2 })),
  h('p', { class: 'hint' }, 'App version and game detection/version are attached automatically.'),
  h('button', { class: 'btn btn-primary', type: 'submit' }, 'Save report'));

  return { el: h('div', { class: 'split' }, card('New test report', form),
    card('Saved reports', [listHost, viewer])), load: loadList };
}

export default {
  id: 'logs',
  title: 'Logs & Test Reports',
  short: 'LR',
  async render(root, ctx) {
    const appLog = appLogPanel(ctx);
    const reports = reportsPanel(ctx);
    let gameLog;
    try {
      gameLog = await gameLogPanel(ctx);
    } catch (err) {
      gameLog = errorBox(`HOI4 logs: ${err.message}`);
    }
    await Promise.all([appLog.start(), reports.load()]);
    root.addEventListener('mounted', () => {
      for (const el of root.querySelectorAll('.log-pre, .log-list')) el.scrollTop = el.scrollHeight;
    });
    root.append(
      viewHeader('Logs & Test Reports', 'Application log, the game\'s own logs and tester reports.'),
      h('div', { class: 'split' }, appLog.el, gameLog),
      reports.el,
    );
    return () => appLog.stop();
  },
};
