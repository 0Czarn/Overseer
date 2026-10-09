"""Verified equipment additions: documented console command, checked against a newer save.

`add_equipment N <archetype>` (console documentation: "Gives player amount of equipment that has the specified
name"). In-game test 2026-10-09 (SOV, paused, mapa.hoi4 -> sprzet.hoi4): `add_equipment 100 infantry_equipment_1`
added exactly 100; `add_equipment -50 train_equipment_1` ADDED 1000 instead of removing 50 - negative amounts are
not supported, so the app only prepares additions. The stockpile is not read live, so the result is verified by
the next save of the running game: amount of that archetype must grow by exactly N.
"""

from __future__ import annotations

import itertools
import re
import threading
import time
from pathlib import Path

from .live import console
from .saves.binary import SaveFormatError

MAX_AMOUNT = 1_000_000
TIMEOUT_S = 900
ARCHETYPE = re.compile(r"[a-z][a-z0-9_]{1,80}")


class ChangeError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def archetype_total(data: dict, archetype: str) -> float:
    return sum(n for i, n in data["stockpile"].items() if (data["variants"].get(i) or {}).get("type") == archetype)


class EquipmentChanges:
    def __init__(self, svc, clock=time.time) -> None:
        self.svc = svc
        self.clock = clock
        self._ops: dict[str, dict] = {}
        self._ids = itertools.count(1)
        self._lock = threading.Lock()

    def _history(self) -> console.ConsoleHistory:
        install = self.svc._install_path()
        if install is None:
            raise ChangeError("no_install", "Game installation not found")
        return console.ConsoleHistory(install / console.HISTORY_FILE)

    def _newest(self, tag: str) -> tuple[Path, dict]:
        picked = self.svc._pick_save(None)
        if picked is None:
            raise ChangeError("no_save", "No save file available")
        try:
            return picked[0], self.svc.saves.equipment(picked[0], tag)
        except SaveFormatError as exc:
            raise ChangeError("save_in_progress" if exc.code == "in_progress" else exc.code, str(exc)) from exc

    def _player_tags(self, save_data: dict) -> list[str]:
        live = getattr(self.svc, "live", None)
        players = live.players() if live is not None else []
        return players or [((save_data["analysis"].get("header") or {}).get("player_tag"))]

    def create(self, tag: str, archetype: str, amount) -> dict:
        tag = tag.upper()
        if not ARCHETYPE.fullmatch(archetype or ""):
            raise ChangeError("bad_archetype", f"Not an equipment archetype key: {archetype!r}")
        if not isinstance(amount, int) or isinstance(amount, bool) or not 1 <= amount <= MAX_AMOUNT:
            raise ChangeError("bad_amount", f"Amount must be a whole number 1..{MAX_AMOUNT} (the game cannot "
                                            "remove equipment with this command)")
        path, data = self._newest(tag)
        known = {v.get("type") for v in data["variants"].values()}
        if archetype not in known:
            raise ChangeError("unknown_archetype", f"{archetype} is not in the equipment table of {path.name}")
        if tag not in self._player_tags(data):
            raise ChangeError("not_player", f"Console commands change the player's country, not {tag}")
        op = {"id": f"eq-{next(self._ids)}", "tag": tag, "archetype": archetype, "amount": amount,
              "command": f"add_equipment {amount} {archetype}", "before": archetype_total(data, archetype),
              "before_save": path.name, "before_mtime": data["analysis"]["file"]["mtime"],
              "mark": self._history().mark(), "state": "waiting_for_command", "created": self.clock()}
        op["expected"] = op["before"] + amount
        op["message"] = (f"Enter `{op['command']}` in the game console (game paused), then save the game. "
                         f"Expected {archetype}: {op['before']:g} -> {op['expected']:g}.")
        with self._lock:
            self._ops[op["id"]] = op
        self.svc.log.info("Equipment change %s: %s %s %s -> expected %s via `%s`", op["id"], tag, archetype,
                          op["before"], op["expected"], op["command"])
        return self._public(op)

    def poll(self, op_id: str) -> dict:
        with self._lock:
            op = self._ops.get(op_id)
        if op is None:
            raise ChangeError("unknown_operation", f"Unknown operation {op_id}")
        if op["state"] in ("confirmed", "mismatch", "expired"):
            return self._public(op)
        if self.clock() - op["created"] > TIMEOUT_S:
            return self._finish(op, "expired", "No verifying save within 15 minutes")
        if op["state"] == "waiting_for_command":
            if not self._history().executed_since(op["mark"], op["command"]):
                return self._public(op)
            op.update(state="waiting_for_save", message="Command entered - now save the game (still paused).")
        try:
            path, data = self._newest(op["tag"])
        except ChangeError as exc:
            if exc.code != "save_in_progress":
                raise
            op["message"] = "The game is still writing the save - checking again shortly."
            return self._public(op)  # regression: a save being written aborted the check
        if data["analysis"]["file"]["mtime"] <= op["before_mtime"]:
            return self._public(op)
        after = archetype_total(data, op["archetype"])
        op["actual"], op["after_save"] = after, path.name
        if abs(after - op["expected"]) < 0.5:
            return self._finish(op, "confirmed", f"Verified in {path.name}: {op['archetype']} "
                                                 f"{op['before']:g} -> {after:g} (expected {op['expected']:g}).")
        return self._finish(op, "mismatch", f"{path.name} shows {after:g}, expected {op['expected']:g} "
                                            "(game unpaused, or production/losses in between?).")

    def _finish(self, op: dict, state: str, message: str) -> dict:
        op.update(state=state, message=message, finished=self.clock())
        self.svc.log.log(20 if state == "confirmed" else 30, "Equipment change %s %s: %s", op["id"], state, message)
        return self._public(op)

    @staticmethod
    def _public(op: dict) -> dict:
        return {k: v for k, v in op.items() if k != "mark"}
