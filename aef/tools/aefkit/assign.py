"""Agent assignment — automatic from classification, manual by command.

Two paths, one record. Whichever path assigned an agent, the result is written
into .ai/state/plan.yaml and carries WHY it was assigned, so a later agent can
tell a decision from a guess.

Manual assignment is surgical: it rewrites the single `agent:` line for one node
rather than re-serialising the file. A plan carries the planner's comments and
ordering, and a round-trip through a YAML dumper would silently destroy both.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Any

from . import yamlio

__all__ = ["Catalogue", "Suggestion", "load_catalogue", "suggest", "set_agent", "AssignError"]


class AssignError(Exception):
    pass


@dataclass
class Suggestion:
    agent: str | None
    basis: str          # change_class | owner_role | title_keyword | none
    reason: str
    confidence: str     # strong | moderate | weak | none


class Catalogue:
    def __init__(self, data: dict[str, Any]):
        self.agents: dict[str, dict[str, Any]] = data.get("agents") or {}
        rules = data.get("assignment") or {}
        self.by_change_class: dict[str, str] = rules.get("by_change_class") or {}
        self.by_owner_role: dict[str, str] = rules.get("by_owner_role") or {}
        self.by_title_keyword: dict[str, list[str]] = rules.get("by_title_keyword") or {}
        self.fallback: str | None = rules.get("fallback")
        self.constraints: dict[str, Any] = data.get("constraints") or {}

    def role_of(self, agent: str | None) -> str | None:
        if not agent:
            return None
        return (self.agents.get(agent) or {}).get("role")

    def known(self, agent: str) -> bool:
        return agent in self.agents


def load_catalogue(project_root: str = ".", *, force_bundled: bool = False) -> Catalogue:
    """Framework defaults, with the project's `agents:` override deep-merged over
    them. Same precedence rule as framework.yaml / overrides.yaml."""
    base_path = os.path.join(project_root, "aef", "config", "agents.yaml")
    if not os.path.exists(base_path):
        raise AssignError(f"agent catalogue not found at {base_path}")
    data = yamlio.load(base_path, force_bundled=force_bundled) or {}

    override_path = os.path.join(project_root, ".ai", "config", "overrides.yaml")
    if os.path.exists(override_path):
        overrides = yamlio.load(override_path, force_bundled=force_bundled) or {}
        # `agents:` adds or replaces catalogue entries; `assignment:` adjusts the
        # rules. Two keys rather than one nested blob, so a project adding an
        # agent does not have to restate the rule table to do it.
        for key in ("agents", "assignment", "constraints"):
            section = overrides.get(key)
            if isinstance(section, dict):
                data = _deep_merge(data, {key: section})
    return Catalogue(data)


def _deep_merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def suggest(task: dict[str, Any] | None, title: str, catalogue: Catalogue) -> Suggestion:
    """Pick the implementing agent for one unit of work.

    Evidence order is deliberate and is the same order routing.yaml already
    trusts: an explicit classification beats a declared role, and both beat a
    word in a title. The weakest basis is labelled weak in the reason so nobody
    reads a keyword match as a decision.
    """
    task = task or {}

    change_class = task.get("change_class")
    if change_class and change_class in catalogue.by_change_class:
        agent = catalogue.by_change_class[change_class]
        return Suggestion(
            agent, "change_class",
            f"change_class '{change_class}' routes to {agent}",
            "strong",
        )

    owner_role = task.get("owner_role")
    if owner_role and owner_role in catalogue.by_owner_role:
        agent = catalogue.by_owner_role[owner_role]
        return Suggestion(
            agent, "owner_role",
            f"owner_role '{owner_role}' routes to {agent}",
            "moderate",
        )

    haystack = f"{title} {task.get('title') or ''} {task.get('objective') or ''}".lower()
    for agent, keywords in catalogue.by_title_keyword.items():
        for keyword in keywords:
            if re.search(rf"\b{re.escape(str(keyword).lower())}\b", haystack):
                return Suggestion(
                    agent, "title_keyword",
                    f"WEAK: matched the word '{keyword}' in the title — no change_class "
                    "or owner_role was set. Classify the task to assign it properly.",
                    "weak",
                )

    if catalogue.fallback:
        return Suggestion(catalogue.fallback, "fallback",
                          f"no rule matched; catalogue fallback is {catalogue.fallback}", "weak")
    return Suggestion(None, "none",
                      "no change_class, owner_role or keyword matched — left unassigned "
                      "deliberately rather than guessed", "none")


# ---------------------------------------------------------------------------
# Writing back
# ---------------------------------------------------------------------------

_ID_LINE = re.compile(r"^(?P<indent>\s*)(?:-\s+)?id:\s*(?P<quote>['\"]?)(?P<id>[^'\"\s#]+)(?P=quote)\s*(?:#.*)?$")


def set_agent(plan_path: str, node_id: str, agent: str | None, *,
              locked: bool = True, catalogue: Catalogue | None = None) -> str:
    """Set (or clear) one node's agent, in place, preserving everything else.

    `locked=True` marks the assignment as MANUAL, which stops a later
    `assign --auto` pass from overwriting a human's decision. That is the whole
    point of the flag: automatic assignment must never quietly undo an explicit
    one.
    """
    if agent and catalogue is not None and not catalogue.known(agent):
        known = ", ".join(sorted(catalogue.agents)) or "(catalogue empty)"
        raise AssignError(
            f"unknown agent '{agent}'. Known agents: {known}\n"
            "Add it to .ai/config/overrides.yaml under `agents:` before assigning it."
        )

    with open(plan_path, "r", encoding="utf-8") as handle:
        lines = handle.read().splitlines(keepends=True)

    start = _find_node(lines, node_id, plan_path)
    indent, body_start, body_end = _node_body(lines, start)

    existing_agent = _find_key(lines, body_start, body_end, indent, "agent")
    existing_locked = _find_key(lines, body_start, body_end, indent, "agent_locked")

    replacement: list[str] = []
    if agent is not None:
        replacement.append(f"{indent}agent: {agent}\n")
        if locked:
            replacement.append(f"{indent}agent_locked: true\n")

    # Remove the old pair, high index first so earlier indices stay valid.
    for position in sorted([position for position in (existing_agent, existing_locked) if position is not None],
                           reverse=True):
        del lines[position]
        if position < body_start:
            body_start -= 1

    insert_at = existing_agent if existing_agent is not None else body_start
    insert_at = min(insert_at, len(lines))
    lines[insert_at:insert_at] = replacement

    with open(plan_path, "w", encoding="utf-8", newline="") as handle:
        handle.write("".join(lines))

    if agent is None:
        return f"cleared the agent on {node_id}"
    return f"assigned {node_id} -> {agent}" + (" (manual, locked)" if locked else " (auto)")


def _find_node(lines: list[str], node_id: str, plan_path: str) -> int:
    matches = [
        index for index, line in enumerate(lines)
        if (match := _ID_LINE.match(line.rstrip("\n"))) and match.group("id") == node_id
    ]
    if not matches:
        raise AssignError(f"no node with id '{node_id}' in {plan_path}")
    if len(matches) > 1:
        raise AssignError(
            f"id '{node_id}' appears {len(matches)} times in {plan_path}; "
            "fix the duplicate before assigning"
        )
    return matches[0]


def _node_body(lines: list[str], id_index: int) -> tuple[str, int, int]:
    """Return (indent of the node's keys, first body line, one-past-last body line).

    The node's keys sit at the indentation of its `id:` key. For a `- id: X`
    entry that is two columns right of the dash.
    """
    raw = lines[id_index].rstrip("\n")
    stripped = raw.lstrip(" ")
    lead = len(raw) - len(stripped)
    indent = " " * (lead + 2) if stripped.startswith("- ") else " " * lead

    end = id_index + 1
    while end < len(lines):
        line = lines[end].rstrip("\n")
        if line.strip() == "" or line.lstrip().startswith("#"):
            end += 1
            continue
        current = len(line) - len(line.lstrip(" "))
        if current < len(indent) or (current == len(indent) and line.lstrip().startswith("- ")):
            break
        end += 1
    return indent, id_index + 1, end


def _find_key(lines: list[str], start: int, end: int, indent: str, key: str) -> int | None:
    """Index of `key:` at exactly this node's own level. Nested occurrences at a
    deeper indent belong to a child and must not be touched."""
    pattern = re.compile(rf"^{re.escape(indent)}{re.escape(key)}:")
    for index in range(start, min(end, len(lines))):
        if pattern.match(lines[index].rstrip("\n")):
            return index
    return None
