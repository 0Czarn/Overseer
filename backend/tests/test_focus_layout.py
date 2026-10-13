import unittest

from hoi4dbg import focus
from hoi4dbg.saves import text


class FocusLayoutTest(unittest.TestCase):
    def test_icon_from_plain_and_conditional_blocks(self):
        plain = focus._focus(text.parse("id = A icon = GFX_goal_a x = 1 y = 0"))
        self.assertEqual(plain["icon"], "GFX_goal_a")
        cond = focus._focus(text.parse("id = B icon = { key = GFX_goal_b trigger = { always = yes } } x = 0 y = 1"))
        self.assertEqual(cond["icon"], "GFX_goal_b")
        self.assertIsNone(focus._focus(text.parse("id = C"))["icon"])

    def test_start_conditions_and_select_effect(self):
        plain = focus._focus(text.parse("id = A available = { } cost = 10"))
        cond = focus._focus(text.parse("id = B available = { has_war = no }"))
        picked = focus._focus(text.parse("id = C select_effect = { add_political_power = 10 }"))
        self.assertEqual((plain["start_conditions"], plain["select_effect"]), (False, False))
        self.assertEqual((cond["start_conditions"], picked["select_effect"]), (True, True))

    def test_layout_like_the_game(self):
        # A on top; B and C below it are mutually exclusive; D needs B or C (dashed alternative lines)
        f = lambda i, x, y, pre=(), ex=(): {"id": i, "x": x, "y": y, "prerequisites": [list(p) for p in pre],  # noqa: E731
                                            "exclusive": list(ex)}
        tree = [f("A", 1, 0), f("B", 0, 1, [["A"]], ["C"]), f("C", 2, 1, [["A"]], ["B"]), f("D", 1, 2, [["B", "C"]])]
        lay = focus.layout(tree)
        pos = {i["id"]: (i["left"], i["top"]) for i in lay["items"]}
        self.assertEqual(pos["B"], (focus.PAD, focus.PAD + focus.SPACING[1]))
        self.assertEqual(pos["C"][0] - pos["B"][0], 2 * focus.SPACING[0])
        self.assertEqual(len(lay["lines"]), 4)
        self.assertEqual([l["alternative"] for l in lay["lines"] if l["to"] == "D"], [True, True])
        self.assertEqual([(x["a"], x["b"]) for x in lay["exclusive"]], [("B", "C")])   # one link per pair
        first = next(l for l in lay["lines"] if l["to"] == "B")["points"]
        self.assertEqual(first[0][0], pos["A"][0] + focus.NODE["w"] / 2)   # leaves the parent's centre
        self.assertEqual(first[-1], [pos["B"][0] + focus.NODE["w"] / 2, pos["B"][1]])   # enters the child's top
        self.assertEqual(focus.layout([])["items"], [])


if __name__ == "__main__":
    unittest.main()
