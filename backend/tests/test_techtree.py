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

    def test_layout_like_the_game(self):
        # infantry_folder: gridbox infantry_weapons_tree at 140/325, 70 px slots, LEFT; infantry_weapons1 y = @1936 = 2
        # -> x 280, under the "1936" label at 270 of the game's window
        (self.tmp / "interface").mkdir()
        (self.tmp / "interface" / "countrytechtreeview.gui").write_text(
            'guiTypes = {\n'
            '  containerWindowType = { name = "infantry_folder" position = { x = 0 y = 47 } size = { width = 100%% }\n'
            '    containerWindowType = { name = "techtree_stripes" position = { x = 0 y = 0 }\n'
            '      instantTextBoxType = { name = "infantry_year3" position = { x = 270 y = 50 } font = "hoi_36header" text = "1936" } }\n'
            '    gridboxtype = { name = "infantry_weapons_tree" position = { x = 140 y = 325 }\n'
            '      slotsize = { width = 70 height = 70 } format = "LEFT" } }\n'
            '  containerWindowType = { name = "techtree_infantry_folder_item" position = { x = -56 y = -7 }\n'
            '    size = { width = 183 height = 84 } }\n}\n', encoding="utf-8")
        techtree._gui.cache_clear()
        layout = techtree.folder_layout((str(self.tmp),), "infantry_folder")
        self.assertEqual(layout["grids"]["infantry_weapons_tree"],
                         {"x": 140.0, "y": 325.0, "w": 70.0, "h": 70.0, "format": "LEFT"})
        self.assertEqual(layout["labels"], [{"text": "1936", "x": 270.0, "y": 50.0, "size": 36}])
        self.assertEqual(layout["big"], {"dx": -56.0, "dy": -7.0, "w": 183.0, "h": 84.0})
        self.assertEqual(layout["small"], {"dx": 0, "dy": 0, "w": 72, "h": 72})   # template missing: game default
        grid = layout["grids"]["infantry_weapons_tree"]
        self.assertEqual(techtree.place((0, 2), grid), (280.0, 325.0))
        self.assertEqual(techtree.place((1, 2), {**grid, "format": "UP"}), (210.0, 465.0))
        techs = {"infantry_weapons": {"parents": [], "positions": {"infantry_folder": (0, -1)}},
                 "infantry_weapons1": {"parents": ["infantry_weapons"], "positions": {"infantry_folder": (0, 2)}},
                 "lonely": {"parents": [], "positions": {"infantry_folder": (5, 5)}}}
        self.assertIs(techtree.branch_grid("infantry_weapons1", techs, "infantry_folder", layout["grids"]), grid)
        self.assertIsNone(techtree.branch_grid("lonely", techs, "infantry_folder", layout["grids"]))
        self.assertIsNone(techtree.folder_layout((str(self.tmp),), "naval_folder"))

    def test_lines_go_around_items(self):
        # a -> c on one row with b in between: the straight line would run through b
        items = [{"id": "a", "x": 0, "y": 100, "w": 50, "h": 50}, {"id": "b", "x": 100, "y": 100, "w": 50, "h": 50},
                 {"id": "c", "x": 200, "y": 100, "w": 50, "h": 50}, {"id": "d", "x": 200, "y": 0, "w": 50, "h": 50}]
        lines = [{"from": "a", "to": "c"}, {"from": "a", "to": "b"}, {"from": "b", "to": "d"}]
        routes = techtree.route_lines(items, lines)
        self.assertEqual(techtree.line_report(items, lines, routes)["through_items"], 0)
        straight = [[(25, 125), (225, 125)], [(50, 125), (100, 125)], [(150, 125), (200, 25)]]
        self.assertEqual(techtree.line_report(items, lines[:1], straight[:1])["through_items"], 1)
        self.assertEqual(routes[1], [(50, 125.0), (100, 125.0)])   # neighbours: straight
        for points in routes:   # orthogonal polylines only
            for (x1, y1), (x2, y2) in zip(points, points[1:]):
                self.assertTrue(x1 == x2 or y1 == y2)

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
