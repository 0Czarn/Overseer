import logging
import tempfile
import unittest
from pathlib import Path

from hoi4dbg import ic_history
from hoi4dbg.ic_history import IcHistory, IcRecorder, scan_game_log


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

    def test_players_are_kept_per_day_and_filled_where_missing(self):
        t = day(1941, 11, 1)
        gid = self.history.add(self.sample(t, SOV=[10, 1, 5]))                       # recorded before player lists
        self.history.add({**self.sample(t + 1, SOV=[12, 1, 5]), "players": {"SOV": {"n": "Czarny", "s": ["MON"]}}})
        self.history.add(self.sample(t + 2, SOV=[12, 1, 5]))
        players = self.history.game(gid)["players"]
        self.assertEqual(players, [{"SOV": {"n": "Czarny", "s": ["MON"]}}] * 3)
        old = self.history.add(self.sample(day(1950, 1, 1), player="GER", GER=[1, 1, 1]))
        self.assertEqual(self.history.game(old)["players"], [{"GER": {"n": None, "s": []}}])   # the campaign's player

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

    def test_the_campaign_id_decides_however_far_the_date(self):
        t = day(1936, 1, 1)
        a = self.history.add({**self.sample(t), "campaign": "A"})
        b = self.history.add({**self.sample(t + 1), "campaign": "B"})   # another campaign of the same country
        self.assertNotEqual(a, b)
        later = IcHistory(self.history.folder)                       # app restarted, a save of A a year later
        self.assertEqual(later.add({**self.sample(t + 400), "campaign": "A"}), a)
        self.assertEqual(later.how, "recognised by the campaign id")
        self.assertEqual(later.add({**self.sample(t + 200), "campaign": "A"}), a)   # an earlier save of A
        self.assertEqual(later.game(a)["dates"], ["1936.01.01", ic_history.date_text(t + 200)])
        self.assertEqual(later.add({**self.sample(t + 2), "campaign": "B"}), b)
        self.assertEqual([g["campaign"] for g in later.games() if g["id"] == b], ["B"])

    def test_a_file_recorded_without_the_id_is_continued_and_noted(self):
        t = day(1936, 1, 1)
        gid = self.history.add(self.sample(t))
        self.assertEqual(self.history.add({**self.sample(t + 1), "campaign": "A"}), gid)
        self.assertEqual(IcHistory(self.history.folder).add({**self.sample(t + 90), "campaign": "A"}), gid)
        self.assertNotEqual(IcHistory(self.history.folder).add(self.sample(t + 90)), gid)   # no id: by the date, too far

    def test_the_users_new_recording_and_continue(self):
        t = day(1936, 1, 1)
        a = self.history.add({**self.sample(t), "campaign": "A"})
        self.history.add({**self.sample(t + 1), "campaign": "A"})
        self.history.request(None)
        new = self.history.add({**self.sample(t + 2), "campaign": "A"})
        self.assertNotEqual(new, a)
        self.assertEqual(self.history.how, "new recording started manually")
        self.assertEqual(self.history.add({**self.sample(t + 3), "campaign": "A"}), new)
        self.assertEqual(IcHistory(self.history.folder).add({**self.sample(t + 4), "campaign": "A"}), new)   # newest
        self.history.request(a)
        self.assertEqual(self.history.add({**self.sample(t + 1), "campaign": "A"}), a)
        self.assertEqual(self.history.how, "chosen manually")
        self.assertEqual(self.history.game(a)["dates"], ["1936.01.01", "1936.01.02"])   # day 2 recorded again
        self.assertEqual(IcHistory(self.history.folder).add({**self.sample(t + 5), "campaign": "A"}), a)   # linked last
        self.history.request(None)
        self.history.cancel_request()
        self.assertEqual(self.history.add({**self.sample(t + 2), "campaign": "A"}), a)
        with self.assertRaises(FileNotFoundError):
            self.history.request("NOPE_1")

    def test_bad_ids_are_refused(self):
        with self.assertRaises(ValueError):
            self.history.game("../secret")


class FakeLive:
    def __init__(self):
        self.t = day(1941, 11, 1)
        self.snapshots = 0

    def game_day(self):
        return self.t

    def ensure_combat_log_patch(self):
        pass

    def ic_snapshot(self, with_factions, with_infra=False):
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

    def test_the_day_a_game_starts_on_is_recorded_once(self):
        live = FakeLive()
        live.launch = None
        live.game_launch = lambda: live.launch
        rec = IcRecorder(live, IcHistory(Path(tempfile.mkdtemp())), logging.getLogger("test"))
        live.t = day(1936, 1, 1)       # country selection: not in a game
        self.assertFalse(rec.step())
        live.launch = "start#1"        # "Launching SINGLEPLAYER-game" ... map shown
        self.assertTrue(rec.step())
        self.assertEqual(rec.status()["last"], "1936.01.01")
        self.assertFalse(rec.step())   # the same day, paused: once
        live.t += 1
        self.assertTrue(rec.step())    # then every played day as before
        live.launch, live.t = "start#2", day(1941, 6, 1)   # back to the menu, a save loaded
        self.assertTrue(rec.step())
        self.assertEqual(live.snapshots, 3)

    def test_game_log_states(self):
        log = ["[16:09:29][no_game_date][gameapplication.cpp:2968]: Resetting game",
               "[16:09:52][1936.01.01.12][frontend.cpp:682]: ", "\t\t[[ Launching SINGLEPLAYER-game ]]",
               "\tStart-date: 1936.1.1.12"]
        state = scan_game_log(log)
        self.assertEqual((state["pending"], state["in_game"]), (True, None))   # loading: the map not shown yet
        state = scan_game_log(["[16:09:56][1936.01.01.12][ingameidler.cpp:5323]: End RestoreDeviceObjects"], state)
        self.assertEqual(state["in_game"], 1)
        state = scan_game_log(["[19:25:00][1941.10.21.13][ingameidler.cpp:5323]: End RestoreDeviceObjects"], state)
        self.assertEqual(state["in_game"], 1)   # a graphics reset in the game is no new start
        state = scan_game_log(["[23:04:53][1941.10.23.04][ingameidler.cpp:6691]: Resetting gamestate"], state)
        self.assertIsNone(state["in_game"])
        state = scan_game_log(log[2:] + ["[23:05:16][1936.01.01.12][ingameidler.cpp:5323]: End RestoreDeviceObjects"], state)
        self.assertEqual(state["in_game"], 2)

    def test_all_zero_production_is_skipped(self):
        live = FakeLive()
        live.ic_snapshot = lambda f, i=False: {"t": live.t, "player": "SOV", "countries": {"SOV": [0, 0, 0, 0, 0, 0]}, "factions": None}
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


    def test_players_with_and_without_their_subjects_of_each_day(self):
        game = {**self.GAME, "players": [{"GER": {"n": "Czarny", "s": []}, "SOV": {"n": "Frytek", "s": []}},
                                         {"GER": {"n": "Czarny", "s": ["ITA"]}, "SOV": {"n": "Frytek", "s": []}}]}
        v = ic_history.view(game, "mil", None, False, by_player=True)
        self.assertEqual([(s["key"], s["values"]) for s in v["series"]], [("Frytek", [90, 160]), ("Czarny", [100, 150])])
        self.assertEqual({p["name"]: (p["tag"], p["subjects"], p["value"]) for p in v["players"]},
                         {"Czarny": ("GER", ["ITA"], 150), "Frytek": ("SOV", [], 160)})
        own = ic_history.view(game, "mil", None, False, by_player=True, subjects=False)
        self.assertEqual([(s["key"], s["values"]) for s in own["series"]], [("Frytek", [90, 160]), ("Czarny", [100, 120])])
        self.assertEqual(ic_history.view(self.GAME, "mil", None, False, by_player=True)["series"], [])   # none recorded


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


class PerFactoryTest(unittest.TestCase):
    def test_ic_per_assigned_factory_older_days_and_groups(self):
        history = IcHistory(Path(tempfile.mkdtemp()))
        t = day(1936, 1, 2)
        # an older row: no assigned factories - military / naval from the wasted IC (34 factories, 2 idle)
        gid = history.add({"t": t, "player": "SOV", "factions": {"SOV": "Comintern", "MON": "Comintern"},
                           "countries": {"SOV": [60.0, 12.0, 50.0, 46, 34, 6, 3.75, 0.0, 4.0, None, None, None]}})
        history.add({"t": t + 1, "player": "SOV", "countries": {
            "SOV": [64.0, 12.0, 50.0, 46, 34, 6, 0.0, 0.0, 0.0, None, None, None, 32, 6, 10],
            "MON": [2.0, 0.0, 5.0, 2, 2, 0, 0.0, 0.0, 0.0, None, None, None, 2, 0, 2]}})
        game = history.game(gid)
        sov = game["countries"]["SOV"]
        self.assertEqual(sov["pmil"], [round(63.75 / 34, 3), 2.0])     # (IC + wasted) / factories, then IC / 32
        self.assertEqual(sov["pnav"], [2.0, 2.0])
        self.assertEqual(sov["pciv"], [None, 5.0])                     # civilian: only days with assigned factories
        self.assertIsNone(game["countries"]["MON"]["pnav"][1])          # no dockyard on a line
        f = ic_history.view(game, "pmil", None, True)
        self.assertEqual(f["series"][0]["key"], "Comintern")
        self.assertEqual(f["series"][0]["values"][1], round(66 / 34, 3))   # its IC / its factories, not a mean
        self.assertEqual(f["countries"][0]["pmil"], 2.0)

    def test_the_recorder_stores_assigned_factories_after_the_losses(self):
        live = FakeLive()
        live.ic_snapshot = lambda f, i=False: {"t": live.t, "player": "SOV", "factions": None,
                                      "countries": {"SOV": [9.0, 0.0, 5.0, 1, 2, 0, 0, 0, 0]}, "assigned": {"SOV": [2, 0, 1]}}
        history = IcHistory(Path(tempfile.mkdtemp()))
        rec = IcRecorder(live, history, logging.getLogger("test"))
        rec.step()
        live.t += 1
        self.assertTrue(rec.step())
        game = history.game(history.active)
        self.assertEqual((game["countries"]["SOV"]["amil"], game["countries"]["SOV"]["pmil"]), ([2], [4.5]))
        self.assertEqual(game["countries"]["SOV"]["lcom"], [None])


class EquipmentHistoryTest(unittest.TestCase):
    def test_days_series_of_one_archetype_appended_lines_and_replayed_days(self):
        history = IcHistory(Path(tempfile.mkdtemp()))
        t = day(1936, 1, 2)
        gid = history.add({"t": t, "player": "SOV", "countries": {"SOV": [1.0, 0.0, 0.0]}, "factions": None})
        history.add_equipment(gid, t, {"SOV": {"infantry_equipment": [1000, 800, 50, 87.5], "train_equipment": [0, 0, 300, 0]},
                                       "MON": {"infantry_equipment": [100, 100, 0, 0]}})
        history.add_equipment(gid, t + 1, {"SOV": {"infantry_equipment": [1000, 850, 87, 87.5]}})
        e = history.equipment(gid, ["SOV"], None)
        self.assertEqual(e["archetype"], "infantry_equipment")            # the biggest one by default
        self.assertEqual(e["series"]["held"], [800, 850])
        self.assertEqual(e["series"]["produced"], [87.5, 87.5])
        self.assertEqual(list(e["archetypes"]), ["infantry_equipment", "train_equipment"])
        self.assertEqual(history.equipment(gid, ["SOV"], "train_equipment")["series"]["stockpile"], [300, 0])
        self.assertEqual(history.equipment(gid, ["SOV", "MON"], None)["series"]["needed"], [1100, 1000])
        history.add_equipment(gid, t + 2, {"SOV": {"infantry_equipment": [1000, 900, 0, 90]}})   # read after the cache
        self.assertEqual(history.equipment(gid, ["SOV"], None)["series"]["held"], [800, 850, 900])
        history._cut(gid, t + 1)                                           # a save of day t loaded: later days replayed
        self.assertEqual(history.equipment(gid, ["SOV"], None)["t"], [t])

    def test_the_recorder_writes_the_equipment_of_the_day(self):
        live = FakeLive()
        live.ic_snapshot = lambda f, i=False: {"t": live.t, "player": "SOV", "factions": None, "countries": {"SOV": [9.0, 0.0, 5.0]},
                                      "equipment": {"SOV": {"infantry_equipment": [10, 5, 1, 2.5]}}}
        history = IcHistory(Path(tempfile.mkdtemp()))
        rec = IcRecorder(live, history, logging.getLogger("test"))
        rec.step()
        live.t += 1
        self.assertTrue(rec.step())
        self.assertEqual(history.equipment(history.active, ["SOV"], None)["series"]["needed"], [10])


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


class DeleteTest(unittest.TestCase):
    def test_a_campaign_and_its_groups_are_deleted_but_not_the_one_being_recorded(self):
        history = IcHistory(Path(tempfile.mkdtemp()))
        old = history.add({"t": day(1936, 1, 2), "player": "SOV", "countries": {"SOV": [1.0]}})
        history.set_groups(old, {"custom": ["Mine"], "assign": {"SOV": "Mine"}})
        new = history.add({"t": day(1941, 6, 1), "player": "GER", "countries": {"GER": [1.0]}})
        with self.assertRaises(ValueError):
            history.delete(new)                                       # being recorded
        history.delete(old)
        self.assertEqual([g["id"] for g in history.games()], [new])
        self.assertFalse((history.folder / f"{old}.groups.json").exists())
        with self.assertRaises(FileNotFoundError):
            history.delete(old)


class DesignDatesTest(unittest.TestCase):
    def test_first_seen_day_of_plane_designs_and_replayed_days_dropped(self):
        history = IcHistory(Path(tempfile.mkdtemp()))
        t0 = day(1936, 5, 1)
        gid = history.add({"t": t0, "player": "POL", "countries": {"POL": [1.0]}})
        history.note_designs(gid, t0, {"POL": [1711, 1713]})                  # existing when the recording began
        history.add({"t": t0 + 5, "player": "POL", "countries": {"POL": [1.0]}})
        history.note_designs(gid, t0 + 5, {"POL": [1711, 1713, 4505], "GER": [1374]})   # P.23 new; GER: new country
        self.assertEqual(history.designs(gid), {"POL": {"1711": [t0, True], "1713": [t0, True], "4505": [t0 + 5, False]},
                                                "GER": {"1374": [t0 + 5, False]}})
        history.add({"t": t0 + 3, "player": "POL", "countries": {"POL": [1.0]}})   # an earlier save loaded
        self.assertEqual(history.designs(gid), {"POL": {"1711": [t0, True], "1713": [t0, True]}, "GER": {}})
        history.add({"t": day(1941, 1, 1), "player": "GER", "countries": {"GER": [1.0]}})
        history.delete(gid)
        self.assertEqual(history.designs(gid), {})


class WastedAndLossesTest(unittest.TestCase):
    def test_idle_factories_at_the_countrys_own_output(self):
        ic = {"mil": 75.0, "nav": 0.0, "civ": 120.0, "amil": 30, "anav": 0, "aciv": 30}
        w = ic_history.wasted_ic(ic, {"mil": 3, "nav": 2, "civ": -1})
        self.assertEqual(w, {"wmil": 7.5, "wnav": 4.0, "wciv": 0})   # 2.5 a factory; no dockyard line: base speed

    def test_loss_deltas_count_growth_new_records_and_ignore_dropped_ones(self):
        before = {"SOV": {(295, "combat", 1, 9): (100.0, 0.5), (295, "attrition", 1, 9): (50.0, 0.5),
                          (291, "attrition", 0, 9): (10.0, 0.5)}}
        now = {"SOV": {(295, "combat", 1, 9): (110.0, 0.5), (295, "attrition", 1, 9): (50.0, 0.5),
                       (295, "combat", 2, 4506): (2.0, 14.35), (295, "enemy", 2, 1699): (40.0, 0.5)},
               "POL": {(323, "attrition", 3, 1699): (4.0, 0.5)}}
        self.assertIsNone(ic_history.loss_deltas(None, now))
        self.assertEqual(ic_history.loss_deltas(before, now), {"SOV": [33.7, 0.0, 20.0], "POL": [0.0, 2.0, 0.0]})

    def test_a_country_without_a_log_gets_its_equipment_the_logged_ones_destroyed(self):
        before = {"POL": {(1, "enemy", 5, 1455): (100.0, 0.5, "SOV")}}
        now = {"POL": {(1, "enemy", 5, 1455): (140.0, 0.5, "SOV"), (1, "enemy", 6, 1459): (2.0, 3.0, "SOV"),
                       (1, "enemy", 6, 9): (4.0, 1.0, "MON"), (1, "combat", 6, 7): (1.0, 2.0, "POL")},
               "ITA": {(2, "enemy", 6, 3): (10.0, 1.0, "ETH")}, "ETH": {(3, "combat", 6, 4): (1.0, 1.0, "ETH")}}
        self.assertEqual(ic_history.loss_deltas(before, now), {
            "POL": [2.0, 0.0, 30.0], "ITA": [0.0, 0.0, 10.0], "ETH": [1.0, 0.0, 0.0],   # ETH: its own log wins
            "SOV": [26.0, None, None], "MON": [4.0, None, None]})

    def test_casualty_deltas_per_war(self):
        before = {"ITA": {"ETH": (500, 2000)}, "ETH": {"ITA": (2000, 500)}}
        now = {"ITA": {"ETH": (581, 2971), "ABY": (3, 1)}, "ETH": {"ITA": (2971, 581)}}   # ABY: a war begun since
        self.assertIsNone(ic_history.casualty_deltas(None, now))
        self.assertEqual(ic_history.casualty_deltas(before, now), {"ITA": [84, 972], "ETH": [971, 81]})
        self.assertEqual(ic_history.casualty_deltas(now, {}), {})   # peace: the wars are gone

    def test_recorder_adds_losses_from_the_second_day(self):
        live = FakeLive()
        log = {"SOV": {(1, "combat", 0, 9): (10.0, 1.0)}}
        live.ic_snapshot = lambda f, i=False: {"t": live.t, "player": "SOV", "factions": None, "losses": {k: dict(v) for k, v in log.items()},
                                      "countries": {"SOV": [1.0, 0, 0, 1, 1, 0, 0, 0, 0], "ITA": [1.0, 0, 0, 1, 1, 0, 2.5, 0, 0]}}
        history = IcHistory(Path(tempfile.mkdtemp()))
        rec = IcRecorder(live, history, logging.getLogger("test"))
        rec.step()
        for units, step in ((12.0, 1), (15.0, 1), (21.0, 3)):   # 3 days skipped at high speed: 2 a day
            live.t += step
            log["SOV"][(1, "combat", 0, 9)] = (units, 1.0)
            self.assertTrue(rec.step())
        first = history.active
        live.t = day(1941, 6, 1)   # a save loaded: its first played day is unknown again
        rec.step()
        live.t += 1
        rec.step()
        self.assertEqual(history.game(history.active)["countries"]["SOV"]["lcom"], [None])
        game = history.game(first)
        sov, ita = game["countries"]["SOV"], game["countries"]["ITA"]
        self.assertEqual((sov["lcom"], sov["lall"], ita["lcom"], ita["wall"]),
                         ([None, 3.0, 2.0], [None, 3.0, 2.0], [None, None, None], [2.5, 2.5, 2.5]))

    def test_loss_sums_skip_countries_without_a_combat_log(self):
        game = {"t": [1, 2], "dates": ["a", "b"], "factions": {"SOV": "Comintern", "MON": "Comintern"},
                "countries": {"SOV": {"lcom": [None, 5.0]}, "MON": {"lcom": [None, None]}, "ITA": {"lcom": [None, None]}}}
        for k in ic_history.METRICS:
            for c in game["countries"].values():
                c.setdefault(k, [0, 0])
        v = ic_history.view(game, "lcom", None, True)
        self.assertEqual(v["series"], [{"key": "Comintern", "values": [None, 5.0]}])   # no Non-aligned line


def extra(**values):
    """A row's EXTRA values (2026-10-21) by name."""
    return [values.get(k) for k in ic_history.EXTRA]


def full_row(mil=0.0, losses=(None, None, None), **values):
    """A whole STORED row: IC, factories, wasted IC, losses, assigned factories and the EXTRA values."""
    return [mil, 0, 0, 0, 0, 0, 0, 0, 0, *losses, None, None, None, *extra(**values)]


class CampaignAnalysisTest(unittest.TestCase):
    def setUp(self):
        self.history = IcHistory(Path(tempfile.mkdtemp()) / "ic-history")
        self.t = day(1941, 11, 1)

    def add(self, t, countries, players=None, wall=None, still=0, factions=None):
        return self.history.add({"t": t, "player": "GER", "countries": countries, "factions": factions,
                                 "players": players, "wall": wall, "still": still})

    def test_group_values_sum_but_stability_is_a_mean(self):
        gid = self.add(self.t, {"GER": full_row(stab=80, divs=100, pp=50), "ITA": full_row(stab=40, divs=50, pp=10)},
                       factions={"GER": "Axis", "ITA": "Axis"})
        game = self.history.game(gid)
        axis = lambda m: next(s for s in ic_history.view(game, m, None, True)["series"] if s["key"] == "Axis")  # noqa: E731
        self.assertEqual(axis("stab")["values"], [60])
        self.assertEqual(axis("divs")["values"], [150])
        self.assertEqual(ic_history.combine([None, 3], "pp"), None)   # a day recorded before the value existed
        self.assertEqual(ic_history.combine([None, 30], "stab"), 30)

    def test_destroyed_per_lost_is_a_ratio_of_running_sums(self):
        self.assertEqual(ic_history.cum_ratio([0, 1, 3], [10, None, 5], [5, 5, None]), [2.0, 1.0, 2.0])
        gid = self.add(self.t, {"GER": full_row(losses=(2, 2, 20))})
        self.add(self.t + 1, {"GER": full_row(losses=(4, 2, 10))})
        game = self.history.game(gid)
        self.assertEqual(game["countries"]["GER"]["kd"], [5.0, 3.0])
        players = ic_history.view(game, "kd", None, False, by_player=True)
        self.assertEqual(players["series"][0]["values"], [5.0, 3.0])

    def test_ranking_of_players_now_and_a_month_before(self):
        p = {"GER": {"n": "Rodan", "s": []}, "SOV": {"n": "Czarny", "s": []}}
        gid = self.add(self.t, {"GER": full_row(mil=50, divs=10), "SOV": full_row(mil=10, divs=20)}, p)
        self.add(self.t + 40, {"GER": full_row(mil=60, divs=10), "SOV": full_row(mil=90, divs=5)}, p)
        rank = ic_history.ranking(self.history.game(gid))
        ic = next(c for c in rank["categories"] if c["key"] == "icall")
        self.assertEqual([(r["name"], r["rank"], r["rank_before"]) for r in ic["rows"]], [("Czarny", 1, 2), ("Rodan", 2, 1)])
        self.assertEqual(rank["since"], "1941.11.01")

    def test_sessions_players_and_stopped_time(self):
        a = {"GER": {"n": "Rodan", "s": []}}
        b = {"GER": {"n": "Rodan", "s": []}, "SOV": {"n": "Czarny", "s": []}}
        gid = self.add(self.t, {"GER": full_row()}, a, wall=1000)
        self.add(self.t + 10, {"GER": full_row()}, b, wall=1600, still=120)
        self.add(self.t + 20, {"GER": full_row()}, a, wall=2200)
        self.add(self.t + 30, {"GER": full_row()}, a, wall=9000)   # next evening
        out = ic_history.sessions(self.history.game(gid))
        first, second = out["sessions"]
        self.assertEqual((first["minutes"], first["days"], first["stopped_minutes"]), (20.0, 20, 2.0))
        self.assertEqual(first["days_per_hour"], 60.0)
        self.assertEqual([j["name"] for j in first["joined"]], ["Czarny"])
        self.assertEqual([j["name"] for j in first["left"]], ["Czarny"])
        self.assertEqual(second["minutes"], 0)
        rodan = next(p for p in out["players"] if p["name"] == "Rodan")
        self.assertEqual((rodan["sessions"], rodan["minutes"]), (2, 20.0))

    def test_map_rows_are_changes_and_cut_with_replayed_days(self):
        gid = self.add(self.t, {"GER": full_row()})
        self.history.add_map(gid, self.t, {1: ["GER", "GER"], 2: ["POL", "POL"]}, True)
        self.history.add_map(gid, self.t + 5, {2: ["POL", "GER"]}, False)
        self.assertEqual(self.history.map_states(gid), {"1": ["GER", "GER"], "2": ["POL", "GER"]})
        self.assertEqual(self.history.map_states(gid, self.t + 1)["2"], ["POL", "POL"])
        self.add(self.t + 6, {"GER": full_row()})
        self.history.request(gid)
        self.add(self.t + 3, {"GER": full_row()})   # an earlier save loaded into the same file
        self.assertEqual(self.history.map_states(gid)["2"], ["POL", "POL"])

    def test_notes(self):
        gid = self.add(self.t, {"GER": full_row()})
        self.history.set_note(gid, self.t, "ITA betrayed us")
        [note] = self.history.set_note(gid, self.t + 2, "second", None)[1:]
        self.assertEqual(note["id"], 2)
        self.assertEqual([n["text"] for n in self.history.set_note(gid, self.t, "", 1)], ["second"])   # deleted
        with self.assertRaises(ValueError):
            self.history.set_note(gid, self.t, "  ")


class MapLive(FakeLive):
    def __init__(self):
        super().__init__()
        self.control = {1: ["SOV", "SOV"], 2: ["FIN", "FIN"]}
        self.front = {}   # provinces off their state's controller
        self.units = {100: {"SOV": [2, 50, 200, {"Rifle": 2}]}, 200: {"FIN": [1, 40, 100, {"Jalkav": 1}]}}
        self.hours = None
        self.infra_days = []

    def game_hours(self):
        return self.hours if self.hours is not None else self.t * 24

    def ic_snapshot(self, with_factions, with_infra=False):
        s = super().ic_snapshot(with_factions)
        self.infra_days.append(with_infra)
        infra = {"r": {"1-2": 2}, "b": {"53": [0, 2, 0, 1]}} if with_infra else None
        return {**s, "extra": {"SOV": extra(stab=55.5, divs=300)}, "units": dict(self.units), "infra": infra,
                "map": {"states": dict(self.control), "provinces": dict(self.front)},
                "casualties": {"SOV": {"FIN": (100 * (self.t % 1000), 50)}}}


class RecorderCampaignTest(unittest.TestCase):
    def test_fast_game_gets_the_map_between_full_days(self):
        """A game day in 0.25 s, the full reading 1 s: full days every FAST_FULL_EVERY days, the map in between."""
        live = MapLive()
        clock = [0.0]
        snap = live.ic_snapshot

        def full(f, i=False):
            s = snap(f, i)
            clock[0] += 1.0                      # the reading takes a second: 4 game days pass meanwhile
            live.t += 4
            return s
        frames = []

        def frame(with_map=False):
            frames.append(with_map)
            return {"t": live.t, "hour": 0, "units": dict(live.units), "front": {}, "divs": None,
                    "map": {"states": dict(live.control), "provinces": {}} if with_map else None}
        live.ic_snapshot, live.frame_snapshot = full, frame
        history = IcHistory(Path(tempfile.mkdtemp()))
        rec = IcRecorder(live, history, logging.getLogger("test"))
        rec.monotonic = lambda: clock[0]
        rec.step()
        for _ in range(60):
            clock[0] += 0.25
            live.t += 1
            live.control[2] = ["FIN", "SOV" if live.t % 2 else "FIN"]   # the front moves every day
            rec.step()
        gid = history.active
        days = history.game(gid)["t"]
        map_days = [r["t"] for r in history.map_rows(gid)]
        self.assertTrue(rec.fast())
        self.assertTrue(all(b - a >= ic_history.FAST_FULL_EVERY for a, b in zip(days[1:], days[2:])), days)
        self.assertTrue(all(frames))                    # light readings only, nothing within a day
        self.assertLessEqual(max(b - a for a, b in zip(map_days, map_days[1:])), 5)   # was the 4-5 days of a reading
        self.assertGreater(len(map_days), 3 * len(days))

    def test_slow_game_reads_every_day_in_full(self):
        live = MapLive()
        clock = [0.0]
        snap = live.ic_snapshot

        def full(f, i=False):
            clock[0] += 1.0
            return snap(f, i)
        live.ic_snapshot = full
        rec = IcRecorder(live, IcHistory(Path(tempfile.mkdtemp())), logging.getLogger("test"))
        rec.monotonic = lambda: clock[0]
        rec.step()
        for _ in range(10):
            clock[0] += 3.0          # a day in 3 s (+ the reading)
            live.t += 1
            self.assertTrue(rec.step())
        self.assertFalse(rec.fast())

    def test_divisions_one_by_one_and_their_history(self):
        live = MapLive()
        day = {"n1": ["SOV", "1st Rifle", "Rifle"], "p1": [100, 0], "s1": [50, 200, 100, 9000, 5, 100], "e1": {"inf": 900},
               "n2": ["FIN", "Jalkav 1", "Jalkav"], "p2": [200, 0], "s2": [40, 100, 50, 5000, 2, 90], "e2": {}}
        live.days = dict(day)
        snap = live.ic_snapshot
        live.ic_snapshot = lambda f, i=False: {**snap(f, i), "divs": dict(live.days), "templates": {"SOV|Rifle": {"b": ["infantry"]}}}
        live.frame_snapshot = lambda: {"t": live.t, "hour": live.hours % 24, "units": dict(live.units), "front": {},
                                       "divs": dict(live.moving)}
        history = IcHistory(Path(tempfile.mkdtemp()))
        rec = IcRecorder(live, history, logging.getLogger("test"))
        rec.step()
        live.t += 1
        live.hours = live.t * 24
        self.assertTrue(rec.step())
        live.moving = {"n1": ["SOV", "1st Rifle", "Rifle"], "p1": [100, 200]}   # 6 hours: 1 attacks, 2 is gone
        live.hours += 6
        rec.step()
        gid, t = history.active, live.t
        rows = history.delta_rows("divs", gid)
        self.assertEqual([(r.get("h"), r["u"]) for r in rows[1:]],
                         [(6, {"p1": [100, 200], "n2": None, "p2": None, "s2": None, "e2": None})])   # stats kept
        self.assertEqual(history.delta_at("divs", gid, t + 0.1), day)
        self.assertEqual(sorted(history.delta_at("divs", gid, t + 0.3)), ["e1", "n1", "p1", "s1"])
        self.assertEqual(history.key_history("divs", gid, ["n2", "p1"]),
                         [[t, "n", day["n2"]], [t, "p", [100, 0]], [t + 0.25, "n", None], [t + 0.25, "p", [100, 200]]])
        self.assertEqual(history.delta_rows("tmpl", gid)[0]["u"], {"SOV|Rifle": {"b": ["infantry"]}})

    def test_divisions_moves_and_battles_every_six_game_hours(self):
        live = MapLive()
        live.fight = {"m100-200": {"SOV": 2}, "c200": ["SOV", "FIN", 2, 1, 70]}
        live.frame_snapshot = lambda: {"t": live.t, "hour": live.hours % 24, "units": dict(live.units),
                                       "front": dict(live.fight)}
        snap = live.ic_snapshot
        live.ic_snapshot = lambda f, i=False: {**snap(f, i), "front": dict(live.fight), "hour": 0}
        history = IcHistory(Path(tempfile.mkdtemp()))
        rec = IcRecorder(live, history, logging.getLogger("test"))
        rec.step()
        live.t += 1
        live.hours = live.t * 24
        self.assertTrue(rec.step())   # the day: everything at hour 0
        live.hours += 3
        rec.step()                    # 3 hours later: nothing yet
        live.units = {100: {"SOV": [2, 30, 190, {"Rifle": 2}]}, 200: {"FIN": [1, 40, 100, {"Jalkav": 1}]}}
        live.hours += 3
        rec.step()                    # 6 hours: the battle goes on; only organisation and strength changed
        live.units = {200: {"FIN": [1, 20, 90, {"Jalkav": 1}], "SOV": [2, 30, 190, {"Rifle": 2}]}}
        live.fight = {"c200": ["SOV", "FIN", 2, 1, 85]}
        live.hours += 6
        rec.step()                    # 12 hours: SOV moved in
        gid = history.active
        units = history.units_rows(gid)
        self.assertEqual([(r.get("h"), sorted(r["u"])) for r in units], [(None, ["100", "200"]), (12, ["100", "200"])])
        self.assertEqual(units[1]["u"]["100"], None)
        front = history.delta_rows("front", gid)
        self.assertEqual([(r.get("h"), r["u"]) for r in front],
                         [(None, {"m100-200": {"SOV": 2}, "c200": ["SOV", "FIN", 2, 1, 70]}),
                          (12, {"m100-200": None, "c200": ["SOV", "FIN", 2, 1, 85]})])
        live.units = {200: {"FIN": [1, 15, 90, {"Jalkav": 1}], "SOV": [2, 30, 190, {"Rifle": 2}]}}
        live.hours += 6
        rec.step()                    # 18 hours: organisation only - not within a day
        live.t += 1
        live.hours = live.t * 24
        self.assertTrue(rec.step())   # the next day: organisation and strength again
        self.assertEqual([(r.get("h"), r["u"]) for r in history.units_rows(gid)[2:]], [(None, {"200": live.units[200]})])

    def test_extra_values_map_changes_and_stopped_time(self):
        live = MapLive()
        history = IcHistory(Path(tempfile.mkdtemp()))
        rec = IcRecorder(live, history, logging.getLogger("test"))
        clock = [0.0]
        rec.monotonic = lambda: clock[0]
        rec.wall = lambda: 5000 + clock[0]
        rec.step()
        live.t += 1
        self.assertTrue(rec.step())
        clock[0] = 10                     # the same hour for 10 s: paused
        rec.step()
        live.control[2] = ["FIN", "SOV"]
        live.front = {512: "FIN"}
        live.units = {100: {"SOV": [1, 50, 200, {"Rifle": 1}]}, 300: {"SOV": [1, 45, 190, {"Rifle": 1}]}}
        live.t += 1
        clock[0] = 11
        self.assertTrue(rec.step())
        game = history.game(history.active)
        self.assertEqual(game["countries"]["SOV"]["stab"], [55.5, 55.5])
        self.assertEqual(game["countries"]["SOV"]["divs"], [300, 300])
        self.assertEqual(game["countries"]["SOV"]["mpl"], [None, 100])   # unknown the first day, then the growth
        self.assertEqual(game["countries"]["SOV"]["mpk"], [None, 0])
        self.assertEqual(game["still"], [0, 11])
        rows = history.map_rows(history.active)
        self.assertEqual([r.get("full") for r in rows], [1, None])
        self.assertEqual(rows[1]["s"], {"2": ["FIN", "SOV"]})
        self.assertEqual([r.get("x") for r in rows], [{}, {"512": "FIN"}])   # all of them, only when changed
        units = history.units_rows(history.active)   # all the first day, then the changed provinces (null: left)
        self.assertEqual([(r.get("full"), sorted(r["u"])) for r in units], [(1, ["100", "200"]), (None, ["100", "200", "300"])])
        self.assertEqual((units[1]["u"]["200"], units[1]["u"]["300"]), (None, {"SOV": [1, 45, 190, {"Rifle": 1}]}))
        self.assertEqual(live.infra_days, [True, False])   # railways and buildings every INFRA_EVERY days
        self.assertEqual(history.delta_rows("infra", history.active), [{"t": rows[0]["t"], "u": {"r1-2": 2, "b53": [0, 2, 0, 1]},
                                                                         "full": 1}])
