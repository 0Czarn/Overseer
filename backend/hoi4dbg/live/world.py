"""The game world for triggers.evaluate, read lazily from game memory (each fact read once per evaluation).

Countries that exist = tags with a country object and at least one owned state. Subject / guarantee / pact links
come from each country's diplomatic relations (pointers.read_links), the faction leader is the first member
(SOV first in the Comintern, 2026-10-16).
"""

from __future__ import annotations

from . import pointers


class LiveWorld:
    def __init__(self, mem, module_base: int, order: list[str], ideologies: list[str], dlcs: set[str] | None,
                 rules: dict[str, str] | None = None) -> None:
        self.mem, self.base, self.order, self.ideologies, self._dlcs = mem, module_base, order, ideologies, dlcs
        self.rules = rules or {}   # game rules {rule: option} (has_game_rule)
        self.flags: dict[str, dict] = {}   # {tag: {flag: value}} from the newest save of this game (not in memory yet)
        self.objects = pointers.country_objects(mem, module_base, order)
        owned = pointers.owned_states(mem, module_base, order)
        self._countries = [t for t in order if t in self.objects and owned.get(t, 0) > 0]
        self._by_object = {c: t for t, c in self.objects.items()}
        self._cache: dict[tuple, object] = {}

    def _get(self, name: str, tag, fn):
        key = (name, tag)
        if key not in self._cache:
            try:
                self._cache[key] = fn()
            except pointers.PointerError:
                self._cache[key] = None
        return self._cache[key]

    def _slot_tag(self, slot: int) -> str | None:
        return self.order[slot - 1] if 0 < slot <= len(self.order) else None

    def countries(self) -> list[str]:
        return self._countries

    def players(self) -> set[str]:
        return self._get("players", None, lambda: {p["tag"] for p in pointers.read_players(self.mem, self.base, self.order)}) or set()

    def dlcs(self) -> set[str] | None:
        return self._dlcs

    def game_rule(self, rule: str) -> str | None:
        return self.rules.get(rule)

    def country_flags(self, tag: str) -> dict | None:
        return self.flags.get(tag)

    def government(self, tag: str) -> str | None:
        c = self.objects.get(tag)
        return self._get("gov", tag, lambda: pointers.read_parties(self.mem, c, self.ideologies)["ruling"]) if c else None

    def ideology_names(self) -> list[str]:
        return self.ideologies

    def popularity(self, tag: str, ideology: str) -> float | None:
        """Party popularity as the triggers compare it (0..1)."""
        c = self.objects.get(tag)
        pop = self._get("pop", tag, lambda: pointers.read_parties(self.mem, c, self.ideologies)["popularity"]) if c else None
        return pop[ideology] / 100 if pop and ideology in pop else None

    def army_manpower(self, tag: str) -> int | None:
        """Manpower of the divisions in the field (has_army_manpower)."""
        c = self.objects.get(tag)
        raw = self._get("army_mp", tag, lambda: self.mem.read(c + pointers.ARMY["manpower_field"], 4)) if c else None
        return int.from_bytes(raw, "little", signed=True) if raw else None

    def links(self, tag: str) -> list[tuple[str, str, str]] | None:
        c = self.objects.get(tag)
        if not c:
            return None
        return self._get("links", tag, lambda: [(k, self._slot_tag(a), self._slot_tag(b))
                                                for k, a, b in pointers.read_links(self.mem, c, self.base)])

    def overlord(self, tag: str) -> str | None:
        return next((a for k, a, b in self.links(tag) or [] if k == "subject" and b == tag), None)

    def subjects(self, tag: str) -> list[str]:
        return [b for k, a, b in self.links(tag) or [] if k == "subject" and a == tag]

    def wars(self, tag: str) -> list[str]:
        c = self.objects.get(tag)
        return (self._get("wars", tag, lambda: [w["enemy"] for w in pointers.read_wars(self.mem, c, self.order, tag)])
                or []) if c else []

    def faction(self, tag: str) -> list[str] | None:
        c = self.objects.get(tag)
        f = self._get("faction", tag, lambda: pointers.read_faction(self.mem, c, self._by_object)) if c else None
        return f["members"] if f else None

    def completed(self, tag: str) -> list[str]:
        c = self.objects.get(tag)
        return (self._get("focus", tag, lambda: pointers.read_focus(self.mem, c)["completed"]) or []) if c else []

    def ideas(self, tag: str) -> list[str]:
        c = self.objects.get(tag)
        return (self._get("ideas", tag, lambda: pointers.read_ideas(self.mem, c)) or []) if c else []

    def dynamic_modifiers(self, tag: str) -> list[str]:
        c = self.objects.get(tag)
        return (self._get("dyn", tag, lambda: [d["id"] for d in pointers.read_dynamic_modifiers(self.mem, c)])
                or []) if c else []

    def techs(self, tag: str) -> list[str]:
        c = self.objects.get(tag)
        return (self._get("techs", tag, lambda: pointers.read_researched(self.mem, c)) or []) if c else []

    def _states(self) -> dict[int, dict]:
        return self._get("states", None, lambda: {s["id"]: s for s in pointers.read_states(
            self.mem, self.base, self.order, [], [])}) or {}

    def state(self, sid: int) -> dict | None:
        return self._states().get(sid)

    def state_ids(self) -> list[int]:
        return list(self._states())

    def opinion(self, tag: str, other: str) -> int | None:
        c = self.objects.get(tag)
        if not c or other not in self.order:
            return None
        return self._get("opinion", (tag, other), lambda: pointers.read_relation(
            self.mem, c, self.order.index(other) + 1, self.base)["opinion"])

    def justifying(self, tag: str) -> set[str] | None:
        c = self.objects.get(tag)
        if not c:
            return None
        sides = self._get("just", tag, lambda: pointers.read_justifications(self.mem, c))
        return None if sides is None else {self._slot_tag(b) for a, b in sides if self._slot_tag(a) == tag}

    def political_power(self, tag: str) -> float | None:
        c = self.objects.get(tag)
        return self._get("pp", tag, lambda: pointers.read_field(self.mem, c, "political_power")) if c else None

    def factories(self, tag: str) -> int | None:
        c = self.objects.get(tag)
        f = self._get("factories", tag, lambda: pointers.read_factories(self.mem, c)) if c else None
        if not f:
            return None
        return sum(int(f[k]["total"]) for k in ("military", "dockyards", "civilian") if k in f)
