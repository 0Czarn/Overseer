import tempfile
import unittest
from pathlib import Path

from hoi4dbg import doctrines


class DoctrineDefinitionsTest(unittest.TestCase):
    def test_folders_grand_subs_and_reward_thresholds(self):
        root = Path(tempfile.mkdtemp())
        d = root / "common" / "doctrines"
        for sub in ("folders", "tracks", "grand_doctrines", "subdoctrines/land"):
            (d / sub).mkdir(parents=True)
        (d / "folders" / "f.txt").write_text("land = { name = land_doctrine_folder ledger_gfx = GFX_land }\n"
                                             "naval = { name = naval_doctrine_folder }", encoding="utf-8")
        (d / "tracks" / "t.txt").write_text("infantry = { name = DOCTRINE_TRACK_INFANTRY icon = GFX_inf }", encoding="utf-8")
        (d / "grand_doctrines" / "g.txt").write_text(
            "grand_battleplan = { folder = land name = GRAND_DOCTRINE_GRAND_BATTLEPLAN icon = GFX_gb tracks = { infantry }"
            " command_power_gain = 0.25 enable_tactic = tactic_planned_attack"
            " milestones = { { max_dig_in_factor = 0.05 } } }", encoding="utf-8")
        (d / "subdoctrines" / "land" / "i.txt").write_text(
            "commandos = { track = infantry name = SUBDOCTRINE_COMMANDOS icon = GFX_c"
            " rewards = { a = { category_light_infantry = { reliability = 0.05 } } b = { mastery = 50 } c = { x = 1 } } }",
            encoding="utf-8")
        defs = doctrines.definitions((str(root),))
        self.assertEqual([f["id"] for f in defs["folders"]], ["land", "naval"])
        g = doctrines.resolve("GRAND_DOCTRINE_GRAND_BATTLEPLAN", defs, "grand")
        self.assertEqual((g["tracks"], g["modifiers"], g["tactics"]), (["infantry"], {"command_power_gain": 0.25},
                                                                       ["tactic_planned_attack"]))
        self.assertEqual(g["milestones"][0]["modifiers"], {"max_dig_in_factor": 0.05})
        s = doctrines.resolve("SUBDOCTRINE_COMMANDOS", defs, "subs", "infantry")
        self.assertEqual([(r["id"], r["threshold"]) for r in s["rewards"]], [("a", 100.0), ("b", 150.0), ("c", 250.0)])
        self.assertEqual(s["rewards"][0]["modifiers"], {"reliability@category_light_infantry": 0.05})
        self.assertIsNone(doctrines.resolve(None, defs, "subs"))


if __name__ == "__main__":
    unittest.main()
