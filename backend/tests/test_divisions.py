import tempfile
import unittest
from pathlib import Path

from hoi4dbg import divisions, doctrines

UNITS = """sub_units = {
    infantry = { categories = { category_light_infantry category_all_infantry } combat_width = 2 max_strength = 25
        max_organisation = 60 default_morale = 0.3 manpower = 1000 training_time = 90 suppression = 1.5 weight = 0.5
        supply_consumption = 0.06 need = { infantry_equipment = 100 } }
    field_hospital = { affects_speed = no max_strength = 2 max_organisation = 20 default_morale = 0.3 manpower = 500
        weight = 0.1 supply_consumption = 0.05 casualty_trickleback = 0.2
        battalion_mult = { category = category_all_infantry max_strength = 0.10 } need = { support_equipment = 30 } }
    logistics_company = { affects_speed = no max_strength = 1 max_organisation = 10 default_morale = 0.3 manpower = 500
        weight = 0.1 supply_consumption_factor = -0.1 need = { support_equipment = 20 } }
    anti_air_battery = { affects_speed = no categories = { category_anti_air } max_strength = 0.1 default_morale = 0.1
        manpower = 180 weight = 0.1 supply_consumption = 0.06 defense = -0.6 breakthrough = -0.6 soft_attack = -0.6
        hard_attack = -0.6 air_attack = -0.6 need = { anti_air_equipment = 16 } }
}"""
TECHS = """technologies = {
    antiair1 = { category_anti_air = { air_attack = 0.2 } }
    infantry_weapons2 = { category_light_infantry = { soft_attack = 0.05 } }
    not_researched = { category_light_infantry = { soft_attack = 5 } }
}"""
SUBDOCTRINES = """commandos = { track = infantry name = SUBDOCTRINE_COMMANDOS
    logistics_company = { battalion_mult = { category = category_light_infantry max_strength = 5 add = yes } }
    rewards = { a = { category_light_infantry = { reliability = 0.05 } }
                b = { logistics_company = { battalion_mult = { category = category_all_infantry defense = 0.1 } } } }
}"""


class DivisionDesignerTest(unittest.TestCase):
    def setUp(self):
        root = Path(tempfile.mkdtemp())
        (root / "common" / "units").mkdir(parents=True)
        (root / "common" / "technologies").mkdir(parents=True)
        (root / "common" / "doctrines" / "subdoctrines").mkdir(parents=True)
        (root / "common" / "doctrines" / "grand_doctrines").mkdir(parents=True)
        (root / "common" / "units" / "u.txt").write_text(UNITS, encoding="utf-8")
        (root / "common" / "technologies" / "t.txt").write_text(TECHS, encoding="utf-8")
        (root / "common" / "doctrines" / "grand_doctrines" / "g.txt").write_text(
            "grand_battleplan = { folder = land name = GRAND_DOCTRINE_GRAND_BATTLEPLAN tracks = { infantry } }",
            encoding="utf-8")
        (root / "common" / "doctrines" / "subdoctrines" / "s.txt").write_text(SUBDOCTRINES, encoding="utf-8")
        self.roots = (str(root),)
        self.tabs = divisions.tables(self.roots)
        self.equipment = {   # designs from game memory (bonuses included)
            "infantry_equipment": {"defense": 28.98, "breakthrough": 4.24, "soft_attack": 10.215, "hard_attack": 1.875,
                                   "ap_attack": 5.0, "maximum_speed": 4.0, "reliability": 0.972},
            "anti_air_equipment": {"defense": 4.0, "breakthrough": 1.1, "soft_attack": 3.85, "hard_attack": 11.44,
                                   "air_attack": 26.0, "ap_attack": 60.0, "maximum_speed": 4.0, "reliability": 0.84},
            "support_equipment": {"reliability": 0.8},
        }

    def stats(self, rewards):
        state = [{"grand": "GRAND_DOCTRINE_GRAND_BATTLEPLAN", "tracks": [{"sub": "SUBDOCTRINE_COMMANDOS", "rewards": rewards}]}]
        mods, mults = divisions.bonuses(self.tabs, ["antiair1", "infantry_weapons2"], state,
                                        doctrines.definitions(self.roots))
        template = {"battalions": ["infantry"] * 3, "support": ["field_hospital", "logistics_company"],
                    "regimental": ["anti_air_battery"]}
        return divisions.template_stats(template, self.tabs, self.equipment, mods, mults)

    def test_rules_found_in_the_designer(self):
        res = self.stats(rewards=2)
        s = res["stats"]
        # (25 + 5 commandos, added first) x 1.1 field hospital = 33 per infantry
        self.assertAlmostEqual(s["max_strength"], 3 * 33 + 2 + 1 + 0.1)
        # bonuses add to the sub-unit's own factor: battery 26 x (1 - 0.6 + 0.2) = 15.6
        self.assertAlmostEqual(s["air_attack"], 15.6)
        self.assertAlmostEqual(s["soft_attack"], 3 * 10.215 * 1.05 + 3.85 * 0.4)
        self.assertAlmostEqual(s["defense"], 3 * 28.98 * 1.1 + 4.0 * 0.4)   # reward b: +10% for infantry
        self.assertAlmostEqual(s["max_organisation"], (3 * 60 + 20 + 10) / 6)
        self.assertAlmostEqual(s["supply_consumption"], (3 * 0.06 + 0.05 + 0.06) * 0.9)
        self.assertAlmostEqual(s["ap_attack"], 0.4 * 60 + 0.6 * (3 * 5 + 60) / 6)
        self.assertEqual((s["maximum_speed"], s["combat_width"], s["manpower"], s["training_time"]), (4.0, 6.0, 4180.0, 90.0))
        self.assertAlmostEqual(s["reliability"], (3 * 1.0 + 0.8 + 0.8 + 0.84) / 6)   # infantry 0.972 + 0.05, capped
        self.assertEqual(res["missing_equipment"], [])

    def test_equipment_cost_column_and_production_cost_range(self):
        # POL Dywizja Piechoty (inf_pol.jpg) as 9 infantry + 1 hospital-like company: rifles 0.43 / 0.5, support 4
        template = {"battalions": ["infantry"] * 9, "support": ["field_hospital"], "regimental": []}
        costs = {"infantry_equipment": [0.43, 0.5], "support_equipment": [4.0]}
        res = divisions.equipment_cost(template, self.tabs, self.equipment, costs)
        self.assertEqual(res["equipment"], {"infantry_equipment": 900.0, "support_equipment": 30.0})
        self.assertEqual((res["cost_min"], res["cost_max"]), (507.0, 570.0))   # 900 x 0.43 + 120 / 900 x 0.5 + 120
        self.assertEqual((res["fuel_usage"], res["fuel_capacity"], res["no_design"]), (0.0, 0.0, []))
        trucks = {**self.equipment, "infantry_equipment": {**self.equipment["infantry_equipment"], "fuel_consumption": 1.2}}
        res = divisions.equipment_cost(template, self.tabs, trucks, {})
        self.assertEqual((res["fuel_usage"], res["fuel_capacity"]), (10.8, 1036.8))   # 9 x 1.2, 96 hours of it
        self.assertEqual((res["cost_min"], res["no_design"]), (0, ["infantry_equipment", "support_equipment"]))

    def test_locked_rewards_and_unknown_sub_units(self):
        s = self.stats(rewards=0)["stats"]
        self.assertAlmostEqual(s["defense"], 3 * 28.98 + 4.0 * 0.4)
        self.assertIsNone(divisions.template_stats({"battalions": ["mystery"], "support": [], "regimental": []},
                                                   self.tabs, self.equipment, [], []))


class DesignBonusTests(unittest.TestCase):
    def test_plane_design_takes_the_bonuses_of_its_role_categories(self):
        # FW 190 B (2026-10-20): air attack 56.7 / agility 49.5 in the design, 59.5 / 51.9 in the plane designer with
        # Airspace Dominance's loose formation (category_fighter +5 %); a CAS design keeps its own values
        units = {"fighter": {"need": {"small_plane_airframe": 1}, "cats": {"fighter", "category_fighter"}},
                 "cas": {"need": {"small_plane_cas_airframe": 1}, "cats": {"cas", "category_cas"}}}
        mods = [("category_fighter", "air_attack", 0.05), ("category_fighter", "air_agility", 0.05),
                ("category_fighter", "air_range", 0.1), ("infantry", "defense", 0.1)]
        role, stats, add = divisions.design_with_bonuses(units, mods, "small_plane_airframe_2",
                                                         {"air_attack": 56.7, "air_agility": 49.5, "range": 910, "air_defence": 19})
        self.assertEqual(role, "fighter")
        self.assertEqual((stats["air_attack"], stats["air_agility"], stats["range"], stats["air_defence"]), (59.535, 51.975, 1001.0, 19))
        self.assertEqual(add, {"air_attack": 0.05, "air_agility": 0.05, "range": 0.1})
        self.assertEqual(divisions.design_with_bonuses(units, mods, "small_plane_cas_airframe_1", {"air_attack": 3})[1:], ({"air_attack": 3}, {}))

    def test_tank_design_takes_its_role_factors_and_the_battalion_supply_and_suppression(self):
        # Sturer Emil Ausf. G (2026-10-20): hard attack 49.28 in the design, 73.9 in the tank designer = x (1 + 0 own +
        # 0.5 for category_tank_destroyers); production cost 29.36 as the game
        units = {"heavy_tank_destroyer_brigade": {"need": {"heavy_tank_destroyer_chassis": 40},
                                                  "cats": {"heavy_tank_destroyer_brigade", "category_tank_destroyers"},
                                                  "stats": {"breakthrough": -0.25, "ap_attack": 0.15, "supply_consumption": 0.3,
                                                            "suppression": 1.25}},
                 "heavy_tank_destroyer_support": {"need": {"heavy_tank_destroyer_chassis": 10}, "cats": {"x"}, "stats": {}}}
        mods = [("category_tank_destroyers", "hard_attack", 0.5), ("category_tank_destroyers", "breakthrough", 0.25)]
        role, stats, add = divisions.design_with_bonuses(units, mods, "heavy_tank_destroyer_chassis_1",
                                                         {"hard_attack": 49.28, "breakthrough": 53.625, "ap_attack": 125, "armor_value": 103})
        self.assertEqual(role, "heavy_tank_destroyer_brigade")
        self.assertEqual((stats["hard_attack"], stats["breakthrough"], stats["ap_attack"], stats["armor_value"]), (73.92, 53.625, 143.75, 103))
        self.assertEqual((stats["supply_consumption"], stats["suppression"]), (0.3, 1.25))
        self.assertEqual(add, {"ap_attack": 0.15, "hard_attack": 0.5})   # breakthrough: -0.25 own + 0.25 = no change
