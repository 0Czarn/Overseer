import json
import unittest

from hoi4dbg import applog, demo
from hoi4dbg.reports import ReportError, ReportStore
from hoi4dbg.service import CAPABILITIES, DEMO, LIVE, UNAVAILABLE, NotFound

from helpers import TempDirMixin, make_service


class AppLogTests(TempDirMixin, unittest.TestCase):
    def test_ring_buffer_filters_and_pages(self):
        logger, ring = applog.setup(self.tmp / "logs", capacity=3)
        logger.debug("a")
        logger.info("b")
        logger.warning("c")
        logger.error("d")
        entries = ring.entries()
        self.assertEqual([e["message"] for e in entries], ["b", "c", "d"])  # capacity respected
        self.assertEqual([e["message"] for e in ring.entries(min_level="warning")], ["c", "d"])
        self.assertEqual([e["message"] for e in ring.entries(after_seq=entries[1]["seq"])], ["d"])
        self.assertTrue((self.tmp / "logs" / "app.log").exists())
        applog.setup(None)  # release the file handle before the temp dir is removed


class ReportStoreTests(TempDirMixin, unittest.TestCase):
    def test_create_list_get(self):
        store = ReportStore(self.tmp)
        report = store.create({"title": "Stability does not refresh", "severity": "major",
                               "steps": "1. open editor"}, {"game": {"detected": False}})
        self.assertEqual(report["severity"], "major")
        self.assertTrue((self.tmp / f"{report['id']}.md").read_text(encoding="utf-8").startswith("# Stability"))
        self.assertEqual(store.list()[0]["id"], report["id"])
        self.assertEqual(store.get(report["id"])["steps"], "1. open editor")

    def test_duplicate_titles_get_unique_ids(self):
        store = ReportStore(self.tmp)
        a = store.create({"title": "Same"}, {})
        b = store.create({"title": "Same"}, {})
        self.assertNotEqual(a["id"], b["id"])
        self.assertEqual(len(store.list()), 2)

    def test_validation(self):
        store = ReportStore(self.tmp)
        with self.assertRaises(ReportError):
            store.create({"title": "  "}, {})
        with self.assertRaises(ReportError):
            store.create({"title": "x", "severity": "apocalyptic"}, {})

    def test_get_rejects_path_traversal(self):
        store = ReportStore(self.tmp)
        self.assertIsNone(store.get("../secrets"))
        self.assertIsNone(store.get("..\\x"))


class ServiceTests(TempDirMixin, unittest.TestCase):
    def test_game_data_is_always_marked_demo(self):
        svc = make_service(self.tmp)
        for payload in (svc.countries(), svc.country("ger"), svc.states(), svc.focus("GER"),
                        svc.equipment("GER")):
            self.assertEqual(payload["source"], DEMO)
            self.assertIn("DEMO", payload["note"])

    def test_nothing_is_writable_yet(self):
        svc = make_service(self.tmp)
        self.assertTrue(all(cap["write"] is False for cap in svc.capabilities().values()))
        self.assertFalse(svc.country("GER")["data"]["editable"])
        self.assertFalse(svc.focus("GER")["data"]["queue_supported"])

    def test_null_integration_marks_detection_unavailable(self):
        svc = make_service(self.tmp)
        status = svc.status()
        self.assertFalse(status["game"]["detected"])
        self.assertEqual(status["capabilities"]["detection"]["source"], UNAVAILABLE)
        self.assertEqual(CAPABILITIES["detection"]["source"], LIVE)  # global table not mutated

    def test_country_fields_cover_spec(self):
        keys = {f["key"] for f in demo.COUNTRY_FIELDS}
        self.assertEqual(keys, {"political_power", "stability", "war_support", "manpower", "fuel", "convoys",
                                "command_power", "army_experience", "air_experience", "navy_experience"})
        for tag in (c["tag"] for c in demo.COUNTRIES):
            self.assertEqual(set(demo.country(tag)["values"]), keys)

    def test_states_filter_by_owner_or_controller(self):
        svc = make_service(self.tmp)
        ids = {s["id"] for s in svc.states("ger")["data"]}
        self.assertEqual(ids, {"demo-1", "demo-2"})  # demo-2 is owned by POL, controlled by GER

    def test_unknown_country(self):
        svc = make_service(self.tmp)
        with self.assertRaises(NotFound):
            svc.country("XXX")

    def test_tools_have_explicit_scope(self):
        svc = make_service(self.tmp)
        for tool in svc.tools()["data"]:
            self.assertIn(tool["scope"], ("local", "shared"))
            self.assertIn(tool["status"], ("available", "planned"))
        shared = [t for t in svc.tools()["data"] if t["scope"] == "shared"]
        self.assertTrue(all(t["status"] == "planned" for t in shared))

    def test_create_report_attaches_environment(self):
        svc = make_service(self.tmp)
        report = svc.create_report({"title": "Env check"})["data"]
        self.assertIn("app", report["environment"])
        self.assertFalse(report["environment"]["game"]["detected"])
        json.dumps(report)  # serialisable

    def test_client_log_reaches_ring(self):
        svc = make_service(self.tmp)
        svc.client_log({"level": "warning", "message": "from ui"})
        last = svc.app_log(10, "debug", 0)["data"][-1]
        self.assertEqual((last["origin"], last["level"], last["message"]), ("ui", "warning", "from ui"))


if __name__ == "__main__":
    unittest.main()
