# Human actions

Things only the operator can do. Each one is here because an agent either *may
not* perform it (it changes persistent OS configuration, or it needs a secret)
or *cannot* (it needs a browser session, a payment method, or a decision).

Nothing in this file is optional-but-nice. If an item is not done, the
capability it belongs to is not working, and the task that depends on it says so
rather than assuming.

---

## 1. Register the publish tick with Windows Task Scheduler (T-018, DR-009)

**Status: REQUIRED for scheduled publishing. Not done by any agent.**

DR-009 chose Windows Task Scheduler over a daemon so the OS supervises the
scheduler and it survives reboot. Registering the task is a persistent
machine-configuration change, so it is yours to make — an agent creating
scheduled tasks on your machine is not a thing this project does.

Without it, `scheduled_at` on a post does nothing on its own: the post waits at
`approved` until you publish it by hand, and once its window closes the next
tick you *do* run will mark it `missed` rather than post it late (C-27).

### What the task runs

```
python -m promedia publish-tick --json
```

Run it from the repository directory. It is idempotent — two overlapping ticks
cannot double-publish, because publishing claims the post transactionally before
any platform call.

### The operator token

`publish-tick` requires operator authority, because it publishes. Supply the
token the same way the CLI already accepts it, through the environment:

```
PROMEDIA_OPERATOR_TOKEN=<your token>
```

Set it on the scheduled task itself, not as a system-wide variable — a
system-wide operator token is readable by every process you run.

> **Do not put the token in the task's Arguments field.** Command-line arguments
> are visible to every process on the machine and are recorded in Task
> Scheduler's own history. This is the rule T-024 enforces in the CLI, and it
> applies to the scheduler for the same reason.

### Interval

Pick an interval **shorter than your tolerance** (`publishing.tolerance_seconds`
in `promedia.toml`, default 300s). A 1-minute trigger against a 5-minute
tolerance leaves room for a missed tick; a 10-minute trigger against it
guarantees windows are missed.

### Suggested settings

| Setting | Value | Why |
|---|---|---|
| Trigger | Daily, repeat every 1 minute, indefinitely | Resolution has to beat the tolerance |
| Run whether user is logged on or not | **No** — run only when logged on | Credentials are DPAPI-bound to your user session (T-022) |
| Run with highest privileges | No | It needs no privilege it does not already have |
| Stop if runs longer than | 5 minutes | A wedged tick should be killed, not stacked |
| If task is already running | Do not start a new instance | Belt and braces; the claim already prevents double-publishing |

### The limitation you are accepting

**Nothing runs while the machine is off or asleep.** DR-009 states this plainly
rather than designing around it. Schedule posts inside hours the machine is
reliably on, and treat `missed` entries as the expected signal when it was not —
they are the system telling you the truth, not malfunctioning.

Check what the scheduler is doing without publishing anything:

```
python -m promedia schedule-status --json
```

---

## 2. Register the backup tick with Windows Task Scheduler (T-039, DR-009)

**Status: REQUIRED for scheduled backups. Not done by any agent.**

DR-009's reasoning applies a second time here (T-018 registered the publish
tick the same way): Windows Task Scheduler supervises the process and it
survives reboot, so this reuses that mechanism rather than inventing a
second scheduler.

Without it, the permanent set is exported only when you run `backup-tick` or
`export-permanent-set` by hand — which is exactly the silent failure mode
T-039 exists to close: "the job stops and everything looks normal until a
restore is needed."

### What the task runs

```
python -m promedia backup-tick --json
```

Run it from the repository directory. It is idempotent — the local snapshot
it writes is overwritten in place, never accumulated, so an overlapping or
re-run tick leaves exactly one file.

### What it does, and what it deliberately does not do

Each run writes a fresh local snapshot (no drive needed — safe to automate)
and checks the audit log for the last successful `send-offsite` transport,
escalating (an audit entry, surfaced by `backup-status`) if either is stale
past its configured threshold (`backup.local_export_overdue_hours`,
`backup.offsite_overdue_days` in `promedia.toml`).

**It does NOT send anything off-site by itself.** OD-9 chose a removable
drive, and its mount point is not stable across sessions — an unattended
tick has no destination it could safely assume, so off-site transport stays
a deliberate, manual action:

```
python -m promedia send-offsite --destination <drive path> --json
```

Plug in the drive and run that yourself on whatever cadence you choose
(`backup.offsite_overdue_days` defaults to 14 — see `promedia.toml` to
change it). `backup-tick`'s job is to make it visible when that has not
happened recently enough, not to force it.

### The operator token

Same as `publish-tick`: `backup-tick` requires operator authority, because it
writes the entire audit log and publication history to disk, even at a fixed
local path. Supply the token through the environment, on the scheduled task
itself rather than system-wide:

```
PROMEDIA_OPERATOR_TOKEN=<your token>
```

> **Do not put the token in the task's Arguments field** — same reasoning as
> `publish-tick`'s own warning above.

### Suggested settings

| Setting | Value | Why |
|---|---|---|
| Trigger | Daily | `backup.local_export_overdue_hours` defaults to 26h — headroom over a 24h cadence, the same relationship publish-tick's trigger keeps against its own tolerance |
| Run whether user is logged on or not | **No** — run only when logged on | Same DPAPI credential binding as publish-tick (T-022) |
| Run with highest privileges | No | It needs no privilege it does not already have |
| Stop if runs longer than | 15 minutes | A wedged export should be killed, not stacked; export is normally seconds at this project's data scale |
| If task is already running | Do not start a new instance | Belt and braces — the tick is idempotent either way |

Check freshness without writing anything (no operator token needed — agent
authority):

```
python -m promedia backup-status --json
```

---

## 3. Supply platform credentials (T-019, fabrication F-001)

**Status: DEFERRED by operator decision (OD-4). Publishing is simulated.**

Until real X and LinkedIn credentials exist AND their API terms, rate limits and
pricing are verified against live documentation, `publishers.StubPublisher`
publishes nothing anywhere. It is unreachable unless
`publishing.allow_simulation` is explicitly true, and every simulated result is
marked `simulated` all the way into the publication record.

Verifying pricing against the $100/month ceiling (project.md O-3) cannot be done
from model memory and must not be guessed.

---

## 4. Independent human-experience review (OD-5)

**Status: OPEN. This is what closes the review shortfall in OD-6.**

`routing.yaml` requires a human-experience reviewer for this change class. Every
such pass so far has been performed by the implementing session, and
`framework.yaml` sets `self_review_counts_as_review: false`, so it does not
count.

What is needed: one real screen-recording walkthrough with simulation on,
covering ingest → attest → determine rights → seal → queue → approve → publish.

Two screens have never been looked at by a human at all:

- the generic `/ops/{name}` operation forms (T-034), and
- the **decision-context confirmation screen** (T-035), which is the screen that
  shows the account, rights verdict, ruleset version and asset hash before an
  approve or publish control. Its behaviour is verified by tests and against a
  live server; its *legibility* is not, and legibility is the entire point of it.

---

## 5. Run a real restore drill periodically (T-040)

**Status: OPTIONAL but recommended. The automated proof already runs on every
test suite invocation (`tests/test_restore_drill.py`); this section is for
actually exercising it against your own drive and your own database, which no
agent may do unattended (destroying a real database is exactly the kind of
irreversible action `NON-NEGOTIABLES.md` reserves for the operator).**

A backup nobody has restored is a hypothesis, not a plan. `tests/
test_restore_drill.py` proves the mechanism works, twice, against scratch
data on every run — but it can never prove *your* drive, mounted the way you
actually mount it, holds a readable artefact. Only running the real thing
does that. There is no fixed cadence recorded for this (no project.md
constraint names one); doing it once after first setting up off-site backup,
and again any time the backup or restore code changes, is the reasonable
floor.

### What to do

1. **Send a real backup off-site**, to the real drive:

   ```
   python -m promedia send-offsite --destination <drive path> --json
   ```

2. **Find the artefact via the drive's own manifest** — not a path you
   remember from step 1. `<drive path>/promedia-backup-manifest.jsonl` is a
   plain JSON-lines file; its last line's `artefact_file` is the one to use.
   Reading it this way is the point: it is what you would have to do if this
   machine were gone and only the drive remained.

3. **Move the real database aside** (do not delete it until step 5 confirms
   the restore worked): rename `promedia.db` in your data directory to
   something like `promedia.db.pre-drill`. `restore-permanent-set` refuses a
   non-empty database on purpose (T-037, AC-4) — moving the file aside is
   what makes the next command operate on a genuinely empty one, the same
   shape a real disk loss would leave you in.

4. **Restore from the off-site artefact alone**:

   ```
   python -m promedia restore-permanent-set --source <artefact path from step 2> --json
   ```

5. **Verify the result**, same as the automated drill does:

   ```
   python -m promedia backup-scope --json
   python -m promedia rights --asset-id <an asset you know> --json
   python -m promedia audit --limit 20 --json
   ```

   Confirm: rights verdicts match what you expect, the audit log has your
   publishing history, and `backup-scope` still reports `media_included:
   false` — a reminder that this restores rights, provenance, publication and
   audit records, and **never media**. Re-acquiring media after a real
   incident means re-ingesting from wherever the original files still exist
   (if anywhere); that is outside what a backup regime for a 100 GB-capped,
   transient-media system (F-7) can promise, and restating it here is
   deliberate, not an oversight.

6. Once satisfied, delete `promedia.db.pre-drill` — or keep it a while longer
   if you would rather double-check by hand first. Nothing further deletes it
   for you.

### What this does NOT test

Media recovery, because there is none to recover (project.md 5.4: masters and
derivatives are transient by policy). This drill is scoped to the permanent
set — rights evidence, provenance, publication and audit records — exactly
what F-7/F-8 require to survive.
