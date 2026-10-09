"""Tester-written test reports, stored as JSON + Markdown in the debugger's data dir."""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

SEVERITIES = ("info", "minor", "major", "critical")
TEXT_FIELDS = ("title", "area", "steps", "expected", "actual", "notes")
MAX_FIELD_LEN = 10_000


class ReportError(ValueError):
    pass


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:40] or "report"


class ReportStore:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)

    def create(self, payload: dict, environment: dict) -> dict:
        if not isinstance(payload, dict):
            raise ReportError("Report payload must be an object")
        title = str(payload.get("title", "")).strip()
        if not title:
            raise ReportError("Title is required")
        severity = str(payload.get("severity", "info")).lower()
        if severity not in SEVERITIES:
            raise ReportError(f"Severity must be one of: {', '.join(SEVERITIES)}")

        report = {field: str(payload.get(field, "")).strip()[:MAX_FIELD_LEN] for field in TEXT_FIELDS}
        report["title"] = title[:200]
        report["severity"] = severity
        now = dt.datetime.now()
        report["created"] = now.isoformat(timespec="seconds")
        report["id"] = f"{now:%Y%m%d-%H%M%S}-{_slug(title)}"
        report["environment"] = environment

        base = self.directory / report["id"]
        suffix = 1
        while base.with_suffix(".json").exists():
            suffix += 1
            report["id"] = f"{now:%Y%m%d-%H%M%S}-{_slug(title)}-{suffix}"
            base = self.directory / report["id"]

        base.with_suffix(".json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        base.with_suffix(".md").write_text(to_markdown(report), encoding="utf-8")
        return report

    def list(self) -> list[dict]:
        items = []
        for path in sorted(self.directory.glob("*.json"), reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            items.append({k: data.get(k) for k in ("id", "title", "severity", "area", "created")})
        return items

    def get(self, report_id: str) -> dict | None:
        if not re.fullmatch(r"[A-Za-z0-9-]+", report_id or ""):
            return None
        path = self.directory / f"{report_id}.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))


def to_markdown(report: dict) -> str:
    env = report.get("environment") or {}
    lines = [
        f"# {report['title']}",
        "",
        f"- **Severity:** {report['severity']}",
        f"- **Area:** {report.get('area') or '-'}",
        f"- **Created:** {report['created']}",
        "",
    ]
    for field, heading in (("steps", "Steps to reproduce"), ("expected", "Expected"),
                           ("actual", "Actual"), ("notes", "Notes")):
        lines += [f"## {heading}", "", report.get(field) or "-", ""]
    lines += ["## Environment", "", "```json", json.dumps(env, indent=2, ensure_ascii=False), "```", ""]
    return "\n".join(lines)
