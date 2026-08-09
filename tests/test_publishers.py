"""T-012 — the stub is a fabrication and must behave like one."""

from __future__ import annotations

import pytest

from promedia.core import publishers
from promedia.core.publishers.base import UNKNOWN
from promedia.core.publishers.stub import SIMULATED_MARKER, StubPublisher
from promedia.errors import ConfigurationError
from tests.conftest import make_config


def test_stub_requires_explicit_simulation_flag(config):
    """AC-2: a fabrication must not be reachable by default."""
    with pytest.raises(ConfigurationError, match="F-001"):
        publishers.for_platform("x", config)


def test_stub_marks_simulated(tmp_path):
    """AC-1: and the marker is visibly fake, not a plausible id."""
    cfg = make_config(tmp_path, **{"publishing.allow_simulation": True})
    publisher = publishers.for_platform("x", cfg)
    result = publisher.publish(body="hello", content_hash="abc", credential_ref="x:me")
    assert result.simulated is True
    assert SIMULATED_MARKER in result.platform_post_id
    assert "NOTHING WAS PUBLISHED" in result.detail["warning"]


def test_stub_never_confirms_published(tmp_path):
    """verify_published gates irreversible deletion. A stub must never assert live."""
    cfg = make_config(tmp_path, **{"publishing.allow_simulation": True})
    publisher = publishers.for_platform("linkedin", cfg)
    assert publisher.verify_published("anything") is False


def test_real_platform_limits_are_unknown_not_guessed(agent_ctx):
    """AC-3: operator instruction — no rate limits from model memory."""
    from promedia.core.registry import invoke

    caps = invoke(agent_ctx, "platform-capabilities", {"platform": "x"})
    assert caps["max_body_chars"] == UNKNOWN
    assert caps["posts_per_day"] == UNKNOWN
    assert caps["verified_against_documentation"] is False


def test_unsupported_platform_rejected(tmp_path):
    cfg = make_config(tmp_path, **{"publishing.allow_simulation": True})
    with pytest.raises(ConfigurationError):
        publishers.for_platform("myspace", cfg)
