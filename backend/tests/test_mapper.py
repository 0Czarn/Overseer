"""Save field -> country object location, found across many countries at once."""

import unittest
from unittest import mock

from hoi4dbg.live import mapper

from test_live import BASE, FakeMemory


def country_snapshots(n, place):
    """n fake countries; `place(mem, base, i)` writes country i's values; returns ({tag: snapshot}, mem)."""
    mem = FakeMemory(0x10000)
    snaps = {}
    for i in range(n):
        base = BASE + i * 0x4000 if i < 3 else BASE + 0x10_0000 + (i - 3) * 0x4000
        if base + 0x4000 > BASE + 0x10_0000 + 0x10000:
            break
        place(mem, base, i)
        snaps[f"T{i:02d}"] = mapper.snapshot(mem, base)
    return snaps


@mock.patch.object(mapper, "PTR_RANGE", (BASE, BASE + 0x20_0000))  # fake memory lives low
class MapperTests(unittest.TestCase):
    def test_numeric_leaves(self):
        block = [("stability", "0.7"), ("politics", [("political_power", "12.5"), ("ruling_party", "fascism"),
                                                     ("deep", [("x", "1")])]), "bare"]
        self.assertEqual(mapper.numeric_leaves(block), {("stability",): 0.7, ("politics", "political_power"): 12.5})

    def test_field_found_directly_and_behind_a_pointer(self):
        def place(mem, base, i):
            mem.put(base + 0x10D0, "q", 50000 + i * 1000)          # direct, fixed64_100000
            mem.put(base + 0xF90, "Q", base + 0x3000)              # pointer to a sub-object
            mem.put(base + 0x3000 + 0xE0, "q", (10 + i) * 100000)  # behind the pointer
        snaps = country_snapshots(6, place)
        values = {t: (0.5 + i * 0.01, 0.001) for i, t in enumerate(snaps)}
        found = mapper.map_field(snaps, values)
        self.assertEqual(found[0]["location"], mapper.Location(None, 0x10D0, "fixed64_100000"))
        self.assertEqual((found[0]["matched"], found[0]["countries"]), (6, 6))
        pp = mapper.map_field(snaps, {t: (10.0 + i, 0.001) for i, t in enumerate(snaps)})
        self.assertIn(mapper.Location(0xF90, 0xE0, "fixed64_100000"), [r["location"] for r in pp])

    def test_same_value_everywhere_or_few_countries_is_not_evidence(self):
        def place(mem, base, i):
            mem.put(base + 0x100, "i", 7)
        snaps = country_snapshots(6, place)
        self.assertEqual(mapper.map_field(snaps, {t: (7.0, 0.001) for t in snaps}), [])
        self.assertEqual(mapper.map_field(dict(list(snaps.items())[:3]), {"T00": (7.0, 0.001)}), [])

    def test_object_at_the_end_of_readable_memory(self):
        """Regression: a 12 KB read past the end of a region returned nothing (ETH, GUA, PAL)."""
        mem = FakeMemory(0x4000)
        base = BASE + 0x2000                                      # only 8 KB readable from here
        mem.put(base + 0x10D0, "q", 50000)
        snap = mapper.snapshot(mem, base)
        self.assertEqual(len(snap["obj"]), 0x2000)
        self.assertEqual(mapper._value_at(snap, mapper.Location(None, 0x10D0, "fixed64_100000")), 0.5)


if __name__ == "__main__":
    unittest.main()
