import unittest

from hoi4dbg import government


DEFS = {
    "idea_meta": {
        "volunteer_only": {"category": "mobilization_laws", "law": True},
        "civilian_economy": {"category": "economy", "law": True},
        "GER_holzmann": {"category": "industrial_concern", "picture": "GER_holzmann_pic", "traits": ["railway_company"]},
        "special_law": {"category": "press_laws", "law": True},
        "sisu": {"category": "country"},
    },
    "idea_names": {}, "ideas": {"volunteer_only": {"conscription": 0.015}, "GER_holzmann": {"x": 1.0}},
    "traits": {"railway_company": {"production_speed_rail_way_factor": 0.1}, "kerrl": {"party_popularity_stability_factor": 0.1}},
}
STATE = {
    "ideas": ["volunteer_only", "civilian_economy", "GER_holzmann", "special_law", "sisu"],
    "advisors": [{"slot": "political_advisor", "id": "1"}, {"slot": "high_command", "id": "2"}],
    "characters": {
        "1": {"name": "GER_kerrl", "token": "GER_kerrl", "portraits": {"civilian": {"small": "GFX_kerrl_small"}},
              "advisors": [{"slot": "political_advisor", "idea_token": "GER_kerrl", "traits": ["kerrl"]}]},
        "2": {"name": "GER_schorner", "token": "GER_schorner",
              "portraits": {"civilian": {"large": "GFX_civ"}, "army": {"small": "GFX_army_small"}},
              "advisors": [{"slot": "high_command", "idea_token": "schorner", "traits": []}]},
    },
}


class GovernmentTests(unittest.TestCase):
    def setUp(self):
        self.s = government.sections(STATE, DEFS)

    def test_laws_in_game_order_with_empty_trade_law_and_extra_law_last(self):
        laws = [(i["slot"], i["kind"], i["id"]) for i in self.s["laws"]]
        self.assertEqual(laws[:4], [("mobilization_laws", "law", "volunteer_only"), ("trade_laws", "empty", None),
                                    ("economy", "law", "civilian_economy"), ("press_laws", "law", "special_law")])
        self.assertEqual([i["kind"] for i in self.s["laws"][4:]], ["advisor", "empty", "empty"])   # 3 political slots

    def test_company_modifiers_include_its_traits(self):
        company = next(i for i in self.s["research"] if i["kind"] == "company")
        self.assertEqual(company["modifiers"], {"production_speed_rail_way_factor": 0.1, "x": 1.0})
        self.assertEqual(company["icon"], "GFX_idea_GER_holzmann_pic")
        self.assertEqual(len(self.s["research"]), 6)   # 5 company categories + theorist

    def test_military_slots_and_portraits(self):
        mil = self.s["military"]
        self.assertEqual([i["slot"] for i in mil], ["army_chief", "navy_chief", "air_chief"] + ["high_command"] * 3)
        self.assertEqual(mil[3]["icon"], "GFX_army_small")                       # military portrait preferred
        self.assertEqual(self.s["laws"][4]["icon"], "GFX_kerrl_small")
        self.assertEqual(self.s["laws"][4]["modifiers"], {"party_popularity_stability_factor": 0.1})


if __name__ == "__main__":
    unittest.main()
