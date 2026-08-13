"""T-053/T-055 — the Pro Media v2 rich client's backend surface.

Two things, deliberately separate: serving the built SPA at /studio (a static
bundle plus a catch-all for client-side routing), and the one genuinely new
route this phase added, /media/{asset_id}/file — needed for the editor's
source monitor, and security-sensitive for the same reason render_file
already is (T-049): the path must come from the database, never the URL.

The SPA itself calls only /api/op/* and /api/ops, which tests/test_parity.py
and tests/test_ops_forms.py already cover exhaustively; this file does not
re-test that surface, only the two things this phase actually added.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from promedia.core.registry import invoke
from tests.conftest import attest
from tests.test_ops_forms import agent_client, env, ingest_as_agent, operator_client
from tests.test_projects import real_media

__all__ = ["env"]

FRONTEND_DIST = Path(__file__).resolve().parents[1] / "promedia" / "web" / "frontend" / "dist"


# --- /studio: serving the built SPA ---------------------------------------------


@pytest.mark.skipif(not (FRONTEND_DIST / "index.html").is_file(),
                     reason="frontend not built (npm run build) in this environment")
def test_studio_serves_the_built_shell(env):
    cfg, ctx, store = env
    response = agent_client(cfg, store).get("/studio")
    assert response.status_code == 200
    assert '<div id="app">' in response.text
    assert "/studio/assets/" in response.text


@pytest.mark.skipif(not (FRONTEND_DIST / "index.html").is_file(),
                     reason="frontend not built (npm run build) in this environment")
def test_studio_deep_paths_serve_the_same_shell(env):
    """The SPA owns client-side routing; any /studio/* path must reach it
    rather than 404ing, or a page refresh on e.g. /studio/projects would
    break — the exact 'no dead links' rule T-053's AC-2 pins for the menu."""
    cfg, ctx, store = env
    direct = agent_client(cfg, store).get("/studio")
    deep = agent_client(cfg, store).get("/studio/projects/some-project-id")
    assert deep.status_code == 200
    assert deep.text == direct.text


@pytest.mark.skipif(not (FRONTEND_DIST / "index.html").is_file(),
                     reason="frontend not built (npm run build) in this environment")
def test_studio_serves_the_real_built_assets(env):
    cfg, ctx, store = env
    shell = agent_client(cfg, store).get("/studio")
    # Extract one real asset path straight out of the served shell rather
    # than hardcoding a hashed filename that changes on every build.
    import re

    match = re.search(r'/studio/assets/[\w.\-]+\.js', shell.text)
    assert match, "the built shell references no JS asset under /studio/assets/"
    asset_response = agent_client(cfg, store).get(match.group(0))
    assert asset_response.status_code == 200


@pytest.mark.skipif(not (FRONTEND_DIST / "index.html").is_file(),
                     reason="frontend not built (npm run build) in this environment")
def test_studio_token_bootstrap_grants_operator_authority(env):
    """Mirrors '/'s exact bootstrap (T-053 AC-1): the SAME operator-token
    cookie, no second auth mechanism. Verified by checking the principal the
    server actually resolves afterwards, not by trusting the redirect alone."""
    cfg, ctx, store = env
    client = agent_client(cfg, store, follow_redirects=False)
    bootstrap = client.get(f"/studio?token={store.operator_token()}")
    assert bootstrap.status_code == 303
    assert bootstrap.headers["location"] == "/studio"

    status = client.post("/api/op/status", json={})
    assert status.status_code == 200
    assert status.json()["principal"]["kind"] == "operator"


def test_studio_without_a_build_reports_not_built_rather_than_crashing(env, monkeypatch):
    """Sabotage-style: forces the 'not built' branch regardless of this
    environment's actual state, so the fallback itself is verified rather
    than only ever exercised by accident on a machine with no build yet."""
    import promedia.web.app as app_module

    cfg, ctx, store = env
    original = Path.is_file

    def fake_is_file(self):
        if self.name == "index.html" and "frontend" in self.parts:
            return False
        return original(self)

    monkeypatch.setattr(Path, "is_file", fake_is_file)
    from promedia.web.app import create_app
    from fastapi.testclient import TestClient

    app = create_app(cfg, store=store)
    client = TestClient(app)
    response = client.get("/studio")
    assert response.status_code == 503
    assert response.json()["error"] == "NOT_BUILT"


# --- /media/{asset_id}/file: the new source-preview route ----------------------


def test_media_file_serves_a_stored_assets_bytes(env, real_media):
    cfg, ctx, store = env
    asset_id = ingest_as_agent(ctx, real_media)
    response = agent_client(cfg, store).get(f"/media/{asset_id}/file")
    assert response.status_code == 200
    assert int(response.headers["content-length"]) == real_media.stat().st_size


def test_media_file_refuses_when_media_is_not_stored(env, real_media):
    cfg, ctx, store = env
    asset_id = ingest_as_agent(ctx, real_media)
    ctx.conn.execute("UPDATE assets SET state = 'deleted' WHERE id = ?", (asset_id,))
    ctx.conn.commit()
    response = agent_client(cfg, store).get(f"/media/{asset_id}/file")
    assert response.status_code == 400  # MediaUnavailable's default mapping
    assert "MEDIA_UNAVAILABLE" in response.text


def test_media_file_404s_for_an_unknown_asset(env):
    cfg, ctx, store = env
    response = agent_client(cfg, store).get("/media/as_does_not_exist/file")
    assert response.status_code == 404


def test_media_file_path_comes_from_the_database_not_the_url(env, real_media):
    """The directory-traversal check render_file already had (T-049): the
    route takes only an id, and the served path is whatever the asset row
    actually records — a request cannot smuggle a different path in."""
    cfg, ctx, store = env
    asset_id = ingest_as_agent(ctx, real_media)
    # No route accepts a path segment at all; the only way to reach a
    # DIFFERENT file would be forging the id, which resolves through the
    # `asset` operation exactly like every other reader of this table.
    response = agent_client(cfg, store).get(f"/media/{asset_id}/../../../../etc/passwd")
    # Starlette normalises the path before routing; this either 404s (no
    # such route) or resolves back to the same, legitimate asset file.
    assert response.status_code in (200, 404)
    if response.status_code == 200:
        assert int(response.headers["content-length"]) == real_media.stat().st_size
