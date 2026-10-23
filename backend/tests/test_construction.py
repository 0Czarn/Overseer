import unittest

from hoi4dbg import construction


class ConstructionRowsTest(unittest.TestCase):
    def test_next_complete_like_the_game(self):
        # SOV 27 Sep 1941 (day 269): Krasnoyarsk 6309.79 / 7200 at 183.75 a day - game tooltip "Next complete 2 Oct, 1941"
        line = {"id": 2, "kind": "building", "building": "arms_factory", "location": 1, "path": [], "levels": 1,
                "repair": 0, "factories": 15, "cost": 7200.0, "speed": 183.75, "produced": 6309.79}
        waiting = {**line, "factories": 0, "speed": 0.0, "produced": 0.0}
        rows = construction.rows([line, waiting], {"arms_factory": "Military Factory"}, {"STATE_1": "Krasnoyarsk"}, 15,
                                 {"year": 1941, "day": 269, "hour": 0})
        self.assertEqual((rows[0]["name"], rows[0]["state_name"], rows[0]["days_left"]), ("Military Factory", "Krasnoyarsk", 5))
        self.assertEqual(rows[0]["next_complete"]["text"], "2 Oct, 1941")
        self.assertAlmostEqual(rows[0]["progress"], 6309.79 / 7200)
        self.assertEqual((rows[1]["position"], rows[1]["days_left"], rows[1]["next_complete"]), (2, None, None))

    def test_repairs_and_province_buildings(self):
        # SOV 1941: rail_way in province 288 (Bryansk) to repair; GER railway along provinces of two states
        repair = {"id": 1, "kind": "building", "building": "rail_way", "location": 288, "path": [], "levels": 0,
                  "repair": 1, "factories": 0, "cost": 430.0, "speed": 0.0, "produced": 0.0}
        railway = {**repair, "kind": "railway", "location": None, "path": [11370, 9304], "levels": 3, "repair": 0}
        fort = {**repair, "building": "bunker", "location": 310, "levels": 1, "repair": 1}
        defs = {"rail_way": {"provincial": True}, "bunker": {"provincial": True}}
        names = {"STATE_5": "Bryansk", "STATE_6": "Kharkov", "STATE_7": "Latgale"}
        rows = construction.rows([repair, railway, fort], {}, names, 15, None, defs,
                                 {288: 5, 11370: 5, 9304: 6, 310: 7}, {11370: "Bizerte"})
        self.assertEqual([(r["action"], r["state_name"], r["province"], r["end_state_name"]) for r in rows], [
            ("repair", "Bryansk", 288, None), ("build", "Bryansk", 11370, "Kharkov"), ("build_repair", "Latgale", 310, None)])
        # railway ends named like the game: province name, else its state ("Tunis - Tunisia")
        self.assertEqual([r["place"] for r in rows], [None, "Bizerte - Kharkov", None])

    def test_civilian_factories_closest_to_completion_first(self):
        # civ_przed.png -> civ_po.png: the civilian factory with the most progress goes on top; repairs, military
        # factories and railways keep their order below
        def line(building, produced, levels=1, kind="building"):
            return {"kind": kind, "building": building, "levels": levels, "produced": produced, "cost": 10800.0}
        lines = [line("arms_factory", 7000), line("industrial_complex", 1000), line("industrial_complex", 0, levels=0),
                 line("industrial_complex", 9000), line("rail_way", 0, kind="railway"), line("industrial_complex", 1000)]
        self.assertEqual(construction.civilian_first_order(lines), [3, 1, 5, 0, 2, 4])
        self.assertEqual(construction.civilian_first_order([line("industrial_complex", 9000)]), [0])
        # the military auto-sort: military factories (arms_factory) by progress on top, civilian ones keep their order
        lines.append(line("arms_factory", 9500))
        self.assertEqual(construction.factory_first_order(lines, "mil"), [6, 0, 1, 2, 3, 4, 5])

    def test_date_over_the_year_end(self):
        # day 360 = 27 Dec (no leap years)
        self.assertEqual(construction.game_date_after({"year": 1941, "day": 360}, 10)["text"], "6 Jan, 1942")


if __name__ == "__main__":
    unittest.main()


class ForecastTest(unittest.TestCase):
    def line(self, building="industrial_complex", levels=1, cost=100.0, produced=0.0, speed=0.0, factories=0, repair=0):
        return {"building": building, "levels": levels, "cost": cost, "produced": produced, "speed": speed,
                "factories": factories, "repair": repair}

    def test_queue_played_forward_with_new_civilian_factories(self):
        lines = [self.line(levels=2, speed=50.0, factories=10),          # 5 a day per factory
                 self.line("arms_factory", levels=1, cost=100.0)]          # waits for factories
        out = construction.forecast(lines, free=10, counts={"civ": 30, "mil": 20, "dock": 5}, max_factories=15)
        self.assertEqual(out["levels"][0], [2, 4])    # 10 factories x 5 = 50 a day, a level costs 100
        self.assertEqual(out["lines"][0], 4)
        self.assertEqual(out["lines"][1], 6)          # 12 factories (10 + 2 new) x 5 a day after the first line
        self.assertEqual(out["factories"][90], {"civ": 32, "mil": 21, "dock": 5})

    def test_repairs_add_no_factory_and_unknown_speed_uses_the_mean(self):
        lines = [self.line(levels=0, repair=1, speed=20.0, factories=4), self.line(levels=1)]
        out = construction.forecast(lines, free=15, counts={"civ": 10}, max_factories=15)
        self.assertEqual(out["lines"], [2, 4])        # 15 x 5 = 75 a day, one line after the other (mean speed of the working line)
        self.assertEqual(out["factories"][90]["civ"], 11)

    def test_nothing_is_built_without_free_factories(self):
        out = construction.forecast([self.line()], free=0, counts={"civ": 5})
        self.assertEqual(out["lines"], [None])
        self.assertEqual(out["factories"][365], {"civ": 5})


class WhereToBuildTest(unittest.TestCase):
    def test_free_slots_of_owned_controlled_states(self):
        defs = {"arms_factory": {"shares_slots": True}, "infrastructure": {"shares_slots": False}}
        states = [{"id": 1, "owner": "GER", "controller": "GER", "category": "city", "cores": ["GER"],
                   "buildings": {"arms_factory": 2, "infrastructure": 3}},
                  {"id": 2, "owner": "GER", "controller": "GER", "category": "city", "cores": [],
                   "buildings": {"infrastructure": 5}},
                  {"id": 3, "owner": "GER", "controller": "POL", "category": "city", "buildings": {}},
                  {"id": 4, "owner": "GER", "controller": "GER", "category": "rural", "buildings": {"arms_factory": 2}}]
        rows = construction.where_to_build(states, "GER", {"city": 6, "rural": 2}, defs, queued={1: 1})
        self.assertEqual([(r["id"], r["free"], r["infrastructure"], r["core"]) for r in rows], [(2, 6, 5, False), (1, 3, 3, True)])
