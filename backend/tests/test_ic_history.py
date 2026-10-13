import logging
import tempfile
import unittest
from pathlib import Path

from hoi4dbg import ic_history
from hoi4dbg.ic_history import IcHistory, IcRecorder


def day(year, month, dom):
    return year * 365 + sum(ic_history.MONTH_DAYS[:month - 1]) + dom - 1


class IcHistoryTest(unittest.TestCase):
    def setUp(self):
        self.history = IcHistory(Path(tempfile.mkdtemp()) / "ic-history")

    def sample(self, t, player="SOV", factions=None, **countries):
        return {"t": t, "player": player, "countries": countries or {"SOV": [1551.5, 19.8, 1242.5]}, "factions": factions}

    def test_dates_have_no_leap_years(self):
        self.assertEqual(ic_history.date_text(day(1941, 11, 2)), "1941.11.02")
        self.assertEqual(ic_history.date_text(day(1940, 3, 1)), "1940.03.01")
        self.assertEqual(ic_history.day_number({"year": 1941, "day": 305, "hour": 1}), day(1941, 11, 2))

    def test_days_append_and_series_fill_missing_countries(self):
        t = day(1941, 11, 1)
        gid = self.history.add(self.sample(t, factions={"SOV": "Comintern"}, SOV=[10, 1, 5]))
        self.history.add(self.sample(t + 1, SOV=[12, 1, 5], FIN=[3, 0, 2]))
        game = self.history.game(gid)
        self.assertEqual(game["dates"], ["1941.11.01", "1941.11.02"])
        self.assertEqual(game["countries"]["SOV"]["mil"], [10, 12])
        self.assertEqual(game["countries"]["FIN"]["mil"], [0, 3])   # did not exist on the first day
        self.assertEqual((game["player"], game["factions"]), ("SOV", {"SOV": "Comintern"}))
        [g] = self.history.games()
        self.assertEqual((g["first"], g["last"], g["days"], g["active"]), ("1941.11.01", "1941.11.02", 2, True))

    def test_reload_cuts_replayed_days_and_other_country_starts_a_new_campaign(self):
        t = day(1941, 11, 1)
        gid = self.history.add(self.sample(t))
        for i in range(1, 6):
            self.history.add(self.sample(t + i))
        self.assertEqual(self.history.add(self.sample(t + 2)), gid)   # an earlier save of this campaign
        self.assertEqual(self.history.game(gid)["dates"][-1], "1941.11.03")
        self.assertEqual(len(self.history.game(gid)["dates"]), 3)
        other = self.history.add(self.sample(t + 3, player="GER", GER=[2000, 90, 980]))
        self.assertNotEqual(other, gid)
        self.assertEqual(len(self.history.games()), 2)

    def test_older_sessions_are_never_cut(self):
        t = day(1941, 11, 1)
        gid = self.history.add(self.sample(t + 10))
        later = IcHistory(self.history.folder)   # app restarted
        self.assertNotEqual(later.add(self.sample(t)), gid)   # a new game of the same country, earlier date
        self.assertEqual(len(later.game(gid)["dates"]), 1)

    def test_a_later_session_continues_the_campaign(self):
        t = day(1941, 11, 1)
        gid = self.history.add(self.sample(t))
        self.assertEqual(IcHistory(self.history.folder).add(self.sample(t + 3)), gid)

    def test_bad_ids_are_refused(self):
        with self.assertRaises(ValueError):
            self.history.game("../secret")


class FakeLive:
    def __init__(self):
        self.t = day(1941, 11, 1)
        self.snapshots = 0

    def game_day(self):
        return self.t

    def ic_snapshot(self, with_factions):
        self.snapshots += 1
        return {"t": self.t, "player": "SOV", "countries": {"SOV": [1.0, 0.0, 2.0]},
                "factions": {"SOV": "Comintern"} if with_factions else None}


class IcRecorderTest(unittest.TestCase):
    def test_one_sample_per_played_game_day(self):
        live = FakeLive()
        history = IcHistory(Path(tempfile.mkdtemp()))
        rec = IcRecorder(live, history, logging.getLogger("test"))
        self.assertFalse(rec.step())   # paused game / menu: no day has passed yet
        self.assertFalse(rec.step())
        live.t += 1
        self.assertTrue(rec.step())
        self.assertFalse(rec.step())   # same day: nothing read
        live.t += 3                    # high speed: days skipped
        self.assertTrue(rec.step())
        self.assertEqual(live.snapshots, 2)
        self.assertEqual(rec.status()["last"], "1941.11.05")
        self.assertEqual(len(history.game(history.active)["dates"]), 2)

    def test_menu_and_loading_a_save_are_not_played_days(self):
        live = FakeLive()
        rec = IcRecorder(live, IcHistory(Path(tempfile.mkdtemp())), logging.getLogger("test"))
        rec.step()
        live.t = day(1936, 1, 1)       # back to the main menu / country selection
        self.assertFalse(rec.step())
        live.t = day(1941, 6, 1)       # a save loaded
        self.assertFalse(rec.step())
        self.assertEqual(live.snapshots, 0)
        live.t += 1
        self.assertTrue(rec.step())

    def test_all_zero_production_is_skipped(self):
        live = FakeLive()
        live.ic_snapshot = lambda f: {"t": live.t, "player": "SOV", "countries": {"SOV": [0, 0, 0, 0, 0, 0]}, "factions": None}
        rec = IcRecorder(live, IcHistory(Path(tempfile.mkdtemp())), logging.getLogger("test"))
        rec.step()
        live.t += 1
        self.assertFalse(rec.step())


class ViewTest(unittest.TestCase):
    GAME = {"t": [1, 2], "dates": ["a", "b"], "factions": {"GER": "Axis", "ITA": "Axis", "SOV": "Comintern"},
            "countries": {"GER": {"mil": [100, 120], "nav": [10, 10], "civ": [50, 60]},
                          "ITA": {"mil": [20, 30], "nav": [5, 5], "civ": [10, 10]},
                          "SOV": {"mil": [90, 160], "nav": [1, 1], "civ": [70, 70]},
                          "SWE": {"mil": [5, 6], "nav": [0, 0], "civ": [9, 9]},
                          "XXX": {"mil": [3, 0], "nav": [0, 0], "civ": [0, 0]}}}

    def test_countries_and_faction_sums(self):
        v = ic_history.view(self.GAME, "mil", ["SOV", "GER", "NOPE"], False)
        self.assertEqual([c["tag"] for c in v["countries"]], ["SOV", "GER", "ITA", "SWE"])   # XXX is gone today
        self.assertEqual([s["key"] for s in v["series"]], ["SOV", "GER"])
        f = ic_history.view(self.GAME, "mil", None, True)
        self.assertEqual([(s["key"], s["values"]) for s in f["series"]],
                         [("Comintern", [90, 160]), ("Axis", [120, 150]), ("Non-aligned", [8, 6])])
        self.assertEqual(f["factions"], ["Axis", "Comintern"])
        with self.assertRaises(ValueError):
            ic_history.view(self.GAME, "gold", None, False)


class RecorderLockTest(unittest.TestCase):
    def test_only_one_instance_records(self):
        history = IcHistory(Path(tempfile.mkdtemp()))
        first = IcRecorder(FakeLive(), history, logging.getLogger("test"))
        second = IcRecorder(FakeLive(), IcHistory(history.folder), logging.getLogger("test"))
        self.assertTrue(first._lock())
        self.assertFalse(second._lock())
        first._lock_file.close()
        self.assertTrue(second._lock())
        second._lock_file.close()


class FactoryCountTest(unittest.TestCase):
    def test_factories_per_day_and_rows_recorded_before_them(self):
        history = IcHistory(Path(tempfile.mkdtemp()))
        t = day(1941, 11, 1)
        gid = history.add({"t": t, "player": "SOV", "countries": {"SOV": [1551.5, 19.8, 1242.5]}, "factions": None})
        history.add({"t": t + 1, "player": "SOV", "countries": {"SOV": [1560.0, 20.0, 1250.0, 152, 200, 5]},
                     "factions": {"SOV": "Comintern"}})
        game = history.game(gid)
        self.assertEqual(game["countries"]["SOV"]["fmil"], [None, 200])   # not counted on the first day
        self.assertEqual(game["countries"]["SOV"]["fall"], [None, 357])
        v = ic_history.view(game, "fciv", None, True)
        self.assertEqual(v["series"], [{"key": "Comintern", "values": [None, 152]}])
        self.assertEqual(v["countries"][0]["fdock"], 5)


class GroupsTest(unittest.TestCase):
    GAME = ViewTest.GAME

    def test_moved_countries_and_custom_groups(self):
        groups = ic_history.check_groups({"custom": ["Nordic", " Nordic "], "assign": {"SWE": "Nordic", "ITA": "", "SOV": "Axis"}})
        self.assertEqual(groups["custom"], ["Nordic"])
        f = ic_history.view(self.GAME, "mil", None, True, groups)
        sums = {s["key"]: s["values"] for s in f["series"]}
        self.assertEqual(sums, {"Axis": [190, 280], "Nordic": [5, 6], "Non-aligned": [23, 30]})   # ITA left the Axis
        self.assertEqual(f["factions"], ["Axis", "Nordic"])
        c = {x["tag"]: x for x in ic_history.view(self.GAME, "mil", [], False, groups)["countries"]}
        self.assertEqual((c["SOV"]["faction"], c["SOV"]["game_faction"]), ("Axis", "Comintern"))
        empty = ic_history.view(self.GAME, "mil", None, True, {"custom": ["Empty"], "assign": {}})
        self.assertIn({"key": "Empty", "values": [0.0, 0.0]}, empty["series"])

    def test_bad_groups_and_storage(self):
        for bad in ({"custom": ["x" * 41]}, {"custom": ["Non-aligned"]}, {"assign": {"bad tag": "A"}}, []):
            with self.assertRaises(ValueError):
                ic_history.check_groups(bad)
        history = IcHistory(Path(tempfile.mkdtemp()))
        gid = history.add({"t": day(1941, 11, 1), "player": "SOV", "countries": {"SOV": [1, 0, 0, 1, 1, 0]}, "factions": None})
        self.assertEqual(history.groups(gid), {"custom": [], "assign": {}})
        history.set_groups(gid, {"custom": ["Nordic"], "assign": {"SWE": "Nordic"}})
        self.assertEqual(history.groups(gid)["assign"], {"SWE": "Nordic"})
        self.assertEqual(len(history.games()), 1)   # the groups file is not a campaign
        with self.assertRaises(FileNotFoundError):
            history.set_groups("NOPE_1", {})
