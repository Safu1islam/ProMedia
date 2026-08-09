"""T-020 — dual-surface parity as a build gate (F-1, S4).

S4 calls a single-surface capability a build failure, not a gap. These tests
are what make that true: they enumerate the registry and assert both surfaces
cover it, so adding an operation reachable from only one place fails the suite
rather than shipping.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from promedia.cli import _build_parser
from promedia.core.registry import load_operations
from promedia.web.app import create_app
from tests.conftest import make_config

OPERATIONS = load_operations()


def test_every_operation_on_both_surfaces():
    """AC-1: the registry is the contract; both surfaces must satisfy it."""
    parser = _build_parser(OPERATIONS)
    cli_commands: set[str] = set()
    for action in parser._actions:
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict):
            cli_commands |= set(choices)

    missing_from_cli = set(OPERATIONS) - cli_commands
    assert not missing_from_cli, f"operations absent from the CLI surface: {sorted(missing_from_cli)}"


def test_web_covers_every_operation(tmp_path):
    """T-005 AC-3: the generic /api/op/{name} route projects the whole registry."""
    cfg = make_config(tmp_path)
    client = TestClient(create_app(cfg))
    listed = client.get("/api/ops").json()
    web_names = {op["name"] for op in listed["operations"]}
    missing_from_web = set(OPERATIONS) - web_names
    assert not missing_from_web, f"operations absent from the web surface: {sorted(missing_from_web)}"


def test_authority_identical_across_surfaces(tmp_path, monkeypatch):
    """AC-2 / T-003 AC-3: the same call is denied identically on both surfaces.

    Authority lives in the operation layer, so this holds by construction — the
    test exists to detect anyone moving it into an adapter.
    """
    monkeypatch.setenv("PROMEDIA_CREDENTIAL_STORE", str(tmp_path / "creds.json"))
    cfg = make_config(tmp_path)

    # Web surface, no operator token in the store -> agent authority.
    client = TestClient(create_app(cfg))
    response = client.post("/api/op/approve-post", data={"post_id": "post_missing"})
    assert response.status_code == 403
    assert response.json()["error"] == "FORBIDDEN"

    # Operation layer directly, agent principal -> the same refusal.
    from promedia.core import db
    from promedia.core.principal import agent
    from promedia.core.registry import Context, invoke
    from promedia.errors import Forbidden

    conn = db.connect(cfg.db_path)
    db.apply_schema(conn)
    ctx = Context(config=cfg, conn=conn, principal=agent("cli"))
    with pytest.raises(Forbidden):
        invoke(ctx, "approve-post", {"post_id": "post_missing"})
    conn.close()


def test_operation_metadata_matches_across_surfaces(tmp_path):
    """Parameters and authority must be described identically, or agents mis-call."""
    cfg = make_config(tmp_path)
    client = TestClient(create_app(cfg))
    web = {op["name"]: op for op in client.get("/api/ops").json()["operations"]}
    for name, op in OPERATIONS.items():
        assert web[name]["authority"] == op.authority
        assert [p["name"] for p in web[name]["params"]] == [p.name for p in op.params]


def test_no_business_logic_in_adapters():
    """The invariant that keeps parity true: adapters must stay thin.

    A crude but effective guard — adapters may not import domain modules
    directly, because doing so is how logic starts living on one surface.
    """
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "promedia"
    domain_modules = ("core.posts", "core.rights_engine", "core.ingest", "core.provenance")
    for adapter in (root / "cli.py", root / "web" / "app.py"):
        text = adapter.read_text(encoding="utf-8")
        for module in domain_modules:
            assert f"import {module}" not in text and f"from ..{module}" not in text, (
                f"{adapter.name} reaches into {module}; adapters must go through the registry"
            )
