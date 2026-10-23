import test from 'node:test';
import assert from 'node:assert/strict';
import { extraNote, isCasualtyMetric, isLevelMetric, metricFormat } from '../renderer/views/summary.js';
import { forecast } from '../renderer/views/summary-equipment.js';
import { rgb, rowAt, standings, statesAt } from '../renderer/views/summary-map.js';
import { minutesText, rankMove } from '../renderer/views/summary-extra.js';
import { esc, reportName } from '../renderer/views/summary-report.js';

test('values recorded from 2026-10-21 are levels with their own format', () => {
  for (const m of ['pp', 'stab', 'divs', 'vp', 'tech', 'mpall', 'kd']) assert.equal(isLevelMetric(m), true, m);
  assert.equal(metricFormat('stab')(55.25), '55.3%');
  assert.equal(metricFormat('divs')(41.6), '42');
  assert.equal(metricFormat('kd')(1.234), '1.23');
  assert.match(extraNote('kd'), /above 1/);
});

test('war casualties are flows (men a day) with a cumulative chart', () => {
  for (const m of ['mpl', 'mpk']) {
    assert.equal(isCasualtyMetric(m), true, m);
    assert.equal(isLevelMetric(m), false, m);
  }
  assert.equal(isCasualtyMetric('mpall'), false);
});

test('production forecast: days to fill the missing equipment at today\'s production', () => {
  const rows = forecast({ inf: [1000, 600, 100, 50], art: [100, 100, 20, 5], tank: [50, 0, 0, 0] },
    [{ key: 'inf', name: 'Infantry' }], 1941 * 365);
  assert.deepEqual(rows.map((r) => [r.key, r.missing, r.days]), [['tank', 50, null], ['inf', 300, 6], ['art', 0, 0]]);
  assert.equal(rows[1].ready, '1941.01.07');
  assert.equal(rows[1].name, 'Infantry');
});

test('campaign map: states of a day from the last full row and the changes after it', () => {
  const rows = [{ t: 1, full: 1, s: { 1: ['GER', 'GER'], 2: ['POL', 'POL'] } }, { t: 5, s: { 2: ['POL', 'GER'] } },
    { t: 9, full: 1, s: { 1: ['GER', 'GER'], 2: ['GER', 'GER'] } }];
  assert.deepEqual(statesAt(rows, 1), { 1: ['GER', 'GER'], 2: ['POL', 'GER'] });
  assert.deepEqual(statesAt(rows, 2)[2], ['GER', 'GER']);
  assert.equal(rowAt(rows, 6), 1);
  assert.equal(rowAt(rows, 0), -1);
  const top = standings(statesAt(rows, 1), { 2: 10 });
  assert.deepEqual(top.map((s) => [s.tag, s.owned, s.controlled, s.vp]), [['GER', 1, 2, 10], ['POL', 1, 0, 0]]);
  assert.deepEqual(rgb('#ff8000'), [255, 128, 0]);
});

test('ranking moves, session times and report text', () => {
  assert.deepEqual(rankMove(1, 3), { text: '▲2', cls: 'gs-up' });
  assert.deepEqual(rankMove(2, 1), { text: '▼1', cls: 'gs-down' });
  assert.equal(rankMove(1, null).text, '');
  assert.equal(minutesText(125), '2 h 05 min');
  assert.equal(minutesText(45), '45 min');
  assert.equal(esc('<b>"Axis" & co</b>'), '&lt;b&gt;&quot;Axis&quot; &amp; co&lt;/b&gt;');
  assert.equal(reportName('GER_1936-01-01_x'), 'overseer-GER_1936-01-01_x.html');
});

test('map colours: shade darker and towards white', async () => {
  const { shade } = await import('../renderer/lib/mapview.js');
  assert.deepEqual(shade([100, 50, 0], 0.5), [50, 25, 0]);
  assert.deepEqual(shade([100, 50, 0], 1.5), [178, 153, 128]);
});

test('construction forecast rows and the finish text of a line', async () => {
  const { finishText, forecastRows } = await import('../renderer/views/construction.js');
  const rows = forecastRows({ now: { civ: 30, mil: 20, dock: 5 }, 90: { civ: 32, mil: 20, dock: 5 }, 180: { civ: 35, mil: 22, dock: 5 },
    365: { civ: 40, mil: 25, dock: 6 }, dates: { 90: '1 Apr, 1936', 180: '30 Jun, 1936', 365: '1 Jan, 1937' } });
  assert.deepEqual(rows.map((r) => [r.label, r.civ, r.delta.civ, r.date]), [['Now', 30, 0, null], ['3 months', 32, 2, '1 Apr, 1936'],
    ['6 months', 35, 5, '30 Jun, 1936'], ['12 months', 40, 10, '1 Jan, 1937']]);
  assert.equal(finishText({ finish_days: 72, finish: { text: '14 Mar, 1937' } }), 'Forecast - all done: 14 Mar, 1937 (in 72 days)');
  assert.match(finishText({ finish_days: null }), /not done within 2 years/);
  assert.deepEqual(forecastRows(null), []);
});

test('campaign map keys: factions with the user\'s moves, players with their subjects', async () => {
  const { keyFn, keyStandings, valueAt } = await import('../renderer/views/summary-map.js');
  assert.equal(valueAt([[10, 'a'], [20, 'b']], 15), 'a');
  assert.equal(valueAt([[10, 'a'], [20, 'b']], 5), 'a');   // before the first: the first
  assert.equal(valueAt([], 5), null);
  const factions = { GER: 'Axis', ITA: 'Axis', ENG: 'Allies' };
  const f = keyFn('factions', { factions, groups: { assign: { ITA: '', SWE: 'Nordic' } } });
  assert.deepEqual(['GER', 'ITA', 'SWE', 'POL'].map(f), ['Axis', null, 'Nordic', null]);
  const players = { GER: { n: 'Rodan', s: ['SLO'] }, SOV: { n: null, s: [] } };
  assert.deepEqual(['GER', 'SLO', 'SOV', 'POL'].map(keyFn('players', { players, subjects: true })), ['Rodan', 'Rodan', 'SOV', null]);
  assert.equal(keyFn('players', { players })('SLO'), null);
  assert.equal(keyFn('countries')('POL'), 'POL');
  const rows = [{ tag: 'GER', owned: 5, controlled: 6, vp: 50 }, { tag: 'ITA', owned: 3, controlled: 3, vp: 20 },
    { tag: 'POL', owned: 2, controlled: 1, vp: 5 }];
  assert.deepEqual(keyStandings(rows, keyFn('factions', { factions })),
    [{ key: 'Axis', owned: 8, controlled: 9, vp: 70, lead: 'GER' }]);
});

test('map names: each key named on its largest piece of neighbouring states, sized to it', async () => {
  const { measure, placeLabels, provinceCentre, cityThreshold, LAND, SEA } = await import('../renderer/lib/mapview.js');
  // 40 x 10 map: provinces 1 | 2 | sea | 3 (states 1, 2, -, 3); the sea splits the land, 3 is a small island
  const width = 40; const height = 10;
  const pids = new Uint16Array(width * height);
  const kind = new Uint8Array(width * height);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      const i = y * width + x;
      const p = x < 10 ? 1 : x < 20 ? 2 : x < 37 ? 0 : 3;
      pids[i] = p; kind[i] = p ? LAND : SEA;
    }
  }
  const provState = Uint16Array.from([0, 1, 2, 3]);
  const map = { pids, kind, provState, ...measure(width, height, pids, kind, provState) };
  assert.deepEqual(map.neighbours, [[1, 2]]);
  assert.deepEqual(provinceCentre(map, 1), [4.5, 4.5]);
  const owner = { 1: 'GER', 2: 'GER', 3: 'GER' };
  const labels = placeLabels(map, (sid) => owner[sid], (k) => ({ GER: 'Germany' }[k]), undefined, 10);
  assert.equal(labels.length, 1);   // the island is under a quarter of the mainland
  assert.equal(labels[0].text, 'Germany');
  assert.equal(labels[0].x, 9.5);
  assert.equal(labels[0].size, 6);   // a long name on small land: the smallest size
  owner[2] = 'POL';
  assert.deepEqual(placeLabels(map, (sid) => owner[sid], (k) => k, undefined, 10).map((l) => l.text).sort(), ['GER', 'GER', 'POL']);   // now the island is a third of GER's land
  owner[1] = 'POL';   // POL: states 1 and 2 (200 px); GER: the island alone
  const vp = { 1: 0, 2: 0, 3: 0 };
  assert.deepEqual(placeLabels(map, (sid) => owner[sid], (k) => k, (sid) => vp[sid], 10).map((l) => l.text), ['POL', 'GER']);
  owner[3] = 'POL'; vp[3] = 50;   // the island has the capital: POL's name goes there, not on the larger mainland
  const pol = placeLabels(map, (sid) => owner[sid], (k) => k, (sid) => vp[sid], 10);
  assert.equal(pol[0].x, 38);
  assert.equal(cityThreshold(0.1), Infinity);
  assert.equal(cityThreshold(2), 0);
});

test('campaign map front: the provinces off their state\'s controller from the last row listing them', async () => {
  const { frontAt } = await import('../renderer/views/summary-map.js');
  const rows = [{ t: 1, full: 1, s: {} }, { t: 2, s: {}, x: { 12714: 'ITA' } }, { t: 3, s: { 1: ['ETH', 'ITA'] } },
    { t: 4, s: {}, x: {} }, { t: 5, full: 1, s: {} }];
  assert.deepEqual(frontAt(rows, 0), {});   // recorded before provinces were
  assert.deepEqual(frontAt(rows, 2), { 12714: 'ITA' });
  assert.deepEqual(frontAt(rows, 3), {});
  assert.deepEqual(frontAt(rows, 4), {});   // a full row without them: none known
});

test('campaign map units: replayed from the last full row; the allies a country sees with', async () => {
  const { unitsAt, alliesOf } = await import('../renderer/views/summary-map.js');
  const rows = [{ t: 10, full: 1, u: { 1: { GER: [2, 50, 200, { Inf: 2 }] }, 2: { POL: [1, 40, 100, { Inf: 1 }] } } },
    { t: 11, u: { 2: null, 3: { GER: [1, 50, 200, { Inf: 1 }] } } },
    { t: 40, full: 1, u: { 5: { SOV: [9, 30, 90, { Rifle: 9 }] } } }];
  assert.deepEqual(unitsAt(rows, 5), {});
  assert.deepEqual(Object.keys(unitsAt(rows, 10)), ['1', '2']);
  assert.deepEqual(Object.keys(unitsAt(rows, 20)), ['1', '3']);   // POL left province 2
  assert.deepEqual(Object.keys(unitsAt(rows, 40)), ['5']);
  assert.deepEqual([...alliesOf('GER', { GER: 'Axis', ITA: 'Axis', ENG: 'Allies' }, { GER: { n: 'Rodan', s: ['SLO'] } })].sort(),
    ['GER', 'ITA', 'SLO']);
});

test('fog of war: the provinces held and their land neighbours; markers per state when zoomed out', async () => {
  const { seenProvinces, unitMarkers } = await import('../renderer/lib/mapview.js');
  const map = { adjacent: [[], [2], [1, 3], [2, 4], [3]], provState: Uint16Array.from([0, 1, 1, 2, 2]),
    prov: { count: [0, 10, 10, 10, 10], sx: [0, 10, 30, 50, 70], sy: [0, 10, 10, 10, 10] } };
  assert.deepEqual([...seenProvinces(map, [1])].sort(), [1, 2]);
  const units = [{ pid: 1, key: 'GER', color: [1, 2, 3], count: 2 }, { pid: 2, key: 'GER', color: [1, 2, 3], count: 1 }];
  assert.deepEqual(unitMarkers(map, units, 0.2).map((m) => [m.count, m.x]), [[3, 2]]);   // state 1: both provinces
  assert.equal(unitMarkers(map, units, 1).length, 2);
});

test('map outlines: decoded from the backend binary, each border smoothed the same both ways', async () => {
  const { decodeBorders, traceArc, borderKind, LAND, SEA } = await import('../renderer/lib/mapview.js');
  // campaign_map.encode_borders: 2 arcs - 1|2 straight down x = 2, and a 3-point arc 1|0; province 1: one ring [0, ~1]
  const points = [[4, 0], [4, 4], [4, 4], [0, 2], [4, 0]];
  const words = [1, 1, 2, 0, ~1];
  const buf = new ArrayBuffer(24 + 4 * 3 + 4 * 2 + 4 * points.length + 4 * words.length);
  const dv = new DataView(buf);
  [..."OVB1"].forEach((c, i) => dv.setUint8(i, c.charCodeAt(0)));
  [4, 2, 2, points.length, words.length].forEach((v, i) => dv.setUint32(4 + 4 * i, v, true));
  [0, 2, 5].forEach((v, i) => dv.setUint32(24 + 4 * i, v, true));
  [1, 2, 0, 1].forEach((v, i) => dv.setUint16(36 + 2 * i, v, true));
  points.flat().forEach((v, i) => dv.setUint16(44 + 2 * i, v, true));
  words.forEach((v, i) => dv.setInt32(64 + 4 * i, v, true));
  const o = decodeBorders(Buffer.from(buf).toString('base64'));
  assert.equal(o.arcs, 2);
  assert.deepEqual([...o.pts.slice(0, 4)], [2, 0, 2, 2]);   // half pixels -> pixels
  assert.deepEqual(o.rings.get(1), [[0, ~1]]);
  assert.deepEqual(o.provBox.get(1), [0, 0, 2, 2]);
  const record = () => { const calls = []; return { calls, moveTo: (...a) => calls.push(['M', ...a]),
    lineTo: (...a) => calls.push(['L', ...a]), quadraticCurveTo: (...a) => calls.push(['Q', ...a]) }; };
  const fwd = record(); traceArc(fwd, o, 1, true);
  assert.deepEqual(fwd.calls, [['M', 2, 2], ['L', 1, 1.5], ['Q', 0, 1, 1, 0.5], ['L', 2, 0]]);
  const back = record(); traceArc(back, o, ~1, true);   // the same curve, from the other end
  assert.deepEqual(back.calls, [['M', 2, 0], ['L', 1, 0.5], ['Q', 0, 1, 1, 1.5], ['L', 2, 2]]);
  const map = { provKind: Uint8Array.from([SEA, LAND, LAND]), provState: Uint16Array.from([0, 7, 8]) };
  const paint = { group: Int32Array.from([0, 1, 1]), style: { states: true } };
  assert.equal(borderKind(map, o, 0, paint), 'state');
  assert.equal(borderKind(map, o, 1, paint), 'coast');
  assert.equal(borderKind(map, o, 0, { group: Int32Array.from([0, 1, 2]), style: {} }), 'country');
  assert.equal(borderKind(map, o, 0, { ...paint, style: { highlight: 8 } }), 'highlight');
  assert.equal(borderKind(map, o, 0, { ...paint, style: {} }), null);
});

test('map rivers: smoothed lines, the narrow ones only when zoomed in', async () => {
  const { smoothLine, riverThreshold, railThreshold } = await import('../renderer/lib/mapview.js');
  assert.deepEqual([railThreshold(0.2), railThreshold(0.4), railThreshold(1)], [3, 2, 1]);   // main lines from afar
  const calls = [];
  const path = { moveTo: (...a) => calls.push(['M', ...a]), lineTo: (...a) => calls.push(['L', ...a]),
    quadraticCurveTo: (...a) => calls.push(['Q', ...a]) };
  smoothLine(path, [6, 0, 0, 2, 2, 4, 4], 1);   // width class 6 first, then the points
  assert.deepEqual(calls, [['M', 0, 0], ['L', 1, 1], ['Q', 2, 2, 3, 3], ['L', 4, 4]]);
  assert.deepEqual([riverThreshold(0.2), riverThreshold(0.5), riverThreshold(1)], [9, 6, 3]);
});

test('map front: readings within a day, battles', async () => {
  const { rowTime, frameText, battleText, unitsAt } = await import('../renderer/views/summary-map.js');
  assert.equal(rowTime({ t: 10 }), 10);
  assert.equal(rowTime({ t: 10, h: 6 }), 10.25);
  assert.deepEqual([frameText(0), frameText(0.5)], ['0.01.01', '0.01.01 12:00']);
  const rows = [{ t: 10, full: 1, u: { c5: ['SOV', 'GER', 2, 1, 70] } }, { t: 10, h: 12, u: { c5: null, 'm1-2': { SOV: 1 } } }];
  assert.deepEqual(unitsAt(rows, 10.25), { c5: ['SOV', 'GER', 2, 1, 70] });   // before the noon reading
  assert.deepEqual(unitsAt(rows, 10.5), { 'm1-2': { SOV: 1 } });
  assert.equal(battleText(['SOV', 'GER', 2, 1, 70]), 'Battle: SOV attacks GER - 2 vs 1 division, attacker 70%');
});

test('division card: the division at a time, its level, needs and equipment', async () => {
  const { stateAt, templateAt, needOf, expLevel, equipmentRows } = await import('../renderer/views/division-card.js');
  const history = [[10, 'n', ['GER', '25. Inf', 'Inf']], [10, 's', [50, 200, 2880, 9600, 8, 100]], [10.25, 'p', [1, 2]], [12, 'n', null]];
  assert.deepEqual(stateAt(history, 10.1), { n: ['GER', '25. Inf', 'Inf'], p: null, s: [50, 200, 2880, 9600, 8, 100], e: null });
  assert.equal(stateAt(history, 12).n, null);   // gone
  const templates = { 'GER|Inf': [[10, { b: ['infantry', 'infantry'], s: ['engineer'] }], [11, { b: ['infantry'] }]] };
  assert.deepEqual(templateAt(templates, 'GER|Inf', 10.5).b, ['infantry', 'infantry']);
  assert.deepEqual(templateAt(templates, 'GER|Inf', 11).b, ['infantry']);
  const units = { infantry: { manpower: 1000, need: { infantry_equipment: 100 } }, engineer: { manpower: 300, need: { support_equipment: 10 } } };
  assert.deepEqual(needOf(templates['GER|Inf'][0][1], units), { manpower: 2300, equipment: { infantry_equipment: 200, support_equipment: 10 } });
  assert.deepEqual([expLevel(2880, 9600).name, expLevel(0, 9600).name, expLevel(9000, 9600).name], ['Regular', 'Green', 'Elite']);
  assert.deepEqual(equipmentRows({ infantry_equipment_1: 150, infantry_equipment_2: 20 }, {}, { infantry_equipment: 200, support_equipment: 10 }),
    [{ archetype: 'infantry_equipment', held: 170, need: 200 }, { archetype: 'support_equipment', held: 0, need: 10 }]);
});

test('time machine: divisions filtered and sorted, a whole day reads its last reading', async () => {
  const { filterDivisions, readTime } = await import('../renderer/views/time-machine.js');
  const list = [{ id: 1, tag: 'GER', name: '2. Inf', template: 'Inf', where: 'Berlin', s: [50, 200] },
    { id: 2, tag: 'GER', name: '10. Inf', template: 'Inf', where: 'Hamburg', s: [30, 210] },
    { id: 3, tag: 'POL', name: '1 DP', template: 'DP', where: 'Warszawa', s: null }];
  assert.deepEqual(filterDivisions(list, { tag: 'GER' }).map((d) => d.id), [1, 2]);   // numeric order of names
  assert.deepEqual(filterDivisions(list, {}, { key: 'org', desc: true }).map((d) => d.id), [1, 2, 3]);
  assert.deepEqual(filterDivisions(list, { text: 'hamb' }).map((d) => d.id), [2]);
  assert.equal(readTime(10), 10 + 23.5 / 24);
  assert.equal(readTime(10.25), 10.25);
  const { divisionsByProvince } = await import('../renderer/views/summary-map.js');
  assert.deepEqual(Object.fromEntries(Object.entries(divisionsByProvince([{ pid: 5, tag: 'B', name: 'x' }, { pid: 5, tag: 'A', name: 'y' }]))
    .map(([k, v]) => [k, v.map((d) => d.tag)])), { 5: ['A', 'B'] });
});

test('border strength scales the opacity of the state and province lines', async () => {
  const { strengthen, BORDER_STRENGTH } = await import('../renderer/lib/mapview.js');
  assert.equal(strengthen('rgba(0, 0, 0, .3)', 2), 'rgba(0, 0, 0, 0.600)');
  assert.equal(strengthen('rgba(0, 0, 0, .6)', 4), 'rgba(0, 0, 0, 1.000)');   // up to opaque
  assert.equal(strengthen('rgb(12, 12, 12)', 3), 'rgb(12, 12, 12)');
  assert.ok(BORDER_STRENGTH[0] < 1 && BORDER_STRENGTH[1] > 1);
});
