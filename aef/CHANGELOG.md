# Changelog

All notable changes to AEF are recorded here.
Versions follow semantic versioning. Projects pin a version; upgrades are deliberate.

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
