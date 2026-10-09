import datetime as dt
import json
import os
import sys
import time
import unittest
from pathlib import Path

from hoi4dbg.integration import install as inst
from hoi4dbg.integration import winproc
from hoi4dbg.integration.hoi4 import Hoi4Integration
from hoi4dbg.integration.session import parse_game_log
from hoi4dbg.integration.userdata import UserData, resolve_user_dir

from helpers import TempDirMixin, make_service

HASH = "c01a3d507f10bd8c713e88234de69ca110618138"
OTHER_HASH = "ffff3d507f10bd8c713e88234de69ca110618138"

# Shapes copied from a real 1.19.3 install / user folder.
LIBRARYFOLDERS = r'''"libraryfolders"
{
	"0"
	{
		"path"		"{LIB0}"
		"apps"
		{
			"4000"		"7274418072"
		}
	}
	"1"
	{
		"path"		"{LIB1}"
		"apps"
		{
			"394360"		"6783407654"
		}
	}
}
'''
APPMANIFEST = '''"AppState"
{
	"appid"		"394360"
	"name"		"Hearts of Iron IV"
	"installdir"		"Hearts of Iron IV"
	"buildid"		"25205862"
}
'''
LAUNCHER_SETTINGS = {
    "gameId": "hoi4",
    "version": "Operation Postern v1.19.3.0.c01a (5632)",
    "rawVersion": "1.19.3.0",
    "gameDataPath": "%USER_DOCUMENTS%/Paradox Interactive/Hearts of Iron IV",
}
CODE_REVISIONS = f"""game_hash_long: {{hash}}
game_hash_short: c01a3d507
game_timestamp: 2026-09-09 10:59:00 +0200
game_commit_count: 1
"""
GAME_LOG = """[09:47:34][no_game_date][defines.cpp:270]: 4470 defines loaded
[09:47:53][no_game_date][gameapplication.cpp:2968]: Resetting game
[09:47:55][1936.01.01.12][history.cpp:165]: Executing History from 2.1.1.1 to  1936.1.1.12
[09:48:12][1936.01.01.12][frontend.cpp:682]:

		[[ Launching SINGLEPLAYER-game ]]
	Start-date: 1936.1.1.12

[09:48:16][1936.01.01.12][effectbase.cpp:1783]: Something went wrong with the Conflict Risk stuff
"""


def vdf_path(p: Path) -> str:
    return str(p).replace("\\", "\\\\")


class FixtureMixin(TempDirMixin):
    """Builds a fake Steam + HOI4 install + user folder in a temp dir."""

    def setUp(self):
        super().setUp()
        self.steam = self.tmp / "Steam"
        self.lib1 = self.tmp / "SteamLibrary"
        (self.steam / "steamapps").mkdir(parents=True)
        (self.steam / "steamapps" / "libraryfolders.vdf").write_text(
            LIBRARYFOLDERS.replace("{LIB0}", vdf_path(self.steam)).replace("{LIB1}", vdf_path(self.lib1)),
            encoding="utf-8")
        steamapps = self.lib1 / "steamapps"
        self.install = steamapps / "common" / "Hearts of Iron IV"
        self.install.mkdir(parents=True)
        (steamapps / "appmanifest_394360.acf").write_text(APPMANIFEST, encoding="utf-8")
        (self.install / "hoi4.exe").write_bytes(b"")
        (self.install / "launcher-settings.json").write_text(json.dumps(LAUNCHER_SETTINGS), encoding="utf-8")
        (self.install / "hoi4_rev.txt").write_text(HASH, encoding="utf-8")

        self.user = self.tmp / "Documents" / "Paradox Interactive" / "Hearts of Iron IV"
        (self.user / "logs").mkdir(parents=True)
        (self.user / "save games").mkdir()
        (self.user / "logs" / "game.log").write_text(GAME_LOG, encoding="utf-8")
        (self.user / "logs" / "code_revisions.log").write_text(CODE_REVISIONS.format(hash=HASH), encoding="utf-8")
        (self.user / "continue_game.json").write_text(
            '{\n\t"title":\t"German Reich 1937.3.1.2",\n\t"filename":\t"autosave.hoi4",\n\t"is_remote":\tfalse\n}',
            encoding="utf-8")
        self.processes: list[dict] = []

    def running(self, started: dt.datetime | None = None, path: str | None = "default"):
        started = started or dt.datetime.now(dt.timezone.utc) - dt.timedelta(minutes=10)
        self.processes = [{"pid": 4242, "name": "hoi4.exe",
                           "path": str(self.install / "hoi4.exe") if path == "default" else path,
                           "started": started.isoformat(timespec="seconds"), "uptime_s": 600}]

    def integration(self) -> Hoi4Integration:
        return Hoi4Integration(process_finder=lambda name: list(self.processes),
                               steam_path_finder=lambda: self.steam, user_dir=self.user)


class VdfTests(unittest.TestCase):
    def test_nested_and_escaped(self):
        data = inst.parse_vdf('"a" { "path" "C:\\\\X\\\\Y" "b" { "c" "1" } "d" "say \\"hi\\"" }')
        self.assertEqual(data["a"]["path"], "C:\\X\\Y")
        self.assertEqual(data["a"]["b"], {"c": "1"})
        self.assertEqual(data["a"]["d"], 'say "hi"')

    def test_appmanifest(self):
        self.assertEqual(inst.parse_vdf(APPMANIFEST)["AppState"]["buildid"], "25205862")

    def test_unbalanced_input_does_not_crash(self):
        self.assertIsInstance(inst.parse_vdf('"a" { "b" "c" } } } "x"'), dict)


class InstallTests(FixtureMixin, unittest.TestCase):
    def test_libraries_and_install_lookup(self):
        libs = inst.steam_libraries(self.steam)
        self.assertEqual(libs, [self.steam, self.lib1])
        install_dir, manifest = inst.find_install_dir(libs)
        self.assertEqual(install_dir, self.install)
        self.assertEqual(manifest["buildid"], "25205862")

    def test_old_libraryfolders_format(self):
        (self.steam / "steamapps" / "libraryfolders.vdf").write_text(
            f'"LibraryFolders"\n{{\n\t"TimeNextStatsReport"\t"1"\n\t"1"\t"{vdf_path(self.lib1)}"\n}}', encoding="utf-8")
        self.assertIn(self.lib1, inst.steam_libraries(self.steam))

    def test_version(self):
        version = inst.read_version(self.install)
        self.assertEqual(version["raw"], "1.19.3.0")
        self.assertEqual(version["build_suffix"], "c01a")
        self.assertEqual(version["display"], "Operation Postern v1.19.3.0.c01a (5632)")
        self.assertIsNone(inst.read_version(self.tmp))

    def test_revisions(self):
        self.assertEqual(inst.read_install_revision(self.install), HASH)
        parsed = inst.parse_code_revisions(CODE_REVISIONS.format(hash=HASH))
        self.assertEqual(parsed["game_hash_short"], "c01a3d507")
        self.assertEqual(parsed["game_timestamp"], "2026-09-09 10:59:00 +0200")


class SessionTests(unittest.TestCase):
    def test_parse_real_game_log_shape(self):
        hints = parse_game_log(GAME_LOG)
        self.assertEqual(hints["launch_type"], "SINGLEPLAYER")
        self.assertEqual(hints["start_date"], "1936.1.1.12")
        self.assertEqual(hints["last_game_date"], "1936.01.01.12")
        self.assertEqual(hints["last_log_time"], "09:48:16")

    def test_menu_only_log(self):
        hints = parse_game_log("[09:47:34][no_game_date][defines.cpp:270]: 4470 defines loaded\n")
        self.assertIsNone(hints["last_game_date"])
        self.assertIsNone(hints["launch_type"])


class UserDataTests(FixtureMixin, unittest.TestCase):
    def test_summary_and_logs(self):
        ud = UserData(self.user)
        self.assertEqual(ud.summary()["last_save"]["title"], "German Reich 1937.3.1.2")
        self.assertEqual(ud.log_names(), ["code_revisions.log", "game.log"])
        tail = ud.tail("game.log", 2)
        self.assertEqual(len(tail["lines"]), 2)
        self.assertTrue(tail["truncated"])

    def test_rejects_path_traversal(self):
        (self.user / "secret.txt").write_text("x", encoding="utf-8")
        ud = UserData(self.user)
        for name in ("../secret.txt", "..\\continue_game.json", "game.log/..", "x.txt", ""):
            self.assertIsNone(ud.tail(name, 10), name)

    def test_tail_of_big_file_drops_partial_first_line(self):
        big = self.user / "logs" / "big.log"
        big.write_text("".join(f"line {i:07d}\n" for i in range(250_000)), encoding="utf-8")  # ~3 MB
        tail = UserData(self.user).tail("big.log", 0)
        self.assertTrue(all(line.startswith("line ") and len(line) == 12 for line in tail["lines"]))
        self.assertEqual(tail["lines"][-1], "line 0249999")

    def test_resolve_user_dir_from_launcher_setting(self):
        resolved = resolve_user_dir("%USER_DOCUMENTS%/Paradox Interactive/Hearts of Iron IV")
        self.assertEqual(resolved.parts[-2:], ("Paradox Interactive", "Hearts of Iron IV"))


class Hoi4IntegrationTests(FixtureMixin, unittest.TestCase):
    def test_not_running(self):
        snap = self.integration().detect()
        self.assertIsNone(snap["process"])
        self.assertEqual(snap["install"]["source"], "Steam library")
        self.assertEqual(snap["install"]["version"]["raw"], "1.19.3.0")
        self.assertEqual(snap["install"]["steam"]["build_id"], "25205862")
        self.assertIsNone(snap["session"])  # no process -> no session hints
        self.assertEqual(snap["warnings"], [])

    def test_running(self):
        self.running()
        snap = self.integration().detect()
        self.assertEqual(snap["process"]["pid"], 4242)
        self.assertEqual(snap["install"]["source"], "running process")
        self.assertEqual(snap["session"]["launch_type"], "SINGLEPLAYER")
        self.assertTrue(snap["session"]["from_current_run"])
        rev = snap["install"]["revision"]
        self.assertEqual((rev["install_hash"], rev["running_hash"], rev["from_current_run"]), (HASH, HASH, True))
        self.assertEqual(snap["warnings"], [])

    def test_build_mismatch_is_reported(self):
        self.running()
        (self.user / "logs" / "code_revisions.log").write_text(CODE_REVISIONS.format(hash=OTHER_HASH), encoding="utf-8")
        self.assertTrue(any("differs" in w for w in self.integration().detect()["warnings"]))

    def test_stale_game_log_is_ignored(self):
        self.running(started=dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1))  # log older than process
        snap = self.integration().detect()
        self.assertIsNone(snap["session"])
        self.assertTrue(any("older than the running process" in w for w in snap["warnings"]))
        self.assertFalse(snap["install"]["revision"]["from_current_run"])

    def test_access_denied_and_multiple_processes(self):
        self.running(path=None)
        self.processes.append({**self.processes[0], "pid": 4343})
        snap = self.integration().detect()
        self.assertEqual(snap["install"]["source"], "Steam library")  # falls back when exe path is unknown
        self.assertTrue(any("2 hoi4.exe processes" in w for w in snap["warnings"]))
        self.assertTrue(any("access denied" in w for w in snap["warnings"]))

    def test_process_outside_steam_library(self):
        other = self.tmp / "Other" / "hoi4.exe"
        other.parent.mkdir()
        other.write_bytes(b"")
        self.running(path=str(other))
        snap = self.integration().detect()
        self.assertEqual(snap["install"]["path"], str(other.parent))
        self.assertIsNone(snap["install"]["version"])
        self.assertTrue(any("not the Steam install" in w for w in snap["warnings"]))

    def test_nothing_installed(self):
        integration = Hoi4Integration(process_finder=lambda n: [], steam_path_finder=lambda: None,
                                      user_dir=self.tmp / "missing")
        snap = integration.detect()
        self.assertIsNone(snap["install"])
        self.assertIsNone(snap["userdata"])
        self.assertEqual(len(snap["warnings"]), 2)

    def test_process_enumeration_failure_is_a_warning(self):
        def broken(name):
            raise OSError(5, "denied")
        integration = Hoi4Integration(process_finder=broken, steam_path_finder=lambda: self.steam, user_dir=self.user)
        snap = integration.detect()
        self.assertIsNone(snap["process"])
        self.assertTrue(any("Process enumeration failed" in w for w in snap["warnings"]))

    def test_install_lookup_is_cached(self):
        calls = []
        integration = Hoi4Integration(process_finder=lambda n: [], user_dir=self.user,
                                      steam_path_finder=lambda: calls.append(1) or self.steam)
        integration.detect()
        integration.detect()
        self.assertEqual(len(calls), 1)

    def test_service_exposes_game_logs(self):
        self.running()
        svc = make_service(self.tmp, self.integration())
        status = svc.status()
        self.assertTrue(status["game"]["detected"])
        self.assertEqual(status["capabilities"]["detection"]["source"], "live")
        self.assertIn("game.log", svc.game_log_names()["data"])
        self.assertEqual(svc.game_log("game.log", 1)["source"], "live")
        self.assertEqual(svc.game_log("../x.log", 1)["source"], "unavailable")


class WinProcTests(unittest.TestCase):
    def test_find_processes_filters_by_name(self):
        found = winproc.find_processes("hoi4.exe", lister=lambda: [(1, "explorer.exe"), (2, "HOI4.EXE")],
                                       details=lambda pid: {"path": f"p{pid}"})
        self.assertEqual(found, [{"pid": 2, "name": "HOI4.EXE", "path": "p2"}])

    @unittest.skipUnless(sys.platform == "win32", "WinAPI test")
    def test_real_winapi_sees_this_process(self):
        pids = dict(winproc.list_processes())
        self.assertIn(os.getpid(), pids)
        details = winproc.process_details(os.getpid())
        self.assertEqual(Path(details["path"]).name.lower(), Path(sys.executable).name.lower())
        started = dt.datetime.fromisoformat(details["started"])
        self.assertLess(abs(time.time() - started.timestamp()), 3600)
        self.assertGreaterEqual(details["uptime_s"], 0)

    @unittest.skipUnless(sys.platform == "win32", "WinAPI test")
    def test_missing_pid(self):
        self.assertIsNone(winproc.process_details(0xFFFFFFF0)["path"])


if __name__ == "__main__":
    unittest.main()
