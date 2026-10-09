// Focus statuses from the completed set and the current focus (same rules as backend focus.statuses):
// completed, in_progress, excluded (mutually exclusive with a taken focus), available (prerequisites met:
// every prerequisite group has one completed focus), blocked. Used to refresh the tree from live memory.

export function focusStatuses(focuses, completed, current) {
  const taken = new Set(completed);
  if (current) taken.add(current);
  const excluded = new Set();
  for (const f of focuses) if (taken.has(f.id)) for (const e of f.exclusive ?? []) excluded.add(e);
  const out = new Map();
  for (const f of focuses) {
    let status;
    if (completed.has(f.id)) status = 'completed';
    else if (f.id === current) status = 'in_progress';
    else if (excluded.has(f.id)) status = 'excluded';
    else if ((f.prerequisites ?? []).every((group) => group.some((p) => completed.has(p)))) status = 'available';
    else status = 'blocked';
    out.set(f.id, status);
  }
  return out;
}
