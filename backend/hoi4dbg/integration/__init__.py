"""Game integration layer.

Everything that touches Hearts of Iron IV (process, install, user files, and
later anything more invasive) lives in this package. The UI and API layers
only talk to the `GameIntegration` interface defined in `base`.
"""

from .base import GameIntegration, NullIntegration

__all__ = ["GameIntegration", "NullIntegration"]
