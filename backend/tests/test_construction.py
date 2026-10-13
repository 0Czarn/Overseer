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

    def test_date_over_the_year_end(self):
        # day 360 = 27 Dec (no leap years)
        self.assertEqual(construction.game_date_after({"year": 1941, "day": 360}, 10)["text"], "6 Jan, 1942")


if __name__ == "__main__":
    unittest.main()
