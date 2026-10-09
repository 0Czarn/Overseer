"""Focus trees from game files, state from saves, queue validation."""

import unittest

from hoi4dbg import focus
from hoi4dbg.saves import text

from helpers import TempDirMixin

TREE = """
focus_tree = {
	id = test_focus
	shared_focus = SH_root
	focus = { id = T_a  x = 5 y = 0 cost = 10 }
	focus = { id = T_b  x = -1 y = 1 relative_position_id = T_a cost = 5
		prerequisite = { focus = T_a } mutually_exclusive = { focus = T_c } }
	focus = { id = T_c  x = 1 y = 1 relative_position_id = T_a  # comment
		prerequisite = { focus = T_a } mutually_exclusive = { focus = T_b } available = { has_war = yes } }
	focus = { id = T_d  x = 0 y = 2 relative_position_id = T_a
		prerequisite = { focus = T_b focus = T_c } }
}
shared_focus = { id = SH_root x = 20 y = 0 cost = 10 }
shared_focus = { id = SH_next x = 0 y = 1 relative_position_id = SH_root cost = 10 prerequisite = { focus = SH_root } }
shared_focus = { id = SH_other x = 0 y = 1 cost = 10 prerequisite = { focus = UNRELATED } }
"""


class FocusTests(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        folder = self.tmp / "common" / "national_focus"
        folder.mkdir(parents=True)
        (folder / "test.txt").write_text(TREE, encoding="utf-8")
        loc = self.tmp / "localisation" / "english"
        loc.mkdir(parents=True)
        (loc / "focus_l_english.yml").write_text('﻿l_english:\n T_a:0 "Alpha"\n T_a_desc:0 "x"\n', encoding="utf-8")
        focus._load.cache_clear()
        focus._all_loc.cache_clear()
        self.folders = focus.focus_folders(self.tmp)
        self.tree = focus.tree(self.folders, "test_focus")

    def test_tree_with_shared_branch_and_positions(self):
        by_id = {f["id"]: f for f in self.tree}
        self.assertEqual(set(by_id), {"T_a", "T_b", "T_c", "T_d", "SH_root", "SH_next"})  # not SH_other
        self.assertEqual((by_id["T_b"]["x"], by_id["T_b"]["y"]), (4, 1))
        self.assertEqual((by_id["SH_next"]["x"], by_id["SH_next"]["y"]), (20, 1))
        self.assertEqual(by_id["T_b"]["days"], 35)
        self.assertEqual(by_id["T_d"]["prerequisites"], [["T_b", "T_c"]])
        self.assertTrue(by_id["T_c"]["has_conditions"])
        self.assertEqual(focus.loc_names(self.tmp, {"T_a", "T_b"}), {"T_a": "Alpha"})

    def test_save_state_and_statuses(self):
        block = text.parse('focus_tree=test_focus\nfocus={\n\tcompleted="T_a"\n\tprogress=14\n\tcurrent="T_b"\n\tpaused=no\n}\n')
        state = focus.save_state(block)
        self.assertEqual((state["tree"], state["completed"], state["current"], state["progress"]),
                         ("test_focus", ["T_a"], "T_b", 14.0))
        st = {f["id"]: f for f in focus.statuses(self.tree, state)}
        self.assertEqual({k: v["status"] for k, v in st.items()},
                         {"T_a": "completed", "T_b": "in_progress", "T_c": "excluded", "T_d": "blocked",
                          "SH_root": "available", "SH_next": "blocked"})
        self.assertAlmostEqual(st["T_b"]["progress"], 14 / 35)

    def test_queue_validation(self):
        state = {"completed": ["T_a"], "current": None, "progress": 0}
        res = focus.validate_queue(self.tree, state, ["T_d", "T_b", "T_d", "T_c", "T_a", "SH_next", "SH_root", "X"])
        self.assertEqual([(r["id"], r["ok"]) for r in res],
                         [("T_d", False), ("T_b", True), ("T_d", True), ("T_c", False), ("T_a", False),
                          ("SH_next", False), ("SH_root", True), ("X", False)])
        self.assertEqual(res[0]["reason"], "needs T_b or T_c")
        self.assertIn("mutually exclusive", res[3]["reason"])


if __name__ == "__main__":
    unittest.main()
