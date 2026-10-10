import unittest

from hoi4dbg import modifiers
from hoi4dbg.saves import politics

from helpers import TempDirMixin

# Shape of a real 1.19.3 text save (SOV, 1936): country block + character manager.
SAVE = b"""HOI4txt
player="SOV"
countries={
\tSOV={
\t\tdynamic_modifier={
\t\t\tmodifier={
\t\t\t\tmodifier="SOV_plan"
\t\t\t\tvalue={
\t\t\t\t\t-0.15 0.05
\t\t\t\t}
\t\t\t\tenabled=yes
\t\t\t}
\t\t}
\t\tcharacters={
\t\t\tappointed_advisors={
\t\t\t\t{
\t\t\t\t\tslot="political_advisor"
\t\t\t\t\tcharacter={ id=4432 type=73 }
\t\t\t\t}
\t\t\t}
\t\t}
\t\tpolitics={
\t\t\tparties={
\t\t\t\tdemocratic={
\t\t\t\t\tpopularity=12
\t\t\t\t}
\t\t\t\tcommunism={
\t\t\t\t\tpopularity=88
\t\t\t\t\tcountry_leader={
{
\t\t\t\t\t\t\tideology="stalinism"
\t\t\t\t\t\t\tcharacter={ id=4352 type=73 }
\t\t\t\t\t\t}
 \t\t\t\t\t}
\t\t\t\t}
\t\t\t}
\t\t\tideas={
\t\t\t\ttrotskyite_plot_nsb civilian_economy
\t\t\t}
\t\t\truling_party=communism
\t\t}
\t\tstability=0.7
\t\twar_support=0.3
\t\tmajor=yes
\t\tpride_of_the_fleet={ id=32 type=51 }
\t}
}
faction={
\tid={ id=3 type=88 }
\tmembers={
\t\t"SOV" "MON"
\t}
\trule_status={
\t\trules={
\t\t\tjoining_rule_communist_only\t\t\twar_declaration_rule_major_only\t\t\tunknown_condition_rule\t\t}
\t}
}
character_manager={
\thistorical={
\t\tcharacter={
\t\t\tid={ id=4352 type=73 }
\t\t\ttoken="SOV_iosif_stalin"
\t\t\tname="SOV_iosif_stalin"
\t\t\tcountry="SOV"
\t\t\tcountry_leaders={
\t\t\t\tcountry_leader={
\t\t\t\t\tideology=stalinism
\t\t\t\t\ttraits={ stalin_heart_of_steel }
\t\t\t\t}
\t\t\t}
\t\t}
\t\tcharacter={
\t\t\tid={ id=4432 type=73 }
\t\t\ttoken="SOV_genrikh_yagoda"
\t\t\tname="SOV_genrikh_yagoda"
\t\t\tcountry="SOV"
\t\t\tadvisors={
\t\t\t\tadvisor={
\t\t\t\t\tslot="political_advisor"
\t\t\t\t\tidea_token="SOV_genrikh_yagoda"
\t\t\t\t\ttraits={
"head_of_the_nkvd"
\t\t\t\t\t}
\t\t\t\t}
\t\t\t}
\t\t}
\t\tcharacter={
\t\t\tid={ id=1 type=73 }
\t\t\ttoken="GER_other"
\t\t\tcountry="GER"
\t\t}
\t}
}
rail_way={
}
threat={
	threat={
		value=4.815
		original=0
		tag="GER"
	}
}
"""

IDEAS = """ideas = {
\tcountry = {
\t\ttrotskyite_plot_nsb = {
\t\t\tname = trotskyite_plot
\t\t\tallowed = { always = no }
\t\t\tmodifier = { stability_factor = -0.2 political_power_factor = -0.15 }
\t\t}
\t}
\teconomy = {
\t\tlaw = yes
\t\tcivilian_economy = { modifier = { consumer_goods_factor = 0.35 } }
\t}
}
"""
TRAITS = """leader_traits = {
\tstalin_heart_of_steel = { random = no stability_factor = -0.1 war_support_factor = 0.05 }
\thead_of_the_nkvd = { sprite = 13 stability_factor = -0.05 }
}
"""
DYNAMIC = """SOV_plan = {
\tenable = { always = yes }
\ticon = GFX_x
\tstability_factor = SOV_var_a # evaluated value is in the save
\twar_support_factor = SOV_var_b
}
"""
DEFINES = ("NCountry = {\n\tBASE_STABILITY_PARTY_POPULARITY_FACTOR = 0.15,\n\tMAX_STABILITY = 1.0,\n"
           "\tWAR_SUPPORT_TENSION_IMPACT = 0.4,\t\t-- Total impact of world tension\n}\n")
RULES = """war_declaration_rule_major_only = {
\ttype = war_declaration_rules
\ttrigger = { is_major = yes }
\tmodifier = { war_support_factor = -0.05 stability_factor = -0.05 }
}
joining_rule_communist_only = { type = joining_rules }
unknown_condition_rule = { trigger = { has_war = yes } modifier = { stability_factor = 0.5 } }
"""
STATIC = "pride_of_the_fleet_country = {\n\twar_support_factor = 0.05\n}\n"


class ModifierTests(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        common = self.tmp / "game" / "common"
        for folder, name, content in (("ideas", "SOV.txt", IDEAS), ("country_leader", "00_traits.txt", TRAITS),
                                      ("dynamic_modifiers", "0.txt", DYNAMIC), ("defines", "00_defines.lua", DEFINES),
                                      ("factions/rules", "war.txt", RULES), ("modifiers", "00_static_modifiers.txt", STATIC)):
            (common / folder).mkdir(parents=True, exist_ok=True)
            (common / folder / name).write_text(content, encoding="utf-8")
        modifiers.definitions.cache_clear()
        self.defs = modifiers.definitions((str(self.tmp / "game"),))

    def test_save_summary(self):
        state = politics.read(SAVE, "text", None, None, {"SOV"})["SOV"]
        self.assertEqual(state["ideas"], ["trotskyite_plot_nsb", "civilian_economy"])
        self.assertEqual((state["ruling_party"], state["popularity"]["communism"]), ("communism", 88.0))
        self.assertEqual(state["leader"], "4352")
        self.assertEqual(state["advisors"], [{"slot": "political_advisor", "id": "4432"}])
        self.assertEqual(sorted(state["characters"]), ["4352", "4432"])   # GER character not included
        self.assertEqual(state["characters"]["4352"]["leader_traits"], ["stalin_heart_of_steel"])
        self.assertEqual(state["dynamic_modifiers"], [{"id": "SOV_plan", "values": ["-0.15", "0.05"], "enabled": True}])
        self.assertEqual((state["major"], state["pride_of_the_fleet"], state["tension"]), (True, True, 4.815))
        self.assertEqual(state["faction"]["members"], ["SOV", "MON"])
        self.assertTrue(state["faction"]["leader"])

    def test_breakdown_like_the_game_tooltip(self):
        state = politics.read(SAVE, "text", None, None, {"SOV"})["SOV"]
        names = {"trotskyite_plot": "Trotskyite Plot", "SOV_iosif_stalin": "Iosif Stalin",
                 "stalin_heart_of_steel": "Heart of Steel"}
        b = modifiers.breakdown(state, self.defs, names)
        st = b["stability"]
        self.assertEqual([(p["kind"], p["name"], p["value"]) for p in st["parts"]], [
            ("party", "Ruling party popularity (88%)", 0.132),
            ("idea", "Trotskyite Plot", -0.2),
            ("leader", "Iosif Stalin: Heart of Steel", -0.1),
            ("advisor", "SOV_genrikh_yagoda (political_advisor)", -0.05),
            ("dynamic", "SOV_plan", -0.15),
            ("faction", "war_declaration_rule_major_only", -0.05),
        ])
        self.assertAlmostEqual(st["total"], 0.7 + 0.132 - 0.2 - 0.1 - 0.05 - 0.15 - 0.05)
        ws = [(p["kind"], p["value"]) for p in b["war_support"]["parts"]]
        self.assertIn(("world", 0.01926), ws)          # 0.4 x 4.815 %: the +1.92 % the game showed
        self.assertIn(("static", 0.05), ws)            # Has Pride of The Fleet
        self.assertAlmostEqual(b["war_support"]["total"], 0.3 + 0.05 + 0.05 + 0.01926 + 0.05 - 0.05)
        self.assertEqual(b["unchecked_rules"], ["unknown_condition_rule"])   # condition not evaluated: not added

    def test_major_only_rule_skips_minor_members(self):
        state = {**politics.read(SAVE, "text", None, None, {"SOV"})["SOV"], "major": False}
        b = modifiers.breakdown(state, self.defs)
        self.assertNotIn("faction", [p["kind"] for p in b["stability"]["parts"]])

    def test_total_is_clamped(self):
        state = {"stability": 0.95, "war_support": 0.0, "popularity": {"a": 100.0}, "ruling_party": "a"}
        b = modifiers.breakdown(state, self.defs)
        self.assertEqual((b["stability"]["total"], b["stability"]["clamped"]), (1.0, True))

    def test_loc_keys_use_the_idea_name(self):
        state = politics.read(SAVE, "text", None, None, {"SOV"})["SOV"]
        keys = modifiers.loc_keys(state, self.defs)
        self.assertIn("trotskyite_plot", keys)
        self.assertIn("head_of_the_nkvd", keys)


if __name__ == "__main__":
    unittest.main()
