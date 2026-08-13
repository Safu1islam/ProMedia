# ProMedia — Project Constitution

> Authoritative. Produced by `aef/protocols/01-intake.md` on 2026-08-08.
> Amended only by re-running that protocol. Agents read this file; they do not
> rewrite it in passing. Where this file and the framework conflict, the framework
> wins on process and this file wins on domain facts (Constitution §2).

**Status:** Intake complete. Technology selection (`protocols/02`) NOT yet run.
No technology, language, datastore or hosting choice in this file is decided —
where one appears, it is a constraint on the choice, not the choice.

---

## 1. Purpose

ProMedia is a single-operator system for producing, rights-clearing, scheduling and
publishing social media content, in which every capability is callable identically by
a human through a UI and by an AI agent through the repository, and in which no
content reaches a platform without a passing rights determination and explicit human
approval.

### Stated purpose of the work

Recorded once, per `aef/core/NON-NEGOTIABLES.md` ("What is NOT a reason to refuse"),
so it is not relitigated each session:

This is a legitimate personal productivity tool built by its sole user, for their own
accounts and their own content. It includes automation of publishing, programmatic and
browser-driven interaction with platforms the operator holds accounts on, media
processing, and LLM-assisted drafting and analysis. These are ordinary engineering.
Agents must not invent restrictions around them. The real limits are the ones written
in this document, in platform terms of service, and in the two non-negotiable lists.

---

## 2. Users

Two actor types. There is no third, now or later.

| Actor | Authority | Explicitly cannot |
|---|---|---|
| **Operator** (sole human) | Full. Only authority that may publish, spend money, or clear a rights flag | — |
| **AI agents** (Claude Code, Codex, ≤4 concurrent) | Draft, ingest, analyse, run rights checks, produce derivatives, queue work | **Publish. Spend money. Clear or downgrade a rights flag.** Each requires operator approval in the UI |

**Multi-tenancy is out of scope permanently.** Do not model organisations, teams,
tenants, roles, or per-user permissions. A future second human is not a requirement
and must not be designed for. (Confirmed 2026-08-08.)

---

## 3. Success measures

| # | Measure | Target | Baseline today |
|---|---|---|---|
| S1 | Publishing throughput | 3–5 posts/week across 2 platforms | 0 posts/week |
| S2 | Operator time cost | < 3 hours/week total | n/a |
| S3 | Unresolved-rights publications | **Zero.** Non-negotiable | n/a |
| S4 | Dual-surface coverage | **100%** of capabilities callable from both UI and repo. A capability reachable from only one surface is a **build failure**, not a gap | n/a |
| S5 | Storage ceiling breaches | **Zero.** Ingest is refused or queued before the ceiling is reached, never after | n/a |
| S6 | Missed scheduled posts published late | **Zero.** Missed windows escalate; they never auto-post late | n/a |

---

## 4. Out of scope

Confirmed 2026-08-08. Do not build, and do not propose:

- Paid advertising and ad-account management
- DM inbox, comment moderation, community management
- Multi-tenant SaaS, billing, other people's accounts
- A general-purpose non-linear video editor — the system *orchestrates* editing
  operations, it is not Premiere
- Analytics beyond what informs the operator's own scheduling decisions
- Publishing a previously published asset to a *new* platform after retention has
  deleted it (see C-13 — this is foreclosed by the storage ceiling, not an oversight)

---

## 5. Quantified constraints

Every row is binding. `ASSUMED` marks a value the operator did not supply, recorded
with its revisit trigger in §11 — these are challengeable, not settled.

### 5.1 Latency

| ID | Constraint | Value | Source |
|---|---|---|---|
| C-1 | UI interaction (browse, search, open asset) | p95 < 300 ms | Confirmed |
| C-2 | Rights check, cached evidence, synchronous | p95 < 2 s | Confirmed |
| C-3 | Rights check requiring external lookup | < 30 s, async with progress | Confirmed |
| C-4 | Agent-callable operation, cold-start overhead | < 1 s | Confirmed |
| C-5 | Publish action → queued (not posted) | < 500 ms | Confirmed |
| C-6 | Ingest → first usable thumbnail/proxy, 10-min source | < 30 s | Confirmed |
| C-7 | Full transcode, 10-min source | < 15 min | Confirmed |

C-5 is a semantic constraint as much as a timing one: the UI confirms *intent
recorded*, never *post succeeded*.

### 5.2 Throughput and volume

| ID | Constraint | Value | Source |
|---|---|---|---|
| C-8 | Sustained operation rate | < 1 op/sec | ASSUMED |
| C-9 | Peak batch ingest | < 20 files in one batch | Confirmed |
| C-10 | Publishing rate | 1–2 posts/day, peak day 5 | Confirmed |
| C-11 | Content production rate | 3 videos/week, ~10 min each, screen recordings | ASSUMED (operator projection, no data behind it) |
| C-12 | Typical master file size | ~1.5 GB | ASSUMED (operator projection) |
| C-13 | **Media storage ceiling** | **100 GB hard. Not a target** | Confirmed |
| C-14 | Derivative multiplier at 2 platforms | ~0.5× master (proxy + 2 platform renders ≈ 0.75 GB) | ASSUMED |
| C-15 | Lifecycle footprint per video | ~2.25 GB (master + all derivatives, pre-deletion) | Derived from C-12, C-14 |
| C-16 | Non-media permanent records | Outside the 100 GB cap. Est. < 1 GB/year | ASSUMED |

**Storage headroom model** (derived — the sizing case the design must survive):

| Scenario | Footprint | % of ceiling |
|---|---|---|
| Weekly inflow | 6.75 GB/week | — |
| Steady state (2-week ingest→publish lag) | ~13.5 GB | 14% |
| Peak batch of 20 files alone | ~45 GB | 45% |
| Peak batch arriving during steady state | ~58.5 GB | **59%** |
| Same, if platform targets grow to 4 | ~74 GB | 74% |
| Same, if platform targets grow to 6 | ~90 GB | **breach risk** |

The ceiling holds comfortably at 2 platforms. **Platform expansion is the trigger that
breaks it**, not volume growth — see §11 revisit triggers. C-14 is the most
leverage-bearing assumption in this document; C-12 is second.

### 5.3 Concurrency, determinism, consistency

| ID | Constraint | Value | Source |
|---|---|---|---|
| C-17 | Simultaneous humans | 1 | Confirmed |
| C-18 | Simultaneous agent sessions | Up to 4 (matches `max_parallel_agents`) | Confirmed |
| C-19 | Writers to the same entity | Exactly 1. Enforced exclusive lock, **visible lock owner** | Confirmed |
| C-20 | **Rights verdict determinism** | Same asset + same evidence set + same ruleset version → identical verdict, always | Confirmed — hard architectural constraint |
| C-21 | Content generation determinism | Not required. Model, version, prompt and seed are recorded for traceability | Confirmed |
| C-22 | Publish queue ordering | Scheduled order is posted order, per account | Confirmed |

**C-20 restated because it constrains implementation more than any other line here:
an LLM opinion is evidence, never a verdict.** A verdict is a deterministic function
over recorded evidence, stamped with the ruleset version that produced it. "Ask the
model whether this is fair use" is not an admissible implementation of a rights check.

Consistency tolerances:

| Data | Staleness tolerated |
|---|---|
| Rights status | **Zero** — read-your-writes always |
| Lock state | **Zero** |
| Publish queue state | **Zero** |
| Draft content | ~5 s |
| Platform analytics | 24 h |
| Follower/subscriber counts | 24 h |

### 5.4 Availability, durability, deadlines

| ID | Constraint | Value | Source |
|---|---|---|---|
| C-23 | UI availability | **No target.** Self-hosted, single operator; UI downtime costs nothing | Confirmed |
| C-24 | Scheduler availability | Must be up across every scheduled publish window | Confirmed |
| C-25 | Maintenance block | Automatically blocked when a post is scheduled within 60 min | Confirmed |
| C-26 | Scheduled post tolerance | **±5 minutes** | Confirmed |
| C-27 | Missed window behaviour | Mark `missed`, **escalate, never post late** | Confirmed |
| C-28 | OAuth token refresh | Before expiry; alert at 72 h remaining | ASSUMED |

**Durability — the permanent set** (must survive disk loss; off-site backup in scope):

- Rights evidence
- Provenance chains
- Published-post records
- Approval and audit log

**Durability — the transient set** (deleted post-publish by policy, or recomputable):

- Original media masters — **not permanent**
- Proxies, transcode intermediates, platform renders
- LLM analyses and drafts (recomputable *at API cost* — this is money, not free)
- Caches, thumbnails, analytics snapshots

No backup regime exists today. Off-site backup of the permanent set only is in scope.
Because masters are transient, the permanent set is measured in megabytes — backup is
cheap and fast, and this removes what would otherwise be the largest cost line.

### 5.5 Money and safety

Physical harm: none. Financial loss: four channels, in severity order.

| ID | Channel | Control |
|---|---|---|
| C-29 | **Copyright liability** — statutory damages, strikes, channel termination, demonetisation | Rights are a hard gate. Uncertain ⇒ blocked or escalated, never permitted |
| C-30 | **Platform account loss** via ToS violation | Browser automation requires a stated reason per use; never the default |
| C-31 | **API spend** | **$100/month total ceiling. Hard stop at 150% ($150).** Per-operation cap $5 unless approved |
| C-32 | **Wrong-post cost** — wrong asset or wrong account | Not financially recoverable once seen. Human approval gate before every publish |

---

## 6. Environment

| Aspect | Value | Source |
|---|---|---|
| Runtime | Local-first: Windows 11 desktop. Web UI on localhost; agents call the same operations in-repo | **Confirmed** |
| Remote/mobile access | Not required | ASSUMED |
| Deployment target | Self-hosted, single machine. No cloud provider | **Confirmed** — resolves O-1 to option (C), see DR-009 |
| Platforms | **X** (1 account), **LinkedIn** (1 account). Expansion later | Confirmed |
| Platform rate limits and API pricing | **NOT RECORDED — deliberately.** To be verified against live documentation during `protocols/02`. No figure from model memory is admissible here | Confirmed instruction |
| Content source | Screen recordings | Confirmed |
| Systems replaced | None. No existing scheduler, no existing library | Confirmed |
| Existing assets | **None**, beyond the two platform accounts themselves. No code, templates, prompts or media | **Confirmed** |
| Data residency | **No requirement.** Operator's machine | **Confirmed** |
| Available toolchain | Python 3.11.9, Node 24.14.1, npm 11.11.0, git 2.53. **No ffmpeg/ffprobe. No Go, no .NET** | Observed 2026-08-08 |

### Browser automation policy

Browser automation is a **fallback**, permitted only for a platform with no usable API,
with the reason recorded at the point of use. It is never the default and never chosen
for convenience. This interacts with C-30: automation at volume risks the account
itself.

---

## 7. Compliance

| Aspect | Value | Confidence |
|---|---|---|
| Applicable regimes | **Copyright and platform terms of service only.** No other regime applies | **Confirmed 2026-08-08** |
| Operating jurisdiction | **United Arab Emirates** | **CONFIRMED by the operator, 2026-08-11.** Originally inferred from Windows home location and UTC+04:00; that inference is now superseded by a direct answer |
| Copyright regime | UAE law, plus the terms of each platform | Follows from the confirmed jurisdiction |
| GDPR | Not applicable | Confirmed via "no compliance regime beyond copyright and platform ToS" |
| UAE PDPL | Not applicable | Same |

> **O-2 fully resolved.** Copyright and platform ToS are the only applicable
> regimes, and the jurisdiction that selects *which* copyright regime is now
> confirmed as the UAE. The engine was built without waiting for this, and the
> reasoning below is retained because it explains why the shipped ruleset looks
> the way it does — and why confirming the jurisdiction does **not** by itself
> unlock doctrine-based rules.
>
> Rather than block the rights engine on the unconfirmed answer,
> **jurisdiction is a runtime configuration parameter of the ruleset** (`DR-007`), and
> the shipped default ruleset is **jurisdiction-neutral and deliberately
> conservative**: it recognises only unambiguous permissions (operator-owned, explicit
> written licence, verified public domain) and blocks everything else. A conservative
> ruleset cannot become wrong by learning the jurisdiction later — it can only become
> less restrictive. This is why the constraint does not gate the build.
>
> **What this explicitly does NOT do:** it does not implement fair use, fair dealing,
> or any doctrine requiring jurisdictional interpretation. Those are absent, not
> approximated. Adding them requires confirmed jurisdiction and legal input.

---

## 8. Maintainer capability

Sole maintainer: the operator, indefinitely, with no second person and no handover
plan required.

**Confirmed capability: can operate anything runnable locally.** This is a wide
mandate, and the framework requires it be read carefully rather than as licence for
complexity (`protocols/02` rule 5). Operational burden remains a real cost against
S2 (< 3 hours/week): a design consuming an hour a week in maintenance has already
spent a third of the budget the system exists to protect. **Capability is not the
binding constraint; the operator's time is.** Selection therefore still prefers
low-ops, and DR-001/DR-003 choose zero-daemon options on that basis, not on capability.

Demonstrated capability (observed, not self-reported): comfortable with git, CLI
tooling, agent frameworks, and structured configuration.

---

## 9. Budget

| Item | Value |
|---|---|
| Monthly ceiling, all API and infrastructure | **$100** |
| Hard stop | **150% ($150)** — a stop, not a warning |
| Per-operation cap | **$5** without explicit approval |
| Deadline | **None.** Confirmed 2026-08-08 |
| Cut order if pressure appears | 1st analytics · 2nd scheduling · **rights checking is never cut** (`ASSUMED`) |

> **Risk:** X provides API access through paid tiers, and LinkedIn posting access is
> gated behind app review. Either may consume a large fraction of a $100/month
> ceiling, or be unavailable at this budget. **Figures deliberately not recorded from
> memory** — this is flagged for verification in `protocols/02`. If confirmed, the
> resolution is a budget change or a different posting mechanism, and the latter is
> precisely where C-30's browser-automation clause gets tested. See §12 O-3.

---

## 10. Fixed decisions

Non-negotiable. Not open to trade-off by any agent. Changing one requires re-running
intake.

| # | Decision |
|---|---|
| **F-1** | **Dual entry points.** Every capability is one callable operation with **one implementation**, exposed through both a UI surface and a repo-callable surface. No capability may exist in only one. Two implementations of the same capability is a defect, not an optimisation |
| **F-2** | **Agent authority ceiling.** Agents may draft, ingest, analyse, rights-check and queue. They may **never** publish, spend money, or clear a rights flag without operator approval in the UI |
| **F-3** | **Rights are a hard constraint.** The system determines whether content is owned, licensed, public domain, or permitted, and **blocks or escalates anything uncertain** |
| **F-4** | **Editing is a production function, not a copyright-clearing function. Transforming material never makes it usable.** No amount of cropping, cutting, speed change, filtering or re-encoding converts unusable material into usable material |
| **F-5** | **An LLM opinion is evidence, never a verdict.** Verdicts are deterministic functions over recorded evidence, stamped with the ruleset version |
| **F-6** | **Browser automation is a fallback**, for platforms with no usable API, with a stated reason. Never the default |
| **F-7** | **100 GB media ceiling is hard.** Retention is a first-class feature: track usage, enforce policy, and **queue or refuse ingest that would breach the ceiling** rather than silently filling the disk |
| **F-8** | **Provenance outlives media.** A rights or provenance record must remain valid and readable after the asset it describes is deleted. It must key on content hash and embedded metadata, **never on a file path**, and evidence must be embedded rather than linked |
| **F-9** | **Single operator, permanently.** No multi-tenancy, no second human, no team model |

### Retention policy (derived from F-7, F-8)

Media is transient. Automated deletion is an irreversible data operation, which
`NON-NEGOTIABLES.md` list B would normally require per-instance human approval for.
That is impractical at ~150 deletions/year, so approval is granted once, as policy,
with these guardrails. **Auto-deletion is permitted only when all four hold:**

1. Publish confirmed live on every target platform — not merely "the API returned 200"
2. Provenance and rights records sealed, and **verified readable independently of the
   asset**
3. All planned derivatives produced (see below)
4. Grace period elapsed — **14 days** post-publish (`ASSUMED`)

Anything failing any condition escalates instead of deleting.

**Deletion is final and forecloses repurposing.** Retaining a long-term mezzanine was
evaluated and rejected on arithmetic: at 4 Mbps a 10-min mezzanine is ~300 MB, and
~150 videos/year is ~45 GB/year — it consumes the ceiling within two years. There is
no configuration that preserves long-term re-editability within 100 GB. Therefore
**every distribution variant must be produced before the retention gate fires.**

**Admission control must reserve projected lifecycle footprint** — master plus
not-yet-generated derivatives — not merely incoming source bytes. A system that admits
30 GB of source and then discovers it needs 15 GB of renders has already failed.
Proposed thresholds (`ASSUMED`): warn at 70 GB, refuse/queue new ingest at 85 GB,
never exceed 100 GB. Queued ingest resumes automatically as retention frees space.

---

## 11. Assumptions register

Recorded per Constitution §5 — assumptions are stated and continued from, not asked
about. Each is challengeable. **Global revisit trigger: 2026-09-07** (30 days of real
ingest), or earlier if any specific trigger below fires.

| ID | Assumption | Specific revisit trigger |
|---|---|---|
| A-1 | 3 videos/week, ~10 min each | Actual weekly count differs by >50% for 2 consecutive weeks |
| A-2 | ~1.5 GB per master | Observed median differs by >30%. **Capture resolution above 1080p invalidates this immediately** |
| A-3 | Derivative multiplier ~0.5× at 2 platforms | **Any platform added.** This is the highest-leverage assumption here |
| A-4 | Permanent records < 1 GB/year, outside the cap | Records exceed 2 GB |
| A-5 | 14-day post-publish grace period | Any deletion the operator regrets |
| A-6 | Storage thresholds 70/85/100 GB | First queued ingest event |
| A-7 | Local-first, single machine, no remote access | Operator wants to approve a publish while away from the desk |
| A-8 | ~~Jurisdiction = UAE~~ | **NO LONGER AN ASSUMPTION.** Confirmed by the operator 2026-08-11; promoted to a fact in §7. Adding any doctrine-based rule (fair use / fair dealing) still requires legal input, which confirmation does not supply |
| A-9 | GDPR and UAE PDPL not applicable | Confirmed by operator. Revisit on audience targeting or third-party personal data processing |
| A-10 | Cut order analytics → scheduling → never rights | Operator states a different order |
| A-11 | Low-ops preferred despite unrestricted capability, because operator *time* is the binding constraint | Ops burden approaches 1 h/week |
| A-15 | ~~ffmpeg/ffprobe absent; media duration and codec metadata recorded as `null` with `probe_status: unavailable` rather than guessed~~ **RETIRED 2026-08-13** — ffmpeg 9.0 installed by operator instruction (T-041). Both of its stated trigger conditions fired at once: ffmpeg is installed, and derivative generation entered scope. Probing now returns real duration, resolution, frame rate and codecs. The no-guessing rule it protected still stands and is unchanged: a field ffprobe does not report stays `null`. | — |
| A-16 | Publish windows restricted to hours the machine is on (O-1 option C) | First missed window that mattered |
| A-12 | Sustained < 1 op/sec | — |
| A-13 | OAuth alerting at 72 h before expiry | First token expiry incident |
| A-14 | Dependency licence compatibility is a **check, not a hard gate** — commercial use unlikely but not impossible | Operator decides to commercialise |

---

## 12. Open items carried into technology selection

Not blockers for `protocols/02` unless marked. Presented as decisions, per the
escalation format.

**O-1 — RESOLVED.** Operator confirmed self-hosted on the Windows dev machine, no
cloud. That selects option (C): publish windows are restricted to hours the machine is
on, and a missed window escalates rather than posting late (C-27). Recorded in
**DR-009**. An always-on VPS remains the escape hatch if missed windows become common;
it is a cost decision, not an architectural one, because the scheduler is a thin caller
of the same operation layer either way.

**O-2 — CLOSED 2026-08-11.** Jurisdiction confirmed as the UAE by the operator, so
this is no longer an open item at all. What follows is the original resolution,
retained because it explains the shipped ruleset's shape.

Previously: see §7. Jurisdiction stays inferred; the ruleset
is jurisdiction-parameterised with a conservative default that a later answer can only
relax, never invalidate. No doctrine-based rules are implemented.

**O-3 — OPEN. Deferred to first live connection, not to protocol 02.**
X paid API tiers and LinkedIn's gated posting access must be priced and
access-verified against live documentation. This cannot be resolved from model memory
(operator instruction) and does not block the build: the publisher interface is defined
and the v1 slice ships a **stub publisher** (registered fabrication), so the cost
question is answered when credentials are supplied. If either exceeds the $100 ceiling,
the choice is a budget change or a different mechanism — the latter tests C-30 and F-6.

**O-4 — DECIDED by default, reversible.** Provenance retains content hash + embedded
technical metadata + the full evidence set — option (A) plus (C), without stills, since
the v1 slice has no frame extraction absent ffmpeg (A-15). Stills are added when ffmpeg
enters scope; the provenance record carries a schema version so adding them is additive
rather than a migration. Operator may overrule.

---

## 13. What the architect inherits

Read this file plus `aef/core/CONSTITUTION.md`, then run
`aef/protocols/02-technology-selection.md`. The three constraints that should drive
technology choice hardest, in order:

1. **F-1 dual entry points, one implementation.** This is an architectural constraint
   before it is a UI one — it demands an operation layer that both surfaces are thin
   clients of. Choosing a stack whose natural idiom is UI-first will fight this
   for the life of the project.
2. **F-7 hard storage ceiling with admission control.** Storage is not a resource to
   provision but a budget to enforce, with reservation before work begins.
3. **C-20 / F-5 deterministic rights verdicts over recorded evidence.** This rules out
   any design where a model's output is the decision, and requires versioned rulesets
   and durable evidence records from the first commit.

Per Constitution §8, no technology is chosen by familiarity. Every choice runs through
protocol 02 against the constraints above and produces a decision record with
alternatives and tradeoffs.
