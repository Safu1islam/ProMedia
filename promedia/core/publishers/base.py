"""Publisher interface (DR-010 part A).

Frozen before T-011 depends on it, per protocol 04 step 3.

``capabilities()`` deliberately returns limits as UNKNOWN for real platforms.
The operator's instruction was explicit: rate limits and pricing must not be
written from model memory. An unknown limit must read as unknown, because a
plausible-looking guess is worse than a blank — it gets trusted.

``verify_published()`` exists because the retention policy permits deletion
only on "confirmed live on every target platform, not merely the API returned
200". Without it, retention cannot satisfy its own precondition.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

UNKNOWN = "UNKNOWN — verify against live platform documentation (project.md O-3)"


@dataclass(frozen=True)
class PublishResult:
    platform_post_id: str
    permalink: str | None
    published_at: str
    simulated: bool
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Capabilities:
    platform: str
    max_body_chars: int | str = UNKNOWN
    max_media_bytes: int | str = UNKNOWN
    posts_per_day: int | str = UNKNOWN
    rate_limit_note: str = UNKNOWN
    verified_against_documentation: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "max_body_chars": self.max_body_chars,
            "max_media_bytes": self.max_media_bytes,
            "posts_per_day": self.posts_per_day,
            "rate_limit_note": self.rate_limit_note,
            "verified_against_documentation": self.verified_against_documentation,
        }


class Publisher(Protocol):
    platform: str
    simulated: bool

    def capabilities(self) -> Capabilities: ...

    def publish(self, *, body: str, content_hash: str, credential_ref: str) -> PublishResult: ...

    def verify_published(self, platform_post_id: str) -> bool: ...
