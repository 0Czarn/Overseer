import struct
import tempfile
import unittest
from pathlib import Path

from hoi4dbg import geography


def bmp(path: Path, rows: list[list[tuple[int, int, int]]]) -> None:
    """24-bit BMP, rows given top to bottom (stored bottom-up), colours as (r, g, b)."""
    width, height = len(rows[0]), len(rows)
    stride = (width * 3 + 3) & ~3
    pixels = b"".join(b"".join(bytes((b, g, r)) for r, g, b in row).ljust(stride, b"\0") for row in reversed(rows))
    header = b"BM" + struct.pack("<IHHI", 54 + len(pixels), 0, 0, 54)
    info = struct.pack("<IiiHHIIiiII", 40, width, height, 1, 24, 0, len(pixels), 0, 0, 0, 0)
    path.write_bytes(header + info + pixels)


class GeographyTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "map").mkdir()
        # provinces 1 | 2 / 3 below both; 4 is a sea province (no continent)
        (self.dir / "map" / "definition.csv").write_text(
            "0;0;0;0;land;false;unknown;0\n1;255;0;0;land;false;plains;2\n2;0;255;0;land;false;plains;2\n"
            "3;0;0;255;land;false;plains;6\n4;9;9;9;sea;false;ocean;0\n", encoding="utf-8")
        red, green, blue = (255, 0, 0), (0, 255, 0), (0, 0, 255)
        bmp(self.dir / "map" / "provinces.bmp", [[red, red, green], [blue, blue, blue]])

    def test_neighbours_both_ways_and_cached(self):
        n = geography.province_neighbours(str(self.dir), str(self.dir / "cache"))
        self.assertEqual(n, {1: {2, 3}, 2: {1, 3}, 3: {1, 2}})
        raw = geography._bmp(self.dir / "map" / "provinces.bmp")
        self.assertEqual(geography._pairs_python(*raw), geography._pairs_numpy(*raw))   # same without numpy
        self.assertTrue((self.dir / "cache" / "province_adjacency.json").is_file())

    def test_countries_and_continent(self):
        n = geography.province_neighbours(str(self.dir), "")
        owned = {"USA": [1], "CAN": [2], "MEX": [3]}
        self.assertEqual(geography.countries_touching(owned, n, "USA"), {"CAN", "MEX"})
        continents = geography.province_continents(str(self.dir))
        self.assertEqual(geography.main_continent([1, 2, 3], continents), 2)
        self.assertIsNone(geography.main_continent([4], continents))


if __name__ == "__main__":
    unittest.main()
