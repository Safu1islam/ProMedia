#!/usr/bin/env python3
"""AEF command line — the plan, its progress, and who is assigned to what.

    python aef/tools/aef.py dashboard        open the tree + progress views
    python aef/tools/aef.py progress         one-screen text summary
    python aef/tools/aef.py tree             the plan as an ASCII tree
    python aef/tools/aef.py validate         exit 1 if the plan and tasks disagree
    python aef/tools/aef.py assign ...       assign an agent, automatically or by hand
    python aef/tools/aef.py doctor           what this tool can see and read

Stdlib only. No install step. Works from a project root that contains aef/.
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from aefkit import AEF_TOOLS_VERSION, assign as assign_mod, model, render, server, yamlio  # noqa: E402

_GLYPH = {
    "complete": "[x]",
    "in_progress": "[~]",
    "pending": "[ ]",
    "blocked": "[!]",
    "failed": "[X]",
    "waiting_dependency": "[.]",
}


def _load(args) -> model.Plan:
    try:
        return model.Plan.load(args.root, force_bundled=args.force_bundled)
    except model.PlanError as exc:
        sys.stderr.write(f"error: {exc}\n")
        raise SystemExit(2)


def _plan_path(args) -> str:
    return os.path.join(args.root, ".ai", "state", "plan.yaml")


# ---------------------------------------------------------------------------

def cmd_dashboard(args) -> int:
    server.serve(args.root, args.host, args.port)
    return 0


def cmd_tree(args) -> int:
    plan = _load(args)

    def walk(node: model.Node, prefix: str = "", last: bool = True, top: bool = True) -> None:
        if top:
            progress = plan.progress(node)
            print(f"{node.title}  —  {progress.percent}% ({progress.counts.get('complete', 0)}/{progress.leaf_count})")
        else:
            branch = "`-- " if last else "|-- "
            agent = f"  -> {node.agent}" if node.agent else ""
            if node.is_leaf:
                tid = f" ({node.task_id})" if node.task_id else ""
                print(f"{prefix}{branch}{_GLYPH[node.status]} {node.title}{tid}{agent}")
            else:
                progress = plan.progress(node)
                print(f"{prefix}{branch}{_GLYPH[node.status]} {node.title}  "
                      f"[{progress.percent}% {progress.counts.get('complete', 0)}/{progress.leaf_count}]{agent}")
        children = node.children
        for index, child in enumerate(children):
            is_last = index == len(children) - 1
            extension = "" if top else ("    " if last else "|   ")
            walk(child, prefix + extension, is_last, False)

    walk(plan.root)
    if plan.problems:
        print(f"\n{len(plan.problems)} plan problem(s) — run `validate`.", file=sys.stderr)
    return 0


def cmd_progress(args) -> int:
    plan = _load(args)
    progress = plan.progress()
    counts = progress.counts

    print(f"{plan.root.title}")
    print(f"Project Progress: {progress.percent}%")
    width = 34
    filled = int(round(width * progress.percent / 100.0))
    print(f"  [{'#' * filled}{'-' * (width - filled)}]")
    print()
    for status in model.STATUSES:
        value = counts.get(status, 0)
        if value:
            print(f"  {value:>4}  {model.STATUS_LABELS[status].lower()}")
    print(f"  {'-' * 4}")
    print(f"  {progress.leaf_count:>4}  tasks in the plan")

    def section(title: str, nodes: list[model.Node], reason: bool = False) -> None:
        print(f"\n{title}")
        if not nodes:
            print("  (none)")
            return
        for node in nodes:
            agent = f"  -> {node.agent}" if node.agent else "  -> unassigned"
            where = " / ".join(node.path()[1:-1])
            line = f"  {_GLYPH[node.status]} {node.title}"
            if node.task_id:
                line += f" ({node.task_id})"
            print(line + agent)
            if where:
                print(f"        in: {where}")
            if reason and node.task and node.task.get("blocked_reason"):
                print(f"        why: {' '.join(str(node.task['blocked_reason']).split())}")

    section("Being worked on now:", plan.current())
    section("Coming next:", plan.upcoming(8))
    section("Needs attention:", plan.attention(), reason=True)

    agents = plan.agents()
    if agents:
        print("\nBy agent:")
        for name, stats in agents.items():
            done = stats["counts"].get("complete", 0)
            print(f"  {name:<18} {done}/{stats['total']} complete")

    if plan.problems:
        print(f"\n{len(plan.problems)} plan problem(s) — run `validate`.", file=sys.stderr)
        return 1
    return 0


def cmd_validate(args) -> int:
    plan = _load(args)
    if not plan.problems:
        progress = plan.progress()
        print(f"plan OK — {progress.leaf_count} leaves, {len(plan.tasks)} tasks, all accounted for")
        return 0
    print(f"{len(plan.problems)} problem(s):", file=sys.stderr)
    for problem in plan.problems:
        print(f"  - {problem}", file=sys.stderr)
    return 1


def cmd_assign(args) -> int:
    plan = _load(args)
    catalogue = assign_mod.load_catalogue(args.root, force_bundled=args.force_bundled)
    path = _plan_path(args)

    if args.list:
        print("Agents in the catalogue:\n")
        for name, spec in catalogue.agents.items():
            does = " ".join(str(spec.get("does") or "").split())
            print(f"  {name:<16} role={spec.get('role', '?'):<26} tier={spec.get('tier', '?')}")
            if does:
                print(f"  {'':<16} {does[:96]}")
        return 0

    if args.auto:
        changed = 0
        skipped = 0
        for node in plan.root.leaves():
            if node.agent_source == "manual":
                skipped += 1
                continue
            if node.agent and not args.overwrite:
                continue
            suggestion = assign_mod.suggest(node.task, node.title, catalogue)
            if not suggestion.agent or suggestion.agent == node.agent:
                continue
            if args.dry_run:
                print(f"would assign {node.id:<10} -> {suggestion.agent:<16} ({suggestion.reason})")
            else:
                assign_mod.set_agent(path, node.id, suggestion.agent, locked=False, catalogue=catalogue)
                print(f"{node.id:<10} -> {suggestion.agent:<16} ({suggestion.reason})")
            changed += 1
        verb = "would change" if args.dry_run else "assigned"
        print(f"\n{verb} {changed} node(s); {skipped} left alone because they were assigned by hand")
        return 0

    if not args.node:
        sys.stderr.write("error: give --node NODE_ID with --agent NAME, or use --auto / --list\n")
        return 2

    try:
        if args.clear:
            print(assign_mod.set_agent(path, args.node, None, catalogue=catalogue))
        else:
            if not args.agent:
                sys.stderr.write("error: --agent is required unless --clear is given\n")
                return 2
            print(assign_mod.set_agent(path, args.node, args.agent, locked=True, catalogue=catalogue))
    except assign_mod.AssignError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 2
    return 0


def cmd_doctor(args) -> int:
    root = os.path.abspath(args.root)
    print(f"aef tools    {AEF_TOOLS_VERSION}")
    print(f"python       {sys.version.split()[0]}")
    print(f"yaml reader  {yamlio.reader_name()}")
    print(f"project root {root}")
    version_path = os.path.join(root, "aef", "VERSION")
    if os.path.exists(version_path):
        with open(version_path, encoding="utf-8") as handle:
            pinned = handle.read().strip()
        print(f"aef/VERSION  {pinned}" + ("" if pinned == AEF_TOOLS_VERSION else "   <-- MISMATCH with tools"))
    for relative in (".ai/state/plan.yaml", ".ai/state/tasks.yaml", "aef/config/agents.yaml"):
        full = os.path.join(root, relative)
        print(f"{'found  ' if os.path.exists(full) else 'MISSING'}      {relative}")

    # Prove the bundled reader on this project's own files, both ways when
    # PyYAML is present. Claiming the fallback works without running it would be
    # exactly the unverified claim the constitution forbids.
    if yamlio.USING_PYYAML:
        import yaml as pyyaml
        for relative in (".ai/state/plan.yaml", ".ai/state/tasks.yaml"):
            full = os.path.join(root, relative)
            if not os.path.exists(full):
                continue
            try:
                mine = yamlio.load(full, force_bundled=True)
                theirs = pyyaml.safe_load(open(full, encoding="utf-8"))
                verdict = "agree" if mine == theirs else "DISAGREE"
            except Exception as exc:  # noqa: BLE001 - report, do not crash doctor
                verdict = f"bundled reader failed: {type(exc).__name__}: {exc}"
            print(f"readers {verdict:<9} on {relative}")
    return 0


# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aef", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", default=".", help="project root containing aef/ and .ai/ (default: .)")
    parser.add_argument("--force-bundled", action="store_true",
                        help="ignore PyYAML and use the bundled reader (for testing the fallback)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    dashboard = subparsers.add_parser("dashboard", help="serve the tree and progress views")
    dashboard.add_argument("--port", type=int, default=7423)
    dashboard.add_argument("--host", default="127.0.0.1",
                           help="default 127.0.0.1; a plan is internal, bind wider only on purpose")
    dashboard.set_defaults(func=cmd_dashboard)

    subparsers.add_parser("tree", help="print the plan as a tree").set_defaults(func=cmd_tree)
    subparsers.add_parser("progress", help="print the progress summary").set_defaults(func=cmd_progress)
    subparsers.add_parser("validate", help="check the plan against tasks.yaml").set_defaults(func=cmd_validate)
    subparsers.add_parser("doctor", help="report what the tool can see").set_defaults(func=cmd_doctor)

    assign_parser = subparsers.add_parser("assign", help="assign agents to plan nodes")
    assign_parser.add_argument("--node", help="plan node id, e.g. N-014")
    assign_parser.add_argument("--agent", help="agent id from the catalogue")
    assign_parser.add_argument("--clear", action="store_true", help="remove the assignment")
    assign_parser.add_argument("--auto", action="store_true", help="assign every unassigned leaf automatically")
    assign_parser.add_argument("--overwrite", action="store_true",
                               help="with --auto, also replace automatic assignments (never manual ones)")
    assign_parser.add_argument("--dry-run", action="store_true", help="with --auto, show changes without writing")
    assign_parser.add_argument("--list", action="store_true", help="list the agent catalogue")
    assign_parser.set_defaults(func=cmd_assign)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
