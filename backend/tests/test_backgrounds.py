import base64
import tempfile
import unittest
from pathlib import Path

from hoi4dbg.backgrounds import BackgroundError, Backgrounds

PNG = b"\x89PNG\r\n\x1a\n" + bytes(20)


def uri(raw, mime="image/png"):
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


class BackgroundsTest(unittest.TestCase):
    def setUp(self):
        self.store = Backgrounds(Path(tempfile.mkdtemp()) / "backgrounds")

    def test_add_list_get_delete(self):
        item = self.store.add("my map.png", uri(PNG), "2026-10-15 18:00:00")
        self.assertEqual([(b["id"], b["name"], b["size"]) for b in self.store.list()], [(item["id"], "my map.png", len(PNG))])
        self.assertEqual(self.store.get(item["id"]), uri(PNG))
        self.store.delete(item["id"])
        self.assertEqual(self.store.list(), [])
        with self.assertRaises(FileNotFoundError):
            self.store.get(item["id"])

    def test_only_jpg_and_png_are_taken(self):
        with self.assertRaises(BackgroundError):
            self.store.add("x.gif", "data:image/gif;base64,R0lGODlh", "t")
        with self.assertRaises(BackgroundError):   # a PNG name over other bytes
            self.store.add("x.png", uri(b"GIF89a" + bytes(10)), "t")
        self.store.add("photo.jpg", uri(b"\xff\xd8\xff\xe0" + bytes(10), "image/jpeg"), "t")
        with self.assertRaises(BackgroundError):
            self.store.get("../../secret")


if __name__ == "__main__":
    unittest.main()
