import test from 'node:test';
import assert from 'node:assert/strict';
import { CELL, FRAME, traitState, treeLines } from '../renderer/views/mio-tree.js';

const trait = (token, x, y, more = {}) => ({ token, x, y, parents: [], parents_needed: 1, exclusive: [], unlocked: false, ...more });
// Henschel's top-left corner: two exclusive engines, two children of either one (any_parent), one of both wheels
const tree = [
  trait('single', 0, 0, { exclusive: ['dual'] }),
  trait('dual', 2, 0, { exclusive: ['single'], unlocked: true }),
  trait('interleaved', 0, 2, { parents: ['single', 'dual'], exclusive: ['overlapped'] }),
  trait('overlapped', 2, 2, { parents: ['single', 'dual'], exclusive: ['interleaved'], unlocked: true }),
  trait('steel', 1, 3, { parents: ['interleaved', 'overlapped'], parents_needed: 2 }),
  trait('far', 5, 4, { parents: ['dual'], exclusive: ['steel'] }),
];
const by = new Map(tree.map((t) => [t.token, t]));

test('trait state: unlocked, available, needs parents, excluded by an unlocked exclusive trait', () => {
  assert.equal(traitState(by.get('dual'), by), 'unlocked');
  assert.equal(traitState(by.get('single'), by), 'excluded');
  assert.equal(traitState(by.get('interleaved'), by), 'excluded');
  assert.equal(traitState(by.get('steel'), by), 'locked');            // both parents needed, one unlocked
  assert.equal(traitState(by.get('far'), by), 'available');
  assert.equal(traitState(trait('root', 4, 0), by), 'available');
});

test('parent lines: straight below, elbow under the parent, green from an unlocked parent, dotted for any one of several', () => {
  const { links } = treeLines(tree);
  const cx = (x) => x * CELL.w + CELL.w / 2;
  const straight = links.find((l) => l.points.length === 2 && l.points[0][0] === cx(0));
  assert.deepEqual(straight.points, [[cx(0), FRAME.h], [cx(0), 2 * CELL.h]]);
  assert.equal(straight.on, false);
  assert.equal(straight.dotted, true);
  const fromDual = links.filter((l) => l.points[0][0] === cx(2) && l.points[0][1] === FRAME.h);
  assert.ok(fromDual.every((l) => l.on));
  const toSteel = links.filter((l) => l.points.at(-1)[0] === cx(1));
  assert.equal(toSteel.length, 2);
  assert.ok(toSteel.every((l) => !l.dotted && l.points.length === 4 && l.points[1][1] === 2 * CELL.h + FRAME.h + 10));
});

test('exclusive pairs once each: on one row between the frames, else across', () => {
  const { exclusive } = treeLines(tree);
  assert.equal(exclusive.length, 3);
  const top = exclusive.find((e) => e.row && e.x1 === FRAME.left + FRAME.w);
  assert.equal(top.x2, 2 * CELL.w + FRAME.left);
  assert.equal(exclusive.filter((e) => !e.row).length, 1);
});
