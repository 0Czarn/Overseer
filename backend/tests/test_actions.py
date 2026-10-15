import logging
import tempfile
import unittest
from pathlib import Path

from hoi4dbg import actions, ic_history
from hoi4dbg.ic_history import IcHistory, IcRecorder


def day(year, month, dom):
    return year * 365 + sum(ic_history.MONTH_DAYS[:month - 1]) + dom - 1


def snap(**kw):
    base = {"focus": {"current": "POL_a", "completed": []}, "research": ["tech_a"], "researched": ["tech_0"],
            "ideas": ["civilian_economy"], "advisors": ["10"], "leader": "1", "wars": [], "justifications": [],
            "templates": {"Inf": [["infantry"], [None], [None]]}, "designs": {"1": "PZL P.23"}, "construction": {},
            "trade": {}}
    base.update(kw)
    return base


class DiffTest(unittest.TestCase):
    def test_first_snapshot_is_only_the_baseline(self):
        self.assertEqual(actions.diff(None, snap()), [])

    def test_every_kind_of_change(self):
        now = snap(focus={"current": "POL_b", "completed": ["POL_a"]}, research=["tech_b"], researched=["tech_0", "tech_a"],
                   ideas=["partial_economic_mobilisation"], advisors=["10", "11"], leader="2", wars=["GER"],
                   justifications=["LIT"], templates={"Inf": [["infantry", "infantry"], [None], [None]], "Cav": [[], [], []]},
                   designs={"1": "PZL P.23", "2": "PZL P.24"}, construction={"7": "industrial_complex@10"},
                   trade={"ENG aluminium": 8.0})
        got = {(e["kind"], e["action"], e["id"]) for e in actions.diff(snap(), now)}
        self.assertEqual(got, {
            ("focus", "started", "POL_b"), ("focus", "completed", "POL_a"),
            ("research", "started", "tech_b"), ("researched", "completed", "tech_a"),   # tech_a done: not "stopped"
            ("ideas", "added", "partial_economic_mobilisation"), ("ideas", "removed", "civilian_economy"),
            ("advisors", "hired", "11"), ("leader", "changed", "2"), ("wars", "declared", "GER"),
            ("justifications", "started", "LIT"), ("templates", "created", "Cav"), ("templates", "edited", "Inf"),
            ("designs", "created", "2"), ("construction", "queued", "7"), ("trade", "deal made", "ENG aluminium")})

    def test_cancelled_focus_and_stopped_research(self):
        now = snap(focus={"current": None, "completed": []}, research=[])
        got = {(e["kind"], e["action"], e["id"]) for e in actions.diff(snap(), now)}
        self.assertEqual(got, {("focus", "cancelled", "POL_a"), ("research", "stopped", "tech_a")})


class FakeLive:
    def __init__(self):
        self.t = day(1936, 5, 1)

    def game_day(self):
        return self.t

    def ensure_combat_log_patch(self):
        pass

    def ic_snapshot(self, with_factions):
        return {"t": self.t, "player": "POL", "countries": {"POL": [1.0, 0, 0, 1, 1, 0, 0, 0, 0]}, "factions": None}


class RecorderTest(unittest.TestCase):
    def test_events_of_the_player_and_watched_countries_and_replayed_days_dropped(self):
        live = FakeLive()
        snaps = {"POL": snap(), "GER": snap(focus={"current": "GER_x", "completed": []})}
        history = IcHistory(Path(tempfile.mkdtemp()))
        history.set_watched(["GER"])
        asked = []

        def read(tags):
            asked.append(tags)
            return {t: dict(snaps[t]) for t in tags}
        rec = IcRecorder(live, history, logging.getLogger("test"), actions=read)
        rec.step()                                     # first poll: no day passed yet
        live.t += 1
        rec.step()                                     # baseline
        snaps["POL"] = snap(ideas=["civilian_economy", "volunteer_only"])
        live.t += 1
        rec.step()
        gid = history.active
        self.assertEqual(asked[-1], ["GER", "POL"])
        self.assertEqual([(e["t"], e["tag"], e["kind"], e["id"]) for e in history.actions(gid)],
                         [(live.t, "POL", "ideas", "volunteer_only")])
        live.t -= 1                                    # an earlier save loaded: that day is replayed
        rec.step()
        live.t += 1
        rec.step()
        self.assertEqual(history.actions(gid), [])     # the event of the replayed day is gone, the new day is a baseline
        with self.assertRaises(ValueError):
            history.set_watched(["not a tag"])


if __name__ == "__main__":
    unittest.main()
