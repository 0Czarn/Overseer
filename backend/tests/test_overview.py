import tempfile
import unittest
from pathlib import Path

from hoi4dbg import government
from hoi4dbg.saves import politics, text

IDEOLOGIES = """ideologies = {
\tcommunism = {
\t\ttypes = { stalinism = { } marxism = { } }
\t\tcolor = { 255 0 0 }
\t}
\tdemocratic = { types = { liberalism = { } } color = { 0 0 255 } }
}
"""
TEMPLATE = "faction_template_comintern = {\n\tname = Comintern\n\ticon = GFX_faction_logo_comintern\n}\n"


class OverviewTests(unittest.TestCase):
    def test_ideology_colours_parents_and_faction_templates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "common" / "ideologies").mkdir(parents=True)
            (root / "common" / "factions" / "templates").mkdir(parents=True)
            (root / "common" / "ideologies" / "00_ideologies.txt").write_text(IDEOLOGIES)
            (root / "common" / "factions" / "templates" / "soviet.txt").write_text(TEMPLATE)
            government.ideologies.cache_clear()
            d = government.ideologies((tmp,))
        self.assertEqual(d["colors"], {"communism": (255, 0, 0), "democratic": (0, 0, 255)})
        self.assertEqual(d["parent"]["stalinism"], "communism")
        self.assertEqual(d["factions"]["faction_template_comintern"], {"name": "Comintern", "icon": "GFX_faction_logo_comintern"})

    def test_party_names_leader_ideology_and_faction_fields(self):
        block = text.parse("""politics={ parties={
            democratic={ popularity=10 }
            communism={ name="SOV_communism_party_russian" long_name="SOV_communism_party_russian_long" popularity=88
                country_leader={ { ideology="stalinism" character={ id=4352 type=73 } } } } }
            ruling_party=communism }""")
        faction = text.parse('faction={ members={ "SOV" "MON" } template="faction_template_comintern" icon="GFX_x" }')
        world = politics.world([text.get(faction, "faction")], None)
        s = politics.summary(block, None, "SOV", world)
        self.assertEqual((s["leader"], s["leader_ideology"]), ("4352", "stalinism"))
        self.assertEqual(s["party_names"]["communism"], {"name": "SOV_communism_party_russian",
                                                         "long_name": "SOV_communism_party_russian_long"})
        self.assertEqual(s["party_names"]["democratic"], {"name": None, "long_name": None})
        self.assertEqual((s["faction"]["template"], s["faction"]["leader"]), ("faction_template_comintern", True))


if __name__ == "__main__":
    unittest.main()
