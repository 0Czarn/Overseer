"""Focus trees with mods: the game's mod list, merged files, mod localisation, allow_branch, offsets, game rules."""

import unittest

from hoi4dbg import focus, gamefiles, triggers

from helpers import TempDirMixin

GAME_TREE = """
focus_tree = { id = test_focus
	focus = { id = T_a x = 5 y = 0 }
	focus = { id = T_old x = 0 y = 1 relative_position_id = T_a prerequisite = { focus = T_a } }
}
"""
MOD_TREE = """
focus_tree = { id = test_focus
	focus = { id = T_a x = 5 y = 0 }
	focus = { id = T_b x = -1 y = 1 relative_position_id = T_a prerequisite = { focus = T_a }
		mutually_exclusive = { focus = T_c }
		allow_branch = { if = { limit = { has_game_rule = { rule = obsolete_focus_branches_visibility option = HIDE } }
			NOT = { has_completed_focus = T_c } } } }
	focus = { id = T_b2 x = 0 y = 1 relative_position_id = T_b prerequisite = { focus = T_b } }
	focus = { id = T_c x = 1 y = 1 relative_position_id = T_a prerequisite = { focus = T_a }
		offset = { x = 3 y = 0 trigger = { has_completed_focus = T_a } } }
	focus = { id = T_d x = 0 y = 2 relative_position_id = T_a prerequisite = { focus = T_b focus = T_c } }
}
"""
RULES = """obsolete_focus_branches_visibility = { name = "X" default = { name = HIDE } option = { name = SHOW } }"""


class FocusModTests(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.game, self.mod = self.tmp / "game", self.tmp / "mod1"
        for root, tree in ((self.game, GAME_TREE), (self.mod, MOD_TREE)):
            (root / "common" / "national_focus").mkdir(parents=True)
            (root / "common" / "national_focus" / "test.txt").write_text(tree, encoding="utf-8")
        (self.game / "common" / "national_focus" / "other.txt").write_text("focus_tree = { id = other }", encoding="utf-8")
        (self.game / "common" / "game_rules").mkdir(parents=True)
        (self.game / "common" / "game_rules" / "00_game_rules.txt").write_text(RULES, encoding="utf-8")
        focus._load.cache_clear()
        triggers.focus_scripts.cache_clear()

    def test_mod_file_replaces_the_game_file_of_the_same_name(self):
        files = focus.focus_files(self.game, [self.mod])
        self.assertEqual([p.split("\\")[-1].split("/")[-1] for p in files], ["other.txt", "test.txt"])
        ids = {f["id"] for f in focus.tree(files, "test_focus")}
        self.assertNotIn("T_old", ids)   # only in the game's test.txt, which the mod replaced
        (self.mod / "descriptor.mod").write_text('name="M"\nreplace_path="common/national_focus"\n', encoding="utf-8")
        self.assertEqual(len(focus.focus_files(self.game, [self.mod])), 1)

    def test_enabled_mods_follow_the_games_log(self):
        ud = self.tmp / "ud"
        (ud / "mod").mkdir(parents=True)
        (ud / "logs").mkdir()
        for name, folder in (("One", self.mod), ("Two", self.game)):
            (ud / "mod" / f"{name}.mod").write_text(f'name="{name} "\npath="{folder.as_posix()}"\n', encoding="utf-8")
        (ud / "dlc_load.json").write_text('{"enabled_mods": ["mod/Two.mod"]}', encoding="utf-8")
        self.assertEqual(gamefiles.enabled_mods(ud), [self.game])
        (ud / "logs" / "system.log").write_text("[x][y][gameapplication.cpp:1509]: Active Mod Count: 1\n"
                                                "[x][y][gameapplication.cpp:1518]: Active Mod: One \n", encoding="utf-8")
        self.assertEqual(gamefiles.enabled_mods(ud), [self.mod])

    def test_mod_localisation_and_replace_folder(self):
        (self.game / "localisation" / "english").mkdir(parents=True)
        (self.game / "localisation" / "english" / "a_l_english.yml").write_text(
            'l_english:\n T_a:0 "Game A"\n T_b:0 "Game B"\n', encoding="utf-8-sig")
        (self.mod / "localisation" / "replace").mkdir(parents=True)
        (self.mod / "localisation" / "m_l_english.yml").write_text('l_english:\n T_a:0 "Mod A"\n T_c:0 "Mod C" # note\n',
                                                                    encoding="utf-8-sig")
        (self.mod / "localisation" / "replace" / "r_l_english.yml").write_text('l_english:\n T_b:0 "Replaced B"\n',
                                                                               encoding="utf-8-sig")
        focus._all_loc.cache_clear()
        self.assertEqual(focus.loc_names(self.game, {"T_a", "T_b", "T_c"}, mods=(str(self.mod),)),
                         {"T_a": "Game A", "T_b": "Replaced B", "T_c": "Mod C"})
        (self.mod / "localisation" / "english").mkdir()
        (self.mod / "localisation" / "english" / "a_l_english.yml").write_text('l_english:\n T_a:0 "Mod file A"\n',
                                                                               encoding="utf-8-sig")
        focus._all_loc.cache_clear()
        self.assertEqual(focus.loc_names(self.game, {"T_a"}, mods=(str(self.mod),)), {"T_a": "Mod file A"})

    def _shape(self, completed):
        files = focus.focus_files(self.game, [self.mod])
        rules = triggers.game_rule_defaults(tuple(str(f) for f in gamefiles.merged_files([self.game, self.mod],
                                                                                          "common/game_rules")))
        world = triggers.SavedWorld("TST", completed, set(), rules, ["TST"])
        scripts = triggers.focus_scripts(files)
        branch, shifts = {}, {}
        for fid, sc in scripts.items():
            if sc["allow_branch"] is not None:
                branch[fid] = triggers.evaluate(sc["allow_branch"], triggers.Context(world, "TST"))
            for dx, dy, trig in sc["offsets"]:
                if triggers.evaluate(trig, triggers.Context(world, "TST")):
                    shifts[fid] = (dx, dy)
        tree = focus.tree(files, "test_focus", shifts)
        return {f["id"]: (f["x"], f["y"]) for f in tree}, focus.hidden(tree, branch)

    def test_allow_branch_hides_with_dependants_and_offsets_move(self):
        pos, gone = self._shape([])
        self.assertEqual(gone, set())
        self.assertEqual(pos["T_c"], (6, 1))
        pos, gone = self._shape(["T_a", "T_c"])
        self.assertEqual(gone, {"T_b", "T_b2"})        # T_d stays: T_c is another way to it
        self.assertEqual(pos["T_c"], (9, 1))           # offset while T_a is completed

    def test_saved_world_unknown_facts_are_none(self):
        world = triggers.SavedWorld("TST", [], set(), {}, ["TST"])
        ctx = triggers.Context(world, "TST")
        self.assertIsNone(triggers.evaluate(triggers.parse("has_war = yes"), ctx))
        self.assertIn("has_war", ctx.unknown)
        self.assertIs(triggers.evaluate(triggers.parse("has_war = yes has_completed_focus = X"), ctx), False)
        self.assertIsNone(triggers.evaluate(triggers.parse("has_game_rule = { rule = r option = A }"), ctx))

    def test_escaped_quotes_and_hash_in_strings(self):
        # Road to 56 germany.txt: division = "name = \"Volkssturm 'Berlin'\" ..." - the braces after it were misread
        src = 'a = { division = "name = \\"X {\\" # not a comment" b = 1 } c = 2 # comment'
        self.assertEqual(triggers.parse(src), [("a", "=", [("division", "=", 'name = \\"X {\\" # not a comment'),
                                                          ("b", "=", "1")]), ("c", "=", "2")])

    def test_country_flags_from_the_save(self):
        from hoi4dbg.saves import text
        state = focus.save_state(text.parse('focus_tree=t\nflags={\n\tA_flag={ value=2 date="1936.1.1.12" }\n}\n'))
        self.assertEqual(state["flags"], {"A_flag": "2"})
        world = triggers.SavedWorld("TST", [], set(), {}, ["TST"], state["flags"])
        ev = lambda src: triggers.evaluate(triggers.parse(src), triggers.Context(world, "TST"))  # noqa: E731
        self.assertIs(ev("has_country_flag = A_flag"), True)
        self.assertIs(ev("has_country_flag = B_flag"), False)
        self.assertIs(ev("has_country_flag = { flag = A_flag value > 1 }"), True)
        self.assertIsNone(ev("has_country_flag = { flag = A_flag days > 10 }"))
        self.assertIsNone(triggers.evaluate(triggers.parse("has_country_flag = A_flag"),
                                            triggers.Context(triggers.SavedWorld("TST", [], set(), {}, ["TST"]), "TST")))

    def test_changed_game_rules_from_a_text_save(self):
        from hoi4dbg.saves import countries
        data = b'HOI4txt\nplayer="GER"\ngame_rules={\n\tGER_focus_tree_selection=STANDARD_TREE\n}\nid={ id=1 type=2 }\n'
        self.assertEqual(countries.game_rules(data, None), {"GER_focus_tree_selection": "STANDARD_TREE"})
        self.assertEqual(countries.game_rules(b'HOI4txt\ngame_rules={\n}\n', None), {})

    def test_hidden_focus_cannot_be_queued(self):
        tree = [{**f, "hidden": f["id"] == "T_b"} for f in focus.tree(focus.focus_files(self.game, [self.mod]), "test_focus")]
        res = focus.validate_queue(tree, {"completed": ["T_a"], "current": None, "progress": 0}, ["T_b"])
        self.assertFalse(res[0]["ok"])
        self.assertIn("hidden", res[0]["reason"])


if __name__ == "__main__":
    unittest.main()
