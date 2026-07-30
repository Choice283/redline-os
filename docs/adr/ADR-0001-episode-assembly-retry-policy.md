# ADR-0001 — Episode Assembly Retry Policy

**Status:** Accepted. Not implemented — this record establishes policy
only; Mission 13 implements it. No code changes in this document.

**Note on numbering:** this is the first Architecture Decision Record in
Redline OS's history — there is no `ADR-0001` through `ADR-0006` anywhere
in this repository (verified by a full-repo search before writing this
file). This document was requested as "ADR-0007"; it's filed as `ADR-0001`
instead, since numbering it 0007 would leave six unexplained gaps, the
same kind of inconsistency `docs/ROADMAP.md` already had to resolve for
"Phase 3." Renumber before commit if there's an external ADR sequence this
should join instead.

**Establishes:** `docs/adr/` as the canonical location for future
Architecture Decision Records, following this same numbered, single-topic
format.

---

## Context

`EpisodeManager.build_episode()` is fully implemented, unit-tested, and
live-verified (`docs/ARCHITECTURE.md` §3.4), but has no CLI or MCP
exposure at all today. Mission 12 (Phase 9) exposed the read-only manifest
validation half of this capability. Mission 13 would expose the mutating
half — `episode assemble` — but is explicitly blocked pending this
decision, because `build_episode()`'s existing rerun/failure behavior has
real, verified gaps that a CLI would make operationally significant in a
way they currently aren't.

### What exists today (verified against the current code, not assumed)

`EpisodeManager._get_existing_episode_for_build()` rejects a build attempt
in exactly three cases:

1. The `episode_id` is already `EpisodeStatus.ASSEMBLED`.
2. The `episode_id` is `EpisodeStatus.FAILED` ("automatic assembly retry
   is not safe in V1").
3. The `episode_id` is in `self._unsafe_rerun_episode_ids` — an in-memory
   `set()` populated only when the *final* `update_episode_status(ASSEMBLED)`
   call itself fails after every other assembly stage already succeeded
   against Resolve (the "stale status" case: Resolve has the fully
   assembled content, but SQLite still shows a pre-assembly status).

Every other status — `CREATED`, `ASSETS_VERIFIED`, `MEDIA_ORGANIZED`,
`TIMELINE_BUILT`, `RENDER_QUEUED`, `RENDERED`, `ARCHIVED` — currently
passes this check without complaint. Nothing today stops `build_episode()`
from being called against an episode that's already been rendered or
archived.

### The finding that drove this ADR

`self._unsafe_rerun_episode_ids` is instance state on `EpisodeManager`,
initialized fresh in `__init__`. `build_application_services()` constructs
a new `EpisodeManager` on every call, and `cli/main.py`'s `main()` calls
`build_application_services()` fresh on every single process invocation —
already-documented behavior (Missions 9–11B needed a shared-instance
monkeypatch technique specifically to work around this for
`MockResolveAdapter` state). The consequence for this guard specifically:
**it can never fire through the CLI.** A fresh `redline` invocation always
starts with an empty `_unsafe_rerun_episode_ids` set, no matter how many
times a prior invocation hit the stale-status failure. `ARCHITECTURE.md`
§3.4 already documents this guard as "in-memory only, cleared on restart"
— written with a long-running MCP server in mind, where restart is rare.
For a CLI, restart is every command. The practical effect: today, the one
piece of code specifically designed to prevent duplicate Resolve mutation
after a stale-status failure provides **zero protection** in the transport
this ADR is being written to unblock.

This means any real policy decided here will likely require a small,
explicit `EpisodeManager`/schema change (a persisted marker, not an
in-memory one) — Mission 13 is probably not "transport work only" once
this is decided. That's a real scope finding, not a reason to avoid
deciding.

---

## Questions to answer

### 1. When is a retry allowed?

**Decision:** allowed whenever the episode's status is one of
`CREATED`, `ASSETS_VERIFIED`, `MEDIA_ORGANIZED`, `TIMELINE_BUILT` — the
same "hasn't reached a terminal or already-successful state" set
implicitly allowed today, made explicit rather than left as "everything
not on the blocklist." See the exhaustive status matrix below — every
`EpisodeStatus` member is assigned exactly one policy category; none is
governed by an implicit default, which is precisely how the
`RENDER_QUEUED`/`RENDERED`/`ARCHIVED` gap survived in today's guard.

### 2. When is retry blocked?

**Decision:** blocked for `ASSEMBLED` (already succeeded — no
override, not even `allow_unsafe_retry`; re-running a successful assembly
is a different, much riskier operation than retrying a failed one, and
nothing today demonstrates a need for it) and for
`RENDER_QUEUED`/`RENDERED`/`ARCHIVED` (currently *not* blocked at all — a
real, pre-existing gap this ADR surfaces rather than one it invents, also
with no override). `FAILED` and the stale/uncertain-claim case move from
"blocked" to "blocked by default, unblockable only via
`allow_unsafe_retry=True`" — see below.

### Status matrix (exhaustive — all nine `EpisodeStatus` members)

| `EpisodeStatus` | Policy category | Meaning |
|---|---|---|
| `CREATED` | Allowed normally | Fresh episode, no assembly attempted yet |
| `ASSETS_VERIFIED` | Allowed normally | Pre-assembly step complete, no Resolve mutation from assembly yet |
| `MEDIA_ORGANIZED` | Allowed normally | Media organized outside `build_episode()`; assembly itself not yet attempted |
| `TIMELINE_BUILT` | Allowed normally | Timeline exists outside `build_episode()`; assembly itself not yet attempted |
| `FAILED` | Blocked unless forced | A known-bad prior attempt; `allow_unsafe_retry=True` required, subject to the atomic claim below |
| *(uncertain-claim state — see Atomic Assembly Claim)* | Blocked unless forced | A prior attempt whose outcome is unknown (claimed but never resolved to success/known-failure); `allow_unsafe_retry=True` required |
| `ASSEMBLED` | Always blocked | Assembly already completed successfully; no override |
| `RENDER_QUEUED` | Always blocked | Downstream processing has begun; no override |
| `RENDERED` | Always blocked | Downstream processing complete; no override |
| `ARCHIVED` | Always blocked | Terminal lifecycle state; no override |

No `EpisodeStatus` member falls into "invalid/unreachable" — all nine are
reachable and are each assigned an explicit category above.

### 3. Should confirmation be required?

**Decision:** yes, but as a non-interactive `--force` flag, not an
interactive y/n prompt. No command in this CLI has an interactive
confirmation step anywhere today (`create`, `organize-bins`,
`build-timeline`, `place-clips`, `archive episode` are all
non-interactive) — adding one here would be a new, unprecedented CLI
interaction pattern for a single command, and would break scripted usage
with no discussed need for that tradeoff. A `--force` flag is greppable in
scripts, matches common CLI convention, and keeps the command
non-interactive like every sibling command.

### 4. Should `--force` exist?

**Decision:** yes, at the CLI, but narrowly: `--force` bypasses the
`FAILED` / uncertain-claim rejection only. It does not bypass `ASSEMBLED`
(see Q2) and does not bypass the `RENDER_QUEUED`/`RENDERED`/`ARCHIVED`
rejection (retrying assembly on an archived episode is a different
decision than retrying after a failure, and isn't in scope here). The
underlying bypass belongs on `EpisodeManager.build_episode()` itself, not
in the CLI transport — the same "managers own orchestration rules,
transports pass operator intent through" principle every prior mission
has followed. This also directly serves Q6: a future MCP tool gets the
identical rule for free by calling the same manager method, rather than
each transport re-implementing it. See "Core API wording" below for why
the manager-level parameter is not itself named `force`.

### 5. What constitutes a "dirty" episode?

**Decision:** an episode is "dirty" (retry-eligible only with
`allow_unsafe_retry=True`, with a prominent warning) if its status is
`FAILED`, **or** if it carries an uncertain assembly claim (see Atomic
Assembly Claim below — replacing today's ineffective in-memory set). An
episode in `RENDER_QUEUED`/`RENDERED`/`ARCHIVED` is not "dirty" in this
sense — it's simply out of scope for assembly entirely, no override, per
Q2 and the status matrix.

### 6. What is the operator expected to inspect before retrying?

**Decision:** carry forward `ARCHITECTURE.md` §3.4's existing
language unchanged — inspect both the Resolve project and the SQLite
`episodes` row before using `--force` on a `FAILED` or uncertain-claim
episode. The CLI's `--force` help text and any warning output should quote
this existing guidance, not invent new instructions. This is the same
"CLI reports outcomes, doesn't invent new distinctions" discipline applied
to a warning message instead of a result field.

### 7. How will future MCP tools honor the same policy?

**Decision:** by construction, not by convention — because
`allow_unsafe_retry` and the dirty/blocked logic live on
`EpisodeManager.build_episode()` itself (per Q4 and "Core API wording"
below), any future MCP tool (Phase 11) that calls the same method
automatically enforces the same rule. No policy logic should live in
`cli/episode_commands.py` beyond mapping an operator-supplied `--force`
flag to `allow_unsafe_retry=True` — mirroring exactly how `place_clips`'
append-only behavior is enforced once in `TimelineBuilder` and inherited
by every caller, not re-implemented per transport.

---

## Atomic assembly claim (required, not optional)

A persisted marker alone is insufficient. Two separate CLI processes can
each read "eligible" before either writes anything:

```
Process A reads: assembly eligible
Process B reads: assembly eligible
Process A writes: attempt started
Process B writes: attempt started
```

Both could still mutate Resolve. This is not a new risk this ADR
introduces — the earlier architecture review already established that
`FAILED` alone does not identify how far Resolve mutation progressed, that
retries can duplicate media, markers, and clips, and that concurrent
`build_episode()` calls can both pass today's eligibility check. A
persisted marker fixes the "survives restart" half of the problem but
leaves this race intact.

The repository must therefore support an **atomic assembly-attempt
claim** — eligibility check and claim acquisition are one repository
operation, not a read followed by a separate write:

```
eligible state
    ↓ atomic claim
assembly attempt active
    ↓
Resolve mutation
    ↓
success, known failure, or uncertain failure
```

Required invariants (policy-level; exact SQLite mechanism — e.g. a
conditional `UPDATE ... WHERE status = ?` guarding a new claim column
versus a dedicated claims table — is a Mission 13 implementation-contract
decision, not this ADR's):

1. Only one caller may claim a given episode for assembly at a time.
2. The claim must survive process exit or crash — this is what actually
   replaces today's ineffective in-memory `_unsafe_rerun_episode_ids` set.
3. A stale or uncertain claim (assembly started, never resolved to
   success or a known failure) blocks ordinary retry — it is not silently
   equivalent to `FAILED`, since `FAILED` at least means the manager
   itself observed and recorded a definite outcome.
4. `allow_unsafe_retry=True` may override only the explicitly approved
   recoverable states (`FAILED`, uncertain claim) — see the status matrix
   above.
5. Terminal post-assembly states (`ASSEMBLED`, `RENDER_QUEUED`, `RENDERED`,
   `ARCHIVED`) remain blocked even with `allow_unsafe_retry=True`.
6. Eligibility check and claim acquisition are one atomic repository
   operation. A separate read followed by a separate write reintroduces
   exactly the two-process race shown above and does not satisfy this
   invariant.

## Core API wording

`EpisodeManager.build_episode()`'s new parameter is manager-owned, transport-neutral vocabulary — not CLI vocabulary:

```python
build_episode(
    definition: EpisodeBuildDefinition,
    *,
    allow_unsafe_retry: bool = False,
) -> EpisodeBuildResult
```

The CLI maps its own `--force` flag to `allow_unsafe_retry=True`; a future
MCP tool (Phase 11) can map its own explicit confirmation field to the
same manager parameter, without `redline_core` ever knowing the word
"force" or anything about argparse. This is the same transport/manager
ownership boundary every prior mission has followed, applied to a
parameter name instead of a result field.

## Force semantics

`allow_unsafe_retry=True` (and the CLI's `--force` that maps to it) means
exactly this, and the CLI's help text and warning output should say so
directly, quoting `ARCHITECTURE.md` §3.4's existing guidance rather than
inventing new wording:

> The operator has inspected and manually reconciled Resolve and SQLite,
> and accepts the risk of duplicate media, markers, or clips.

It explicitly does **not** mean any of the following, and the ADR
record should make that unambiguous for whoever implements Mission 13:

- Redline OS performed a rollback.
- Redline OS proved the timeline is clean.
- Redline OS made the operation idempotent.
- Redline OS repaired any prior partial mutation.
- Redline OS may overwrite a completed or downstream episode — it may
  not; `ASSEMBLED`/`RENDER_QUEUED`/`RENDERED`/`ARCHIVED` are always
  blocked regardless of this flag, per the status matrix and invariant 5
  above.

This is consistent with, not a change to, what `ARCHITECTURE.md` already
documents: lower layers remain non-idempotent, and an existing timeline
cannot reliably be classified as empty or populated from the outside.

---

## Decision

**Approved**, incorporating the atomic-claim refinement:

- Manager-owned policy: **approved** — `EpisodeManager.build_episode()` is
  the sole authority; no transport implements retry/eligibility logic of
  its own.
- Explicit `--force` (CLI) mapped to `allow_unsafe_retry` (manager),
  rather than an interactive prompt: **approved**.
- Terminal statuses (`ASSEMBLED`, `RENDER_QUEUED`, `RENDERED`, `ARCHIVED`)
  blocked even with `allow_unsafe_retry=True`: **approved**.
- Persistent (not in-memory) retry protection: **approved**.
- Atomic assembly-attempt claim, per the six invariants above, as the
  mechanism that actually closes the two-process race — not merely a
  persisted flag checked and set in two separate steps: **approved,
  required**.

Mission 13's implementation contract should be drafted against this
decided policy, and should openly include the required manager and
persistence changes identified here (the `allow_unsafe_retry` parameter,
the atomic claim mechanism, the new terminal-status rejections) as part
of its scope — not presented as if it were transport-only work.

## Consequences

- `EpisodeManager.build_episode()` gains an `allow_unsafe_retry: bool = False`
  keyword-only parameter and a repository-level atomic claim operation —
  exact SQLite schema/mechanism (new column vs. dedicated claims table;
  exact conditional-`UPDATE` shape) to be specified in Mission 13's
  implementation contract, not here.
- A new, previously-undiscussed rejection is added for
  `RENDER_QUEUED`/`RENDERED`/`ARCHIVED` episodes, closing a real gap in
  existing behavior — this is a `redline_core` behavior change, not purely
  additive, and should be called out plainly in `docs/CHANGELOG.md` when
  implemented, with its own manager-level test proving the new rejection,
  independent of any CLI test.
- `episode assemble --force` becomes the only CLI command in this
  codebase with a confirmation-style flag — worth a short README note
  explaining why this one command has one and no others do.
- `docs/ARCHITECTURE.md` §3.4's "must be solved before broader MCP or
  automated assembly use" caveat is resolved for the CLI specifically,
  including the concurrent-call race it explicitly named; the
  fully-unattended/automated-triggering case is still out of scope for
  this ADR.
- Mission 13 requires new manager-level tests proving the atomic claim
  actually prevents two concurrent `build_episode()` calls from both
  proceeding against the same episode — this is the test that would have
  failed against today's guard and must not be skipped.

## Open follow-up (not decided here)

- Exact persistence mechanism for the atomic claim (new `EpisodeStatus`
  value vs. a separate nullable column/claims table; exact conditional-
  write SQL) — Mission 13 implementation-contract detail, not policy.
- Whether `RENDER_QUEUED`/`RENDERED`/`ARCHIVED` episodes should ever be
  force-assemblable under some future recovery workflow — explicitly
  deferred, not decided as "never."
- Fully-unattended/automated assembly triggering (as opposed to a human
  operator invoking the CLI or an MCP tool interactively) remains outside
  `ARCHITECTURE.md` §3.4's already-stated scope and is not addressed by
  this ADR either.
