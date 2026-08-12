"""The project plan tree, its derived status, and its progress arithmetic.

One authority per fact. This is the rule the whole module is built around, and
it is why there are two files rather than one:

    structure, weight, agent   ->  .ai/state/plan.yaml
    task status and evidence   ->  .ai/state/tasks.yaml
    everything else            ->  DERIVED HERE, never stored

A grouping node's status and a project's percentage are computed on every read.
Storing them would create a second place where "is this done?" is answered, and
the two would drift the first time an agent updated one and not the other.

`validate()` enforces the seam: every task appears as exactly one leaf, and
every leaf points at a real task. A plan that has drifted from its tasks is a
plan that lies, so the dashboard refuses to render one.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Iterator

from . import yamlio

__all__ = [
    "Plan",
    "Node",
    "Progress",
    "PlanError",
    "STATUSES",
    "TASK_STATUS_MAP",
    "NODE_TYPES",
]


class PlanError(Exception):
    """The plan cannot be loaded or does not describe the tasks it claims to."""


# Display vocabulary. Fixed set — the dashboard's legend, the CLI's output and
# the rollup all read from here so a new status cannot appear in one and not the
# others.
STATUSES = (
    "complete",
    "in_progress",
    "blocked",
    "waiting_dependency",
    "failed",
    "pending",
)

STATUS_LABELS = {
    "complete": "Completed",
    "in_progress": "In progress",
    "pending": "Pending",
    "blocked": "Blocked",
    "failed": "Failed",
    "waiting_dependency": "Waiting for dependency",
}

# tasks.yaml status -> display status. `ready` is resolved further at rollup
# time: ready with an unmet dependency is waiting_dependency, not pending.
TASK_STATUS_MAP = {
    "ready": "pending",
    "claimed": "in_progress",
    "in_review": "in_progress",
    "blocked": "blocked",
    "complete": "complete",
    "failed": "failed",
    "abandoned": "failed",
}

NODE_TYPES = ("project", "section", "feature", "task", "subtask")

# Precedence when rolling a group's children up into one status. Failure is
# loudest deliberately: a section containing one failed task must not read as
# "in progress" just because its siblings are moving.
_ROLLUP_PRECEDENCE = ("failed", "in_progress", "blocked", "waiting_dependency", "pending")


@dataclass
class Node:
    id: str
    title: str
    type: str
    children: list["Node"] = field(default_factory=list)
    task_id: str | None = None
    agent: str | None = None
    agent_source: str = "unassigned"  # auto | manual | inherited | unassigned
    weight: float = 1.0
    depends_on: list[str] = field(default_factory=list)
    note: str | None = None
    parent: "Node | None" = None
    # Only meaningful on a leaf with no linked task — a subtask finer-grained
    # than tasks.yaml tracks. Ignored on any node that links a task, because
    # tasks.yaml is the authority there.
    status_override: str | None = None

    # Filled by Plan._resolve(); None until then.
    status: str = "pending"
    task: dict[str, Any] | None = None

    @property
    def is_leaf(self) -> bool:
        return not self.children

    def walk(self) -> Iterator["Node"]:
        yield self
        for child in self.children:
            yield from child.walk()

    def leaves(self) -> Iterator["Node"]:
        for node in self.walk():
            if node.is_leaf:
                yield node

    def path(self) -> list[str]:
        parts: list[str] = []
        node: Node | None = self
        while node is not None:
            parts.append(node.title)
            node = node.parent
        return list(reversed(parts))


@dataclass
class Progress:
    """Counts are of LEAVES, weighted. Grouping nodes are not work; counting them
    would inflate a deep tree's percentage over a flat one describing the same
    work."""

    total: float = 0.0
    by_status: dict[str, float] = field(default_factory=dict)
    leaf_count: int = 0
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def percent(self) -> int:
        if self.total <= 0:
            return 0
        return int(round(100.0 * self.by_status.get("complete", 0.0) / self.total))

    def as_dict(self) -> dict[str, Any]:
        return {
            "percent": self.percent,
            "total_weight": self.total,
            "leaf_count": self.leaf_count,
            "weighted": {status: self.by_status.get(status, 0.0) for status in STATUSES},
            "counts": {status: self.counts.get(status, 0) for status in STATUSES},
            "labels": STATUS_LABELS,
        }


class Plan:
    def __init__(self, root: Node, meta: dict[str, Any], tasks: dict[str, dict[str, Any]],
                 problems: list[str], project_root: str):
        self.root = root
        self.meta = meta
        self.tasks = tasks
        self.problems = problems
        self.project_root = project_root

    # -- loading ----------------------------------------------------------

    @classmethod
    def load(cls, project_root: str = ".", *, force_bundled: bool = False) -> "Plan":
        plan_path = os.path.join(project_root, ".ai", "state", "plan.yaml")
        tasks_path = os.path.join(project_root, ".ai", "state", "tasks.yaml")

        if not os.path.exists(plan_path):
            raise PlanError(
                f"No plan at {plan_path}.\n"
                "AEF 0.2.0 plans a project before it executes it. Run "
                "aef/protocols/04-planning.md to produce one."
            )

        raw = yamlio.load(plan_path, force_bundled=force_bundled) or {}
        tasks: dict[str, dict[str, Any]] = {}
        if os.path.exists(tasks_path):
            task_doc = yamlio.load(tasks_path, force_bundled=force_bundled) or {}
            for entry in task_doc.get("tasks") or []:
                if isinstance(entry, dict) and entry.get("id"):
                    tasks[str(entry["id"])] = entry
            # follow_up_tasks carry the same shape and are real work; a plan that
            # ignored them would report a percentage over an incomplete denominator.
            for entry in task_doc.get("follow_up_tasks") or []:
                if isinstance(entry, dict) and entry.get("id"):
                    tasks[str(entry["id"])] = entry

        tree_raw = raw.get("tree")
        if not isinstance(tree_raw, dict):
            raise PlanError(f"{plan_path}: top-level `tree:` mapping is missing.")

        root = cls._build(tree_raw, parent=None, default_type="project")
        plan = cls(root, raw.get("meta") or {}, tasks, [], os.path.abspath(project_root))
        plan._inherit_agents()
        plan._resolve()
        plan.problems = plan.validate()
        return plan

    @staticmethod
    def _build(raw: dict[str, Any], parent: Node | None, default_type: str) -> Node:
        if not raw.get("id"):
            raise PlanError(f"Every plan node needs an id. Offender: {raw.get('title') or raw!r}")
        node = Node(
            id=str(raw["id"]),
            title=str(raw.get("title") or raw["id"]),
            type=str(raw.get("type") or default_type),
            task_id=str(raw["task"]) if raw.get("task") else None,
            agent=raw.get("agent"),
            agent_source="manual" if raw.get("agent_locked") else ("auto" if raw.get("agent") else "unassigned"),
            weight=float(raw.get("weight", 1.0)),
            depends_on=[str(dep) for dep in (raw.get("depends_on") or [])],
            note=raw.get("note"),
            parent=parent,
            status_override=str(raw["status"]) if raw.get("status") else None,
        )
        if node.type not in NODE_TYPES:
            raise PlanError(f"Node {node.id}: unknown type {node.type!r}. Known: {', '.join(NODE_TYPES)}")
        for child_raw in raw.get("children") or []:
            node.children.append(Plan._build(child_raw, node, "task"))
        return node

    def _inherit_agents(self) -> None:
        """A group's agent is the default for its subtree. Assigning an agent to
        `Frontend` and having every child inherit it is the common case; an
        explicit child assignment always wins."""
        def walk(node: Node, inherited: str | None) -> None:
            if node.agent is None and inherited is not None:
                node.agent = inherited
                node.agent_source = "inherited"
            for child in node.children:
                walk(child, node.agent)
        walk(self.root, None)

    # -- derivation -------------------------------------------------------

    def _resolve(self) -> None:
        """Two passes, because a dependency may point at any node in the tree —
        including one that has not been resolved yet when a single bottom-up
        walk reaches the node depending on it.

        Pass 1 establishes every node's status from its own evidence.
        Pass 2 downgrades still-pending nodes whose dependencies are unmet, then
        re-rolls the groups so a section containing a waiting task says so.
        """
        by_node = {node.id: node for node in self.root.walk()}

        for node in self.root.walk():
            if node.task_id and node.task_id in self.tasks:
                node.task = self.tasks[node.task_id]
                # Dependencies live in tasks.yaml, where the execution protocol
                # already maintains them. A leaf inherits its task's depends_on
                # rather than restating it, so the two cannot disagree; the plan
                # adds structural dependencies that have no task to hang on.
                for dep in node.task.get("depends_on") or []:
                    if str(dep) not in node.depends_on:
                        node.depends_on.append(str(dep))

        def compute(node: Node) -> str:
            if node.is_leaf:
                node.status = self._leaf_status(node)
            else:
                node.status = self._rollup([compute(child) for child in node.children])
            return node.status

        compute(self.root)

        def dependency_met(node: Node) -> bool:
            for dep in node.depends_on:
                target = by_node.get(dep)
                if target is not None:
                    if target.status != "complete":
                        return False
                    continue
                task = self.tasks.get(dep)
                if task is not None:
                    if TASK_STATUS_MAP.get(str(task.get("status") or "ready"), "pending") != "complete":
                        return False
            return True

        for node in self.root.walk():
            if node.is_leaf and node.status == "pending" and node.depends_on:
                if not dependency_met(node):
                    node.status = "waiting_dependency"

        def reroll(node: Node) -> str:
            if not node.is_leaf:
                node.status = self._rollup([reroll(child) for child in node.children])
            if node.status == "pending" and node.depends_on and not dependency_met(node):
                node.status = "waiting_dependency"
            return node.status

        reroll(self.root)

    def _leaf_status(self, node: Node) -> str:
        if node.task is not None:
            return TASK_STATUS_MAP.get(str(node.task.get("status") or "ready"), "pending")
        # A leaf with no linked task carries its own status. Subtasks finer than
        # tasks.yaml tracks are why this exists. The value may be written in
        # either vocabulary; display terms pass through unchanged.
        raw = str(node.status_override or "ready")
        if raw in STATUSES:
            return raw
        return TASK_STATUS_MAP.get(raw, "pending")

    @staticmethod
    def _rollup(child_statuses: list[str]) -> str:
        """Worst-news-first, with one exception: any progress at all outranks
        `pending`, so a half-finished section never reads as untouched."""
        if not child_statuses:
            return "pending"
        present = set(child_statuses)
        if present == {"complete"}:
            return "complete"
        if "failed" in present:
            return "failed"
        if "in_progress" in present or "complete" in present:
            return "in_progress"
        for status in _ROLLUP_PRECEDENCE:
            if status in present:
                return status
        return "pending"

    # -- reporting --------------------------------------------------------

    def progress(self, node: Node | None = None) -> Progress:
        node = node or self.root
        result = Progress()
        for leaf in node.leaves():
            result.total += leaf.weight
            result.leaf_count += 1
            result.by_status[leaf.status] = result.by_status.get(leaf.status, 0.0) + leaf.weight
            result.counts[leaf.status] = result.counts.get(leaf.status, 0) + 1
        return result

    def current(self) -> list[Node]:
        """Leaves being worked on now."""
        return [leaf for leaf in self.root.leaves() if leaf.status == "in_progress"]

    def upcoming(self, limit: int = 12) -> list[Node]:
        """Leaves that could be started next: pending, with dependencies met.
        Ordered by tree position, which is plan order."""
        ready = [leaf for leaf in self.root.leaves() if leaf.status == "pending"]
        return ready[:limit]

    def attention(self) -> list[Node]:
        return [
            leaf for leaf in self.root.leaves()
            if leaf.status in ("blocked", "failed", "waiting_dependency")
        ]

    def agents(self) -> dict[str, dict[str, Any]]:
        """Per-agent workload, counted over leaves only."""
        out: dict[str, dict[str, Any]] = {}
        for leaf in self.root.leaves():
            name = leaf.agent or "unassigned"
            bucket = out.setdefault(name, {"total": 0, "counts": {}})
            bucket["total"] += 1
            bucket["counts"][leaf.status] = bucket["counts"].get(leaf.status, 0) + 1
        return dict(sorted(out.items(), key=lambda item: (-item[1]["total"], item[0])))

    # -- validation -------------------------------------------------------

    def validate(self) -> list[str]:
        """Structural problems, worst first. An empty list means the plan and the
        task graph agree."""
        problems: list[str] = []
        seen_ids: dict[str, int] = {}
        linked: dict[str, list[str]] = {}

        for node in self.root.walk():
            seen_ids[node.id] = seen_ids.get(node.id, 0) + 1
            if node.task_id:
                linked.setdefault(node.task_id, []).append(node.id)
                if node.task_id not in self.tasks:
                    problems.append(
                        f"node {node.id} links task {node.task_id}, which is not in tasks.yaml"
                    )
                if not node.is_leaf:
                    problems.append(
                        f"node {node.id} links a task but has children; only leaves carry tasks"
                    )

        for node_id, count in seen_ids.items():
            if count > 1:
                problems.append(f"duplicate node id {node_id} appears {count} times")

        for task_id, nodes in linked.items():
            if len(nodes) > 1:
                problems.append(
                    f"task {task_id} is claimed by {len(nodes)} nodes ({', '.join(nodes)}); "
                    "a task belongs to exactly one place in the plan"
                )

        uncovered = sorted(set(self.tasks) - set(linked))
        for task_id in uncovered:
            title = str(self.tasks[task_id].get("title") or "")[:60]
            problems.append(
                f"task {task_id} ({title}) is in tasks.yaml but appears nowhere in the plan — "
                "the percentage would be computed over an incomplete denominator"
            )

        known = set(seen_ids) | set(self.tasks)
        for node in self.root.walk():
            for dep in node.depends_on:
                if dep not in known:
                    problems.append(f"node {node.id} depends on {dep}, which does not exist")

        problems.extend(self._cycles())
        return problems

    def _cycles(self) -> list[str]:
        by_id = {node.id: node for node in self.root.walk()}
        state: dict[str, int] = {}
        found: list[str] = []

        def visit(node_id: str, trail: list[str]) -> None:
            if state.get(node_id) == 2:
                return
            if state.get(node_id) == 1:
                cycle = trail[trail.index(node_id):] + [node_id]
                found.append("dependency cycle: " + " -> ".join(cycle))
                return
            state[node_id] = 1
            node = by_id.get(node_id)
            if node is not None:
                for dep in node.depends_on:
                    if dep in by_id:
                        visit(dep, trail + [node_id])
            state[node_id] = 2

        for node_id in by_id:
            visit(node_id, [])
        return found

    # -- serialisation ----------------------------------------------------

    def as_dict(self) -> dict[str, Any]:
        def node_dict(node: Node) -> dict[str, Any]:
            progress = self.progress(node)
            entry: dict[str, Any] = {
                "id": node.id,
                "title": node.title,
                "type": node.type,
                "status": node.status,
                "status_label": STATUS_LABELS[node.status],
                "agent": node.agent,
                "agent_source": node.agent_source,
                "weight": node.weight,
                "depends_on": node.depends_on,
                "leaf": node.is_leaf,
                "percent": progress.percent,
                "counts": progress.as_dict()["counts"],
                "leaf_count": progress.leaf_count,
            }
            if node.note:
                entry["note"] = node.note
            if node.task_id:
                entry["task_id"] = node.task_id
            if node.task is not None:
                criteria = node.task.get("acceptance_criteria") or []
                entry["task"] = {
                    "status": node.task.get("status"),
                    "objective": _one_line(node.task.get("objective")),
                    "owner_role": node.task.get("owner_role"),
                    "mode": node.task.get("mode"),
                    "change_class": node.task.get("change_class"),
                    "claimed_by": node.task.get("claimed_by"),
                    "blocked_reason": _one_line(node.task.get("blocked_reason")),
                    "criteria_total": len(criteria),
                    "criteria_passed": sum(
                        1 for criterion in criteria
                        if isinstance(criterion, dict) and criterion.get("result") == "PASSED"
                    ),
                }
            if node.children:
                entry["children"] = [node_dict(child) for child in node.children]
            return entry

        return {
            "meta": {
                **self.meta,
                "reader": yamlio.reader_name(),
                "project_root": self.project_root,
            },
            "progress": self.progress().as_dict(),
            "tree": node_dict(self.root),
            "agents": self.agents(),
            "current": [_brief(node) for node in self.current()],
            "upcoming": [_brief(node) for node in self.upcoming()],
            "attention": [_brief(node) for node in self.attention()],
            "problems": self.problems,
        }


def _one_line(value: Any) -> str | None:
    if not value:
        return None
    return " ".join(str(value).split())


def _brief(node: Node) -> dict[str, Any]:
    return {
        "id": node.id,
        "title": node.title,
        "status": node.status,
        "status_label": STATUS_LABELS[node.status],
        "agent": node.agent,
        "task_id": node.task_id,
        "path": node.path()[1:-1],
        "reason": _one_line((node.task or {}).get("blocked_reason")) if node.task else None,
    }
