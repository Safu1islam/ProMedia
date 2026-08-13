# Frontend design brief — the ProMedia workspace

**For:** the agent taking T-049 and its children.
**Written by:** the session that built T-041/T-042 (the media engine and its operations).
**Status:** binding. Where this disagrees with your instinct, this wins; where it
disagrees with `.ai/project.md` or a decision record, THOSE win and you should
raise a recommendation rather than pick a side.

You have amnesia and I know it. Everything you need is here or named here.

---

## 1. What you are building

A workspace where one human and one or more AI agents produce and publish media
**together, on the same objects**, and where the human can always see what the
agent did and change it.

The operator's own words on seeing the current UI: *"I found app UI that's not
what we was trying to do."* They were right. What exists is a governance
dashboard plus a table of operations — an approval surface. Your job is to make
it a place where work happens, without breaking the approval surface, which is
load-bearing.

**Read first, in this order:**

1. `aef/core/CONSTITUTION.md` — how work is done here. Short.
2. `.ai/project.md` §§ 3–5 — the constraints. Note §4 "Out of scope" currently
   contradicts this work; see recommendation R-002 and §8 below.
3. `.ai/state/decisions/DR-004.yaml` — why the UI is server-rendered.
4. `.ai/state/decisions/DR-016.yaml` — the media architecture you are surfacing.
5. `python aef/tools/aef.py brief --task T-049`

---

## 2. The five rules you may not break

These are not style preferences. Each has a decision record or a constraint
behind it, and each has already been violated once by someone who did not know
why it existed.

**1. No JavaScript is required for anything.** (DR-004)
Not "minimal JS" — *not required*. Progressive enhancement is acceptable; a
page that does not work without script is not. The reason is narrow and real:
this UI carries publish authority, and the approval path must not be able to
break in a way that leaves the operator unable to approve or, worse, able to
approve something they cannot see. An HTML5 `<video>` element, forms, and links
cover everything in this brief. If you believe a feature genuinely requires
script, raise a recommendation instead of adding it.

**2. The adapter contains no business logic.** (DR-002, F-1)
Every screen is a projection of registered operations. You call
`invoke(ctx, "operation-name", {...})` and render the result. You do not query
tables directly, you do not compute a verdict, you do not decide what is
publishable. If a screen needs something no operation provides, the fix is a new
operation — which is automatically available to the CLI too — not a query in a
route. `tests/test_parity.py` enforces this and will fail you.

**3. Authority lives in the operation layer, not in your templates.** (F-2)
Hiding a button is not a control. The server already refuses what an agent may
not do. Your job is to *show* the refusal well, never to be the thing that
prevents it. Equally: do not hide a control merely because it might fail — show
it and render the refusal.

**4. Decision context precedes the control.** (T-035)
Anywhere a human approves or publishes, the facts that decision rests on —
account, rights verdict, ruleset version, asset hash, whether media is still
present — appear on screen *before* the control, not in the response after it.
This is the single reason the web surface is the authority surface rather than
the CLI.

**5. Never present a substitution as a success.** (Constitution §6)
A render result carries a `substitutions` list. If it is non-empty, the UI says
so, on the render, in plain words. Today: asking for `dissolve`, `wipeleft`,
`wiperight`, `slideup` or `slidedown` renders something else (fabrication
F-003). The existing project page does this — keep it, and apply the same rule
to anything else that reports a gap between what was asked and what happened.

---

## 3. What already exists — do not rebuild it

Running: `python -c "from promedia.web.app import run_server; run_server()"`
(or `preview_start` with the `promedia` config), then `http://localhost:8765`.

| Route | What it is | Verdict |
|---|---|---|
| `/` | v1 dashboard: storage, rights ruleset, posts, assets, accounts | **Rework** — see §5 |
| `/projects` | Project list + what this installation can and cannot do | Keep, extend |
| `/projects/{id}` | Output player, the edit as JSON, media list, version history | **The core screen.** Extend, do not replace |
| `/posts/{id}` | Approval screen with decision context | Keep. Handle with care |
| `/ops`, `/ops/{name}` | Every capability as a generic form | Keep. See §4 |
| `/renders/{id}/file` | Serves a rendered mp4 for playback | Keep |

**The design system is in `promedia/web/templates/base.html`** — CSS variables,
light/dark, `.panel`, `.banner`, `.grid`, `.big`, `.row`, `.mono`, `.muted`,
tables, forms. Extend that block; do not introduce a second styling approach or
a framework. It is deliberately small and it is enough.

---

## 4. The two-layer architecture

This is the part most likely to be misunderstood, so it is stated plainly.

**Layer 1 — the completeness guarantee.** `/ops/{name}` generates a form for
every registered operation from its parameter metadata. It is ugly and it is
supposed to be. Its job is that **no capability is ever unreachable from a
browser**, enforced by the parity gate. It must keep working for all of them.

**Layer 2 — the crafted screens.** A small number of screens for what a human
does repeatedly. These are the ones you are building.

The rule: **a crafted screen never becomes the only way to do something.** If
you build a beautiful upload page, `/ops/ingest` still works. Layer 1 is the
floor; layer 2 is the experience. Never delete from layer 1 to tidy layer 2.

---

## 5. The information architecture

```
/                     Dashboard — "what needs me now"
/projects             Project list
/projects/{id}        THE WORKING SCREEN
/media                Media library — get footage in            [MISSING]
/media/{asset_id}     Asset detail: rights, evidence, provenance [MISSING]
/posts                Publish queue                             [MISSING]
/posts/{id}           Approval (exists)
/publications         What actually went out                    [MISSING]
/settings             Accounts, storage, backup, capabilities   [MISSING]
/ops, /ops/{name}     Everything, always (exists)
```

Organising principle: **the dashboard answers "what needs me", `/projects/{id}`
is where work happens, `/posts/{id}` is where authority happens, `/ops` is the
safety net.**

### Build in this order

**First — `/media`.** The most glaring hole: there is currently *no way to get a
file in from the browser at all*. An operator cannot add footage to their own
project without the CLI. Needs: file upload, import from URL (`yt-dlp` is
installed; T-046 owns the backend), thumbnails, and — non-negotiable — the
rights declaration is collected **at the point of import**, because
`ingest` refuses without one and that refusal is the whole rights model. Do not
build a path that acquires media without a declaration.

**Second — per-clip editing on `/projects/{id}`.** Today the edit is a JSON
textarea. Honest, functional, not usable daily. Build clip rows: trim in/out,
effect dropdown, transition dropdown, speed, reorder up/down, delete. All forms
and POSTs. Every change goes through `set-edl`, which creates a new version —
never mutate in place. **Keep the JSON view** as an escape hatch and because it
is how an agent's edit is most quickly understood.

**Third — dashboard rework.** Lead with what needs the human: pending
approvals, recent renders, anything a fabrication or substitution affected,
storage pressure. The v1 panels move down or into `/settings`.

**Fourth — `/posts`, `/publications`, `/settings`.** Mostly assembling data that
already exists behind operations.

---

## 6. How the human and the AI share this

This is the distinctive thing about the product. Get it right and the rest is
ordinary web work.

**They edit the same object.** A project holds an append-only sequence of EDL
versions. The agent writes one from the IDE; the operator opens the same project
and adjusts it. There is no sync, no merge, no "agent mode" — one document, many
authors. Do not invent a parallel representation for either side.

**Every version records who made it.** `authored_kind` is `operator` or `agent`.
Surface it everywhere a version appears. The question "did a human shape this
edit, or did the machine" is the one an operator asks before approving what came
out of it, and the UI should answer it without being asked.

**The agent proposes; the human disposes.** Agents may draft, ingest, analyse,
edit, and render. They may never publish, spend, or clear a rights flag. So:
an agent's render appearing on screen is normal and needs no ceremony; an
agent's work reaching a platform always passes through a human control that
shows its basis first.

**Design for the agent working while the operator watches.** Locks are real
(C-19) and a render can take minutes. A project being rendered by an agent
should say so rather than appearing broken, and `ENTITY_LOCKED` (HTTP 409)
should read as "someone else is working on this right now, try shortly" — not
as an error. See DR-012.

**Make the agent's work reviewable, not just visible.** The highest-value screen
you could build beyond this brief is a **version diff**: what changed between v4
and v5, in human terms ("clip 2 trimmed 1.2s shorter, caption added"). That is
what turns "the agent edited my project" from unsettling into useful. Treat it
as a stretch goal, and raise it as a recommendation if you do not get to it.

---

## 7. Definition of done

- Every new screen works with JavaScript disabled. Test it.
- `python -m pytest` passes. It is currently **561 passing** — that is your
  baseline, and it must not go down.
- `tests/test_parity.py` still passes with the same operation coverage. If you
  added an operation, the count rises; if it falls, you removed a capability.
- No business logic in `promedia/web/`. A reviewer will check this.
- Tests for what you build, in `tests/test_editor_ui.py`. Prove they can fail —
  sabotage the feature, watch the test go red, revert, verify by hash. This
  project does that for everything and the record shows why: two tests written
  in this codebase passed for the wrong reason and were only caught by chance.
- A screenshot or page-text capture of each new screen in your task record.

## 8. Two things you must know before you start

**`.ai/project.md` currently contradicts this work.** §4 reads *"Do not build,
and do not propose: a general-purpose non-linear video editor"* and F-9 reads
*"Single operator, permanently."* The operator authorised the production
platform on 2026-08-13 and phase one has shipped. This is recorded as
recommendation **R-002 (critical)** and only the operator can reconcile it.
Do not resolve it yourself, and do not treat the out-of-scope line as
permission-by-silence. What you are building is an *orchestrated* editing
surface, which that line explicitly permits; a timeline NLE is what it forbids.

**Nothing actually publishes yet.** The publisher is a stub (fabrication F-001,
task T-019, blocked on operator credentials). Every publication is simulated and
labelled so. Do not design the publish flow as if it were live, and do not hide
the simulated marker to make screens look tidier — that marker is the thing
standing between a demo and a lie.

## 9. Process

Ordinary AEF. Claim your paths in `.ai/state/locks.yaml` **before** editing.
Register your session (`aef.py session start`). Record what you did in the task,
with evidence you actually ran. Release the lock and end the session with a
handoff. If you find something you are not authorised to act on, use
`aef.py recommend add` rather than acting or staying quiet.

You will not be the reviewer of your own work — Constitution §7. Ten tasks in
this project currently carry `independent_review: NOT_RUN`, which is tracked as
recommendation R-003. Do not add to it silently; note it in your handoff.
