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
| Runtime | Local-first: Windows 11 desktop. Web UI on localhost; agents call the same operations in-repo | ASSUMED |
| Remote/mobile access | Not required | ASSUMED |
| Deployment target | Self-hosted, single machine. No cloud provider | ASSUMED — **conflicts with C-24, see §12 O-1** |
| Platforms | **X** (1 account), **LinkedIn** (1 account). Expansion later | Confirmed |
| Platform rate limits and API pricing | **NOT RECORDED — deliberately.** To be verified against live documentation during `protocols/02`. No figure from model memory is admissible here | Confirmed instruction |
| Content source | Screen recordings | Confirmed |
| Systems replaced | None. No existing scheduler, no existing library | Confirmed |
| Data residency | Operator's machine. If off-site backup uses cloud storage, residency becomes a live choice | ASSUMED |

### Browser automation policy

Browser automation is a **fallback**, permitted only for a platform with no usable API,
with the reason recorded at the point of use. It is never the default and never chosen
for convenience. This interacts with C-30: automation at volume risks the account
itself.

---

## 7. Compliance

| Aspect | Value | Confidence |
|---|---|---|
| Operating jurisdiction | **United Arab Emirates** | **INFERRED, UNCONFIRMED.** Evidence: Windows home location = UAE, timezone UTC+04:00. This is a machine setting, not a legal declaration |
| Copyright regime | UAE law, plus the terms of each platform | Follows from the above — unverified |
| GDPR | Assumed not applicable — no EU audience targeting, no third-party personal data processed beyond what platforms already hold | ASSUMED |
| UAE PDPL | Assumed not applicable for the same reason | ASSUMED |

> **Gate:** jurisdiction is unconfirmed and it determines the rights ruleset —
> what counts as fair use versus fair dealing, what public-domain terms apply, what
> licence types are recognised. **The rights ruleset may not be implemented until the
> operator confirms jurisdiction.** Every other part of the system may proceed. See
> §12 O-2.

---

## 8. Maintainer capability

Sole maintainer: the operator, indefinitely, with no second person and no handover
plan required.

Demonstrated capability (from observed behaviour, not self-report): comfortable with
git, CLI tooling, agent frameworks, and structured configuration.

`ASSUMED`: comfortable running Docker and administering a local database, but
**prefers low-ops**. Operational burden is a real cost against S2 (< 3 hours/week) —
a design that consumes an hour a week in maintenance has already spent a third of the
budget the system exists to protect.

---

## 9. Budget

| Item | Value |
|---|---|
| Monthly ceiling, all API and infrastructure | **$100** |
| Hard stop | **150% ($150)** — a stop, not a warning |
| Per-operation cap | **$5** without explicit approval |
| Deadline | None stated. `ASSUMED` no hard date |
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
| A-8 | Jurisdiction = UAE | **Blocks the rights ruleset. Confirm before implementing it** |
| A-9 | GDPR and UAE PDPL not applicable | Any audience targeting or third-party personal data processing |
| A-10 | No hard deadline; cut order analytics → scheduling → never rights | Operator states a date |
| A-11 | Docker and a self-administered DB acceptable; low-ops preferred | Ops burden approaches 1 h/week |
| A-12 | Sustained < 1 op/sec | — |
| A-13 | OAuth alerting at 72 h before expiry | First token expiry incident |
| A-14 | Dependency licence compatibility is a **check, not a hard gate** — commercial use unlikely but not impossible | Operator decides to commercialise |

---

## 12. Open items carried into technology selection

Not blockers for `protocols/02` unless marked. Presented as decisions, per the
escalation format.

**O-1 — The scheduler cannot run on a machine that sleeps.**
C-24 and C-26 require the scheduler to be up at every publish window with ±5 min
tolerance, and C-27 forbids posting late. A single self-hosted desktop that sleeps,
reboots, or travels will miss windows and escalate routinely, converting a hard
guarantee into a recurring interruption — which attacks S2 directly.
Options: **(A)** desktop guaranteed awake during publish windows — free, fragile;
**(B)** minimal always-on VPS for the scheduler only — small monthly cost against the
$100 ceiling, splits the deployment; **(C)** restrict scheduling to hours the machine
is known on — free, gives up optimal posting times.
*Recommendation: decide in `protocols/02` alongside hosting. Do not design the
scheduler until this is settled.*

**O-2 — Jurisdiction is unconfirmed and gates the rights ruleset.**
Inferred UAE from machine settings only. **Blocking for the rights ruleset alone;**
everything else proceeds.

**O-3 — Platform API cost and access may exceed the budget.**
X paid API tiers and LinkedIn's gated posting access must be priced and
access-verified against live documentation in `protocols/02`. If either exceeds the
$100 ceiling, the choice is a budget change or a different mechanism — the latter
tests C-30 and F-6 directly.

**O-4 — Provenance evidence standard after media deletion.**
If a rights claim arrives 18 months post-publish and the master is gone, what is
shown? Options: **(A)** content hash + technical metadata — smallest, proves a file
existed but not what was in it; **(B)** hash + metadata + a small set of stills —
a few hundred KB per video, negligible against the ceiling; **(C)** rely on the
published copy held by the platform.
*Recommendation: **B plus C**. The cost is trivial and A alone is weak evidence.
Not yet accepted by the operator.*

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
