"""Memory layout of confirmed fields, kept across game processes (read-only use).

Heap addresses change with every game start, but fields of one game object keep their distance.
A layout recorded in an earlier process of the SAME game version is used as a hypothesis only:
a field counts as found in the new process when its exact save value sits at the recorded distance
from other fields that hold their exact save values too (at least MIN_CLUSTER fields together).
Nothing is assumed for fields that do not line up - they go through the normal calibration.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

MAX_RECORDS = 20
MIN_CLUSTER = 3   # fields that must line up at the recorded distances (one coincidence is not evidence)


class LayoutStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def records(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def record(self, process: dict, tag: str, fields: dict[str, tuple[str, int]]) -> None:
        """Stores {field: (encoding, address)} of confirmed single locations for this process."""
        if not fields:
            return
        key = (process["pid"], process.get("started"))
        records = [r for r in self.records() if (r.get("pid"), r.get("process_started")) != key]
        old = next((r for r in self.records() if (r.get("pid"), r.get("process_started")) == key), None)
        merged = {**((old or {}).get("fields") or {}),
                  **{f: {"encoding": enc, "address": addr} for f, (enc, addr) in fields.items()}}
        records.append({"pid": process["pid"], "process_started": process.get("started"),
                        "version": process.get("version"), "tag": tag, "recorded_at": time.time(), "fields": merged})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(records[-MAX_RECORDS:], indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def reference(self, process: dict, tag: str) -> dict | None:
        """Newest layout of an EARLIER process of the same game version and country with enough fields."""
        key = (process["pid"], process.get("started"))
        for rec in reversed(self.records()):
            if ((rec.get("pid"), rec.get("process_started")) != key and rec.get("version") == process.get("version")
                    and rec.get("tag") == tag and len(rec.get("fields") or {}) >= MIN_CLUSTER):
                return rec
        return None


def clusters(reference: dict, hits: dict[str, list[int]]) -> tuple[dict[str, int], list[str]]:
    """Fields whose candidates line up at the reference distances.

    `hits`: {field: addresses holding its exact value now (in the reference encoding)}.
    Returns ({field: address}, ambiguous fields). Anchors are tried from the rarest value up; an anchor
    candidate is accepted only if it is the single best one and lines up with >= MIN_CLUSTER fields."""
    ref = {f: v["address"] for f, v in reference["fields"].items() if f in hits}
    sets = {f: set(a) for f, a in hits.items()}
    found: dict[str, int] = {}
    ambiguous: set[str] = set()
    for anchor in sorted(ref, key=lambda f: len(sets[f])):
        if anchor in found:
            continue
        rest = [f for f in ref if f not in found]
        scored = []
        for a in sets[anchor]:
            line = {f: a + ref[f] - ref[anchor] for f in rest if a + ref[f] - ref[anchor] in sets[f]}
            if len(line) >= MIN_CLUSTER:
                scored.append(line)
        if not scored:
            continue
        best = max(len(s) for s in scored)
        top = [s for s in scored if len(s) == best]
        if len(top) == 1:
            found.update(top[0])
        else:
            ambiguous.update(*top)
    return found, sorted(ambiguous - set(found))
