"""Game Tools (Krok G): change rules, campaign checkpoints, live memory check."""

import os
import unittest

from hoi4dbg import game_tools
from hoi4dbg.service import NotFound

from helpers import TempDirMixin, make_service
from test_countries import TEXT_SAVE
from test_saves import FakeSaveIntegration


class ChangeRulesTests(unittest.TestCase):
    def status(self, method, mode, mp=None, running=True, supported=True):
        return game_tools.change_status(method, mode, mp or {}, running, supported)[0]

    def test_single_player_allows_everything(self):
        for method in game_tools.METHODS:
            self.assertEqual(self.status(method, "SINGLEPLAYER"), "allowed", method)

    def test_multiplayer_follows_the_live_guards(self):
        mp = "MULTIPLAYER"
        self.assertEqual(self.status(game_tools.CONSOLE, mp), "untested")        # Krok H
        self.assertEqual(self.status(game_tools.MEMORY, mp), "blocked")
        self.assertEqual(self.status(game_tools.MEMORY, mp, {"enabled": True}), "allowed")   # Options
        self.assertEqual(self.status(game_tools.MEMORY_SP, mp, {"enabled": True}), "blocked")  # strict
        self.assertEqual(self.status(game_tools.CODE_PATCH, mp, {"enabled": True}), "blocked")
        self.assertEqual(self.status(game_tools.VIEW, mp, {"enabled": True}), "blocked")       # its own switch
        self.assertEqual(self.status(game_tools.VIEW, mp, {"fog": True}), "allowed")

    def test_unknown_mode_and_no_game(self):
        self.assertEqual(self.status(game_tools.MEMORY, None), "blocked")
        self.assertEqual(self.status(game_tools.MEMORY, None, {"enabled": True}), "allowed")   # as _require_single_player
        self.assertEqual(self.status(game_tools.VIEW, None, {"fog": True}), "blocked")       # as fog_of_war
        self.assertEqual(self.status(game_tools.CONSOLE, None), "unknown")
        self.assertEqual(self.status(game_tools.MEMORY, "SINGLEPLAYER", running=False), "unknown")
        self.assertEqual(self.status(game_tools.MEMORY, "SINGLEPLAYER", supported=False), "blocked")
        self.assertEqual(self.status(game_tools.CONSOLE, "SINGLEPLAYER", supported=False), "allowed")


class NoLiveTests(TempDirMixin, unittest.TestCase):
    def test_no_live_access(self):
        data = make_service(self.tmp).tool_changes()["data"]
        self.assertFalse(data["running"])
        self.assertEqual({c["status"] for c in data["changes"]}, {"unknown"})
        self.assertEqual(len(data["changes"]), len(game_tools.CHANGES))


class CheckpointTests(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.saves = self.tmp / "saves"
        self.saves.mkdir()
        (self.saves / "ita.hoi4").write_text(TEXT_SAVE, encoding="utf-8", newline="")
        (self.saves / "broken.hoi4").write_bytes(b"\x00\x01nothing")
        os.utime(self.saves / "broken.hoi4", (1, 1))   # oldest
        self.svc = make_service(self.tmp, FakeSaveIntegration(self.saves, None, None))

    def test_header_from_the_first_bytes(self):
        saves = self.svc.checkpoints()["data"]["saves"]
        self.assertEqual([s["name"] for s in saves], ["ita.hoi4", "broken.hoi4"])
        self.assertEqual((saves[0]["date"], saves[0]["player_tag"]), ("1936.2.1.3", "ITA"))
        self.assertIn("error", saves[1])

    def test_notes_are_kept_and_removed(self):
        self.svc.checkpoints({"name": "ita.hoi4", "note": "  before the war  "})
        again = make_service(self.tmp, FakeSaveIntegration(self.saves, None, None))   # read back from the file
        first = again.checkpoints()["data"]["saves"][0]
        self.assertEqual((first["note"], first["note_changed"]), ("before the war", False))
        os.utime(self.saves / "ita.hoi4", (2_000_000_000, 2_000_000_000))   # the save was overwritten
        self.assertTrue(again.checkpoints()["data"]["saves"][0]["note_changed"])
        again.checkpoints({"name": "ita.hoi4", "note": ""})
        self.assertEqual(again.checkpoints()["data"]["saves"][0]["note"], "")

    def test_unknown_save_and_orphan_notes(self):
        with self.assertRaises(NotFound):
            self.svc.checkpoints({"name": "../x.hoi4", "note": "x"})
        self.svc.checkpoints({"name": "ita.hoi4", "note": "kept"})
        (self.saves / "ita.hoi4").unlink()
        self.assertEqual(self.svc.checkpoints()["data"]["orphan_notes"], ["ita.hoi4"])


class FakeLive:
    def __init__(self, process=True):
        self.process = {"pid": 1, "version": "v1.19.3.0.c01a"} if process else None

    def status(self):
        return {"process": self.process, "error": None if self.process else {"message": "HOI4 is not running"}}

    def player_tag(self, process):
        return "GER"

    def running_game(self):
        return {"date": "1 Jan 1936"}

    def session(self):
        return {"game_mode": "SINGLEPLAYER", "states": {"GER": [1, 2]}}

    def values(self, tag):
        return {"political_power": {"status": "live"}, "fuel": {"status": "unavailable"}}

    def focus(self, tag):
        return {"current": None}

    def research(self, tag):
        raise type("LiveError", (Exception,), {"code": "implausible"})("slots not readable")

    def __getattr__(self, name):   # the other readers succeed
        return lambda *a: {"lines": [1, 2], "entries": [], "fog": True, "state": "off"}


class LiveCheckTests(unittest.TestCase):
    def test_every_reader_reported(self):
        out = game_tools.live_check(FakeLive())
        by_id = {c["id"]: c for c in out["checks"]}
        self.assertEqual(out["tag"], "GER")
        self.assertEqual(by_id["values"]["detail"], "1 of 2 fields live")
        self.assertEqual(by_id["date"]["detail"], "1 Jan 1936")
        self.assertFalse(by_id["research"]["ok"])
        self.assertEqual(by_id["research"]["error"], "implausible: slots not readable")
        self.assertEqual(by_id["construction"]["detail"], "2 lines")
        self.assertTrue(all(c["ok"] for c in out["checks"] if c["id"] != "research"))

    def test_game_not_running(self):
        out = game_tools.live_check(FakeLive(process=False))
        self.assertEqual((out["running"], out["checks"], out["error"]), (False, [], "HOI4 is not running"))


if __name__ == "__main__":
    unittest.main()
