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


class CleanupTest(unittest.TestCase):
    def test_old_campaigns_and_size_limit(self):
        import os
        import time
        from tests.helpers import make_service
        tmp = Path(tempfile.mkdtemp())
        svc = make_service(tmp)
        t = 1936 * 365
        old = svc.ic_history.add({"t": t, "player": "POL", "countries": {"POL": [1, 2, 3]}, "factions": None})
        svc.ic_history.active = None   # another game started since
        new = svc.ic_history.add({"t": t, "player": "GER", "countries": {"GER": [1, 2, 3]}, "factions": None})
        for p in svc.ic_history.folder.glob(f"{old}.*"):
            os.utime(p, (time.time() - 40 * 86400,) * 2)
        res = svc.data_cleanup({"days": 30})["data"]
        self.assertEqual(res["deleted"], [old])
        self.assertEqual([g["id"] for g in svc.ic_history.games()], [new])   # the one being recorded stays
        self.assertEqual(svc.data_cleanup({"limit_mb": 0.000001})["data"]["deleted"], [])
        with self.assertRaises(Exception):
            svc.data_cleanup({"days": -1})
