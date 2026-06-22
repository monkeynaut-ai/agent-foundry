# Lessons Learned

This document captures repository-wide lessons learned from the full git history of Agent Foundry and Archipelago as of March 17, 2026. A "lesson learned" here means a concrete takeaway from building, operating, or fixing the system that should change how future engineering work is done.

These lessons were derived from the repository's commit history, tests, ADRs, feature specifications, and architecture documents. They are intended to preserve actionable engineering guidance, not just historical observations.

## Full-History Lessons

- Build the platform as small, testable vertical slices with explicit contracts. The initial build was shipped as granular slices for registry, retriever, planner, compiler, observability, and the demo flow, which kept the system moving without large untestable jumps. Evidence: `docs/implemented/agent_foundry_initial_build_instructions.md`, early slice commits from `aff33ee` through `7d4a172`.

- Put behavior and interface contracts in data, not only in Python code. The repository consistently moved toward versioned YAML role/capability specs plus JSON-schema-validated plans and runtime I/O validation. This enabled deterministic loading, validation, discovery, and reuse across systems. Evidence: `docs/business/agent-foundry-advantages.md`, core build commits `aff33ee`, `bfc6f92`, `603e352`, `353a1cb`.

- Determinism is worth investing in early. The earliest phases emphasized typed errors, duplicate detection, stable retrieval ordering, exact-name boosting, and benchmark budgets. Agent infrastructure becomes hard to debug quickly if startup, retrieval, and validation behavior are nondeterministic. Evidence from commit sequence: `abcbe54`, `86d5414`, `077a666`, `16f2ea7`, `6557dc0`, `de8ad3a`, `26a03c0`.

- Quality controls need explicit tests for both enabled and disabled behavior when feature flags are used. The initial build instructions require this, and the repository repeatedly used flags around imports, schema enforcement, and retries/timeouts. Feature flags create two products unless both branches are exercised. Evidence: `docs/implemented/agent_foundry_initial_build_instructions.md`.

- Products should own their system definitions; the framework should own validation and compilation. A major post-build correction removed the WiringPlanner and product-specific goal maps from the framework. When platform code starts embedding product topology, the abstraction boundary is already degrading. Evidence: `docs/implemented/agent_foundry_initial_build_instructions.md`, `docs/architecture/agent-foundry-separation-spec.md`. Related commits: `c953db3`, `b4078c2`.

- Enforce package boundaries mechanically, not socially. The repository established a hard rule that `agent_foundry` must not import product code and then added `import-linter`. This is a direct lesson from shared-monorepo drift. Evidence: `docs/implemented/agent_foundry_initial_build_instructions.md`, `docs/architecture/agent-foundry-separation-spec.md`. Related commits: `b4078c2`, `551bf3c`.

- Dynamic handler resolution is valuable, but only if paired with strong failure reporting and schema enforcement. The repository moved from explicit handler maps toward spec-driven dynamic resolution, then added tests around resolution errors and runtime validation. Indirection only pays off when misconfiguration fails clearly. Evidence: `tests/agent_foundry/test_compiler_dynamic_resolution.py`. Related commits: `6fb50c3`, `94c937b`, `d4e8db8`.

- Behavioral correctness should be the primary acceptance pressure in agentic development loops, but structural pressure must exist outside that loop. The ADR explicitly chooses black-box testing pressure first and requires static analysis, types, linting, and architectural constraints as compensating controls. The repository then added ruff/mypy, switched to pyright, and added boundary linting. Evidence: `docs/architecture/adr_agent_roles_for_test_source_development_loop.md`. Related commits: `a457071`, `45b2a71`, `551bf3c`.

- PTY scraping is an expensive way to integrate with an agent UI. The middle phase shows repeated work on trust prompts, ICRNL, stdin forwarding, ANSI stripping, and retry loops. The later protocol spec explicitly records that headless JSON mode eliminates most of that pain. Prefer structured machine outputs over terminal emulation whenever the external tool supports them. Evidence: `docs/archipelago/adapter_protocol_spec.md`. Related commits: `651fe37`, `b28f4ca`, `9fe58f6`, `266684f`, `3bbc2bd`, `f0918e7`.

- If the orchestrator depends on model-produced protocol markers, those instructions must live in the worker's stable prompt layer. The `ARCHIPELAGO_TASK_COMPLETE` marker only works if the container's `CLAUDE.md` requires it. Protocol-critical LLM behavior belongs in versioned worker instructions, not only in code assumptions. Evidence: `docs/archipelago/adapter_protocol_spec.md`, `src/archipelago/docker/skills/lessons-learned/SKILL.md`.

- Historical experiment logs are useful, but stable decisions need to be promoted into specs, ADRs, and tests. The Docker testing log explicitly marks itself as historical and points to the protocol spec as authoritative. The separate doc-management writeup makes the same argument more generally. Preserve discovery history, but extract durable truth into artifacts that are maintained and referenced. Evidence: `docs/archipelago/docker-testing-log.md`, `docs/future-systems/engineering-doc-management.md`.

- Container security and autonomy require real runtime enforcement, not only configuration objects. The ACP phase added root entrypoint with `gosu`, filesystem lockdown, capability requirements, and later runtime integration tests that verify hidden/read-only directories and user-drop behavior in real containers. Security boundaries need runtime tests at the container boundary. Evidence: `tests/archipelago/integration/test_permissions_enforcement.py`. Related commits: `06983b8`, `5d23fae`, `2e7a91f`, `d1b4a67`.

- Configuration affecting safety must be tested end-to-end from declarative spec to runtime effect. A late bug showed `node.config` was not reaching handler state; the fix was followed by pipeline tests that go from `GraphWiringPlan` config to env vars to actual lockdown behavior. Config propagation bugs are architecture bugs, not just plumbing bugs. Evidence: `tests/agent_foundry/test_compiler_config_injection.py`, `tests/archipelago/integration/test_config_to_lockdown.py`. Related commits: `a7379f5`, `1ba31c4`.

- Reusable orchestration and security plumbing should be extracted once duplication appears. The repository later extracted env builders and `lockdown.sh` out of larger handlers and entrypoints. Repeated boundary logic should be promoted into named units before it becomes a debugging tax. Related commits: `24ffcee`, `4cb43f9`.

- Terminology changes need a decisive migration plus cleanup sweeps. The repository moved from "capability" to "role" vocabulary and then had to clean stale paths and references. Naming migrations should be treated as broad compatibility work, not simple find/replace. Related commits: `7b65e96`, `22453cb`, `a4a3bc8`.

- Test suites need periodic restructuring as architecture matures. The repository moved from a flatter test layout to `unit/` and `integration/` subdirectories, added runtime container tests, and removed low-value tests. Test organization itself is part of system design and should evolve to match the risk model. Related commits: `71c80fd`, `0c0dd8c`, `b160f03`.

## Highest-Signal Meta Lessons

- The repository repeatedly improved when it replaced implicit behavior with explicit contracts.

- The repository repeatedly improved when it moved from human-observed behavior to machine-verifiable runtime tests.

- The repository repeatedly improved when it separated framework concerns from product concerns and enforced that boundary automatically.

- The repository repeatedly improved when exploratory docs were turned into authoritative specs, ADRs, and tests.
