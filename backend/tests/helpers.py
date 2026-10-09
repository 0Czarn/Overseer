from __future__ import annotations

import tempfile
from pathlib import Path

from hoi4dbg import applog
from hoi4dbg.integration import GameIntegration, NullIntegration
from hoi4dbg.reports import ReportStore
from hoi4dbg.service import DebuggerService


def make_service(tmp: Path, integration: GameIntegration | None = None) -> DebuggerService:
    logger, ring = applog.setup(None)
    return DebuggerService(integration or NullIntegration("test"), ReportStore(tmp / "reports"), ring,
                           logger, str(tmp))


class TempDirMixin:
    def setUp(self) -> None:  # noqa: D401 - unittest hook
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()
