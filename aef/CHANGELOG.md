# Changelog

All notable changes to AEF are recorded here.
Versions follow semantic versioning. Projects pin a version; upgrades are deliberate.

## [0.3.0] — 2026-08-13

Make "being worked on now" true.

0.2.0 derived every status from `tasks.yaml`. That answers "is this done?"
correctly and "is anyone on this right now?" incorrectly, because `status:
claimed` is written when an agent remembers to write it, whereas a file lock is
claimed **before the first edit** — Constitution rule 3 makes it mandatory. The
dashboard was reading the later, weaker signal.

Observed in a live project rather than imagined: three tasks held by a running
agent session, all reading `ready` in `tasks.yaml`, the dashboard reporting
"Nothing is claimed right now", and all three listed under *Coming next* while
that session had their files open.

### Added
- `.ai/state/locks.yaml` is now a **third input** to the plan model. A live lock
  promotes a `pending` or `waiting_dependency` leaf to **In progress**, and the
  holder is shown on the tree, the progress view and `aef.py progress`
- `Lock` in `tools/aefkit/model.py`, with TTL evaluation. Only the active
  `locks:` key is read; `history:` is the past and is ignored
- **Coordination notices** — a second, non-fatal problem channel. A lock that
  disagrees with a task status, a lock left on a finished task, two locks on one
  task, a missing or unreadable TTL: each is reported, none is hidden, and none
  fails the plan
- `tools/tests/test_locks.py` — 18 tests. Proven able to fail by three
  sabotages (promotion disabled; guard rails removed; notices made fatal)

### Changed
- `aef.py validate` reports notices but **exits 0** for them. Gating the
  protocol 04 hand-over on a transient lock would mean a plan cannot be
  validated while anyone is working on the project
- `aef.py progress` prints `held by: <agent> until <expiry>` under live work
- `install/BOOTSTRAP.md` §1 pinned the example checkout at `v0.1.0`, two
  releases stale. A reader following it got a framework with no plan tooling at
  all

### Deliberately not done
- A lock never overrides `complete`, `failed` or `blocked`. Those are findings
  about the work and outrank a claim to be editing it; a lock over one of them
  is reported as a leak instead. Burying a `blocked` task under "In progress"
  would take a `NEEDS_HUMAN` item off the operator's screen
- An absent or unparseable TTL counts as **live**, not expired. Failing the
  other way would silently unlock a file somebody is editing
- Still no write path from the dashboard. Status changes go through protocol 05
  and the agent that did the work

## [0.2.0] — 2026-08-12

Plan before execute, and make the plan visible.

### Added
- `core/CONSTITUTION.md` §4a — **plan the whole project before executing any of
  it**. A new project is planned end to end before the first line of code, and
  the plan is not shortened because the work is long
- `schemas/plan.schema.yaml` — `.ai/state/plan.yaml`, the project plan as a tree
  (project → section → feature → task → subtask). Structure, weight and agent
  live here; status stays in `tasks.yaml`; every rollup is derived on read and
  stored nowhere
- `protocols/09-agent-assignment.md` — automatic assignment from classification,
  manual assignment by command, and the rule that automation never overwrites a
  human decision
- `config/agents.yaml` — agent catalogue and assignment rules, as data. Agents
  are assignable capacity bound to the existing seven roles; adding one does not
  add a role
- `tools/` — the framework's first executable layer. Stdlib only, no install:
  - `aef.py dashboard` — project tree and progress views on localhost, read-only
  - `aef.py progress` / `tree` — the same state as text, for agents
  - `aef.py validate` — fails if the plan and the task graph disagree
  - `aef.py assign` — automatic and manual agent assignment
  - `aef.py doctor` — reports what the tooling can see, and verifies the bundled
    YAML reader against PyYAML on your own files
  - `run_tests.py` — 51 tests, `unittest`, no pytest

### Changed
- `protocols/04-planning.md` — rewritten. Adds the A-to-Z requirement, a twelve
  point coverage checklist, a required `completeness` declaration including
  known omissions, tree construction, and the validation gate
- `schemas/task.schema.yaml` — adds `agent`, adds `blocked_reason`, and adds
  `failed` to the status enum. A task that was attempted and did not succeed is
  not the same as one nobody has started
- `install/BOOTSTRAP.md` — plan creation and the dashboard are part of setup

### Notes
- **No project migration is automatic.** `plan.yaml` does not exist until
  protocol 04 writes one, and the tooling says so rather than inventing a tree.
  Migrating an existing flat `tasks.yaml` is a task like any other (BOOTSTRAP §6)
- `abandoned` and `failed` both display under Failed. Removing a node to improve
  the percentage is explicitly forbidden in protocol 04

### Known gaps
- Still no automated validator for `tasks.yaml` itself; `aef.py validate` checks
  the plan/task seam, not every schema field
- The dashboard has no write path by design. Status changes go through protocol
  05 and the agent that did the work

## [0.1.0] — 2026-08-07

Initial public release.

### Added
- `core/CONSTITUTION.md` — always-loaded operating contract, under 200 lines
- `core/OPERATING-LOOP.md` — ten-stage loop, each stage producing an artifact
- `core/NON-NEGOTIABLES.md` — prohibited actions and human-approval gates
- `protocols/` — intake, technology selection, discovery, planning, execution,
  verification, completion, project skill generation
- `roles/` — seven model-agnostic role contracts
- `config/routing.yaml` — change class to mode, roles, and mandatory quality dimensions
- `config/quality-dimensions.yaml` — 45 dimensions, each with required evidence
- `config/framework.yaml` — autonomy, context budget, model tiering, execution defaults
- `schemas/` — task graph, fabrication registry, file locks, domain memory
- `adapters/` — entry stubs for Claude Code, Codex/AGENTS, Cursor, Gemini
- `install/BOOTSTRAP.md` — installation and upgrade procedure

### Known gaps
- No automated validator yet (`verify` script planned for 0.2.0)
- Not yet battle-tested against a large existing repository
- Routing classes cover common web/service/AI work; specialised domains need extension
