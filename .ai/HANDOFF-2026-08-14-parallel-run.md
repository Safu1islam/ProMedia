# HANDOFF — five-agent parallel run, 2026-08-14

> Written by the coordinating session at the moment it ran out of account
> capacity. **Nothing in this file is a claim that the work is finished.** It is a
> map of what landed, what was proven, and what is still unverified, so the next
> agent starts from facts rather than from the diff.
>
> **All locks from this run are RELEASED** (see `.ai/state/locks.yaml` history).
> The paths are yours to claim. Claim them before editing — Constitution rule 3.

> **RESOLVED 2026-08-14, coordinating session claude-code-coordinator-0814c.**
> Every item this handoff named as unresolved has been checked and closed —
> §3's T-045 judgement call (all seven transitions independently pixel-verified,
> not just dissolve), §5's sabotage checks on T-046 and T-048 (both clean,
> both re-sabotaged-and-reverted by the coordinator to prove the rights gate
> and the C-31 ceiling are real), §6's owed fabrications (F-004/F-005
> registered; T-048's providers found to owe none, recorded as a note instead),
> and §7's shared-file protocol (held — verified directly, not assumed).
> T-045/T-046/T-048 are now `complete` in `.ai/state/tasks.yaml` with
> `independent_review: PASSED`, each reviewed by this session rather than by
> the (absent) implementing agent. Full suite: 769 passed, 3 failed — the 3
> are `tests/test_publishers.py`, pre-existing and unrelated to this run
> (stale tests left by the already-landed T-019, filed as R-013). Full detail
> is in each task's own record and in `.ai/state/fabrications.yaml`; this note
> exists so a reader does not re-verify what is already closed. §9's standing
> shortfall (many earlier tasks still lack independent review) is unchanged by
> this pass and remains open.

---

## 1. What this run was

Five Sonnet 5 agents were given one task each, with file ownership partitioned so
no two agents owned the same file. They ran concurrently in the same working tree
on branch `aef/0.4.0-multi-agent-coordination`.

| Task | Subject | Record returned? | Status now |
|---|---|---|---|
| T-045 | True cross-dissolves, retires F-003 | **Partial** — measurements yes, final record no | `in_progress` |
| T-043 | Renders count against the storage ledger | **Full** | `complete` — see §4 caveat |
| T-046 | URL acquisition through the rights gate | **None** | `in_progress` |
| T-047 | Transcription, subtitles, silence rough cut | **Full** | `complete` |
| T-048 | AI providers and the C-31 spend ledger | **None** | `in_progress` |

All five were terminated by an account session limit, not by finishing. T-047 was
additionally interrupted once by a connection drop mid-sabotage-test; the tree was
checked and no sabotaged code was left behind.

---

## 2. The full suite — actually observed, after all five agents landed

The coordinating session ran this centrally after the agents stopped, so this is a
**single coherent observation of the final tree**, not a stitched-together set of
agent reports:

```
python -m pytest -p no:cacheprovider
```

**15 failures.** No import or collection errors. Baseline before this run was 561
passed. Every failure, with its root cause:

| Test | Cause | Action |
|---|---|---|
| `test_projects.py::test_a_render_reports_what_it_did_not_do_as_asked` | T-045 retired F-003 | §3 — stale expectation |
| `test_projects.py::test_each_unimplemented_transition_is_reported_on_the_render[dissolve, wipeleft, wiperight, slideup, slidedown]` (5) | T-045 retired F-003 | §3 — stale expectation |
| `test_editor_ui.py::test_the_transition_picker_marks_known_substitutions` | T-045 retired F-003 | §3 — same root cause |
| `test_editor_ui.py::test_dashboard_shows_recent_renders_and_flags_substitutions` | T-045 retired F-003 | §3 — same root cause |
| `test_ops_forms.py::test_get_of_a_mutating_form_changes_nothing[acquire, record-spend, run-capability]` (3) | New mutating operations with no probe value | A pin firing as designed. Supply probe values |
| `test_registry.py::test_operator_only_operations_are_the_expected_set` | `record-spend` and `run-capability` are now operator authority | §5 — pin firing correctly |
| `test_publishers.py::test_stub_requires_explicit_simulation_flag`, `::test_stub_never_confirms_published`, `::test_real_platform_limits_are_unknown_not_guessed` (3) | **Pre-existing.** Uncommitted T-019 work already in the tree before this run | Not this run's to fix |

**Eight of the fifteen are one root cause** — T-045's F-003 retirement invalidating
tests that assert the old substitution reporting. Three are a pin doing its job on
new operations. Three are inherited. One is the authority pin.

`tests/test_restore.py` **passes** — so T-048's `backup.classify_tables()` did
classify the new spend table. An earlier agent report suspected otherwise; that
suspicion was from a mid-run snapshot and is superseded by this observation.

Nothing fails in `test_analyse.py`, `test_render_storage.py`, `test_acquire.py`,
`test_providers.py`, `test_parity.py`, `test_transitions.py`, `test_edl.py` or
`test_media.py`.

---

## 3. T-045 — the decision waiting for you

This is the most consequential unresolved item, and it is a **judgement call, not
a bug fix.**

T-045 set out to implement true cross-dissolves and, on its own report, went
further: `render.TRANSITION_REALITY` now maps **all seven** transitions to `None`,
meaning every one is claimed to render as named and F-003 is fully retired.

The evidence it returned for that claim is genuinely good, and is quoted here
because the agent that produced it is gone:

- **Sabotage cycle completed and reverted.** Reverting `dissolve` to the old
  fade-from-black path failed 8 tests in `tests/test_transitions.py`, including
  `test_dissolve_blends_both_clips_at_the_midpoint_ac1` and
  `test_f_003_is_fully_retired`. Post-revert hashes:
  `render.py` `627552ba0da99fcccc331139b20270fe0f35335aaa6d1e3fb7de287c8950a345`,
  `edl.py` `d0b9fa1cb4d5de2539d2e500b2c6ea8133c3aea1c7b4f9b2c4fff1bb4f6c9c2f`.
  `tests/test_transitions.py` then passed 21/21.
- **AC-1 measured, not eyeballed.** Red→blue dissolve, 3s+3s clips, 1.0s
  transition. At the transition midpoint (t=2.5s): R=119.9, G=7.5, B=132.2, mean
  luminance 86.5 — a real blend of both colours. The same clips with `fade`: mean
  luminance 43.7 at its midpoint, and **0.0 (pure black) at the cut point**. That
  contrast is exactly the discrimination AC-1 asked for.
- **AC-2 measured.** Dissolve expected 5.0s, ffprobe-measured 5.0s exactly, where
  the naive sum would have been 6.0s. Overlap is genuinely accounted for.

**What is NOT established**, and what you must settle before marking T-045
complete:

1. The measurement above covers `dissolve`. **The other six transitions
   (`wipeleft`, `wiperight`, `slideup`, `slidedown`, and the rest of the
   vocabulary) were not shown to be measured the same way** in anything the agent
   returned. `TRANSITION_REALITY` now asserts all seven are real. Verify that
   claim per transition, the same way `dissolve` was verified. If any one of them
   does not render as named, it must go back to being reported as a substitution —
   an over-claim here is a worse outcome than the original F-003, because F-003 at
   least reported itself.
2. **Eight tests now assert behaviour that is deliberately obsolete** — 6 in
   `tests/test_projects.py` (`test_a_render_reports_what_it_did_not_do_as_asked`
   plus the five parametrised
   `test_each_unimplemented_transition_is_reported_on_the_render[...]` cases) and
   2 in `tests/test_editor_ui.py`
   (`test_the_transition_picker_marks_known_substitutions`,
   `test_dashboard_shows_recent_renders_and_flags_substitutions`). Nobody owned
   either file in this run, so nobody updated them. The UI pair matters
   independently: those screens exist to warn the operator that a transition will
   not render as named, and if that warning is now simply gone, confirm it is gone
   because the substitutions are gone — not because the plumbing broke.
   **Do not simply delete any of the eight.** The rule
   `test_every_advertised_transition_is_either_implemented_or_reported` is the one
   that matters and must survive: it asserts the two sets match as a rule over the
   vocabulary, not as a list of known-bad names. Rewrite the stale cases to assert
   the new reality only after you have independently confirmed item 1.
3. F-003 in `.ai/state/fabrications.yaml` is **still open.** Close it only after
   item 1, and record what proved it.

---

## 4. T-043 — complete, with one process caveat and one real gap

The record is written into `.ai/state/tasks.yaml` and the evidence is strong: real
ffmpeg renders through the operation layer, a ledger delta matching the output
byte size exactly (246768 → 366630 → 246768 across render and delete), and a
sabotage cycle where making `storage.release()` a no-op failed exactly the two
reservation-leak tests, with `storage.py` hash-verified on revert as
`75fe623ef409e7106b4db0e90fae8b3920cb7b2deac8384f96c82334750be3ed`.

**Process caveat, recorded rather than hidden:** agents in this run were instructed
not to write to `.ai/**` — the coordinator was to write records, to stop five
agents contending on one YAML file. T-043's record is nonetheless present in
`tasks.yaml` and the coordinating session did not write it. Either the agent wrote
it despite the instruction, or a concurrent session did. **Verify its provenance
before trusting it as coordinator-reviewed** — the content matches what the agent
returned, so the risk is process, not fabrication.

**Real gap the agent disclosed itself:** `delete_render()` implements AC-3 but is
**not registered as an operation**, because `promedia/core/ops/projects.py` was
outside its claim. So it is reachable from neither surface, which is an F-1 / S4
problem — the parity gate cannot see it. Registering it as `delete-render` with
`entity='project'` is a small, well-defined next task.

Also worth knowing: T-043 flagged that `config.defaults()` does not deep-copy
nested dict values, and its new `media.estimated_bitrate_bytes_per_second` is the
first nested-dict config value in the codebase. Nothing mutates it in place today.
It is a latent trap, not a live bug.

---

## 5. T-046 and T-048 — code landed, nothing verified

**Treat both as unverified work in progress.** Their code is in the tree. Neither
agent returned a completion record, so no acceptance criterion has evidence behind
it and no sabotage cycle is known to have completed.

Files present from **T-046** (URL acquisition):
`promedia/core/acquire.py`, `promedia/core/ops/acquire.py`, `tests/test_acquire.py`

Files present from **T-048** (providers and spend ledger):
`promedia/core/providers/`, `promedia/core/ops/providers.py`,
`tests/test_providers.py`, plus edits to `promedia/core/schema.sql` and
`promedia/core/backup.py`

Before trusting either, in this order:

1. **Check for left-behind sabotage.** Both were instructed to run a
   sabotage-and-revert cycle and both died without confirming a revert. T-048's
   last words were "Now the full suite", i.e. past its sabotage step; T-046's
   position is unknown. Run each one's test file and, if anything looks
   deliberately broken, `git diff` the file and restore it. This is the first
   thing to do and it is not optional.
2. **T-048 specifically — verify no purchase path exists.** The operator's
   instruction was absolute: the spend ledger records and refuses, nothing buys
   anything, not even a stub. Grep the new provider code for any payment,
   checkout, or top-up path and confirm it is empty. Do not take its absence on
   faith.
3. **T-048 — the authority pin fired, and it fired correctly.**
   `test_registry.py::test_operator_only_operations_are_the_expected_set` reports
   `record-spend` and `run-capability` as extra operator-authority operations.
   That is the right call under F-2 — anything that could commit money needs the
   operator — but the pin exists to force the reasoning to be *written down*
   rather than assumed. Add both to the expected set **with a comment explaining
   why**, the way `publish-tick` and `export-permanent-set` were justified when
   they joined it. Do not just widen the set silently.
   Note that `tests/test_restore.py` **passes**, so `backup.classify_tables()`
   did classify the new spend table — verify how it was classified and whether
   that choice is defensible (a spend record is the operator's money history,
   which argues permanent, not a recomputable cache).
4. **T-046 — establish whether any real network fetch ever happened.** Its tests
   were supposed to fake the downloader boundary. If a mocked `yt-dlp` is being
   read as a live one anywhere, that is exactly the silent-substitution class
   Constitution section 6 forbids. Any mock must be registered in
   `.ai/state/fabrications.yaml`.
5. **T-046 — confirm no second ingest path was grown.** The rule was that
   acquisition calls the existing `ingest` capability rather than reimplementing
   hashing, storage accounting or declaration validation. Two implementations of
   one capability is the F-1 defect.
6. **Both — confirm rights cannot be bypassed.** There must be no path that
   acquires media without a rights declaration.

---

## 6. Fabrications owed to the registry

The coordinator was to write these and did not get to it. `.ai/state/tasks.yaml`
already references **F-004** and **F-005** in T-047's `fabrications_introduced`,
**but no such entries exist in `.ai/state/fabrications.yaml` yet.** Write them, or
renumber to whatever is free:

- **F-004 — transcription unavailable.** `faster-whisper` is not installed on this
  machine (verified twice: `pip show` reports nothing, `import` raises
  `ModuleNotFoundError`, `torch` also absent). The `transcribe` operation raises a
  structured `TranscriptionUnavailable` naming package, install command, model
  size, download-size estimate, CPU realtime-factor estimate and remedy — it never
  returns empty and calls it success. *Replacement condition:* `pip install
  faster-whisper` plus a model choice. **Operator decision — an agent should not
  install it unasked.** No code change follows.
- **F-005 — transcription cost estimates.** The per-model download sizes and CPU
  realtime factors in `transcription_requirements()` are disclosed estimates from
  general knowledge, not benchmarks on this hardware. *Replacement condition:* a
  real run on this machine, the way T-041 measured render speed.

T-043 additionally disclosed three estimates that should be registered:
`estimated_bitrate_bytes_per_second` for the `fast` and `quality` presets
(extrapolated from CRF, whereas `balanced` and `hardware` are anchored to real
T-041 measurements), `unknown_clip_duration_seconds` (a 60s fallback, flagged at
runtime by `duration_measured: False`), and `render_size_safety_margin` (1.25, a
round number with no error distribution behind it yet).

T-048's unavailable capabilities were each supposed to be registered as a
fabrication gap. That list was never returned. Rebuild it from the code.

---

## 7. Shared-file protocol — verify it held

Three files could not be cleanly partitioned and took additive edits from several
agents: `promedia/core/ops/__init__.py`, `promedia/config.py`, `promedia.toml`.
Each agent was told to re-verify its own lines at the end. T-047 and T-043 both
confirmed theirs survived. **T-045, T-046 and T-048 never confirmed.**

Check that `ops/__init__.py` imports and `__all__`-exports every one of
`acquire`, `analyse`, `providers` — a missing name here does not fail any test. It
just silently removes the capability from both surfaces, which is precisely the
F-1 defect the parity gate exists to catch and cannot catch in this direction.

Also confirm `promedia.toml` and `config.py` still carry the `[analysis]`,
`[acquire]`, `[spend]` and new `[media]` keys, and that nobody's edit clobbered
another's.

---

## 8. State bookkeeping still owed

- `T-045`, `T-046`, `T-048` are `in_progress` with `NOT_RUN` criteria and a
  `claimed_by` naming an agent that no longer exists. Resolve each to `complete`
  with evidence, or back to `ready` with an honest note. **Do not leave a
  `claimed_by` pointing at a dead session** — that is the lock-leak pattern AEF
  0.3.0's validator was written to catch.
- `.ai/state/plan.yaml` percentages will have moved.
- Nothing from this run has been committed. `git status` shows the five agents'
  files alongside pre-existing uncommitted work from other sessions (T-019
  publishers, the frontend). **Do not `git checkout` or `git reset` anything
  without checking whose work it is** — several sessions' unreviewed work shares
  this tree.

---

## 9. Standing shortfall

None of the five tasks has an independent review (Constitution section 7). That is
now a long-running gap across many consecutive tasks, tracked as R-003 / OD-6.
This run made it worse, not better: five tasks landed in one day, self-reviewed.
If review capacity exists on the new account, spending it here is likely worth
more than starting a sixth task.
