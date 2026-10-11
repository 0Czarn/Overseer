import unittest

from hoi4dbg.saves import politics, text

# Shape of the SOV 1936 country block (values from SOV_1936_03_12_01.hoi4)
BLOCK = """resources={
    produced={ oil=223 rubber=2 steel=593 }
    imported={ rubber=8 }
    to_use={ { oil=112 rubber=9 steel=297 } { } { rubber=-8 steel=-59 } }
    to_export={ oil=111 rubber=1 steel=296 }
    exported={ oil=111 steel=24 }
    export={ receiver="CHI" resource="oil" delivered=15 }
    export={ receiver="SIK" resource="steel" delivered=8 }
}"""


class ResourceTests(unittest.TestCase):
    def test_resources_of(self):
        r = politics.resources_of(text.parse(BLOCK))
        self.assertEqual(r["produced"]["steel"], 593.0)
        self.assertEqual((r["to_market"]["steel"], r["exported"]["steel"]), (296.0, 24.0))
        self.assertEqual((r["imported"]["rubber"], r["available"]["rubber"], r["used"]["rubber"]), (8.0, 9.0, 8.0))
        self.assertEqual(r["exports"], [{"receiver": "CHI", "resource": "oil", "amount": 15.0},
                                        {"receiver": "SIK", "resource": "steel", "amount": 8.0}])

    def test_missing_block(self):
        r = politics.resources_of([])
        self.assertEqual((r["produced"], r["used"], r["exports"]), ({}, {}, []))




class ResearchSaveTests(unittest.TestCase):
    def test_research_of(self):
        block = text.parse("""technology={ technologies={ basic_train={ level=1 } mechanical_computing={ research_points=12.5 } }
            slots={ empty={ points=30 } mechanical_computing={ used_saved_points=1 points_factor=1.08 } empty={ points=22 } } }""")
        empty = {"technology": None, "speed": None, "points": None}
        self.assertEqual(politics.research_of(block), [
            {"slot": 1, **empty}, {"slot": 2, "technology": "mechanical_computing", "speed": 1.08, "points": 12.5},
            {"slot": 3, **empty}])
        self.assertEqual(politics.research_of([]), [])

    def test_limited_bonuses_of(self):
        block = text.parse("""technology={ slots={ empty={ points=30 } }
            limited_use_bonus={ bonus=0.5 uses=1 id=1 name="SUBDOCTRINE_MOBILE_INFANTRY" category=motorized_equipment }
            limited_use_bonus={ bonus=1 uses=1 id=2 name="GER_the_four_year_plan" category=industry } }""")
        self.assertEqual(politics.limited_bonuses_of(block), [
            {"id": 1, "name": "SUBDOCTRINE_MOBILE_INFANTRY", "bonus": 0.5, "uses": 1, "categories": ["motorized_equipment"]},
            {"id": 2, "name": "GER_the_four_year_plan", "bonus": 1.0, "uses": 1, "categories": ["industry"]}])
        self.assertEqual(politics.limited_bonuses_of([]), [])

    def test_progress_like_the_game(self):
        # the user's game 1936.9.21 (day 263): excavation1 18.7 % / 146 days, interwar_artillery 24 % / 111 days,
        # antiair1 (start 1939, 2.28 years ahead) 5.5 % / 401 days
        from hoi4dbg.service import research_progress
        defines = {"BASE_TECH_COST": 110.0, "BASE_YEAR_AHEAD_PENALTY_FACTOR": 2.0}
        today = 1936 + 263 / 365
        exc = research_progress({"technology": "excavation1", "speed": 1.13, "points": 41.28, "bonus": 0.1},
                                {"cost": 2, "start_year": None}, defines, today)
        self.assertEqual((exc["cost"], exc["days_left"], exc["estimate"]), (220.0, 146, False))
        self.assertAlmostEqual(exc["progress"], 0.18764, places=5)
        art = research_progress({"technology": "interwar_artillery", "speed": 1.13, "points": 40.68, "bonus": 0.0},
                                {"cost": 1.5, "start_year": 1936}, defines, today)
        self.assertEqual((art["cost"], art["days_left"], art["ahead_years"]), (165.0, 111, None))
        aa = research_progress({"technology": "antiair1", "speed": 0.20327, "points": 6.0981, "bonus": 0.0},
                               {"cost": 1, "start_year": 1939}, defines, today, country_speed=1.13)
        self.assertEqual(aa["cost"], 110.0)                        # not increased ahead of time
        self.assertAlmostEqual(aa["progress"], 0.0554, places=4)   # game: 5.5 %
        self.assertAlmostEqual(aa["ahead_years"], 2.2795, places=4)
        self.assertEqual((aa["days_left"], aa["estimate"]), (401, False))   # game: 401
        # 18.5 days later the slot speed is unchanged (penalty of the start day); game: 8.9 %, 383 days
        later = research_progress({"technology": "antiair1", "speed": 0.20327, "points": 9.7917, "bonus": 0.0},
                                  {"cost": 1, "start_year": 1939}, defines, 1936 + 281.5 / 365, country_speed=1.13)
        self.assertEqual(later["days_left"], 383)
        self.assertAlmostEqual(later["progress"], 0.089, places=3)
        guessed = research_progress({"technology": "antiair1", "speed": 0.20327, "points": 9.7917, "bonus": 0.0},
                                    {"cost": 1, "start_year": 1939}, defines, 1936 + 281.5 / 365)
        self.assertTrue(guessed["estimate"])                       # no penalty-free slot: base speed guessed
        saved = research_progress({"technology": "x", "speed": 1.0, "points": 0.0}, {"cost": 1, "start_year": None},
                                  defines, today)
        self.assertTrue(saved["estimate"])                         # from a save: technology bonus unknown


if __name__ == "__main__":
    unittest.main()
