"""Projects — the persistent home of an edit (T-042).

T-041 built a render engine and registered no capability, so it was reachable
from neither the agent nor the operator. This module is what turns it into
something either can drive, and the shape it imposes is the point:

An edit is stored as an APPEND-ONLY sequence of EDL versions. There is no update
path. Every change — whether the agent proposes it or the operator makes it —
writes a new version with its author recorded, so:

  * an earlier edit is always recoverable, which is what makes an agent's
    autonomous change safe to accept;
  * "what did the agent change" is answerable by comparing two rows, rather
    than by trusting a summary of itself;
  * a render names the version it came from, so an output can always be traced
    to the edit that produced it.

Authority (F-2): drafting, editing and RENDERING are agent-callable. Rendering
produces a file; it does not publish, spend money, or clear a rights flag. The
operator gate stays where it already is — approval and publication.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..errors import NotFound, ValidationError
from .db import iso, new_id, transaction
from .media import ffmpeg, render as render_engine
from .media.edl import EDL
from .registry import Context


def create(ctx: Context, *, title: str) -> dict[str, Any]:
    """A new project, with an empty EDL as version 1.

    Version 1 exists immediately rather than on first edit, so a project always
    has a readable current state and callers never handle "no version yet".
    """
    clean = title.strip()
    if not clean:
        raise ValidationError("a project needs a title", parameter="title")

    project_id = new_id("prj")
    moment = iso()
    with transaction(ctx.conn):
        ctx.conn.execute(
            "INSERT INTO projects (id, title, status, created_by, created_at, updated_at)"
            " VALUES (?, ?, 'draft', ?, ?, ?)",
            (project_id, clean, ctx.principal.id, moment, moment),
        )
        _append_version(ctx, project_id, EDL(), version=1, note="created", at=moment)

    return {
        "ok": True,
        "project_id": project_id,
        "title": clean,
        "status": "draft",
        "edl_version": 1,
        "note": "empty edit; add clips with set-edl before rendering",
    }


def _append_version(
    ctx: Context, project_id: str, edl: EDL, *, version: int, note: str, at: str
) -> None:
    ctx.conn.execute(
        "INSERT INTO project_edl_versions (project_id, version, edl_json, note,"
        " authored_by, authored_kind, authored_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            project_id,
            version,
            json.dumps(edl.to_dict(), sort_keys=True),
            note,
            ctx.principal.id,
            # Recorded because "did a human shape this edit, or an agent" is the
            # question an operator asks before approving what came out of it —
            # the same reasoning that put authorship on rights declarations.
            ctx.principal.kind,
            at,
        ),
    )


def _project_row(ctx: Context, project_id: str) -> Any:
    row = ctx.conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise NotFound(f"no project {project_id}", project_id=project_id)
    return row


def current_version(ctx: Context, project_id: str) -> tuple[int, EDL]:
    row = ctx.conn.execute(
        "SELECT version, edl_json FROM project_edl_versions WHERE project_id = ?"
        " ORDER BY version DESC LIMIT 1",
        (project_id,),
    ).fetchone()
    if row is None:
        raise NotFound(f"project {project_id} has no EDL", project_id=project_id)
    return int(row["version"]), EDL.from_dict(json.loads(row["edl_json"]))


def set_edl(ctx: Context, *, project_id: str, edl: Any, note: str | None = None) -> dict[str, Any]:
    """Replace the edit with a new version. Validates BEFORE storing.

    An invalid EDL is refused rather than stored, because a stored one is a
    version an operator may later restore, and restoring to something that
    cannot render is a trap with a delay on it.
    """
    _project_row(ctx, project_id)
    document = EDL.from_dict(edl if isinstance(edl, dict) else json.loads(edl))
    document.validate()

    version, _ = current_version(ctx, project_id)
    next_version = version + 1
    moment = iso()
    with transaction(ctx.conn):
        _append_version(
            ctx, project_id, document, version=next_version,
            note=(note or "edited").strip()[:200], at=moment,
        )
        ctx.conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (moment, project_id))

    return {
        "ok": True,
        "project_id": project_id,
        "edl_version": next_version,
        "previous_version": version,
        "authored_kind": ctx.principal.kind,
        **document.summary(),
    }


def get(ctx: Context, *, project_id: str, version: int | None = None) -> dict[str, Any]:
    row = _project_row(ctx, project_id)
    if version is None:
        number, document = current_version(ctx, project_id)
    else:
        stored = ctx.conn.execute(
            "SELECT version, edl_json FROM project_edl_versions"
            " WHERE project_id = ? AND version = ?",
            (project_id, int(version)),
        ).fetchone()
        if stored is None:
            raise NotFound(
                f"project {project_id} has no version {version}",
                project_id=project_id, version=version,
            )
        number, document = int(stored["version"]), EDL.from_dict(json.loads(stored["edl_json"]))

    return {
        "ok": True,
        "project_id": project_id,
        "title": row["title"],
        "status": row["status"],
        "edl_version": number,
        "edl": document.to_dict(),
        **document.summary(),
    }


def versions(ctx: Context, *, project_id: str) -> dict[str, Any]:
    """The edit history, without the documents — who changed what, and when."""
    _project_row(ctx, project_id)
    rows = ctx.conn.execute(
        "SELECT version, note, authored_by, authored_kind, authored_at"
        " FROM project_edl_versions WHERE project_id = ? ORDER BY version DESC",
        (project_id,),
    ).fetchall()
    return {
        "ok": True,
        "project_id": project_id,
        "count": len(rows),
        "versions": [dict(r) for r in rows],
    }


def list_projects(ctx: Context) -> dict[str, Any]:
    rows = ctx.conn.execute(
        "SELECT p.*, (SELECT MAX(version) FROM project_edl_versions v"
        " WHERE v.project_id = p.id) AS edl_version"
        " FROM projects p ORDER BY p.updated_at DESC"
    ).fetchall()
    return {"ok": True, "count": len(rows), "projects": [dict(r) for r in rows]}


def _substitutions(document: EDL) -> list[dict[str, str]]:
    """What this render will NOT do as asked.

    Fabrication F-003. The EDL VALIDATES transitions against its vocabulary, so
    accepting one is an active promise that it is supported — and four of the
    seven render as hard cuts while the render reports success. That is the
    shape Constitution section 6 exists for: a silent substitution that succeeds
    prompts nobody to look, whereas a failure at least invites a question.

    Derived from render.TRANSITION_REALITY rather than listed here. The first
    version of this function WAS a hand-written list, it named only 'dissolve',
    and an independent audit found the other four by executing the compiler
    instead of reading either list. One source of truth, next to the filters.
    """
    found: list[dict[str, str]] = []
    seen: set[str] = set()
    for clip in document.clips:
        actual = render_engine.transition_substitution(clip.transition_in)
        if actual is None or clip.transition_in in seen:
            continue
        seen.add(clip.transition_in)
        found.append({
            "requested": clip.transition_in,
            "rendered": actual,
            "why": (
                "the concat graph carries no absolute timeline offsets, which"
                " xfade and wipe transitions both require"
            ),
            "fabrication": "F-003",
            "replacement_task": "T-045",
        })
    return found


def _resolve_sources(ctx: Context, document: EDL) -> dict[str, Path]:
    """Asset id to file path, refusing anything not usable.

    NOTE, and it is the one that matters: this checks that media EXISTS. It does
    NOT check the rights verdict. Rendering from BLOCKED footage currently
    succeeds, which is the F-4 gap T-044 closes — 'transforming material never
    makes unusable material usable', and an editor is a transformation machine.
    Stated here rather than left for someone to discover.
    """
    from . import rights as rights_layer

    sources: dict[str, Path] = {}
    for asset_id in document.asset_ids():
        row = ctx.conn.execute(
            "SELECT id, state, object_path FROM assets WHERE id = ?", (asset_id,)
        ).fetchone()
        if row is None:
            raise NotFound(f"no asset {asset_id} referenced by this edit", asset_id=asset_id)
        state = rights_layer.media_state(ctx, asset_id)
        if state != "stored" or not row["object_path"]:
            from ..errors import MediaUnavailable

            raise MediaUnavailable(
                f"asset {asset_id} has no media on this machine (state '{state}'),"
                " so it cannot be rendered",
                asset_id=asset_id, asset_state=state,
            )
        path = Path(row["object_path"])
        if not path.is_file():
            from ..errors import MediaUnavailable

            raise MediaUnavailable(
                f"asset {asset_id} is recorded as stored but its file is missing",
                asset_id=asset_id, object_path=str(path),
            )
        sources[asset_id] = path
    return sources


def render(ctx: Context, *, project_id: str, quality: str | None = None) -> dict[str, Any]:
    """Render the current edit. Agent-callable: it produces a file, not a post."""
    row = _project_row(ctx, project_id)
    version, document = current_version(ctx, project_id)
    if not document.clips:
        raise ValidationError(
            "this project's edit has no clips, so there is nothing to render",
            project_id=project_id, edl_version=version,
        )

    chosen = quality or str(ctx.config.get("media", "default_quality"))
    sources = _resolve_sources(ctx, document)

    render_id = new_id("rnd")
    output_dir = ctx.config.data_dir / "renders" / project_id
    output_path = output_dir / f"{render_id}.mp4"
    configured_font = str(ctx.config.get("media", "font_path")).strip()

    plan = render_engine.compile_render(
        document, sources, output_path,
        quality=chosen,
        font=Path(configured_font) if configured_font else None,
        workspace=output_dir / f".{render_id}-text",
    )
    result = render_engine.execute(
        plan, timeout_seconds=float(ctx.config.get("media", "render_timeout_seconds"))
    )

    substitutions = _substitutions(document)
    moment = iso()
    with transaction(ctx.conn):
        ctx.conn.execute(
            "INSERT INTO renders (id, project_id, edl_version, output_path, quality,"
            " width, height, duration_seconds, byte_size, substitutions, rendered_by, rendered_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                render_id, project_id, version, str(output_path), chosen,
                result.get("width"), result.get("height"), result.get("duration_seconds"),
                result.get("byte_size", 0),
                json.dumps(substitutions) if substitutions else None,
                ctx.principal.id, moment,
            ),
        )

    return {
        "ok": True,
        "render_id": render_id,
        "project_id": project_id,
        "title": row["title"],
        "edl_version": version,
        **result,
        # Never omitted, even when empty: a caller that has to ask whether a key
        # exists will eventually stop asking.
        "substitutions": substitutions,
        "storage_note": (
            "these bytes are NOT yet counted against the F-7 storage ceiling (T-043)"
        ),
    }


def renders(ctx: Context, *, project_id: str | None = None) -> dict[str, Any]:
    if project_id:
        _project_row(ctx, project_id)
        rows = ctx.conn.execute(
            "SELECT * FROM renders WHERE project_id = ? ORDER BY rendered_at DESC",
            (project_id,),
        ).fetchall()
    else:
        rows = ctx.conn.execute("SELECT * FROM renders ORDER BY rendered_at DESC").fetchall()

    out = []
    for row in rows:
        item = dict(row)
        item["substitutions"] = json.loads(item["substitutions"]) if item["substitutions"] else []
        item["output_exists"] = Path(item["output_path"]).is_file()
        out.append(item)
    return {"ok": True, "count": len(out), "renders": out}


def capabilities(ctx: Context) -> dict[str, Any]:
    """What this installation can actually do, right now.

    Exists because "why did that fail" is otherwise answered by trying it. An
    absent toolchain is reported as absent rather than as a media error.
    """
    from .media.edl import ASPECT_PRESETS, CLIP_EFFECTS, TRANSITIONS
    from .media.render import QUALITY_PRESETS

    available = ffmpeg.available()
    return {
        "ok": True,
        "ffmpeg_available": available,
        "ffmpeg_path": ffmpeg.tool_path("ffmpeg"),
        "font_available": ffmpeg.default_font() is not None,
        "aspects": sorted(ASPECT_PRESETS),
        "effects": list(CLIP_EFFECTS),
        "transitions": list(TRANSITIONS),
        "qualities": sorted(QUALITY_PRESETS),
        # Derived, so this cannot claim a transition works after the compiler
        # stops implementing it — or, as happened, keep claiming only one is
        # broken when five are.
        "known_substitutions": [
            {"requested": name, "rendered": actual, "fabrication": "F-003"}
            for name, actual in sorted(render_engine.TRANSITION_REALITY.items())
            if actual is not None
        ],
        "not_available": [
            {"capability": "video generation", "needs": "a hosted video generation API"},
            {"capability": "image generation", "needs": "a hosted image API; 1 GB VRAM rules out local diffusion"},
            {"capability": "voiceover", "needs": "a hosted TTS API, or local Piper"},
            {"capability": "semantic video analysis", "needs": "a hosted multimodal model"},
        ],
        "note": (
            "ffmpeg is installed and rendering works"
            if available
            else "ffmpeg is NOT installed; no media operation can run"
        ),
    }
