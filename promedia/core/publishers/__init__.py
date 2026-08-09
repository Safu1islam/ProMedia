"""Publisher selection.

Real adapters (T-019) are blocked on credentials and on verifying access terms
against live documentation (O-3). Until then the only available publisher is
the stub, and it is disabled by default.
"""

from __future__ import annotations

from ...config import Config
from ...errors import ConfigurationError
from .base import Capabilities, Publisher, PublishResult
from .stub import StubPublisher

SUPPORTED_PLATFORMS = ("x", "linkedin")

__all__ = ["Capabilities", "Publisher", "PublishResult", "StubPublisher", "for_platform", "SUPPORTED_PLATFORMS"]


def for_platform(platform: str, config: Config) -> Publisher:
    key = platform.strip().lower()
    if key not in SUPPORTED_PLATFORMS:
        raise ConfigurationError(
            f"unsupported platform '{platform}'", platform=platform, supported=list(SUPPORTED_PLATFORMS)
        )
    allow_simulation = bool(config.get("publishing", "allow_simulation"))
    # No real adapter exists yet; this raises unless simulation is explicit.
    return StubPublisher(key, allow_simulation=allow_simulation)
