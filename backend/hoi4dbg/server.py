"""Local JSON API (127.0.0.1 only, token-protected). Thin routing over DebuggerService."""

from __future__ import annotations

import hmac
import json
import re
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from urllib.parse import parse_qs, urlsplit

from .equipment_changes import ChangeError, EquipmentChanges
from .live.service import LiveError
from .reports import ReportError
from .service import DebuggerService, NotFound

TOKEN_HEADER = "X-HOI4DBG-Token"
MAX_BODY = 256 * 1024

Route = tuple[str, re.Pattern, Callable[..., dict]]


def _int(query: dict, key: str, default: int, lo: int, hi: int) -> int:
    try:
        value = int(query.get(key, [default])[0])
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


def _number(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LiveError("bad_amount", "amount must be a number")
    return float(value)


def _str(query: dict, key: str, default: str = "") -> str:
    return query.get(key, [default])[0]


def build_routes(svc: DebuggerService) -> list[Route]:
    def r(method: str, pattern: str, fn: Callable[..., dict]) -> Route:
        return method, re.compile(f"^{pattern}$"), fn

    tag = r"(?P<tag>[A-Za-z0-9_]{1,8})"
    changes = EquipmentChanges(svc)

    def live():
        if svc.live is None:
            raise LiveError("disabled", "Live game access is disabled (--no-game)")
        return svc.live

    def live_write(body: dict) -> dict:
        if body.get("confirm_local") is not True:
            raise LiveError("not_confirmed", "Direct memory writes must be enabled explicitly (local only)")
        before = body.get("expected_before")
        return live().write_value(str(body.get("field", "")), _number(body.get("value")),
                                  str(body.get("tag") or "").upper() or None,
                                  _number(before) if before is not None else None)

    def stockpile_write(body: dict) -> dict:
        if body.get("confirm_local") is not True:
            raise LiveError("not_confirmed", "Direct memory writes must be enabled explicitly (local only)")
        before = body.get("expected_before")
        return live().write_stockpile(str(body.get("id", "")), _number(body.get("amount")),
                                      str(body.get("tag") or "").upper() or None,
                                      _number(before) if before is not None else None)

    def combat_log_patch(body: dict) -> dict:
        enabled = body.get("enabled") is True
        if enabled and body.get("confirm_local") is not True:
            raise LiveError("not_confirmed", "The combat log patch must be enabled explicitly (local only)")
        return live().set_combat_log_patch(enabled)

    def construction_sort(body: dict) -> dict:
        if body.get("confirm_local") is not True:
            raise LiveError("not_confirmed", "Direct memory writes must be enabled explicitly (local only)")
        return svc.construction_sort(apply=True)

    def focus_autostart(body: dict) -> dict:
        if body.get("confirm_local") is not True:
            raise LiveError("not_confirmed", "Direct memory writes must be enabled explicitly (local only)")
        return svc.focus_autostart(apply=True)

    def calibration(body: dict) -> dict:
        field, action = str(body.get("field", "")), body.get("action")
        if action == "start":
            return live().start_calibration(field)
        if action == "refine":
            return live().refine_calibration(field, str(body.get("source", "")))
        if action == "reset":
            return live().reset_calibration(field)
        raise LiveError("bad_action", "action must be start, refine or reset")
    return [
        r("GET", "/api/health", lambda q, b: {"ok": True}),
        r("GET", "/api/status", lambda q, b: svc.status()),
        r("GET", "/api/countries", lambda q, b: svc.countries()),
        r("GET", f"/api/countries/{tag}", lambda q, b, tag: svc.country(tag)),
        r("GET", f"/api/countries/{tag}/stability", lambda q, b, tag: svc.stability(tag)),
        r("GET", f"/api/countries/{tag}/spirits", lambda q, b, tag: svc.spirits(tag)),
        r("GET", f"/api/countries/{tag}/government", lambda q, b, tag: svc.government(tag)),
        r("GET", f"/api/countries/{tag}/overview", lambda q, b, tag: svc.overview(tag)),
        r("GET", f"/api/countries/{tag}/resources", lambda q, b, tag: svc.resources(tag)),
        r("GET", f"/api/countries/{tag}/research", lambda q, b, tag: svc.research(tag)),
        r("GET", f"/api/countries/{tag}/trade-advice", lambda q, b, tag: svc.trade_advice(
            tag, _str(q, "mode") or "surplus", _int(q, "limit", 25, 10, 100) / 100)),
        r("GET", f"/api/countries/{tag}/military", lambda q, b, tag: svc.military(tag)),
        r("GET", "/api/summary/games", lambda q, b: svc.summary_games()),
        r("GET", r"/api/summary/games/(?P<gid>[A-Za-z0-9_.-]{1,80})", lambda q, b, gid: svc.summary_game(
            gid, (q.get("metric") or ["mil"])[0], [t for t in (q.get("tags") or [""])[0].upper().split(",") if t],
            (q.get("factions") or [""])[0] == "1", (q.get("groups_from") or [""])[0] or None)),
        r("GET", "/api/live/combat-log-patch", lambda q, b: live().combat_log_patch()),
        r("POST", "/api/live/combat-log-patch", lambda q, b: combat_log_patch(b)),
        r("GET", r"/api/summary/games/(?P<gid>[A-Za-z0-9_.-]{1,80})/groups", lambda q, b, gid: svc.summary_groups(gid)),
        r("POST", r"/api/summary/games/(?P<gid>[A-Za-z0-9_.-]{1,80})/groups", lambda q, b, gid: svc.summary_groups(gid, b)),
        r("GET", f"/api/countries/{tag}/doctrines", lambda q, b, tag: svc.doctrines(tag)),
        r("GET", f"/api/countries/{tag}/factories", lambda q, b, tag: svc.factories(tag)),
        r("GET", f"/api/countries/{tag}/construction", lambda q, b, tag: svc.construction(tag)),
        r("GET", "/api/research/tabs", lambda q, b: svc.research_tabs()),
        r("GET", f"/api/countries/{tag}/research/tree", lambda q, b, tag: svc.research_tree(tag, (q.get("folder") or [""])[0])),
        r("GET", f"/api/countries/{tag}/save-values",
          lambda q, b, tag: svc.country_save_values(tag, _str(q, "name") or None)),
        r("GET", "/api/states", lambda q, b: svc.states(_str(q, "owner") or None)),
        r("GET", f"/api/focus/{tag}/state", lambda q, b, tag: svc.focus_state(tag)),
        r("GET", f"/api/focus/{tag}", lambda q, b, tag: svc.focus(tag)),
        r("POST", f"/api/focus/{tag}/queue", lambda q, b, tag: svc.set_focus_queue(tag, b.get("queue"))),
        r("GET", f"/api/equipment/{tag}", lambda q, b, tag: svc.equipment(tag)),
        r("POST", f"/api/equipment/{tag}/changes", lambda q, b, tag: changes.create(
            tag, str(b.get("archetype", "")), b.get("amount"), str(b.get("variant", "")))),
        r("GET", r"/api/equipment/changes/(?P<op>eq-[0-9]{1,9})", lambda q, b, op: changes.poll(op)),
        r("GET", "/api/tools", lambda q, b: svc.tools()),
        r("GET", "/api/saves", lambda q, b: svc.saves_list()),
        r("GET", "/api/saves/analysis", lambda q, b: svc.save_analysis(_str(q, "name") or None)),
        r("GET", "/api/saves/fields", lambda q, b: svc.save_fields()),
        r("GET", "/api/live", lambda q, b: live().status()),
        r("GET", "/api/live/session", lambda q, b: svc.live_session()),
        r("GET", "/api/live/focus", lambda q, b: svc.live_focus(_str(q, "tag").upper() or None)),
        r("GET", "/api/live/values", lambda q, b: {"data": live().values(_str(q, "tag").upper() or None)}),
        r("POST", "/api/live/calibration", lambda q, b: calibration(b)),
        r("POST", "/api/live/write", lambda q, b: live_write(b)),
        r("GET", "/api/live/focus/autostart", lambda q, b: svc.focus_autostart(apply=False)),
        r("POST", "/api/live/focus/autostart", lambda q, b: focus_autostart(b)),
        r("GET", "/api/live/construction/sort", lambda q, b: svc.construction_sort(apply=False)),
        r("POST", "/api/live/construction/sort", lambda q, b: construction_sort(b)),
        r("GET", "/api/live/stockpile", lambda q, b: svc.live_stockpile(_str(q, "tag").upper() or None)),
        r("POST", "/api/live/stockpile", lambda q, b: stockpile_write(b)),
        r("POST", "/api/live/operations", lambda q, b: live().create_operation(
            str(b.get("field", "")), str(b.get("mode", "")), _number(b.get("amount")))),
        r("GET", r"/api/live/operations/(?P<op>op-[0-9]{1,9})", lambda q, b, op: live().poll_operation(op)),
        r("POST", r"/api/live/operations/(?P<op>op-[0-9]{1,9})/cancel",
          lambda q, b, op: live().cancel_operation(op)),
        r("GET", "/api/logs/app", lambda q, b: svc.app_log(
            _int(q, "limit", 200, 1, 2000), _str(q, "level", "debug"), _int(q, "after", 0, 0, 10**12))),
        r("POST", "/api/logs/app", lambda q, b: svc.client_log(b)),
        r("GET", "/api/logs/game", lambda q, b: svc.game_log_names()),
        r("GET", r"/api/logs/game/(?P<name>[A-Za-z0-9_.-]{1,64})",
          lambda q, b, name: svc.game_log(name, _int(q, "lines", 200, 1, 5000))),
        r("GET", "/api/reports", lambda q, b: svc.list_reports()),
        r("POST", "/api/reports", lambda q, b: svc.create_report(b)),
        r("GET", r"/api/reports/(?P<rid>[A-Za-z0-9-]{1,120})", lambda q, b, rid: svc.get_report(rid)),
    ]


def make_handler(svc: DebuggerService, token: str) -> type[BaseHTTPRequestHandler]:
    routes = build_routes(svc)

    class Handler(BaseHTTPRequestHandler):
        server_version = "HOI4Debugger"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args) -> None:
            pass  # status polling would flood the app log; failures are logged in _send

        def _send(self, status: int, payload: dict) -> None:
            if status >= 400:
                svc.log.debug("API %s %s -> %s %s", self.command, self.path, int(status), payload.get("error"))
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _dispatch(self, method: str) -> None:
            supplied = self.headers.get(TOKEN_HEADER, "")
            if not hmac.compare_digest(supplied.encode(), token.encode()):
                self._send(HTTPStatus.UNAUTHORIZED, {"error": "invalid token"})
                return

            parts = urlsplit(self.path)
            query = parse_qs(parts.query)
            body: dict = {}
            if method == "POST":
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    self._send(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "body too large"})
                    return
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except json.JSONDecodeError:
                    self._send(HTTPStatus.BAD_REQUEST, {"error": "invalid JSON"})
                    return
                if not isinstance(body, dict):
                    self._send(HTTPStatus.BAD_REQUEST, {"error": "JSON body must be an object"})
                    return

            path_matched = False
            for route_method, pattern, fn in routes:
                match = pattern.match(parts.path)
                if not match:
                    continue
                path_matched = True
                if route_method != method:
                    continue
                try:
                    self._send(HTTPStatus.OK, fn(query, body, **match.groupdict()))
                except NotFound as exc:
                    self._send(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                except ReportError as exc:
                    self._send(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                except (LiveError, ChangeError) as exc:
                    self._send(HTTPStatus.CONFLICT, {"error": str(exc), "code": exc.code})
                except Exception as exc:  # keep the server alive, surface the error in the app log
                    svc.log.exception("Unhandled error on %s %s", method, parts.path)
                    self._send(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"internal error: {exc}"})
                return
            if path_matched:
                self._send(HTTPStatus.METHOD_NOT_ALLOWED, {"error": "method not allowed"})
            else:
                self._send(HTTPStatus.NOT_FOUND, {"error": "not found"})

        def do_GET(self) -> None:
            self._dispatch("GET")

        def do_POST(self) -> None:
            self._dispatch("POST")

    return Handler


def make_server(svc: DebuggerService, token: str, port: int = 0) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer(("127.0.0.1", port), make_handler(svc, token))
    server.daemon_threads = True
    return server
