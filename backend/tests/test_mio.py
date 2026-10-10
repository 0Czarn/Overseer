import tempfile
import unittest
from pathlib import Path

from hoi4dbg import mio
from hoi4dbg.saves import politics, text

ORGS = """generic_tank_organization = {
    allowed = { always = yes }
    equipment_type = { armor }
    initial_trait = { name = generic_tank_initial production_bonus = { production_capacity_factor = 0.05 } }
    trait = { token = t1 equipment_bonus = { reliability = 0.05 } }
    trait = { token = t2 any_parent = { t1 } production_bonus = { production_cost_factor = -0.04 } }
    trait = { token = t3 any_parent = { t1 } equipment_bonus = { soft_attack = 0.1 } }
}
SOV_kirov_organization = {
    include = generic_tank_organization
    icon = GFX_idea_SOV_kirov
    override_trait = { token = t1 equipment_bonus = { reliability = 0.1 } }
    remove_trait = { t3 }
    add_trait = { token = sov_extra organization_modifier = { military_industrial_organization_research_bonus = 0.05 } }
}
CZE_bmm_organization = { include = CZE_td allowed = { always = yes } }
CZE_td = { equipment_type = { light_tank_destroyer_chassis } }
generic_escort_ship_organization = { equipment_type = { screen_ship } }
generic_infantry_equipment_organization = { equipment_type = { infantry_equipment mio_cat_eq_only_light_fighter } }
"""
POLICIES = "mio_policy_general_ruthless_contracts = { organization_modifier = { military_industrial_organization_funds_gain = 0.2 } }\n"


class MioTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        base = root / "common" / "military_industrial_organization"
        (base / "organizations").mkdir(parents=True)
        (base / "policies").mkdir()
        (base / "organizations" / "x.txt").write_text(ORGS, encoding="utf-8")
        (base / "policies" / "p.txt").write_text(POLICIES, encoding="utf-8")
        mio.definitions.cache_clear()
        self.defs = mio.definitions((str(root),))

    def tearDown(self):
        self._tmp.cleanup()

    def test_include_override_remove_add(self):
        r = mio.resolve(self.defs, "SOV_kirov_organization")
        self.assertEqual(sorted(r["traits"]), ["sov_extra", "t1", "t2"])
        self.assertEqual(r["traits"]["t1"]["equipment_bonus"], {"reliability": 0.1})
        self.assertEqual((r["category"], r["icon"]), ("tank_manufacturer", "GFX_idea_SOV_kirov"))

    def test_categories(self):
        self.assertEqual(mio.resolve(self.defs, "CZE_bmm_organization")["category"], "tank_manufacturer")   # not a destroyer
        self.assertEqual(mio.resolve(self.defs, "generic_escort_ship_organization")["category"], "naval_manufacturer")
        self.assertEqual(mio.resolve(self.defs, "generic_infantry_equipment_organization")["category"], "materiel_manufacturer")

    def test_current_bonuses_from_initial_and_unlocked_traits_and_policy(self):
        s = mio.summary({"id": "SOV_kirov_organization", "size": 2, "traits": ["t1", "t2", "unknown"],
                         "policy": "mio_policy_general_ruthless_contracts"}, self.defs)
        self.assertEqual([t["token"] for t in s["traits"]], ["t1", "t2"])
        self.assertEqual(s["bonuses"], {
            "equipment_bonus": {"reliability": 0.1},
            "production_bonus": {"production_capacity_factor": 0.05, "production_cost_factor": -0.04},
            "organization_modifier": {"military_industrial_organization_funds_gain": 0.2}})
        self.assertIsNone(mio.summary({"id": "removed_organization"}, self.defs))

    def test_save_mios_binary_and_text_shapes(self):
        binary_like = [("production", [("industrial_organisations", [("SOV_kirov_organization", [
            ("size", "2"), ("funds", "6115.7"), ("icon", "GFX_idea_SOV_kirov"),
            ("mio_unlocked_trait", [("mio_trait", "t1")]), ("mio_unlocked_trait", [("mio_trait", "t2")]),
            ("#4007", [("mio_trait", "t3")]), ("mio_policy", "mio_policy_general_ruthless_contracts")])])])]
        m = politics.mios_of(binary_like)[0]
        self.assertEqual((m["size"], m["traits"], m["policy"]), (2, ["t1", "t2"], "mio_policy_general_ruthless_contracts"))
        text_like = text.parse("production={ industrial_organisations={ SOV_kirov_organization={ size=2 "
                               "x={ trait=t3 } y={ trait=t1 } y={ trait=t2 } } } }")
        self.assertEqual(politics.mios_of(text_like)[0]["traits"], ["t1", "t2"])   # the key repeated `size` times


if __name__ == "__main__":
    unittest.main()
