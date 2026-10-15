"""Players actions (2026-10-15, user's request): what the watched countries did in the game, day by day.

The IC recorder (ic_history.py) takes a snapshot of every watched country once a game day (live/service.action_snapshot:
focus, research, laws and spirits, advisors, leader, wars, war goal justifications, division templates, equipment
designs, construction queue, trade deals - all from game memory) and keeps what changed against the day before as
events. The game keeps no such log: the first snapshot after the app starts (or a save is loaded) is only the baseline,
and what happened while the app was closed is not known.

Event: {"t": day number, "tag", "kind", "action", "id", "detail"} - kind / action below, id = what changed (a focus,
technology, idea or character id, a tag, a template name, an equipment id), detail = extra text (a design's name, a
trade deal's resource and amount).
"""

from __future__ import annotations

# kind -> the snapshot part; set parts become added / removed events, dict parts also "changed"
KINDS = ("focus", "research", "researched", "ideas", "advisors", "leader", "wars", "justifications", "templates",
         "designs", "construction", "trade")


def _diff_set(kind: str, before: set, now: set, added: str = "added", removed: str = "removed") -> list[dict]:
    return ([{"kind": kind, "action": added, "id": i} for i in sorted(now - before, key=str)]
            + [{"kind": kind, "action": removed, "id": i} for i in sorted(before - now, key=str)])


def diff(before: dict | None, now: dict) -> list[dict]:
    """Events between two snapshots of one country ([] for the first one - the baseline)."""
    if not before:
        return []
    out: list[dict] = []
    # focus: a new focus selected, the previous one completed (it is in "completed" now) or cancelled
    fb, fn = before.get("focus") or {}, now.get("focus") or {}
    if fb.get("current") != fn.get("current"):
        if fn.get("current"):
            out.append({"kind": "focus", "action": "started", "id": fn["current"]})
        if fb.get("current") and fb["current"] not in set(fn.get("completed") or []):
            out.append({"kind": "focus", "action": "cancelled", "id": fb["current"]})
    for f in sorted(set(fn.get("completed") or []) - set(fb.get("completed") or [])):
        out.append({"kind": "focus", "action": "completed", "id": f})
    # research: slots (a technology leaving its slot because it is done is "completed", not "stopped")
    rb, rn, done = set(before.get("research") or []), set(now.get("research") or []), set(now.get("researched") or [])
    out += [{"kind": "research", "action": "started", "id": i} for i in sorted(rn - rb)]
    out += [{"kind": "research", "action": "stopped", "id": i} for i in sorted(rb - rn - done)]
    out += _diff_set("researched", set(before.get("researched") or []), set(now.get("researched") or []),
                     "completed", "lost")
    out += _diff_set("ideas", set(before.get("ideas") or []), set(now.get("ideas") or []))
    out += _diff_set("advisors", set(before.get("advisors") or []), set(now.get("advisors") or []), "hired", "dismissed")
    if before.get("leader") != now.get("leader") and now.get("leader"):
        out.append({"kind": "leader", "action": "changed", "id": now["leader"]})
    out += _diff_set("wars", set(before.get("wars") or []), set(now.get("wars") or []), "declared", "ended")
    out += _diff_set("justifications", set(before.get("justifications") or []), set(now.get("justifications") or []),
                     "started", "finished")
    tb, tn = before.get("templates") or {}, now.get("templates") or {}
    out += _diff_set("templates", set(tb), set(tn), "created", "deleted")
    out += [{"kind": "templates", "action": "edited", "id": n} for n in sorted(set(tb) & set(tn)) if tb[n] != tn[n]]
    db, dn = before.get("designs") or {}, now.get("designs") or {}
    out += [{"kind": "designs", "action": "created", "id": i, "detail": dn[i]} for i in sorted(set(dn) - set(db), key=str)]
    cb, cn = before.get("construction") or {}, now.get("construction") or {}
    out += [{"kind": "construction", "action": "queued", "id": i, "detail": cn[i]} for i in sorted(set(cn) - set(cb), key=str)]
    out += [{"kind": "construction", "action": "left the queue", "id": i, "detail": cb[i]}
            for i in sorted(set(cb) - set(cn), key=str)]
    trb, trn = before.get("trade") or {}, now.get("trade") or {}
    out += [{"kind": "trade", "action": "deal made", "id": k, "detail": trn[k]} for k in sorted(set(trn) - set(trb))]
    out += [{"kind": "trade", "action": "deal ended", "id": k, "detail": trb[k]} for k in sorted(set(trb) - set(trn))]
    out += [{"kind": "trade", "action": "deal changed", "id": k, "detail": trn[k]} for k in sorted(set(trb) & set(trn))
            if trb[k] != trn[k]]
    return out
