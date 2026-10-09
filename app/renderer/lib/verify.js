// Independent verification of a value change by comparing two save snapshots (pure, unit tested).

export const PP_TOLERANCE = 0.001;

/** Console command used as a DIAGNOSTIC change method (documented by the game: "Gives political power to player"). */
export function ppCommand(delta) {
  const n = Number(delta);
  if (!Number.isFinite(n) || n === 0) return null;
  return `pp ${Number.isInteger(n) ? n : n.toFixed(3)}`;
}

/**
 * baseline / after: { value, file, mtime, date } where date is the in-game date text.
 * Returns { status: 'pass' | 'fail' | 'inconclusive' | 'waiting', message, expected?, actual? }.
 */
export function verifyChange(baseline, after, delta, tolerance = PP_TOLERANCE) {
  if (!baseline) return { status: 'waiting', message: 'Record a baseline first.' };
  if (!after || after.value === null || after.value === undefined) {
    return { status: 'waiting', message: 'No readable value in the newest save yet.' };
  }
  if (!(after.mtime > baseline.mtime)) {
    return { status: 'waiting', message: 'No newer save than the baseline. Run the command, then "savegame".' };
  }
  const expected = baseline.value + Number(delta);
  const diff = after.value - baseline.value;
  if (after.date !== baseline.date) {
    return { status: 'inconclusive', expected, actual: after.value,
      message: `In-game time moved (${baseline.date} → ${after.date}); daily gain mixes with the change. Pause the game and repeat.` };
  }
  if (Math.abs(after.value - expected) <= tolerance) {
    return { status: 'pass', expected, actual: after.value,
      message: `Verified: ${baseline.value} → ${after.value} (change ${diff.toFixed(3)}) in ${after.file}.` };
  }
  return { status: 'fail', expected, actual: after.value,
    message: `Expected ${expected.toFixed(3)}, save shows ${after.value} (change ${diff.toFixed(3)}).` };
}
