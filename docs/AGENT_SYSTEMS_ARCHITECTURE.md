# Redline Agent Systems Initiative — Mission AS-1: Institutional Memory & Agent Resume Architecture

Status: **Accepted architecture, not implemented.** This document records the
Mission AS-1 design Control Room accepted, with corrections, after a
read-only investigation-and-research mission. No code, schema, registry,
Resume Packet generator, permission system, orchestration, reconciliation,
context-compaction implementation, or specialist agent exists as a result of
this document. Nothing in this document authorizes any of that; each later
mission (AS-2 onward) requires its own separate, explicit founder
authorization per `CLAUDE.md`.

**Agents advise. Paul decides.**

## 0. Naming

Canonical initiative name: **Redline Agent Systems Initiative**.
Canonical mission name: **Mission AS-1 — Institutional Memory & Agent Resume
Architecture**.

Retired names — do not use: "Redline OS V2 Agent Systems Initiative",
"Mission 2A". `docs/V2_MISSION_1A_CLOSURE_2026-08-16.md` and the
`docs/V2_MISSION_1B*_CLOSURE_*.md` family already use "V2" for the
Backup/Restore/Recovery mission track; reusing "V2" for an unrelated
initiative would repeat the exact numbering collision `docs/ROADMAP.md`
("A note on 'Phase 3'") already warns against. The `AS-*` namespace
(`AS-1`, `AS-2`, ...) is deliberately its own sequence, orthogonal to
Redline OS's own `Phase N` / `Mission N` / `V2 Mission NX` numbering, so an
Agent Systems mission number can never collide with a Redline OS roadmap
number, and vice versa.

## 1. Purpose

Define, on paper, how Redline can own durable operational knowledge that
survives the replacement of any single agent, conversation, context window,
or AI provider — so that a fresh agent can safely resume a mission without
depending on the prior agent's memory of it. The goal is not to build agents
yet; it is to define what a disposable agent needs handed to it, and what it
must independently re-verify, in order to be safely disposable.

Core principle: **the agent is disposable, Redline's institutional knowledge
is durable.** A conversation or context window must never be the sole
source of truth for mission state, policy, skills, approved operational
knowledge, production evidence, authorization, safety boundaries, or desired
state.

## 2. Relationship to the Redline OS / Future Parent Platform boundary

`docs/REDLINE_OS_PAUSE_CHECKPOINT_2026-08-12.md` §5/§7 already records a
founder-authored architecture boundary:

```text
Future Creator Platform
        |
        |-- creator intelligence
        |-- content intelligence
        |-- show / podcast discovery
        |-- visual environment intelligence
        |-- agent orchestration
        |-- provenance
        |-- likeness / voice authorization
        `-- human approval
                 |
                 v
      Approved Production Package
                 |
                 v
             Redline OS
                 |
                 v
        DaVinci Resolve Studio
                 |
                 v
         Validated Production
```

That document's §7 "Future Parent Platform" list names, verbatim, work
explicitly deferred outside Redline OS: Hermes evaluation, LangGraph
evaluation, Temporal evaluation, **agent orchestration**, creator/content
intelligence, semantic search, creator likeness/voice systems,
environment/set inference, podcast discovery, shorts intelligence,
**provider-routing architecture**, and dedicated Creator Platform Lab
infrastructure. This document does not erase, reinterpret, or narrow that
boundary — it is a founder decision, and it stands.

**Mission AS-1 adopts a hybrid ownership architecture** that is consistent
with, not a revision of, that boundary:

- **Owned inside `redline-os`**: contracts and Redline-OS-specific
  operational knowledge required for Redline OS to safely expose and
  execute its own capabilities — e.g. a Repository Engineer agent's own
  institutional knowledge about operating *this* repository, the
  mission-lifecycle procedure this session used (currently a global Claude
  Code skill, not repository content — see §14), and Redline-OS-scoped
  Agent Identity declarations (§4).
- **Owned outside `redline-os`**, in whatever becomes the Future Parent
  Platform: cross-specialist institutional memory, shared agent lifecycle
  across multiple specialist domains (audio, video, graphics, QC,
  research...), provider routing, and multi-agent orchestration. This is
  exactly the territory the pause checkpoint already reserved for a
  not-yet-built system.

Nothing in this document assumes the Future Parent Platform exists yet or
names its implementation. Where AS-1 defines a contract that a future
parent-platform agent would also need to satisfy (e.g. the Resume Packet
shape in §11), that contract is written to be provider-neutral and
repository-location-neutral for exactly that reason — see §7.

## 3. Canonical terminology

| Term | Definition |
|---|---|
| **Agent Identity** | A versioned, named, file-stored *declaration* of an agent's role, domain, requested/allowed capabilities, and tool/resource scope. Identity is not itself enforcement — see §4. |
| **Session / Context Memory** | Ephemeral, provider-native working state: conversation transcript, scratch reasoning, currently-loaded context, transient observations. Never a source of institutional truth. Already ranked below durable documentation in the repository's own priority order (`docs/CONTROL_ROOM_V0_ARCHITECTURE.md`: "repository > Git state > tests/production evidence > checkpoints > durable documentation > agent reports > conversation memory"). |
| **Durable Institutional Memory** | Approved, evidence-backed, governance-classified Redline knowledge that survives agent, session, and provider replacement. Subdivides into the three knowledge categories in §5 — never one undifferentiated bucket. |
| **Skill** | A versioned, reusable procedure describing HOW to perform an operation. |
| **Policy** | A binding rule describing WHAT is permitted, required, or prohibited. |
| **Evidence** | An observed fact or artifact, with provenance, that supports a claim and can be independently re-verified against current state before that claim is trusted. |
| **Desired State** | What Redline (approved institutional memory + policy, Git-declared) says SHOULD be true. |
| **Actual / Live State** | What a fresh, current probe observes IS true right now (Resolve, filesystem, SQLite, CI, Git). |
| **Git Source of Truth** | Git is authoritative for the *approved, declared* content and its audit trail — see the explicit boundary in §9. It does not, by itself, prove live state matches it. |
| **Resume Packet** | A provider-neutral, evidence-anchored bundle handed to a fresh agent so it can safely continue a mission without the prior agent's conversation — see §11. |
| **Candidate Knowledge** | An agent's `OBSERVED` or `PROPOSED` claim, before it has passed validation and (where required) approval — see §7. Not yet institutional truth. |
| **Institutional Knowledge** | A record that has reached `ACTIVE` state in the lifecycle (§7) — governed, evidenced, durable, and authoritative until superseded or revoked. |

## 4. Identity vs. enforcement

Agent Identity **declares**: role, domain, requested/allowed capabilities,
tool/resource scope. It is a durable, file-stored, versioned artifact —
never inferred from a conversation.

Agent Identity does **not enforce** anything by itself. Actual enforcement
is the job of two separate layers:

1. **Policy/permission resolution** — deciding, at the moment of an action,
   whether an identity's declared capabilities actually authorize that
   specific action in that specific context.
2. **Runtime/tool boundaries** — the mechanism (e.g. tool-access scoping,
   sandboxing, a technical gate) that actually blocks a disallowed action
   regardless of what the agent or its identity record claims.

This mirrors a caveat already visible in Claude Code's own documentation:
CLAUDE.md-style instructions are "context, not enforced configuration" —
they shape behavior but do not technically block anything by themselves;
hard enforcement requires a separate technical layer. Redline's own
`CLAUDE.md` governance today is exactly that kind of advisory instruction
text. Mission AS-1 does not close that gap — closing it (a real enforcement
layer for Agent Identity's declared scope) is later, separately authorized
work, not something this document should be read as having solved.

## 5. Knowledge categories

Institutional knowledge is not one undifferentiated "memory" bucket. Three
categories, distinguished by what kind of claim they make:

- **Normative knowledge** — what SHOULD be true. Policy, permission rules,
  safety boundaries, authorization scope, creative-authority decisions.
- **Descriptive institutional knowledge** — validated, reusable facts or
  learning about how Redline or its environment actually behaves (e.g. "the
  `broadcast_master` preset requires at least one video TimelineItem" —
  the kind of fact `docs/ROADMAP.md`'s Phase 14 history already records).
- **Mission / episodic state** — what happened in one specific mission:
  its checkpoint, its evidence, its open blockers. Not a general claim about
  how Redline behaves — a record of one mission's history, analogous to a
  closure document.

Every knowledge record (§8) carries exactly one of these three categories.
The category, together with the governance class (§6), determines how much
scrutiny a record needs before it can become `ACTIVE`.

## 6. Governance classes

Not every candidate fact deserves the same promotion friction. Three
governance classes, cutting across the knowledge categories in §5:

- **Governed / high-impact** — policy, permission, authorization, safety
  rule, creative-authority decision. Founder approval is required before
  `ACTIVE`, every time, with no exception. This is the class the mission
  brief's core rule exists to protect: *"an agent must NOT be able to
  convert its own unsupported observation directly into permanent Redline
  truth."*
- **Mechanically verifiable** — a Git SHA, a file hash, a test result, a
  deterministic, machine-checkable system property. May become `ACTIVE`
  through a validation/promotion policy that Paul has *previously*
  approved for that specific class of fact — Paul is not asked to
  personally re-approve, for example, every individual exact-head CI
  verification. The pre-approved policy itself is a governed/high-impact
  record.
- **Interpretive** — an agent's heuristic, recommendation, or qualitative
  observation. Can never self-promote merely because the proposing agent
  believes it. Reaches at most `VALIDATED` on its own evidence; needs
  founder approval to go further, same as governed/high-impact, because
  there is no mechanical test that can confirm an interpretation is
  correct.

This is what makes the lifecycle in §7 workable at scale: it lets
deterministic, mechanically-checkable facts flow without demanding Paul's
attention on every one, while keeping every non-mechanical claim behind an
explicit human gate — never an agent's own say-so.

## 7. Knowledge-promotion lifecycle

```text
OBSERVED -> PROPOSED -> VALIDATED -> APPROVED -> ACTIVE -> SUPERSEDED / REVOKED
```

- **OBSERVED** — a raw agent note. Not yet a candidate; carries no
  provenance requirement yet.
- **PROPOSED** — a candidate with evidence attached (§8's provenance
  field populated).
- **VALIDATED** — the evidence has been mechanically re-checked against
  current state (citations resolve, hash matches, CI run confirmed, etc.).
  An agent can reach this state on its own.
- **APPROVED** — for governed/high-impact and interpretive records: an
  explicit, recorded founder decision. For mechanically-verifiable records:
  satisfying a previously-approved validation policy counts as approval,
  per §6. **No record reaches `ACTIVE` without passing through `APPROVED`
  under one of these two paths — an agent can never skip this step for
  itself.**
- **ACTIVE** — Git-checkpointed and, where the record's governance class
  requires it, CI-integrity-verified. This is institutional truth until
  superseded or revoked.
- **SUPERSEDED / REVOKED** — see §10.

## 8. Institutional-memory record — minimum contract

A record contains:

- `id` — stable identifier.
- `knowledge_category` — one of §5's three values.
- `governance_class` — one of §6's three values.
- `statement` — the claim itself.
- `domain` — the area of Redline (or specialist domain) the claim belongs
  to; a declared classification that the domain-boundary check in §21
  validates a candidate against. The field itself declares and classifies;
  it does not enforce anything — see §4.
- `provenance` / evidence references — what supports the claim, re-checkable
  against current state.
- `lifecycle_state` — one of §7's states. **Single field.** A separate
  "approval status" field is deliberately not included — it would duplicate
  what `lifecycle_state` already encodes and risks drifting out of sync
  with it, the same failure mode Control Room's own design already avoids
  by never inventing a second source of one fact.
- `approval_reference` — present when `lifecycle_state` requires it (§7);
  points at the durable evidence of the actual founder decision (§9), never
  a bare boolean.
- `repository_source_anchor` — the exact commit/SHA the record is anchored
  to.
- `external_authority_reference` — optional, structured; present only when
  the record references an external creative authority (§13).
- `revalidation_policy` — per-record, not a global constant (a safety
  policy and a render-preset quirk do not deserve the same revalidation
  cadence).
- `created_at`, `last_validated_at`.
- `supersedes` / `superseded_by` — see §10.

## 9. Approval evidence and trust boundary

A `lifecycle_state` of `APPROVED` or `ACTIVE` is a claim, not proof by
itself, that a real founder decision occurred. The architecture requires
durable evidence of that decision, proportionate to the record's governance
class:

- **Governed/high-impact and interpretive records** require a durable,
  attributable record of Paul's actual decision (e.g. an explicit
  chat-authorized instruction captured in a closure-style document, or a
  reviewed and merged change to a durable policy document) — something a
  future reader can point at, the same way closure documents already cite
  an "Independent Review" verdict rather than merely asserting one.
- **Mechanically-verifiable records** require evidence that the
  pre-approved validation policy actually ran and passed (e.g. the same
  exact-head CI citation convention already used throughout this
  repository's closure documents).

Cryptographic signing is explicitly **not** designed here — nothing in the
threat model (§21) currently justifies it, and inventing it would be
scope creep beyond what this mission's evidence supports. If a future
threat is found that only signing addresses, that is its own later,
separately justified decision.

**Trust boundary**: no tool an agent uses to propose or validate its own
candidate knowledge may itself assert that founder approval occurred.
This directly reuses the precedent already established in
`docs/BACKUP_RECOVERY_ARCHITECTURE.md` §17.3, where a mutating
Backup/Restore/Recovery capability is permanently barred from MCP exposure
because a call arriving through a running MCP server can never truthfully
attest the precondition (`mcp_stopped`) it depends on. The same reasoning
applies here: a promotion tool must never be able to assert "Paul approved
this" — only Paul's own recorded action can set that.

## 10. Invalidation and supersession

- **REVALIDATE** — evidence is re-checked against current state; success
  resets the record's staleness clock per its own `revalidation_policy`.
- **SUPERSEDE** — a new record replaces an old one; both are retained,
  linked via `supersedes`/`superseded_by`. Never a silent mutation of the
  old record — the same discipline already used for construction revisions
  throughout this repository (Rev1 → Rev2 → ... → RevN, each an explicit
  replacement, never an edit in place).
- **REVOKE** — a record is found false, unsafe, or otherwise disproven.
  It stays in history, marked revoked. **Disproven historical truth is
  never silently deleted** — this repository's own mission-lifecycle
  discipline already states the equivalent rule for a failed publication:
  "The failed publication stays in history exactly as it happened; it is
  evidence, not an embarrassment to erase."
- **Conflicting `ACTIVE` knowledge** fails closed. It is surfaced as an
  attention-required condition — the same shape as Control Room's existing
  `attention.required` signal — and is never automatically arbitrated by
  another agent. Only a founder decision resolves a conflict between two
  `ACTIVE` records.

## 11. Resume Packet

A provider-neutral bundle that lets a fresh agent safely continue a mission
without the prior agent's conversation. It **references** durable
authoritative state; it does not inline copies that could go stale
unnoticed.

Conceptual contents:

- Agent identity reference.
- Mission reference.
- A repository/durable-state **anchor** — a pointer instructing the fresh
  agent to re-derive current repository state (see §12), never a baked
  value.
- Policy references — which policy version was in effect.
- Required skills list.
- References to `ACTIVE` institutional-memory records relevant to the
  mission (by `id`, not inlined content).
- The latest durable mission checkpoint reference (closure-document style).
- Evidence references.
- Open blockers — sourced from the durable checkpoint, never from a
  transcript that might be discarded.
- `required_fresh_probes` — a **mandatory**, non-optional list of exactly
  which live/external facts must be independently re-observed before the
  fresh agent may rely on them (§12).
- Authorization evidence.

**Critical rule**: the Resume Packet may *preserve* authorization evidence.
It does not create, extend, renew, or reinterpret authorization. A fresh
agent must independently confirm that any authorization it finds referenced
in the Packet still applies to the current mission, stage, and scope before
acting on it — exactly the same seven-key discipline (READ-ONLY
INVESTIGATION / IMPLEMENTATION / CHECKPOINT COMMIT / CLOSURE DOCUMENTATION /
CLOSURE COMMIT / PUBLICATION PUSH / POST-FAILURE CORRECTION) already
governing this repository's mission lifecycle. A Resume Packet is never
itself an authorization grant.

## 12. Fresh-state rule

Any Resume Packet field describing live or external state — current Git
HEAD, working-tree condition, whether Resolve is running, a specific SQLite
row, filesystem presence, current CI status, any external-service state —
is a **hint**, explicitly labeled non-authoritative. The fresh agent must
independently re-derive it using the same read-only procedures already
established in this repository (the preflight discipline this very mission
used before writing this document). A Resume Packet without a populated
`required_fresh_probes` list is malformed, not merely incomplete.

## 13. Creative-authority boundary

Redline Agent Systems does not duplicate or redefine Redline Content
creative truth (visual creative standards, show branding, host
personalities, editorial voice, the Universe Bible, Asset ID standards,
Broadcast Package conventions). This generalizes a pattern already present
in this repository: `config/assets.yaml` and `config/naming.yaml` both
state, verbatim, "do not invent" entries — add one only once the external
authority has approved it.

An institutional-memory record's `external_authority_reference` field
points at a stable external identifier (an Asset ID, a Universe Bible
entry) — it never inlines or redefines that authority's content as a
competing source of truth.

## 14. Provider-memory boundary

Provider-native memory (Claude Code auto-memory, ChatGPT memory, Codex
session state, Factory.ai's session summaries, or any other provider's
proprietary persistence) may be used only as working convenience, cache, or
scratch/candidate memory. It is never canonical Redline institutional
truth. Nothing a provider remembers on its own may reach `ACTIVE` without
independently passing through the full lifecycle in §7, evidenced on its
own merits, not on the provider's claim that it is true.

This is not a new constraint invented for AS-1 — it is consistent with
Anthropic's own documentation for Claude Code, which states plainly that
CLAUDE.md and auto memory are "context, not enforced configuration," and
with the observation (§3) that this repository's mission-lifecycle
skill already ranks "agent reports and conversation memory" last in its
source-of-truth order.

One concrete existing gap this boundary makes visible: the mission-lifecycle
and repository-preflight procedures used throughout this very mission are
currently *global Claude Code skills*, not `redline-os` repository content.
Today, some of Redline's own operational procedure knowledge lives outside
the repository, in agent tooling that is itself provider-native. Whether
and how to bring that procedural knowledge under the boundary in §2 (owned
inside `redline-os` vs. the Future Parent Platform) is not decided by this
document — it is named here as an observed gap for a later mission.

## 15. Git authority boundary

Git is authoritative for:

- Approved, declared institutional knowledge (`ACTIVE` records).
- Policy and configuration declarations.
- Version history of every record, including superseded and revoked ones.
- Audit trail — the commit history that shows who approved what, and when.
- Approval/checkpoint evidence that is itself stored as repository content.

Git is **not** authoritative for:

- Whether DaVinci Resolve is currently running.
- Current filesystem state.
- Current database contents.
- Current CI status.
- Any other live or external condition.

Those require a fresh observation (§12), every time. This is the same
distinction Control Room's own Closed-State Currency mechanism already
draws for one narrow case (whether the repository has moved beyond a
recorded closed state) — Git proves what was *declared*; it never proves
what is *currently true* about anything outside itself.

## 16. Storage recommendation

For V0: Git plus structured text (Markdown/YAML/JSON) is the canonical
durable store. No vector database — nothing in this repository's own
engineering culture, nor in any external system researched for this
mission, justifies one; the closest external analogue with a governed
memory concept (GitHub Copilot Memory) uses citations against source, not
embeddings.

A generated index or cache (e.g. a rebuilt SQLite index for fast lookup as
record count grows) may exist later, once record volume actually makes
linear scans through files impractical — this is the concrete mitigation
for the "memory grows until retrieval itself becomes context pollution"
failure mode named in §21 of the threat model below. Any such index must
always be rebuildable from the canonical Git-stored records; it is never
itself authoritative, exactly like Control Room's own principle of parsing
closure documents fresh from source on every read rather than caching them
as truth.

Where a durable artifact (e.g. a Resume Packet, once implemented) needs
integrity guarantees, the required properties are: content binding (the
artifact is anchored to an exact hash/commit), verify-before-trust (a
consumer re-derives rather than assumes), and independent re-derivation
where the underlying fact can be recomputed rather than merely re-read.
This repository's Backup/Restore package format
(`docs/BACKUP_RECOVERY_ARCHITECTURE.md` §5–§6) already satisfies all three
properties for a structurally similar problem, but AS-1 does not mandate
reusing that exact machinery — a later implementation mission should choose
the lightest mechanism that actually satisfies these three properties for
its specific artifact, not copy the full archive pipeline by default.

## 17. Context lifecycle (architecture only)

```text
agent session begins
    -> context grows
    -> candidate discoveries (OBSERVED/PROPOSED) leave transient context
       through governed promotion (§7)
    -> durable checkpoint recorded (closure-document style)
    -> context approaches a replacement threshold
    -> old session is compacted or replaced
    -> fresh agent loads a Resume Packet (§11), never a raw transcript
    -> fresh agent re-probes every required_fresh_probes entry (§12)
    -> mission continues
```

No provider-specific compaction mechanism is designed here. This shape
defines only what must survive a compaction or replacement event so that a
later, separately authorized compaction implementation has something safe
to build against.

## 18. Desired-state / actual-state boundary

This mission defines vocabulary and a conceptual interface only:

- **Desired state** — `ACTIVE` institutional memory + policy, Git-declared.
- **Actual/live state** — freshly probed observation of Resolve, filesystem,
  database, CI, or any other external system.
- **Drift** — the difference between the two, when observed.

**Not authorized by this document**: drift *detection* implementation,
reconciliation, or any form of self-healing. Argo CD's own architecture
treats detection and correction as separable, independently-toggleable
capabilities; Redline should adopt that separation, not its defaults — an
unattended correction against a live Resolve project or SQLite database is
categorically more dangerous than reapplying an idempotent Kubernetes
manifest, and is structurally incompatible with this repository's existing
governance model (`CLAUDE.md` §15: smallest blast radius; "Agents advise.
Paul decides.").

## 19. Orchestration boundary

Full multi-agent orchestration is not designed or implemented in AS-1.
Per §2, cross-specialist orchestration is Future Parent Platform
responsibility, not Redline OS's. Where a later AS-mission needs an
interface that a future orchestrator would eventually call (e.g. how a
single specialist agent exposes its own capabilities), that compatibility
requirement may be recorded without building the orchestrator itself.

## 20. Future UI boundary

Any future visual representation of agents, context growth, or
mission/specialist status (e.g. an "agent avatar," a "send the agent to the
gym" context-compaction affordance) is Control Room / Future Parent
Platform UX, not part of this document. AS-1 defines only the underlying
state concepts (§8's record schema, §11's Resume Packet, §17's context
lifecycle) that such a UI could eventually read — it does not design the
UI itself.

## 21. Threat / failure model

Fail-closed behavior, one line per threat:

- **Agent promotes hallucination into memory** — structurally blocked: no
  record reaches `ACTIVE` without `APPROVED` (§7), and an agent can never
  set `APPROVED` on a governed/high-impact or interpretive record itself.
- **Stale memory outlives its evidence** — `REVALIDATE` (§10) re-checks
  citations against current state before use; a citation that no longer
  resolves is treated as revoked-pending-revalidation, never silently
  trusted.
- **Malicious/corrupt evidence** — every record is anchored to a
  `repository_source_anchor` (§8); evidence that does not independently
  re-verify against that anchor fails closed.
- **Conflicting agent observations** — surfaced as an attention-required
  condition (§10), never auto-arbitrated.
- **Provider auto-memory contradicts Redline memory** — cannot happen at
  the canonical layer, because provider memory is never canonical (§14).
- **Overly broad agent permissions** — Agent Identity (§4) is the only
  place permissions are declared; enforcement is a separate layer (§4),
  and the declaration itself is file-stored and versioned, not inferred
  from a conversation.
- **Specialist agent crosses domain boundary** — a record's `domain` field
  (§8) is the declared classification a domain-boundary check validates
  against, not itself the enforcement mechanism; per §4, actual enforcement
  is the separate job of policy/permission resolution and runtime/tool
  boundaries, neither of which AS-1 implements. A candidate outside an
  agent's declared domain fails that check and is not eligible for that
  agent to promote — but nothing in this document makes that check itself
  a technical guarantee.
- **Stale Resume Packet** — `required_fresh_probes` (§11) is mandatory;
  a Packet without it is malformed.
- **Repository HEAD changes during a mission** — handled exactly as this
  mission's own preflight already behaves: re-derive live state, never
  assume; a mismatch against an expected baseline is a stop condition
  (`CLAUDE.md` §3), not something to silently reconcile.
- **Policy changed after Resume Packet generation** — the Packet's policy
  reference (§11) is checked against live policy state at resume time, not
  trusted from generation time.
- **Live system differs from durable desired state** — this is drift by
  definition (§18); detection is deferred, but the concept is nameable, not
  silently ignored.
- **Agent attempts to resume from a historical unauthorized action** — the
  Resume Packet preserves authorization evidence but never grants
  authorization (§11); every mutation boundary still requires its own
  explicit, current authorization.
- **Context compaction drops an unresolved blocker** — `open_blockers`
  (§11) is a mandatory Resume Packet field, sourced from the durable
  checkpoint, never from the discarded transcript.
- **Memory grows until retrieval itself becomes context pollution** — a
  generated, rebuildable index (§16) is the named mitigation; it is never
  itself authoritative.
- **A promotion tool asserts something it cannot truthfully know** — barred
  structurally (§9), reusing the `mcp_stopped`-attestation precedent from
  `docs/BACKUP_RECOVERY_ARCHITECTURE.md` §17.3.

## 22. Initiative decomposition

```text
AS-1  Institutional Memory & Agent Resume Architecture     (this document)
AS-2  Governed Knowledge Registry + Resume V0
AS-3  Agent Identity & Permission Contracts
AS-4  Single Specialist Agent Pilot

LATER      Multi-Agent Orchestration
LATER      Desired-State Observation / Drift Detection
MUCH LATER Governed Reconciliation / Self-Healing
```

The `LATER` and `MUCH LATER` entries are planning boundaries recorded for
context — they are explicitly **not** implementation authorizations, and
naming them here does not pre-approve them. Each later mission (AS-2
onward) requires its own separate, explicit founder authorization, exactly
like every other Redline mission.

## 23. AS-2 acceptance proof (recorded for the next mission, not authorized here)

The smallest valuable next slice, to be validated as a single unit rather
than as two independently "done" pieces:

```text
ONE agent type
ONE approved institutional-memory record
ONE skill
ONE mission checkpoint
ONE Resume Packet
```

Session A: performs a bounded task, proposes candidate knowledge, attaches
evidence, the knowledge passes governed validation/promotion (§7), a
durable checkpoint is recorded, and the session ends.

Session B: starts with **no prior conversation history**, loads durable
Redline state and the Resume Packet, independently re-probes every
`required_fresh_probes` entry (§12), and safely resumes the mission.

**AS-2 is not complete unless that cold resume succeeds.** A knowledge
registry that no Resume Packet has ever successfully been used to resume
from has not actually proven the core hypothesis in §1.

## 24. Non-goals of this document

Explicitly not decided or designed here: any source code; any runtime agent
infrastructure; a memory registry implementation; Resume Packet generation
code; specialist agent definitions; a permission-enforcement implementation;
an orchestrator; a reconciliation/self-heal implementation; a
context-compaction implementation; changes to MCP, Control Room runtime
code, `docs/control_room/PROJECT_STATE.yaml`, or any production system;
Resolve contact of any kind; a visual/UI design for agent or context state.
