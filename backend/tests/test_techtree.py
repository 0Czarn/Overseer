import unittest

from hoi4dbg import techtree
from hoi4dbg.saves import text

from helpers import TempDirMixin

TAGS = """technology_folders = {
    infantry_folder = { ledger = army }
    armour_folder = { ledger = army available = { NOT = { has_dlc = "No Step Back" } } }
    nsb_armour_folder = { ledger = army available = { has_dlc = "No Step Back" } }
    special_forces_doctrine_folder = { available = { OR = { has_dlc = "Arms Against Tyranny" has_dlc = "X" } }
        ledger = hidden doctrine = yes }
    land_doctrine_folder = { ledger = army doctrine = yes }
    mod_folder = { ledger = army available = { has_country_flag = something } }
}
"""


class TechTreeTests(TempDirMixin, unittest.TestCase):
    def test_tabs_follow_owned_dlcs(self):
        (self.tmp / "common" / "technology_tags").mkdir(parents=True)
        (self.tmp / "common" / "technology_tags" / "00_technology.txt").write_text(TAGS, encoding="utf-8")
        techtree.folders.cache_clear()
        techtree.tab_buttons.cache_clear()
        roots = (str(self.tmp),)
        tabs = techtree.research_tabs(roots, {"No Step Back"}, {"infantry_folder": 43})
        self.assertEqual([(t["id"], t["condition"], t["technologies"]) for t in tabs], [
            ("infantry_folder", "always", 43), ("nsb_armour_folder", "dlc", 0), ("mod_folder", "unknown", 0)])
        without = techtree.research_tabs(roots, set(), {})
        self.assertEqual([t["id"] for t in without], ["infantry_folder", "armour_folder", "mod_folder"])

    def test_tab_buttons_from_the_gui(self):
        (self.tmp / "interface").mkdir()
        (self.tmp / "interface" / "countrytechtreeview.gui").write_text(
            'containerWindowType = { name = "folder_tabs"\n'
            '  buttonType = { name = "infantry_folder_tab" position = { x = 22 y = 0 }\n'
            '    quadTextureSprite = "GFX_infantry_folder_tab" frame = 1 }\n'
            '  buttonType = { position = { x = 645 y = 0 } name = "electronics_folder_tab"\n'
            '    quadTextureSprite = "GFX_techtree_engineering_tab" }\n'
            '  buttonType = { name = "close_button" quadTextureSprite = "GFX_closebutton" } }\n', encoding="utf-8")
        techtree.tab_buttons.cache_clear()
        self.assertEqual(techtree.tab_buttons((str(self.tmp),)), {
            "infantry_folder": {"sprite": "GFX_infantry_folder_tab", "x": 22},
            "electronics_folder": {"sprite": "GFX_techtree_engineering_tab", "x": 645}})

    def test_trigger(self):
        block = text.parse('available = { OR = { has_dlc = "A" AND = { has_dlc = "B" NOT = { has_dlc = "C" } } } }')
        avail = text.get(block, "available")
        self.assertTrue(techtree.trigger(avail, {"A"}))
        self.assertTrue(techtree.trigger(avail, {"B"}))
        self.assertFalse(techtree.trigger(avail, {"B", "C"}))
        self.assertIsNone(techtree.trigger(text.get(text.parse("a = { tag = SOV }"), "a"), set()))

    def test_owned_dlcs_skip_disabled(self):
        install, user = self.tmp / "game", self.tmp / "user"
        for folder, name in (("dlc034_no_step_back", "No Step Back"), ("dlc023_man_the_guns", "Man the Guns")):
            (install / "dlc" / folder).mkdir(parents=True)
            (install / "dlc" / folder / f"{folder}.dlc").write_text(f'name = "{name}"\n', encoding="utf-8")
        user.mkdir()
        (user / "dlc_load.json").write_text('{"disabled_dlcs":["dlc/dlc023_man_the_guns/dlc023_man_the_guns.dlc"]}',
                                           encoding="utf-8")
        self.assertEqual(techtree.owned_dlcs(install, user), {"No Step Back"})
        self.assertEqual(techtree.owned_dlcs(install, None), {"No Step Back", "Man the Guns"})


if __name__ == "__main__":
    unittest.main()
