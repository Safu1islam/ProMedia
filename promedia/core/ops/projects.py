"""Media production capabilities (T-042).

Registering these is what makes the engine exist as far as the system is
concerned. Before this module, T-041's render pipeline was reachable from
neither surface and the F-1 parity gate could not see it — a capability on zero
surfaces, which is the mirror image of the defect S4 calls a build failure.

Authority follows F-2 exactly. Drafting, editing and rendering are agent work:
they produce a file, and a file is not a publication. Nothing here publishes,
spends, or clears a rights flag.

Locking is automatic: each operation that mutates a project declares
``entity="project"`` and takes a ``project_id``, which is the convention
``registry.lock_target`` reads. Two agents cannot render conflicting edits of
the same project, and neither can an agent and the operator.
"""

from __future__ import annotations

from typing import Any

from .. import projects as projects_layer
from ..registry import Context, Param, register


@register(
    "create-project",
    "Start a media project. Its edit begins empty and is versioned from there.",
    params=(Param("title", "str", help="What this project is, in a few words."),),
    mutates=True,
    entity="project",
)
def create_project(ctx: Context, title: str) -> dict[str, Any]:
    return projects_layer.create(ctx, title=title)


@register(
    "set-edl",
    "Replace a project's edit with a new version. The previous version stays readable.",
    params=(
        Param("project_id", "str"),
        Param(
            "edl",
            "json",
            help=(
                "The complete edit document: aspect, clips, text, audio."
                " Replaces the current version rather than merging into it."
            ),
        ),
        Param("note", "str", required=False, help="What changed, for the history."),
    ),
    mutates=True,
    entity="project",
)
def set_edl(ctx: Context, project_id: str, edl: Any, note: str | None = None) -> dict[str, Any]:
    return projects_layer.set_edl(ctx, project_id=project_id, edl=edl, note=note)


@register(
    "project",
    "Show a project and its current edit, or a specific earlier version.",
    params=(
        Param("project_id", "str"),
        Param("version", "int", required=False, help="Omit for the current edit."),
    ),
)
def project(ctx: Context, project_id: str, version: int | None = None) -> dict[str, Any]:
    return projects_layer.get(ctx, project_id=project_id, version=version)


@register("list-projects", "List media projects, most recently changed first.")
def list_projects(ctx: Context) -> dict[str, Any]:
    return projects_layer.list_projects(ctx)


@register(
    "project-versions",
    "The edit history of a project: who changed it, when, and why.",
    params=(Param("project_id", "str"),),
)
def project_versions(ctx: Context, project_id: str) -> dict[str, Any]:
    return projects_layer.versions(ctx, project_id=project_id)


@register(
    "render-project",
    "Render a project's current edit to a video file.",
    params=(
        Param("project_id", "str"),
        Param("quality", "str", required=False,
              help="fast | balanced | quality | hardware. Defaults to configuration."),
    ),
    mutates=True,
    entity="project",
    danger="Encodes video. Can take minutes and writes a file.",
)
def render_project(ctx: Context, project_id: str, quality: str | None = None) -> dict[str, Any]:
    """Agent authority: producing a file is drafting, not publishing (F-2).

    The C-19 lock is taken by invoke() because this declares an entity and a
    project_id — which matters more here than elsewhere, since a render reads
    the edit and can run for minutes. Without it, an edit changed mid-render
    would produce an output attributed to a version it did not come from.
    """
    return projects_layer.render(ctx, project_id=project_id, quality=quality)


@register(
    "renders",
    "List rendered outputs, and whether each file is still present.",
    params=(Param("project_id", "str", required=False),),
)
def renders(ctx: Context, project_id: str | None = None) -> dict[str, Any]:
    return projects_layer.renders(ctx, project_id=project_id)


@register(
    "media-capabilities",
    "What this installation can edit and render, and what it cannot generate.",
)
def media_capabilities(ctx: Context) -> dict[str, Any]:
    """Answers 'why did that fail' without requiring a failure first.

    Also the place a missing capability is stated plainly rather than being
    discovered as an error — the requirement that generation gaps name what
    they need instead of silently skipping.
    """
    return projects_layer.capabilities(ctx)
