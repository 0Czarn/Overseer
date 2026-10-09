"""Equipment from saves and verified additions (console command + newer save)."""

import logging
import os
import time
import unittest
from pathlib import Path

from hoi4dbg import equipment_changes
from hoi4dbg.equipment_changes import ChangeError, EquipmentChanges
from hoi4dbg.live import console
from hoi4dbg.saves import binary as b
from hoi4dbg.saves.binary import SaveFormatError
from hoi4dbg.saves import binvalues, equipment

from helpers import TempDirMixin
from savebuilder import Builder

E = equipment.T
TEXT_SAVE = (
    'HOI4txt\r\nsession=1\r\n'
    'equipments={\r\n\tconvoy_1={\r\n\t\tid={ id=1 type=70 }\r\n\t\tcreator="SOV"\r\n\t}\r\n'
    '\tinfantry_equipment_1={\r\n\t\tid={ id=7 type=70 }\r\n\t\tcreator="SOV"\r\n\t}\r\n'
    '\tlight_tank_chassis_1={\r\n\t\tid={ id=9 type=70 }\r\n\t\tname="T-26"\r\n\t\tobsolete=yes\r\n\t\tcreator="SOV"\r\n\t}\r\n}\r\n'
    'countries={\r\n\tSOV={\r\n\t\tproduction={\r\n\t\t\tequipments={\r\n'
    '\t\t\t\tequipment={\r\n\t\t\t\t\tid={ id=7 type=70 }\r\n\t\t\t\t\tamount=100\r\n\t\t\t\t}\r\n'
    '\t\t\t\tequipment={\r\n\t\t\t\t\tid={ id=9 type=70 }\r\n\t\t\t\t\tamount=12\r\n\t\t\t\t}\r\n'
    '\t\t\t\tallow_zero_entries=no\r\n\t\t\t}\r\n\t\t}\r\n'
    '\t\tconvoys={\r\n\t\t\tequipment={\r\n\t\t\t\tequipment={\r\n\t\t\t\t\tid={ id=1 type=70 }\r\n'
    '\t\t\t\t\tamount=2337\r\n\t\t\t\t}\r\n\t\t\t}\r\n\t\t}\r\n\t}\r\n}\r\n')


def binary_save() -> bytes:
    def eq_id(bld, i):
        return bld.key(E["id"]).open().key(E["id"]).i32(i).key(E["type"]).i32(70).close()
    bld = Builder(8)
    bld.key(E["equipments"]).open()
    eq_id(bld.ustr("convoy_1").tok(b.EQUALS).open(), 1).key(E["creator"]).qstr("SOV").close()
    eq_id(bld.ustr("infantry_equipment_1").tok(b.EQUALS).open(), 7).key(E["creator"]).qstr("SOV").close()
    eq_id(bld.ustr("light_tank_chassis_1").tok(b.EQUALS).open(), 9).key(E["name"]).qstr("T-26")
    bld.key(E["obsolete"]).boolean(True).key(E["creator"]).qstr("SOV").close()
    bld.close()
    bld.key(binvalues.TOKENS["countries"]).open().qstr("SOV").tok(b.EQUALS).open()
    bld.key(E["production"]).open().key(E["equipments"]).open()
    eq_id(bld.key(E["equipment"]).open(), 7).key(E["amount"]).i32(100).close()
    eq_id(bld.key(E["equipment"]).open(), 9).key(E["amount"]).i32(12).close()
    bld.close().close()
    bld.key(E["convoys"]).open().key(E["equipment"]).open()
    eq_id(bld.key(E["equipment"]).open(), 1).key(E["amount"]).i32(2337).close()
    bld.close().close()
    bld.close().close()
    return bld.bytes()


class EquipmentReadTests(unittest.TestCase):
    def check(self, data):
        self.assertEqual(data["stockpile"], {"7": 100, "9": 12})
        self.assertEqual(data["convoys"], {"1": 2337})
        self.assertEqual(data["variants"]["9"], {"type": "light_tank_chassis_1", "name": "T-26", "creator": "SOV",
                                                 "obsolete": True})
        rows = equipment.rows(data, {"infantry_equipment_1": "Infantry Equipment I"})
        self.assertEqual([(r["archetype_name"], r["amount"], r["pool"]) for r in rows],
                         [("Infantry Equipment I", 100, "stockpile"), ("light_tank_chassis_1", 12, "stockpile"),
                          ("convoy_1", 2337, "convoys")])

    def test_text_save(self):
        self.check(equipment.read(TEXT_SAVE.encode(), "text", None, None, "SOV"))

    def test_binary_save(self):
        self.check(equipment.read(binary_save(), "binary", 8, "Operation Postern v1.19.3.0.c01a (5632)", "SOV"))

    def test_missing_country(self):
        with self.assertRaises(b.SaveFormatError):
            equipment.read(TEXT_SAVE.encode(), "text", None, None, "GER")


class FakeService:
    """Newest save = self.save (changes with each 'savegame'); live players from self.players."""

    def __init__(self, install: Path):
        self.install = install
        self.log = logging.getLogger("test")
        self.stock = {"7": 100.0}
        self.variants = {"7": {"type": "infantry_equipment_1"}, "9": {"type": "light_tank_chassis_1"}}
        self.writing = False
        self.mtime = 10.0
        self.players = ["SOV"]
        self.saves = self
        self.live = type("Live", (), {"players": lambda _: self.players})()

    def _install_path(self):
        return self.install

    def _pick_save(self, name):
        return Path(f"s{self.mtime:g}.hoi4"), {}

    def equipment(self, path, tag):
        if self.writing:
            raise SaveFormatError("in_progress", "The game may still be writing this save; try again shortly")
        return {"analysis": {"file": {"mtime": self.mtime}, "header": {"player_tag": "SOV"}},
                "variants": dict(self.variants),
                "stockpile": dict(self.stock), "convoys": {}}


class EquipmentChangeTests(TempDirMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.history = self.tmp / console.HISTORY_FILE
        self.history.write_text("ai\n", encoding="utf-8")
        self.svc = FakeService(self.tmp)
        self.clock = 1000.0
        self.changes = EquipmentChanges(self.svc, clock=lambda: self.clock)

    def type_command(self, cmd):
        with self.history.open("a", encoding="utf-8") as f:
            f.write(cmd + "\n")
        self.clock += 5
        later = time.time() + 10
        os.utime(self.history, (later, later))

    def test_addition_confirmed_by_the_next_save(self):
        op = self.changes.create("sov", "infantry_equipment_1", 100)
        self.assertEqual((op["command"], op["before"], op["expected"]), ("add_equipment 100 infantry_equipment_1", 100, 200))
        self.assertEqual(self.changes.poll(op["id"])["state"], "waiting_for_command")
        self.type_command("add_equipment 100 infantry_equipment_1")
        self.assertEqual(self.changes.poll(op["id"])["state"], "waiting_for_save")
        self.svc.stock["7"], self.svc.mtime = 200.0, 20.0
        res = self.changes.poll(op["id"])
        self.assertEqual((res["state"], res["actual"]), ("confirmed", 200))

    def test_save_being_written_is_waited_for(self):
        """Regression (in game, sprzet2.hoi4): the check stopped with an error while the game was writing the save."""
        op = self.changes.create("SOV", "infantry_equipment_1", 25)
        self.type_command("add_equipment 25 infantry_equipment_1")
        self.svc.writing = True
        res = self.changes.poll(op["id"])
        self.assertEqual(res["state"], "waiting_for_save")
        self.assertIn("still writing", res["message"])
        self.svc.writing, self.svc.stock["7"], self.svc.mtime = False, 125.0, 20.0
        self.assertEqual(self.changes.poll(op["id"])["state"], "confirmed")

    def test_unexpected_amount_is_a_mismatch(self):
        """Like `add_equipment -50 train_equipment_1`, which added 1000 in game."""
        op = self.changes.create("SOV", "infantry_equipment_1", 50)
        self.type_command("add_equipment 50 infantry_equipment_1")
        self.svc.stock["7"], self.svc.mtime = 1100.0, 20.0
        self.assertEqual(self.changes.poll(op["id"])["state"], "mismatch")

    def test_refused_requests(self):
        for archetype, amount, code in (("infantry_equipment_1", -50, "bad_amount"), ("infantry_equipment_1", 1.5, "bad_amount"),
                                        ("Infantry Equipment", 5, "bad_archetype"), ("nuke_1", 5, "unknown_archetype")):
            with self.assertRaises(ChangeError) as ctx:
                self.changes.create("SOV", archetype, amount)
            self.assertEqual(ctx.exception.code, code, archetype)
        with self.assertRaises(ChangeError) as ctx:
            self.changes.create("GER", "infantry_equipment_1", 5)
        self.assertEqual(ctx.exception.code, "not_player")

    def test_design_name_with_space(self):
        """In game: `add_equipment 7 Test Tank` (no quotes) added 7 to the first design named "Test Tank"."""
        self.svc.variants = {"4505": {"type": "light_tank_chassis_2", "name": "Test Tank", "creator": "SOV"},
                             "4507": {"type": "light_tank_chassis_2", "name": "Test Tank", "creator": "SOV"},
                             "4506": {"type": "light_tank_chassis_2", "name": "TestTank", "creator": "SOV",
                                      "obsolete": True}}
        self.svc.stock = {"4505": 20.0, "4506": 5.0}
        self.assertEqual([d["name"] for d in equipment_changes.designs(self.svc.equipment(None, "SOV"), "SOV")],
                         ["Test Tank", "TestTank"])
        op = self.changes.create("SOV", "", 7, variant="Test Tank")
        self.assertEqual((op["command"], op["before"], op["expected"]), ("add_equipment 7 Test Tank", 20, 27))
        self.type_command("add_equipment 7 Test Tank")
        self.svc.stock["4505"], self.svc.mtime = 27.0, 20.0
        self.assertEqual(self.changes.poll(op["id"])["state"], "confirmed")

    def test_design_names_that_cannot_be_typed_or_do_not_exist(self):
        for name, code in (('Tank "X"', "bad_variant"), (" Tank", "bad_variant"), ("a#b", "bad_variant"),
                           ("Unknown Tank", "unknown_variant")):
            with self.assertRaises(ChangeError) as ctx:
                self.changes.create("SOV", "", 5, variant=name)
            self.assertEqual(ctx.exception.code, code, name)

    def test_expires(self):
        op = self.changes.create("SOV", "infantry_equipment_1", 5)
        self.clock += 1000
        self.assertEqual(self.changes.poll(op["id"])["state"], "expired")


if __name__ == "__main__":
    unittest.main()
