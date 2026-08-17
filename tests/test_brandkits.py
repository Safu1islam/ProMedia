"""T-068 — brand kits: data model and CRUD operations (DR-021).

Split from what this task does NOT cover yet: ``apply-brand-kit`` needs a new
``ImageOverlay`` type in ``promedia.core.media.edl`` plus a compiler branch in
``promedia.core.media.render``, and at the time this file was written those
two files (and ``tests/test_edl.py``) were under an active file lock held by
a concurrent session working T-064 (colour grading, same paths — see
R-018/R-019). That half of DR-021 is deferred, not worked around, so this
file tests exactly what create/list/update/delete-brand-kit and the AC-4
backup classification actually do.

AC-1's rights-declaration gate is proved against both failure shapes: an
asset id that does not exist at all, and one that exists in the ``assets``
table but was never ingested through the declaration-requiring path — the
concrete case a rendered derivative produces (``projects.render()``
registers its output with a rights VERDICT, inherited from its sources, but
writes no ``rights_declarations`` row of its own).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from promedia.core import backup
from promedia.core.db import iso, new_id
from promedia.core.registry import invoke
from promedia.errors import NotFound, ValidationError
from tests.conftest import declaration_original


def _ingest_logo(ctx, media_file: Path) -> str:
    result = invoke(
        ctx, "ingest",
        {"source_path": str(media_file), "declaration": declaration_original()},
    )
    return result["asset_id"]


def _undeclared_asset(ctx) -> str:
    """An asset row with NO rights_declarations row — the shape a rendered
    derivative produces (see module docstring), built directly rather than
    through a real render (which needs ffmpeg and is not this task's
    concern) — the property under test is the missing declaration row, not
    how it came to be missing."""
    asset_id = new_id("as")
    ctx.conn.execute(
        "INSERT INTO assets (id, content_hash, byte_size, original_filename,"
        " mime_type, duration_seconds, probe_status, derived_from, state,"
        " ingested_at, object_path) VALUES (?, ?, ?, ?, ?, ?, 'ok', NULL,"
        " 'stored', ?, ?)",
        (asset_id, f"hash-{asset_id}", 123, "derived.mp4", "video/mp4", None,
         iso(), f"/tmp/{asset_id}.mp4"),
    )
    return asset_id


# --- AC-1: create/list/update/delete round-trip, and the rights gate --------


def test_a_brand_kit_round_trips_through_sqlite(agent_ctx, media_file):
    logo = _ingest_logo(agent_ctx, media_file)
    created = invoke(agent_ctx, "create-brand-kit", {
        "name": "Main channel",
        "logo_asset_id": logo,
        "primary_color": "#1a73e8",
        "secondary_color": "#f4b400",
        "font_family": "Inter",
    })
    assert created["ok"] is True
    kit_id = created["brand_kit_id"]

    fetched = invoke(agent_ctx, "brand-kit", {"brand_kit_id": kit_id})["brand_kit"]
    assert fetched["name"] == "Main channel"
    assert fetched["logo_asset_id"] == logo
    assert fetched["primary_color"] == "#1a73e8"
    assert fetched["secondary_color"] == "#f4b400"
    assert fetched["font_family"] == "Inter"
    assert fetched["created_by"] == agent_ctx.principal.id

    listed = invoke(agent_ctx, "list-brand-kits", {})
    assert listed["count"] == 1
    assert listed["brand_kits"][0]["id"] == kit_id


def test_a_brand_kit_cannot_point_at_a_nonexistent_asset(agent_ctx):
    with pytest.raises(NotFound):
        invoke(agent_ctx, "create-brand-kit", {
            "name": "Ghost kit", "logo_asset_id": "as_does_not_exist",
        })


def test_a_brand_kit_cannot_point_at_an_undeclared_asset(agent_ctx):
    """AC-1's real subject: a real, present asset that was never declared —
    the shape a rendered derivative has (module docstring)."""
    orphan = _undeclared_asset(agent_ctx)
    with pytest.raises(ValidationError) as excinfo:
        invoke(agent_ctx, "create-brand-kit", {"name": "Kit", "logo_asset_id": orphan})
    assert excinfo.value.detail["parameter"] == "logo_asset_id"

    before = agent_ctx.conn.execute("SELECT COUNT(*) AS n FROM brand_kits").fetchone()["n"]
    assert before == 0, "a refused create must not write a row"


def test_creating_a_brand_kit_needs_a_name(agent_ctx, media_file):
    logo = _ingest_logo(agent_ctx, media_file)
    with pytest.raises(ValidationError):
        invoke(agent_ctx, "create-brand-kit", {"name": "   ", "logo_asset_id": logo})


def test_update_brand_kit_changes_only_the_given_fields(agent_ctx, media_file):
    logo = _ingest_logo(agent_ctx, media_file)
    kit_id = invoke(agent_ctx, "create-brand-kit", {
        "name": "Original", "logo_asset_id": logo,
        "primary_color": "#000000", "secondary_color": "#ffffff", "font_family": "Arial",
    })["brand_kit_id"]

    updated = invoke(agent_ctx, "update-brand-kit", {
        "brand_kit_id": kit_id, "primary_color": "#ff0000",
    })
    assert updated["primary_color"] == "#ff0000"
    # Untouched fields keep their prior value.
    assert updated["name"] == "Original"
    assert updated["secondary_color"] == "#ffffff"
    assert updated["font_family"] == "Arial"
    assert updated["logo_asset_id"] == logo

    fetched = invoke(agent_ctx, "brand-kit", {"brand_kit_id": kit_id})["brand_kit"]
    assert fetched["primary_color"] == "#ff0000"
    assert fetched["name"] == "Original"


def test_update_brand_kit_logo_is_checked_the_same_way_as_create(agent_ctx, media_file):
    logo = _ingest_logo(agent_ctx, media_file)
    kit_id = invoke(agent_ctx, "create-brand-kit", {"name": "Kit", "logo_asset_id": logo})["brand_kit_id"]

    orphan = _undeclared_asset(agent_ctx)
    with pytest.raises(ValidationError):
        invoke(agent_ctx, "update-brand-kit", {"brand_kit_id": kit_id, "logo_asset_id": orphan})

    # Refused write must not have changed the stored logo reference.
    fetched = invoke(agent_ctx, "brand-kit", {"brand_kit_id": kit_id})["brand_kit"]
    assert fetched["logo_asset_id"] == logo


def test_updating_an_unknown_brand_kit_is_not_found(agent_ctx):
    with pytest.raises(NotFound):
        invoke(agent_ctx, "update-brand-kit", {"brand_kit_id": "bk_nope", "name": "x"})


def test_delete_brand_kit_removes_it(agent_ctx, media_file):
    logo = _ingest_logo(agent_ctx, media_file)
    kit_id = invoke(agent_ctx, "create-brand-kit", {"name": "Kit", "logo_asset_id": logo})["brand_kit_id"]

    result = invoke(agent_ctx, "delete-brand-kit", {"brand_kit_id": kit_id})
    assert result["deleted"] is True

    with pytest.raises(NotFound):
        invoke(agent_ctx, "brand-kit", {"brand_kit_id": kit_id})
    assert invoke(agent_ctx, "list-brand-kits", {})["count"] == 0


def test_deleting_an_unknown_brand_kit_is_not_found(agent_ctx):
    with pytest.raises(NotFound):
        invoke(agent_ctx, "delete-brand-kit", {"brand_kit_id": "bk_nope"})


# --- F-2: agent authority, no operator gate ----------------------------------


def test_every_brand_kit_operation_is_agent_authority():
    """DR-021: drafting an edit (which is all a brand kit is, until applied)
    is not spending or publishing, matching set-edl's own authority level."""
    from promedia.core.registry import load_operations

    ops = load_operations()
    for name in ("create-brand-kit", "list-brand-kits", "brand-kit",
                 "update-brand-kit", "delete-brand-kit"):
        assert ops[name].authority == "agent", f"'{name}' should be agent authority"


# --- AC-4: backup classification ---------------------------------------------


def test_brand_kits_table_is_classified_permanent(agent_ctx):
    classified = backup.classify_tables(agent_ctx.conn)
    assert "brand_kits" in classified["permanent"]
    assert "brand_kits" not in classified["transient"]


def test_a_brand_kit_round_trips_through_backup_and_restore(agent_ctx, media_file):
    logo = _ingest_logo(agent_ctx, media_file)
    kit_id = invoke(agent_ctx, "create-brand-kit", {
        "name": "Backed up kit", "logo_asset_id": logo, "primary_color": "#123456",
    })["brand_kit_id"]

    artefact = backup.build(agent_ctx.conn)
    assert artefact["row_counts"]["brand_kits"] == 1
    verified = backup.verify(artefact)
    assert verified["integrity_verified"] is True

    kit_rows = artefact["payload"]["brand_kits"]
    assert kit_rows[0]["id"] == kit_id
    assert kit_rows[0]["primary_color"] == "#123456"


# --- AC-2/AC-3: apply-brand-kit -----------------------------------------------
#
# The RENDER-side proof that a logo overlay actually appears where asked
# (AC-2's "renders as a real, measurably-present burned-in watermark") lives
# in tests/test_transitions.py against the render engine directly — the
# engine has no idea an EDL came from a brand kit rather than a hand-authored
# edit, so what matters here is narrower: that apply-brand-kit writes the
# RIGHT ImageOverlay, through the same set_edl every other edit goes through,
# and that deleting the brand kit row afterward changes nothing about it
# (DR-021's core constraint, AC-3).


def _ingest(ctx, path: Path) -> str:
    """Same as _ingest_logo, generalised: any real, rights-declared asset —
    used for both the video clip and the logo in the tests below, from two
    files with different bytes so ingest's content-hash dedupe (T-029) gives
    each its own asset id rather than silently reusing one."""
    result = invoke(
        ctx, "ingest",
        {"source_path": str(path), "declaration": declaration_original()},
    )
    return result["asset_id"]


def _project_with_clip(ctx, asset_id: str) -> str:
    """A real project whose CURRENT edit already has one clip — the minimum
    apply-brand-kit needs, since it reads the current edit and APPENDS to
    it rather than replacing it."""
    project = invoke(ctx, "create-project", {"title": "Kit test project"})
    invoke(ctx, "set-edl", {
        "project_id": project["project_id"],
        "edl": {"aspect": "landscape_720",
                "clips": [{"asset_id": asset_id, "start": 0, "end": 2}]},
    })
    return project["project_id"]


def test_apply_brand_kit_writes_a_new_edl_version_with_the_logo_overlay(agent_ctx, tmp_path):
    clip_path = tmp_path / "clip.mp4"
    clip_path.write_bytes(b"clip bytes for apply-brand-kit" * 50)
    clip_asset = _ingest(agent_ctx, clip_path)
    logo_asset_path = tmp_path / "logo.png"
    logo_asset_path.write_bytes(b"logo bytes for apply-brand-kit, different from the clip" * 50)
    logo = _ingest(agent_ctx, logo_asset_path)

    project_id = _project_with_clip(agent_ctx, clip_asset)
    kit_id = invoke(agent_ctx, "create-brand-kit", {"name": "Kit", "logo_asset_id": logo})["brand_kit_id"]

    result = invoke(agent_ctx, "apply-brand-kit", {"project_id": project_id, "brand_kit_id": kit_id})
    assert result["ok"] is True
    assert result["previous_version"] == 2  # v1: empty, from create-project. v2: the clip, from set-edl above.
    assert result["edl_version"] == 3
    assert result["brand_kit_id"] == kit_id
    assert result["logo_asset_id"] == logo
    assert result["image_overlays"] == 1

    fetched = invoke(agent_ctx, "project", {"project_id": project_id})
    assert fetched["edl_version"] == 3
    overlay = fetched["edl"]["image_overlays"][0]
    assert overlay["asset_id"] == logo
    assert overlay["position"] == "bottom_right"  # default, not overridden below
    assert overlay["size"] == 0.15
    assert overlay["margin"] == 24
    # The clip that was already there is untouched, not replaced — DR-021's
    # "writes a NEW version" is additive, not destructive.
    assert len(fetched["edl"]["clips"]) == 1
    assert fetched["edl"]["clips"][0]["asset_id"] == clip_asset


def test_apply_brand_kit_accepts_position_size_margin_and_time_window_overrides(agent_ctx, tmp_path):
    clip_path = tmp_path / "clip.mp4"
    clip_path.write_bytes(b"another clip's bytes" * 50)
    clip_asset = _ingest(agent_ctx, clip_path)
    logo_path = tmp_path / "logo.png"
    logo_path.write_bytes(b"another logo's bytes, still different" * 50)
    logo = _ingest(agent_ctx, logo_path)

    project_id = _project_with_clip(agent_ctx, clip_asset)
    kit_id = invoke(agent_ctx, "create-brand-kit", {"name": "Kit", "logo_asset_id": logo})["brand_kit_id"]

    invoke(agent_ctx, "apply-brand-kit", {
        "project_id": project_id, "brand_kit_id": kit_id,
        "position": "top_left", "size": "0.3", "margin": "8",
        "start": "1.0", "end": "1.5",
    })

    fetched = invoke(agent_ctx, "project", {"project_id": project_id})
    overlay = fetched["edl"]["image_overlays"][0]
    assert overlay["position"] == "top_left"
    assert overlay["size"] == 0.3
    assert overlay["margin"] == 8
    assert overlay["start"] == 1.0
    assert overlay["end"] == 1.5


def test_deleting_the_brand_kit_after_apply_leaves_the_edl_version_untouched_ac3(agent_ctx, tmp_path):
    """AC-3: apply-brand-kit's EDL never carries the brand_kit id, only the
    resolved logo asset id and overlay geometry — so once a version exists,
    deleting the row it came from changes NOTHING about that version, byte
    for byte, proving DR-021's "the brand_kits table is a convenience
    generator, never a live render-time dependency"."""
    clip_path = tmp_path / "clip.mp4"
    clip_path.write_bytes(b"yet another clip" * 50)
    clip_asset = _ingest(agent_ctx, clip_path)
    logo_path = tmp_path / "logo.png"
    logo_path.write_bytes(b"yet another logo, still distinct bytes" * 50)
    logo = _ingest(agent_ctx, logo_path)

    project_id = _project_with_clip(agent_ctx, clip_asset)
    kit_id = invoke(agent_ctx, "create-brand-kit", {"name": "Kit", "logo_asset_id": logo})["brand_kit_id"]
    invoke(agent_ctx, "apply-brand-kit", {"project_id": project_id, "brand_kit_id": kit_id})

    before = invoke(agent_ctx, "project", {"project_id": project_id, "version": 3})

    invoke(agent_ctx, "delete-brand-kit", {"brand_kit_id": kit_id})
    with pytest.raises(NotFound):
        invoke(agent_ctx, "brand-kit", {"brand_kit_id": kit_id})

    after = invoke(agent_ctx, "project", {"project_id": project_id, "version": 3})
    assert after["edl"] == before["edl"], "the EDL version must be byte-identical after the kit is deleted"

    # A fresh apply against the same (now brand-kit-less) history is refused
    # the ordinary way — NotFound, same as any other unknown id — proving the
    # gate is real rather than merely untested.
    with pytest.raises(NotFound):
        invoke(agent_ctx, "apply-brand-kit", {"project_id": project_id, "brand_kit_id": kit_id})


def test_applying_an_unknown_brand_kit_is_not_found(agent_ctx, tmp_path):
    clip_path = tmp_path / "clip.mp4"
    clip_path.write_bytes(b"solo clip bytes" * 50)
    clip_asset = _ingest(agent_ctx, clip_path)
    project_id = _project_with_clip(agent_ctx, clip_asset)

    with pytest.raises(NotFound):
        invoke(agent_ctx, "apply-brand-kit", {"project_id": project_id, "brand_kit_id": "bk_nope"})


def test_applying_to_an_unknown_project_is_not_found(agent_ctx, tmp_path):
    logo_path = tmp_path / "logo.png"
    logo_path.write_bytes(b"a logo with no project to apply to" * 50)
    logo = _ingest(agent_ctx, logo_path)
    kit_id = invoke(agent_ctx, "create-brand-kit", {"name": "Kit", "logo_asset_id": logo})["brand_kit_id"]

    with pytest.raises(NotFound):
        invoke(agent_ctx, "apply-brand-kit", {"project_id": "pr_nope", "brand_kit_id": kit_id})


def test_apply_brand_kit_is_agent_authority():
    from promedia.core.registry import load_operations

    assert load_operations()["apply-brand-kit"].authority == "agent"
