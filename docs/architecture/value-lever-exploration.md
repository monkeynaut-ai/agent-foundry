# Agent Foundry: Value-Lever Exploration

> **Status: exploratory.** This is a working document for choosing value levers for Agent
> Foundry It is **not** architecture-of-record.

## Why this document exists

Agent Foundry grew ad hoc and then drifted toward a larger, half-enterprise
shape. Before committing further effort, we are answering a more basic
question: **what are the value levers that justify adopting Agent Foundry**

A strong lever must satisfy all three of these at once:

1. **Differentiation** — the platform offers at least one capability not
   available (or not made first-class) in other tools.
2. **A defensible opinion** — the lever embodies a clear, arguable point of view
   about effective agentic (AI) systems and AI + human collaboration.
3. **A useful demonstration** — a genuinely useful system, built on Agent
   Foundry, that is useful because of the lever.

A guiding distinction runs through every candidate: **enable vs. support.** Any
general framework *enables* almost any pattern — you can build anything. The
lever is something Agent Foundry *supports* as a first-class capability:
scaffolded, guided, the natural way to do it. Differentiation lives in support,
not enablement.

---

## Candidate 1 — Orthogonal, evaluable judgment gates

**One-line:** As AI continues to increase the quantity of output (software, marketing material, legal opinions, etc),
the bottleneck moves to *judgment and review* to ensure quality; Agent Foundry makes the judgment layer fast, parallel,
measurable, and robust, by routing decisions through orthogonal gates with constrained, evaluable I/O.

### The opinion (strong form)

Effective AI + human collaboration depends on the **judgment layer**, not
the generation layer. Generation is becoming abundant; the constraint is
deciding whether generated work is correct and acceptable. The defensible,
against-the-grain stance:

- **You cannot reliably evaluate an open-ended generator.** A design agent or
  implementation agent has complex inputs and complex outputs; eval'ing it
  reduces to noisy, unvalidated LLM-as-judge over a whole artifact.
- **You *can* evaluate a gate.** A review/decision step with structured input
  and low-dimension, low-cardinality output (findings, severities, pass/fail)
  can be measured against ground truth with standard classification metrics (precision/recall/F1).
   > Note 1: to compute these we need (a) the labeled ground truth and (b) a finding-matching rule — when does a reported finding count as "the same" as a gold finding (exact match, or by category/location/severity)? That matching rule is a real design choice, and it's where the "measurable" claim has to be made concrete --> labeled datasets

  > Note 2: by "precise" and "recall", I mean the statistical measures, i.e. TP/TP+FP and TP/TP+FN ... for each case consider whether false positives or false negatives are more costly/dangerous/risky
- Therefore: **architect the system so that consequential judgment is
  concentrated into gate-shaped components**, and make gate quality the
  measurable control surface for overall system quality. This is a *system-design
  principle*, not just an eval tactic — it changes how agentic systems are
  decomposed, not only how they are tested.

This is distinct from the mainstream agent-eval direction, which pours effort
into judging end-to-end trajectories and open-ended outputs.

### The defense of the coverage gap

Eval'ing gates measures the safety net, not the generator — so on its own it
risks "measure the easy thing, ignore the hard thing." The answer:

- **Externalize correctness.** Quality and correctness for a project should be
  *explicit* and backed by structured documents (requirements, issue
  definitions, security guidelines, project standards). Gates evaluate the
  generated artifact against those explicit criteria. This converts the
  unmeasurable question ("is this design good?") into a tractable one ("does it
  satisfy these criteria?"), and relocates the residual human judgment to a
  place a human can own: *are the criteria complete?*
- **Orthogonal review dimensions.** Each reviewer gets its own instructions and
  criteria, kept orthogonal rather than fused into one LLM call that mixes
  objectives in tension. This yields **localized, regression-safe iteration**:
  tweak one dimension's instructions, re-run that dimension's evals, improve it
  without jeopardizing another. This is the empirical loop, scoped to a single
  gate.

### Residual limitations (kept honest)

- **Tacit dimensions survive.** Security and requirements-conformance externalize
  cleanly; "is this the *right* design / will it age well / is it elegant"
  resists explicit criteria. The scheme measures the externalizable dimensions
  and leaves the rest to humans — by design, not by accident.
- **Orthogonality is aspirational.** Real review axes overlap (a security flaw is
  also a correctness flaw). The lever needs a story for interaction/overlap, not
  an assumption of perfect independence.

### What Agent Foundry must *support* (not merely enable)

The differentiation is first-class support for this pattern. Minimal set:

1. **An orthogonal-review construct** — composes N independent reviewers over one
   structured input, each with its own instructions, criteria reference, and
   low-cardinality output schema. (Today this is hand-assembled from
   Conditional / AICall.)
2. **Criteria as typed, referenceable input** bound to gates — the
   requirements/security/standards documents as structured inputs a reviewer
   evaluates against. (This is where the "project documentation / agent memory"
   concern converges: durable structured context is the substrate that makes
   gates measurable.)
3. **Eval suite bound to the gate declaration** — the gate carries its dataset,
   so "run this dimension's evals" is intrinsic, not bolted on.
4. **Per-gate versioning + regression check** — change one dimension, run its
   suite in isolation, confirm no regression: the empirical loop as a
   first-class, one-command operation.

### Demonstration system

A **parallel orthogonal design-review system**: structured design doc in →
several orthogonal review gates (each a focused dimension) → low-cardinality
findings out → evals attached to the gates. Smallest system that exercises the
lever end-to-end, builds on the existing design agent, and generalizes directly
to PR / code review.

**The gates are primarily automated** (with possible human fallback for cases the
automated gate can't decide). Their findings are a **machine-to-machine control
signal**, not human-facing output: the gate decides accept-or-reject, and **on
rejection it feeds the findings back to the generating agent**, which uses them
to improve its output on the next attempt. Humans are largely *outside* this
inner loop — easing the cognitive load on the humans who remain at the
boundaries is a separate concern (see Candidate 3), not this candidate.

### Platform-identity sub-decision

Proposed: **general core + one differentiated layer.** Keep the mature
construct/compiler core general; make the evaluable-gate layer the sharp,
first-class thing on top.

### What this lets us cut

The enterprise-morph (durability, System/multi-tenant layer) does not serve this
lever. Demo #1 is a bounded, in-process run. Memory/docs enter only as
structured *criteria input* (capability #2), not as a separate subsystem.

### Open questions

- Is design-review substantial enough to read as a *system*, or only as a thin
  wrapper? (Working answer: the weight is in the evals-on-gates discipline and
  the orthogonality, not the reviews themselves — without those it *is* a
  wrapper.)
- What is the interaction/overlap model when review dimensions are not truly
  orthogonal?
- How are the externalized criteria documents authored, versioned, and kept in
  sync with what the gates actually check?

---

## Candidate 2 — Agent memory as a platform-governed control plane

**One-line:** AF controls the agent's execution substrate (ephemeral container +
volume), so it can govern how every agent *acquires* and *contributes to* a
canonical, scoped, accountable memory store — something application-layer memory
tools (mem0, Zep, LangMem, RAG) cannot do because they don't own the substrate.

### The problems being solved

Today's agent memory (Claude Code, Codex, etc.) is broken in specific ways:

1. memories go stale
2. memories bind to a local folder rather than a project
3. agents neglect to check memory
4. memory isn't easily audited, understood, or eval'd
5. domain knowledge gets trapped in one project even when several projects share the domain
6. memory is agent-specific rather than shared
7. memory is opaque and hard to keep accountable

"Memory" here is broad: file memories, RAG, graph RAG, MCP-mediated stores.

### The opinion

*Memory should be a curated, scoped, accountable asset that the platform governs
and delivers through the agent's own substrate — not an opaque file an agent
writes and forgets.* Compete on **scope, freshness, and accountability**, not on
storage/retrieval mechanism (the crowded axis). Treat storage as pluggable.

### The differentiation: AF owns the substrate

AF agents run in containers on **fresh, ephemeral volumes with no memory files**.
That is the lever nobody else has: AF can load the volume with up-to-date,
curated, cleansed memory and place it where each agent type natively expects it
(`CLAUDE.md` / `.claude/` for Claude Code, `AGENTS.md` for Codex, …), so the
agent uses its *normal* memory-reading behavior on *AF-curated content*. This
directly attacks problems 1, 2, 3, 5, 6.

### The model: AF as the memory controller of a tiered hierarchy

The operating model borrows the **computer memory hierarchy** (cache → RAM →
disk): memory lives in tiers that trade immediacy against capacity and freshness,
and AF is the **controller** that moves memory between them. The three delivery
channels are this controller's operations, not a flat list.

Tiers:
- **Fast tier (context window)** — what the agent can attend to *now*. Scarce —
  but scarce for an inverted reason: the binding constraint is **attention, not
  latency**. Overfilling it degrades reasoning ("lost in the middle") and costs
  tokens. So the controller optimizes **signal-to-noise for the current task, not
  capacity** — the opposite of a hardware cache, where bigger is strictly better.
  This is where lossy compaction (a documented Claude Code pain) goes wrong:
  naive eviction instead of relevance-based eviction.
- **Addressable store** — memory fetched on demand by a known handle.
- **Cold canonical store** — the full, curated store; searched/retrieved;
  storage pluggable (RAG/graph/MCP) underneath.

Controller operations (the channels):
- **Provision = cache fill.** At boot, AF promotes the scope-correct,
  agent-adapted working set into the container's native locations
  (`CLAUDE.md`/`.claude/`, `AGENTS.md`, …). The push channel; defeats problem 3
  by construction (the agent reads memory through its *normal* behavior, on
  AF-curated content). Promotion is **relevance-based eviction/selection**, not a
  capacity dump.
- **Pull = fetch.** A first-class, **logged** retrieval tool/skill/MCP for
  emergent, mid-loop needs — addressable or associative against the same
  canonical store. Accountable and scope-aware, not a better retriever.
  Complementary to provision, **not** secondary.
- **Harvest = write-back.** AF captures candidate memories from the ephemeral
  volume before discard, feeding curation. Write timing is a policy choice:
  **write-through** (flush immediately — safe, slower) vs. **write-back** (buffer
  and flush later — faster, risks loss on crash). **Provision + harvest form the
  self-improving loop** — that pairing is the power.

Two axes govern what a memory is and how long it lives:
- **Scope** (who may see it): role · project · domain · org.
- **Lifetime** (when it is reclaimed): *task-scoped* memory auto-evicted when a
  sub-task ends (stack-like) vs. *durable* memory explicitly promoted and retained
  (heap-like).

### Curation is the value, not a risk

Staleness and contradiction handling are the *reason this exists*, not objections
to it — curation is the staleness/contradiction solver that other approaches
skip. Curation decides, per candidate: new / fold / split / supersede / assign
scope (role·project·domain·org) / retire.

Curation is **pluggable policy**, offered two ways that co-exist:
1. **Swappable declarative constructs** AF ships and users extend (in-graph).
2. **Systems/processes built on AF** (out-of-band services).

Both write to the same store through the same interface — enabling
experimentation and swapping of curation strategy without touching delivery.

### Detection (the hard half of curation)

- **Contradiction** is intra-store and tractable — compare competing claims at
  promotion.
- **Staleness is a cache-coherence problem** — the auto-memory analysis named it
  exactly: *"a cache with no invalidation strategy."* A memory rots because the
  *world* changed, not because another memory disagrees, so invalidation needs a
  **trigger**. Working stance: bind every memory to **verifiable provenance** (the
  source it was derived from) so the controller can *snoop the source* — re-verify
  and invalidate/demote when it changes; layer recency/TTL and usage signals
  (never-retrieved → demote) on top. The residual: preference-drift staleness
  ("wrong-for-now") has no source to snoop and stays human-owned.
- **Promotion control:** harvested candidates are **quarantined, not
  auto-promoted**; promotion passes a gated, evaluable checkpoint (structurally
  candidate 1's gate pattern). Open tension: autonomous promotion (fast, risky,
  fully unattended) vs. gated promotion (accountable, safer, partially
  reintroduces a human/control point).

### Platform vs. policy split (the architecturally significant requirement)

- **Platform (AF) — the mechanism:** one storage-agnostic **store interface**;
  per-invocation **scope + lifetime resolution**; **relevance-based provisioning**
  (cache fill) into agent-adapted native files (with sidecar metadata kept
  separate); a **logged pull** tool (fetch); a **harvest seam** (write-back); and
  the **coherence/invalidation** machinery (provenance snoop, TTL, usage).
- **Policy (pluggable) — the engine:** curation (staleness, contradiction,
  scoping, freshness) as AF constructs *or* external systems.
- **Uniform-seam requirement:** every curation producer and the delivery path use
  the *same* store interface, or the store fragments.

### Demonstration system

A memory curation/management system built on AF: ingests candidate memories
(harvested + human-authored + imported), processes them (create / fold / split /
route / scope / retire), and maintains the canonical store that AF provisions
from. The differentiation rides on this demo (as with candidate 1).

### What this lets us cut

Nothing in the enterprise-morph is required. Storage stays pluggable (no bespoke
vector DB). Emergent-retrieval quality competition is explicitly *not* entered.

### Boundary / limitation (own it)

The lever's strength — substrate control — is also its boundary: agents **not**
run through AF get none of it. "AF memory" is a property of AF's execution model,
not a portable standalone memory product. Acceptable, but stated.

### Prior art / competitive check — GitKB and Letta Code

*Source caveat: built from GitKB marketing snippets and adjacent projects, not
deep docs (the site 403'd); internals below are inferred and unverified. The
Letta Code / landscape paragraphs below are corrected against a mid-2026 research
sweep — see [research-agent-memory-landscape.md](./research-agent-memory-landscape.md).*

**What GitKB is:** a git-like distributed knowledge-graph protocol — commit /
checkout / push mental model, sparse sync, an OWL semantic graph, millisecond
full-text search — local-first and OSS, with **code intelligence** (call graphs
across 17 languages, blast-radius, dead-code) as its standout. See
https://gitkb.com/ , the [distributed-KB-protocol talk](https://austin.aitinkerers.org/talks/rsvp_midMkpylNrs),
and adjacent [DiffMem](https://github.com/Growth-Kinetics/DiffMem) /
[Lore](https://arxiv.org/pdf/2603.15566).

**The layer framing (load-bearing):** GitKB is a *store + retrieval + versioning*
layer — the thing an agent **queries**. C2 is a *delivery + governance
control-plane* that owns the agent's **substrate**. C2 already declared storage
pluggable and declined to compete there — so **GitKB is a candidate backing store
for C2, not a competitor at C2's layer.** They stack.

**Where GitKB leads / C2 lags:** it *ships* (OSS, zero-config) while C2 is a
concept; a **code-intelligence moat** C2 has no answer to; mature per-document
versioning/audit; built distributed sync/sharing; fast queryable retrieval.

**Where C2 leads / GitKB lags:** **push** — C2 provisions into the agent's native
boot context because it owns the substrate, defeating "the agent must remember to
pull" (problem 3); GitKB is pull-via-MCP. **Curation governance** — GitKB's "never
forget, just fade" *accretes everything* (the accumulation/staleness weakness C2
attacks with quarantine + gated promotion + retire). Agent-agnostic native
projection. Eval-tied promotion (binds to C1's gates).

**Strategic implication:** storage / retrieval / versioning / code-intelligence is
**conceded ground** — C2 should **integrate a GitKB-like store, not rebuild it**.
C2's defensible wedge narrows to **governed delivery**: substrate push + active
curation + eval-tied promotion. State C2 as "a better-governed *delivery*," not "a
better *store*."

### Competitive check — Letta Code (the real head-to-head)

GitKB is the wrong primary comparison: it's a store, and C2 already concedes the
store layer. The product that actually contests C2's wedge is **Letta Code**,
which stacks all three of C2's controller operations in one shipping tool:

- **Push** — files under `system/` are auto-loaded into the prompt every turn, no
  retrieval call. (So is Letta/MemGPT core memory generally; so are Claude Code
  `SessionStart`-hook tools like claude-mem and claude-memory-compiler.) **Push
  at boot is not novel** — it is shipped by several products.
- **Harvest** — sleep-time "dream" subagents review recent conversations and
  write distilled lessons back into memory. A genuine provision+harvest loop.
- **Active curation** — a memory-defragmentation flow backs up, then splits large
  files, merges duplicates, and restructures the hierarchy; plus a `/doctor`
  audit and a memory subagent for contradictory entries.

This forces a correction to the "Where C2 leads" framing above: **substrate push
+ active curation is largely occupied, not empty.** The competitive picture by
sub-claim:

- **Push into the agent's *own native* boot files** (`CLAUDE.md`/`.claude/`/
  `AGENTS.md`) specifically — *contested, not confirmed-clear.* Letta uses its own
  MemFS markdown, not native files. But blog/repo evidence (AutoDream, rohitg00's
  agentmemory, claude-mem on OpenCode) indicates tools that *do* write into native
  files; these were not adversarially verified, so treat native-file projection as
  **probably already done, pending first-hand check** — not a clean wedge.
- **Active *retirement*** (removing / hard-archiving stale memory below a freshness
  threshold) — *the one element shipped nowhere.* Zep invalidates-but-retains;
  Letta dedupes/merges but does not forget; mem0 v3 is ADD-only. The full
  curation-governance triad (gated promotion + staleness detection + retirement)
  is fully specified only in **SSGM (arXiv 2603.11768), a paper with no
  implementation.**

**Revised wedge statement.** Drop "owns empty space." C2's honest position is
**first to ship the full triad — push + harvest + curation — in one product, with
the missing piece (active retirement + provenance-snoop staleness invalidation)
added and eval-gated.** That is an execution/integration wedge against Letta Code,
not a novelty wedge. Weaker moat, but defensible and true.

### Open questions

- Is a memory even *allowed* into the store without a verifiable source it can
  later be checked against?
- Where does the staleness signal come from in practice — provenance
  re-verification, usage/recency, agent-reported-on-use, or a mix?
- How is pushed (provisioned) memory's *use* tracked, given it arrives as native
  context rather than a logged call? (Provision provenance vs. pull logs.)
- Does the differentiation ride on **provision**, **the provision+harvest loop**,
  or **accountability** — and is that enough to read as a *system* rather than
  plumbing?
- **Verify GitKB's session auto-load before leaning on the push advantage:** if
  GitKB (or similar) already auto-loads prior context at session start, C2's push
  edge narrows. And decide whether C2 names GitKB/DiffMem as a reference *backing
  store* (integrate) vs. treats them purely as prior art.

---

## Candidate 3 — The AI→human information channel as a measurable middleware chain

**One-line:** As AI generates information at machine throughput, the human who
remains at the boundary (approval, escalation, decision) is overwhelmed; AF makes
the AI→human channel a **typed, pluggable, measurable middleware chain** that
shapes *how much*, *how trustworthy*, and *in what form* information reaches the
human — with domain-specific stages supplied by third parties / customers / a
marketplace.

### Relationship to Candidate 1

Distinct and complementary. **C1 removes items from the human's queue** (automate
gate-shaped judgment; machine-to-machine routing). **C3 lowers the cognitive cost
of the items that remain.** Fewer items (C1) vs. cheaper items (C3).

### The problem (cross-domain)

Agents emit findings/claims faster than humans can absorb them, in every domain:
software review, legal/contract review, financial analysis, clinical decision
support, security triage, research synthesis, due diligence. The critical signal
gets buried in undifferentiated volume.

### The opinion

*Human-facing information is a designed artifact, not a byproduct.* The platform
should own the human-interaction boundary (AF already has it: `GateAction` +
the responder protocol) and deliberately shape what crosses it — competing on
**quantity, quality, and modality**, not on raw generation.

### The unifying abstraction: a middleware chain

The AI→human flow resembles an HTTP request passing through ordered middleware.
The three levers become **stages** of one pipeline rather than separate features:

```
enrich (provenance/confidence) → score (importance) → filter/truncate (quantity)
  → transform/render (modality) → observe/measure (blindness guard)
```

Each stage is a pluggable component. The decision logic inside a stage —
especially modality (*what to render visually and how*) — is **domain-dependent,
hard to implement, and hard to eval**, so it must be a separate, swappable
component (third-party, customer-implemented, marketplace). That pluggability is
where the latent value concentrates.

### Seed stage taxonomy (the earlier "four ideas," reorganized)

Exploration produced four cross-domain capabilities; under the middleware framing
they are not competing options — they are the **canonical built-in stages** AF
ships, extended by marketplace stages:

- **`enrich`** — verifiable provenance + calibrated confidence per item (quality).
- **`score`** — importance ranking.
- **`filter/truncate`** — top-N / threshold to a human attention budget (quantity);
  also where "escalate only disagreement" lives.
- **`render/transform`** — task-fit representation (modality); see reach note below.
- **`observe/measure`** — the convenient-blindness guard.

### The load-bearing boundary: the chain shapes, it does not generate

The chain transforms a payload it is **given**; it neither generates findings nor
invents their provenance. Two consequences that define what C3 is and isn't:

- **Consensus/disagreement splits.** Running N diverse reviewers is *upstream*
  (agentic process / Candidate 1 territory). Only "escalate just the contested
  items to the human" is a chain stage (a `filter`).
- **Quality is partly an upstream contract.** Provenance must be carried *from
  generation* — a downstream stage can calibrate or re-rank confidence but cannot
  fabricate provenance it wasn't given. Therefore the **payload schema must
  require provenance fields, populated upstream**; `enrich` refines, it doesn't
  invent.

### The convenient-blindness risk (and why this is safe)

Every stage compresses or filters, so all share one failure mode: the dropped
item was the one that mattered (Goodhart). What makes the chain defensible rather
than a fancy summarizer is the **`measure` stage** — evaluating whether
prioritization/consensus/compression *lost a critical signal*, against labeled
data or downstream outcomes. **C3 therefore depends on Candidate 1's measurement
spine**, not by coincidence but by necessity. AF's **accumulated-state** model
helps: state grows within a subgraph, so stages can *annotate what they removed*
rather than silently erasing it — loss-retention partly comes for free.

### What Agent Foundry must provide (and how little is new)

The "well-typed payload every stage reads/writes" is **not a new requirement** —
it is exactly AF's existing construct boundary (`Construct[I, O]`, scope-in /
scope-out validation, registry dispatch). A stage is a transform construct; the
chain is a `Sequence` over a shared payload type. So:

- **Platform (mostly existing):** typed boundaries + registries + accumulated
  state already supply the chain. Genuinely new and additive: a **defined payload
  model** for human-facing information (items + provenance + confidence +
  importance + per-stage transform audit), binding the chain to the
  gate/responder boundary, and packaging stages for a marketplace.
- **Policy (pluggable):** the stages themselves — built-in seed set plus
  third-party / customer / marketplace components.

This makes C3 **high-leverage and low platform-cost**: the differentiation is the
*concept* (a measurable, pluggable human-boundary pipeline) and the *ecosystem*,
not new infrastructure.

### Modality reach (N3 softened)

Selecting and producing the right representation is domain-dependent and hard to
eval, so it lives in pluggable `render` stages. Whether AF stops at emitting a
renderable spec or owns actual rendering is **decided by where the value lives**,
not by a blanket non-goal — N3 has been softened accordingly. Open: does the
comprehension value live in the representation choice or the rendered experience?

### Demonstration system

A human-in-the-loop review surface (design or PR/code review) where findings pass
through an AF middleware chain — enriched with provenance, scored, truncated to a
budget, rendered task-fit, and measured for information loss — instead of a raw
diff + agent dump. Generalizes across the cross-domain list above by swapping
domain-specific stages.

### What this lets us cut

Nothing in the enterprise-morph is required. The chain rides existing construct
machinery, so little new platform surface is added.

### Open questions

- Single universal payload schema, or a small set of typed payload kinds
  (findings vs. decisions vs. narratives)?
- Bidirectional chain (outbound shaping + inbound decision capture via the
  responder) or two chains? *(design decision — deferred)*
- Canonical stage ordering / dependency declaration. *(deferred — noted for
  future)*
- Modality value: representation choice vs. rendered experience.
- How is the `measure` stage's ground truth obtained per domain (labeled sets vs.
  downstream outcome signals)?

---

## Comparison & decision

### Dependency map

The candidates are not side-by-side options; they share one through-line —
**measurement of low-cardinality decisions** — and lean on each other:

- **C3 → C1 (strong):** every C3 stage compresses/filters, so its
  convenient-blindness guard is a `measure` stage that needs C1's measurement.
  C3 is not credible without C1.
- **C1 → C2 (medium):** C1's coverage-gap defense rests on *externalized
  correctness criteria* as typed input — exactly C2's curated-knowledge domain.
  Hand-authored criteria suffice for a v1; C2 makes them first-class.
- **C2 → C1 (medium, reciprocal):** C2's promotion governance *is* C1's gate
  pattern; its eval-tied promotion binds to C1's gates.
- **C2 ↔ C3 (weak):** same *pattern* (shaped delivery over an AF-owned boundary —
  substrate vs. human), no operational dependency.

**Shape:** C1 is the **keystone** (lowest inbound dependency; both others rely on
its mechanism). C2 and C3 are **applications of the C1 spine to two boundaries** —
C2 the agent-memory boundary, C3 the human-information boundary.

### Comparative ranking (per axis; no false-precision scores)

- **Differentiation (post competitive-check):** C1 > C3 > C2. C1's "evaluate the
  gate, not the generator" is not occupied by the eval incumbents; C3's
  application is non-obvious; C2 is narrowed by GitKB-class tools (storage /
  versioning / retrieval already shipped).
- **Defensible opinion:** C1 > C3 ≈ C2. C1 is the most against-the-grain.
- **Useful demonstration:** C1 > C2 > C3. C1's demo is the smallest real thing and
  rides an existing subsystem; C3's is the fuzziest (drifts toward rendering).
- **Problem validation:** C2 > C1 > C3. C2 owns the best-evidenced pain (E1 +
  P1–P3); C3's problem is least agent-novel.
- **Platform leverage:** C3 > C1 > C2. C3 is nearly free (stages = constructs,
  chain = Sequence); C2 is the heaviest build.
- **Non-obviousness / durability of the differentiation:** C1 > C3 > C2. C2 sits
  in a crowded, fast-moving space.

### Adversarial check on the front-runner (C1)

C1 leads on differentiation, opinion, demo, and durability, and is the keystone.
Hardest shots, and whether it survives:
1. *"Design-review is a thin wrapper."* — Survives **only if** the built thing is
   the per-gate eval suites + orthogonality + externalized criteria + regression
   loop. Ship bare parallel reviews and the shot lands.
2. *"Eval-the-gate is just unit testing."* — Survives **only in the strong form**
   (a decomposition *principle*: architect judgment into evaluable gates).
3. *"You measure the safety net, not the generator."* — Partially survives via
   externalized criteria; tacit dimensions stay an owned human residual.
4. *"Assumes the project has explicit correctness."* — Real limit where
   correctness is tacit; not fatal (externalizable dimensions still get measured).

C1 survives **in its strong form**, with stated residuals.

### Decision

- **Spine = C1** (measurable judgment gates). Implement the platform support for
  evaluable gates first; it unlocks the measurement substrate C2 and C3 consume.
- **C1 and C3 demos built in parallel.** They **compose via a shared payload**:
  C1's gates emit low-cardinality **findings** (machine-to-machine, fed back to
  the generating agent); C3's middleware chain *shapes findings* for the human
  boundary. So the first concrete task is to **define the findings payload
  schema** — the contract both demos build on (and the same typed payload the C3
  chain requires).
  - **C1 demo:** make Archipelago's existing design-review subsystem
    (`agents/design_review/`, `actions/aggregate_design_verdict.py`) *measurable* —
    add per-gate eval suites + the per-gate regression loop. Generalizes to
    PR/code review by swapping input and dimensions.
  - **C3 demo:** a middleware chain over those findings at the human boundary
    (enrich → score → filter/truncate → render → measure), with stages pluggable.
- **C2 deferred**, with a near-term supporting role: its curated-knowledge idea is
  where C1's externalized criteria live, so C2 can *feed* C1 (criteria supplier)
  without being built as a standalone lever. Storage/retrieval is conceded to
  GitKB-class tools; if C2 is later built, it integrates such a store rather than
  rebuilding it.

### Open follow-ups

- Confirm the `design_review` module's current shape before scoping the C1 demo.
- Define the findings payload schema (shared C1/C3 contract) as task one.
- The externalizable-correctness limit (adversarial check #4) bounds where the
  C1 demo's measurability claim holds — pick demo dimensions accordingly.

---

## Appendix A — External pain research (mid-2026)

The candidates above were generated primarily from first-person friction
(Archipelago + daily agent use), which is a small slice of the possible pain. A
web sweep across four external source categories (incumbent-tool complaints,
cross-domain practitioner reports, research literature, and funded-startup /
enterprise-failure signal) was run to validate generality. The two
highest-ranked, most-corroborated, most cross-domain pains are below.

A key finding: the top external pains **converge with the candidates** —
E1 ↔ Candidate 2 (memory), E2 ↔ Candidates 1 + 3 (measurable judgment + shaped
human channel). The candidates are not invented; they are the field's
highest-ranked structural pains.

### E1 — Statelessness / no durable cross-session memory

Agents forget across sessions; context, decisions, and conventions evaporate, and
lossy compaction discards work mid-task. Corroborated across incumbent-tool
complaints, a funded market, and enterprise pilot-failure analysis; structural to
how LLMs work; fully cross-domain. **Maps to Candidate 2.**

Sources:
- Claude Code auto-compact discarding state — https://github.com/anthropics/claude-code/issues/34556 *(sweep, unverified)*
- Cursor "Urgently Needs Memory" — https://github.com/cursor/cursor/issues/2604 *(sweep, unverified)*
- mem0 $24M Series A "memory layer for AI agents" — https://www.prnewswire.com/news-releases/mem0-raises-24m-series-a-to-build-memory-layer-for-ai-agents-302597157.html *(sweep, unverified)*
- MIT NANDA, "The GenAI Divide: State of AI in Business 2025" — https://fortune.com/2025/08/18/mit-report-95-percent-generative-ai-pilots-at-companies-failing-cfo/ and report PDF https://mlq.ai/media/quarterly_decks/v0.1_State_of_AI_in_Business_2025_Report.pdf *(**verified**)*
  - Framing note: the headline is **95% of pilots fail to deliver a financial return** (not "95% fail" generically). The named "learning gap" is **broader than memory** — "tools that don't learn, integrate poorly, or match workflows." Cite for E1 as one of three named factors, not a pure-memory finding.

### E2 — The verification tax

Plausible-but-wrong output without native provenance forces humans to re-verify
everything — often costing more than doing the work — and the standard fix (a
human approval gate) degrades into rubber-stamping under throughput pressure. The
most rigorously measured pain in the literature; fully cross-domain. **Maps to
Candidates 1 + 3.**

Sources:
- METR RCT — experienced OSS devs **19% slower** with AI, while predicting +24% and believing +20% — https://metr.org/blog/2025-07-10-early-2025-ai-experienced-os-dev-study/ *(**verified**)*
  - Scope note: small N (16 devs), familiar codebases, mid-2025 models (Cursor + Claude 3.5/3.7). Rigorous but narrow — do not generalize to all AI coding.
- Stanford RegLab — legal AI hallucinates **>17%** (Lexis+, Ask Practical Law) to **>34%** (Westlaw); users "must verify each and every proposition and citation… undercutting the stated efficiency gains" — https://hai.stanford.edu/news/ai-trial-legal-models-hallucinate-1-out-6-or-more-benchmarking-queries *(**verified**)*
- Damien Charlotin — tracked court-case tally of AI-hallucination incidents (~1,600 across 35 countries) — https://www.damiencharlotin.com/hallucinations/ *(sweep, unverified)*
- PRISMA review — trust-calibration feedback "did not help"; complex explanations *increased* overreliance — https://link.springer.com/article/10.1007/s00146-025-02422-7 *(sweep, unverified)*
- Clinical automation bias — high trust → physicians accepted 26% of AI misdiagnoses — https://www.sciencedirect.com/science/article/pii/S0747563224002206 *(sweep, unverified)*
- "Compliance theatre" / rubber-stamping after long similar runs — https://link.springer.com/article/10.1007/s43681-026-01147-7 *(sweep, unverified)*

---

## Appendix B — Internal pain evidence (Archipelago)

First-person/internal source: a friction audit of the Archipelago repo
(`docs/`, `runs/`, postmortems, lessons-learned, real run artifacts). This is the
highest-fidelity source — observed failures and costs from a real autonomous-SWE
system built on Agent Foundry.

**Headline finding: triple convergence.** The internal pains map onto the *same*
candidates derived from first-person intuition and external research. Archipelago's
own vision doc independently names two of them: *"humans are the bottleneck,
especially reviews… provide sequence and component diagrams. Visual information
carries a lot more"* (C3, including modality) and *"minimize document and
knowledge pain… after each PR merge, purge + merge + clean documentation"* (C2).
First-person + internal + external all point at the same four levers.

### Ranked internal pains (evidence → candidate)

- **P1 — No per-invocation context; agents repeat completed work.** MCP postmortem:
  all 12 tester invocations got the identical prompt, fell back to `CLAUDE.md`, and
  worked on change set 1 every time. Run lasted **4h21m, ~$1.92, delivered 1 of 4
  change sets** — and every agent reported success. → **C2 (provision) + C1
  (verification).** The flagship failure; sits exactly at the C1∩C2 intersection.
- **P2 — Memory staleness, no invalidation.** Auto-memory analysis: *"memory in
  agents is closer to a cache with no invalidation strategy than to a database."*
  Plus index drift (on disk, not in index → invisible), "better-keyworded fact
  wins, not the truer one," no confidence decay. → **C2.** Its tiered
  "auto-maintain" proposal (mechanical linter → heuristic scan → judgment agent)
  *is* C2's curation policy.
- **P3 — Hard-won knowledge never reaches the agents.** Three-runs analysis: the
  tester rediscovers `pdm run pytest` by trial-and-error (3–4 retries) *every run*;
  the documented fix *"was not being injected into the tdd_planner's prompt, so the
  same mistake repeats."* → **C2 harvest+provision loop.**
- **P4 — Vacuous success / reports describe intent, not state.** Empty `{}` outputs
  read as success; *"subagents author reports from memory of intent, not fresh
  observation"*; false-green propagates to the next task. → **C1 (objective
  completion/handoff gates).** The verification tax (E2) inside Archipelago.
- **P5 — Agents hang / can't be cleanly recovered.** Stuck-implementer: a monitor
  polled for a commit string the agent never emitted, *"spun in a sleep 5 cycle
  indefinitely"*, unblocked only by manually injecting the string into the
  container. The 2026-06-02 run **crashed at $2.14** on role-confusion with **no
  auto-recovery/re-route**. → **table-stakes containment** (architecture §2.8);
  the semantic role-boundary slice → C1.
- **P6 — Human responder bottleneck.** Waste analysis: responder waits of
  **9–28 min** per clarification, 1–6 per run; *12 separate identical clarifications*
  filed because *"no one connected the repetition to a structural problem."*
  → **C3 (human bottleneck; dedup/quantity).**
- **P7 — Rework loops & turn-spin; no convergence criteria.** ~**128 turns for a
  2-field rename**; tester×implementer **3–5 iterations** each; runs **50–250 min**
  vs. ~6–7 expected invocations. → **table-stakes** budget/convergence control
  (architecture §2.8); detection of vacuous/non-converging work → C1.

### What the internal audit establishes

- **C2 is the most-validated lever** (P1, P2, P3 + a dedicated body of memory
  analysis in `runs/`). The substrate/harvest framing is confirmed by real
  failures and already has a proposed curation design.
- **C1 is validated by the most expensive failure** (P1/P4 — vacuous success, money
  burned, feature lost). The missing piece is objective accept/reject at the handoff.
- **Containment/recovery pains are real but route to table-stakes** (P5, P7, the
  role-confusion crash). Considered as a lever and dropped — non-novel problem,
  mechanical solution; retained as required infra in architecture §2.8, with the
  semantic-policy slice absorbed by C1.
- **C3 is validated** (P6) and independently named in the vision doc.
- **The levers interlock, not compete:** the flagship failure (P1) required *both*
  C2 (deliver per-invocation context) *and* C1 (verify completion before advancing).
  Neither alone would have caught it.
