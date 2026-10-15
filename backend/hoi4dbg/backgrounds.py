"""The user's own background images for the app (Options tab): JPG / PNG files kept in <data dir>/backgrounds.

Added as data: URIs from the renderer (it has no file system access), checked by their magic bytes, stored under a
random id; the original file name is kept in <id>.json for the list."""

from __future__ import annotations

import base64
import json
import re
import secrets
from pathlib import Path

MAX_BYTES = 12 * 1024 * 1024
MAX_COUNT = 30
UPLOAD_BODY = MAX_BYTES * 4 // 3 + 4096   # a base64 data: URI of MAX_BYTES and the JSON around it
ID = re.compile(r"^[0-9a-f]{16}$")
DATA_URI = re.compile(r"^data:image/(png|jpeg|jpg);base64,(.+)$", re.S)
KINDS = {"png": (b"\x89PNG\r\n\x1a\n", "image/png"), "jpg": (b"\xff\xd8\xff", "image/jpeg")}


class BackgroundError(ValueError):
    pass


class Backgrounds:
    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def _file(self, bid: str) -> Path | None:
        if not ID.match(bid or ""):
            raise BackgroundError("bad background id")
        return next((p for p in (self.folder / f"{bid}.{k}" for k in KINDS) if p.exists()), None)

    def list(self) -> list[dict]:
        """[{"id", "name", "size"}], oldest first."""
        out = []
        for meta in sorted(self.folder.glob("*.json")) if self.folder.exists() else []:
            try:
                info = json.loads(meta.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            path = self._file(meta.stem) if ID.match(meta.stem) else None
            if path:
                out.append({"id": meta.stem, "name": info.get("name") or path.name, "size": path.stat().st_size,
                            "added": info.get("added")})
        return sorted(out, key=lambda b: b.get("added") or "")

    def add(self, name: str, data_uri: str, added: str) -> dict:
        m = DATA_URI.match(data_uri or "")
        if not m:
            raise BackgroundError("Only JPG and PNG images can be added")
        try:
            raw = base64.b64decode(m.group(2), validate=False)
        except ValueError:
            raise BackgroundError("The image data is broken") from None
        kind = next((k for k, (magic, _) in KINDS.items() if raw.startswith(magic)), None)
        if kind is None:
            raise BackgroundError("The file is not a JPG or PNG image")
        if len(raw) > MAX_BYTES:
            raise BackgroundError(f"The image is larger than {MAX_BYTES // (1024 * 1024)} MB")
        if len(self.list()) >= MAX_COUNT:
            raise BackgroundError(f"At most {MAX_COUNT} backgrounds - delete one first")
        self.folder.mkdir(parents=True, exist_ok=True)
        bid = secrets.token_hex(8)
        (self.folder / f"{bid}.{kind}").write_bytes(raw)
        clean = re.sub(r"[\x00-\x1f]", "", str(name or ""))[:120] or f"background.{kind}"
        (self.folder / f"{bid}.json").write_text(json.dumps({"name": clean, "added": added}), encoding="utf-8")
        return {"id": bid, "name": clean, "size": len(raw), "added": added}

    def get(self, bid: str) -> str:
        """The image as a data: URI."""
        path = self._file(bid)
        if path is None:
            raise FileNotFoundError(bid)
        mime = KINDS[path.suffix[1:]][1]
        return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"

    def delete(self, bid: str) -> None:
        path = self._file(bid)
        if path is None:
            raise FileNotFoundError(bid)
        path.unlink()
        (self.folder / f"{bid}.json").unlink(missing_ok=True)
