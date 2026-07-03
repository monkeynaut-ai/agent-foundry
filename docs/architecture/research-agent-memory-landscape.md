# Research — Agent-Memory Landscape: Is C2's Wedge Unfilled?

> **Status: research finding (mid-2026).** Fact-check of one specific claim made
> while evaluating Candidate 2 (memory) in
> [value-lever-exploration.md](./value-lever-exploration.md) as a stand-alone OSS
> repo. Conducted via a fan-out web sweep (6 angles, 22 sources fetched, 104
> claims extracted, 25 adversarially verified). Evidence is product docs, vendor
> blogs, and repo self-descriptions — **feature-existence claims, not
> runtime-verified behavior.**

## The claim under test

The recommendation was: *"Extract C2, frame it as a governed
memory-delivery/curation controller for containerized agents — explicitly not a
store — so you're competing on the **unfilled wedge**."* The wedge was defined as
one product owning all three of:

- **(a) Push** — provision curated, scope-resolved memory into the agent's *native
  boot-context files* (`CLAUDE.md` / `.claude/`, `AGENTS.md`) at session/container
  start, rather than requiring the agent to *pull* via a query tool.
- **(b) Harvest** — extract candidate memories from the ephemeral workspace before
  discard, forming a self-improving provision+harvest loop.
- **(c) Active curation governance** — quarantine + gated/evaluated promotion,
  contradiction + staleness detection, and *retirement* of stale memory — not
  append-only accretion.

## Verdict: the wedge is **partially filled**, not unfilled

The strong claim ("the field is all pull-via-query stores that accrete; nobody
owns the triad") is **false**. Every individual element is shipped, and one
product nearly owns the whole combination.

### Letta Code is the strongest disconfirmer (a shipping product, all three)

- **Push** — `system/` files auto-loaded into the prompt every turn, no retrieval
  call.
- **Harvest** — sleep-time "dream" subagents distill lessons from recent
  conversations back into memory (`/sleeptime`, every N messages, or on
  compaction).
- **Curation** — a memory-defragmentation flow backs up memory, then launches a
  subagent to split large files, merge duplicates, and restructure the hierarchy;
  plus a `/doctor` audit and a memory subagent for messy/contradictory memory.

Gaps vs. the full wedge: writes into its **own** MemFS markdown (not native
`CLAUDE.md`/`AGENTS.md`); non-`system/` files are pull-loaded; **no documented
active retirement/forgetting.**

Sources: `docs.letta.com/letta-code/memory`, `/letta-code/memfs`,
`/guides/agents/architectures/sleeptime/`.

### Push-at-boot is commodity, not novel

Shipped by multiple products via `SessionStart` hooks or always-in-context blocks:

- **claude-memory-compiler** — `SessionStart` hook emits a knowledge index (≤20k
  chars) as `additionalContext`, no agent query. (`github.com/coleam00/claude-memory-compiler`)
- **claude-mem** — `SessionStart` hook silently injects ~50 recent observations
  before the agent runs. (`github.com/thedotmack/claude-mem`)
- **Letta / MemGPT** — core memory blocks prepended to the prompt, always in
  context. (`docs.letta.com/guides/legacy/memgpt-agents-legacy/`)

### Harvest loops are shipped

claude-memory-compiler (`session-end.py` / `pre-compact.py` spawn a detached
`flush.py` that reads the transcript and lets Claude decide what to save) and
Letta Code (dream subagents) both implement genuine provision+harvest loops.

## Even the fallback gap (native-file push) is contested, not clear

When the sweep retreated to a narrower claim — "okay, but nobody writes into the
agent's *own native* boot files specifically" — the workflow's own raw extracted
claims contradict it. These were dropped from adversarial verification by token
budget, **not refuted**, so confidence is medium (blog/repo self-description):

- **AutoDream** (Claude Code consolidation) — reportedly writes consolidated
  memory into native `~/.claude/` and `CLAUDE.md`.
  (`zenvanriel.com/ai-engineer-blog/claude-code-autodream-memory-consolidation-guide/`)
- **agentmemory** (rohitg00) — `SessionStart` push + writes into a Claude-native
  file. (`github.com/rohitg00/agentmemory`)
- **claude-mem on OpenCode** — injects into `<project>/AGENTS.md`.

Treat native-file projection as **probably already done, pending a first-hand
check** — not a clean wedge.

## The one genuinely uncontested element: active retirement

Removing / hard-archiving stale memory below a freshness threshold is shipped
**nowhere**:

- **Zep** — LLM compares new edges against related existing edges, detects
  contradictions, invalidates by setting `t_invalid` (bi-temporal) — but
  invalidated edges are **retained** for audit, not deleted.
  (`arxiv.org/html/2501.13956v1`)
- **Letta** — `memory_replace` / `memory_rethink` overwrite block content in
  place; dedupe/merge, but no forgetting.
- **mem0 v3** — single-pass **ADD-only** (no UPDATE/DELETE); the new fact lives
  alongside the old, both survive; only MD5 exact-dup dedup. (Caveat: the
  *classic* mem0 algorithm did ADD/UPDATE/DELETE conflict resolution.)
  (`github.com/mem0ai/mem0/issues/4896`, `docs.mem0.ai/migration/oss-v2-to-v3`)

The full curation-governance triad (gated promotion + temporal-decay staleness +
pruning/archiving + reconciliation against an immutable ledger) is fully specified
only in **SSGM (arXiv 2603.11768, May 2026)** — which states it is "a rigorous
theoretical architecture," **not a software implementation**, with no experiments.
So even the curation design C2 would claim as novel already exists in the
literature.

## Pull-via-query stores remain common (the original framing isn't wholly wrong)

Zep (graph search API, `f:S→S` over a text query), Cognee (MCP `search`/`codify`
tools), and ReasoningBank (top-k embedding retrieval) are pull-based — confirming
that *much* of the landscape is pull retrieval. The error was "**all** / **none**,"
not the direction.

## Implications for the C2 recommendation

1. **Drop "unfilled wedge."** That ground is largely occupied, primarily by Letta
   Code. Repositioning: **first to ship the full triad — push + harvest +
   curation — in one product, with the missing piece (active retirement +
   provenance-snoop staleness invalidation) added and eval-gated.** An
   execution/integration wedge, not a novelty wedge.
2. **Letta Code, not GitKB, is the head-to-head.** The value-lever doc's
   competitive section compared against a store; the real competitor stacks
   push+harvest+curation. (Now corrected there.)
3. **The eval-gated promotion tie to C1 is the most differentiated thread** —
   it's the part nobody ships and the part that connects to AF's measurement
   spine.
4. **C2 still survives as the best OSS candidate of the three** on severability
   and audience — but the pitch is "best-integrated + adds retirement," not "owns
   empty space."

## Caveats and decay

- **Fast-moving.** claude-memory-compiler (Apr 2026), claude-mem (Claude Code
  2.1.0), Letta MemFS (2025–26), mem0 v3 (Apr 2026) are all recent; claude-mem
  already lists a beta "Endless Mode (biomimetic memory)" suggesting forgetting is
  coming. "Unfilled" decays in weeks.
- **Not runtime-verified.** All feature claims are from documentation/blogs/repos.
- **One known conflation in the source pool:** consolidation/decay features were
  initially mis-attributed to claude-mem; they belong to yuvalsuede/memory-mcp.
  Secondary summaries conflate products — verify per-tool before relying.

## Open follow-ups before banking on the residual wedge

- First-hand confirm whether AutoDream / agentmemory / claude-mem actually write
  into native `CLAUDE.md`/`AGENTS.md`, or merely inject via hook context.
- Confirm no shipping product does active retirement-by-removal (vs. Zep
  invalidate-but-retain, Letta dedupe/merge).
- Check whether claude-mem "Endless Mode" or Letta's roadmap closes the
  retirement gap.
- Given SSGM specifies the full triad, decide whether C2's defensibility is
  "first to ship" (execution) rather than conceptual novelty — and whether that
  changes the OSS-extraction case.
