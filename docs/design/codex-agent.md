# Codex agent refactor

**Date:** 2026-05-17
**Status:** Draft — investigation notes, image-layering decision, concrete change list

## Goal

Agent Foundry currently provides container images that run Claude Code
(`claude`) in headless mode. Add a parallel path that runs OpenAI's
Codex CLI (`codex exec`) in headless mode, selectable per agent at
runtime. Both engines should plug into the same orchestrator turn
loop via the existing `RunTurn` injection seam in
`container_executor.py`, and both should ship inside the same
runtime image.

## Current claude-bound touchpoints

These files and identifiers are where claude-the-CLI is bound to the
platform today. They are the surface area a codex path has to either
parallel or extend.

1. **`src/agent_foundry/agents/docker/Dockerfile.foundry-dev`** —
   installs the `claude` binary and the `pyright-lsp` plugin.
2. **`src/agent_foundry/agents/docker/entrypoint.sh`** — validates
   `CLAUDE_CODE_OAUTH_TOKEN`/`ANTHROPIC_API_KEY`, appends role
   instructions to `/home/agent/.claude/CLAUDE.md`, drops into
   `claude` (or idles for `AGENT_HOST_DRIVEN`).
3. **`src/agent_foundry/agents/docker/settings.foundry-dev.managed.json`**
   — claude managed settings (`extraKnownMarketplaces`,
   `enabledPlugins`).
4. **`src/agent_foundry/orchestration/container_executor.py::_run_claude_turn`**
   (lines 171–296) — hardcoded `claude` invocation:
   `claude -p <prompt> --output-format stream-json --verbose --json-schema <inline-json> --model <m>` plus
   optional `--effort`, `--dangerously-skip-permissions`,
   `--resume <session-id>`. Parses stream-json for the `system/init`
   event (session id) and the assistant `tool_use` block named
   `StructuredOutput` (envelope payload).
5. **`src/agent_foundry/agents/schema_tools.py::to_claude_code_schema`**
   — converts a Pydantic envelope type to claude's JSON Schema dialect.
6. **`src/agent_foundry/primitives/models.py::AgentAction.effort`** —
   maps to claude's `--effort` flag.
7. **`BASE_IMAGE_TAG`** — pinned at the call sites (e.g.
   `archipelago/systems/design_pipeline.py:30`,
   `archipelago/systems/pipeline.py`) to `agent-worker-foundry-dev:latest`.

## Image layering decision

### Four concerns currently smeared across two Dockerfiles

Today's `Dockerfile.base` (→ `agent-worker:latest`) and
`Dockerfile.foundry-dev` (→ `agent-worker-foundry-dev:latest`)
intermix:

1. **OS / platform** — Debian, `claude` user, `gosu`, lockdown
   machinery, `HEALTHCHECK`, `/tmp/.container-ready` marker,
   `AGENT_HOST_DRIVEN` idle mode, role-instructions append skeleton,
   platform skills (lessons-learned), auth-validation framework.
2. **Language tooling** — Python 3.14, uv, pdm, pyright.
3. **Engine** — claude binary, CLAUDE.md, managed-settings, pyright-lsp
   plugin.
4. **Repo** — agent-foundry's own `pyproject.toml`+`pdm.lock`
   wheel-cache prewarm.

### Two-layer model

Agent Foundry provides ONE image, `agent-runtime`. Users (or downstream
products) build a second layer for their language + repo. That's it.

```
agent-runtime                          ← OS, user, gosu, lockdown, healthcheck,
                                         AGENT_HOST_DRIVEN idle, role-injection
                                         skeleton, platform skills,
                                         auth-validation framework,
                                         BOTH claude + codex CLIs + their
                                         settings/config scaffolding
└── agent-runtime-<repo-slug>          ← user-built leaf:
                                         + language toolchain (python/uv/pdm,
                                           or node/pnpm, or rust/cargo, …)
                                         + per-repo dependency prewarm
                                         + per-repo pre-commit hook env cache
                                         + per-repo CLI tools, fixtures,
                                           generated code, etc.
```

### Why one image carries both engines (combine, not split per-engine)

- Both binaries are small (claude ~223 MB native ELF; codex ~222 MB
  npm package + ~119 MB node runtime). The size argument against
  combining is weak.
- Entrypoint stays clean: validate that **at least one** engine's
  creds are present; the orchestrator's per-turn `docker exec`
  dispatches to the chosen CLI. No entrypoint-side branching needed.
- Halves the leaf-image count for users who care about multiple
  engines (no engine × language combinatorial).
- Engine comparison (the whole reason for adding codex) becomes
  frictionless: same image, swap the engine field per agent.
- When to revisit: an engine that bakes in heavy state (model
  weights, plugin trees) or has conflicting system deps. Neither
  applies to claude + codex today.

### Why language tooling lives in the user's leaf, not in `agent-runtime`

- The agent-foundry repo can't predict every consumer's language stack
  (Python 3.13 vs 3.14, pdm vs poetry vs uv, node 20 vs 22, …).
- Pinning a language in `agent-runtime` forces all users to either
  match or override. Pushing language to the leaf lets each user pin
  their own toolchain to whatever their repo actually uses.
- Maintenance: a language layer would require tracking N runtimes
  with their own release cadences and CI builds. A
  `foundry image build` template that produces the leaf is far cheaper
  to maintain than N pinned language images.
- Polyglot: a leaf that legitimately needs Python + Node can install
  both. No need for a "polyglot" image variant.

### Single tradeoff to accept: invocation contract

Today the agent instructions hardcode commands like `pdm test-unit`. If a
user's leaf image installs poetry (or hatch, or uv) instead of pdm,
the leaf has poetry's commands but not `pdm` — so the hardcoded
`pdm test-unit` invocation fails inside that container. Solution:
declare invocation commands in the user's `agent-foundry.toml` spec
(`test = "poetry run pytest"`); the agent instructions look them up
rather than hardcoding. This is a stronger model than the current
hardcoding — the constraint forces good design.

## Cohabitation evidence

Empirically validated on 2026-05-17 with a test image at
`src/agent_foundry/agents/docker_v2/Dockerfile.codex-cohabit-test`
(`FROM agent-worker-foundry-dev:latest` + `npm i -g @openai/codex@0.128.0`):

| Check | Result |
|---|---|
| `claude --version` post-codex-install | ✓ 2.1.143 |
| `codex --version` | ✓ 0.128.0 |
| Both binaries invocable (`--help`) | ✓ |
| Orphan daemons after both invocations | ✓ none |
| PATH collisions | ✓ none — claude at `/home/claude/.local/bin/claude`, codex at `/usr/bin/codex` (paths reflect the v1 image's `claude` Unix user; v2 renames to `agent`) |
| Filesystem collisions | ✓ none — `~/.claude/` and `~/.codex/` disjoint |
| Size hit | +570 MB (1.42 GB → 1.99 GB): claude=223M, codex=222M, node runtime=119M |
| Codex subscription auth via bind-mounted `auth.json` (OPENAI_API_KEY stripped + unset) | ✓ `codex login status` reported "Logged in using ChatGPT"; `codex exec --json` returned a structured response |

Reproducer scripts retained at `src/agent_foundry/agents/docker_v2/`:

- `Dockerfile.codex-cohabit-test` — the test image
- `test-codex-auth-mount.sh` — sanitizes a copy of `~/.codex/auth.json`
  (strips `OPENAI_API_KEY`), bind-mounts it, runs `codex exec` inside
  the container, asserts ChatGPT-subscription auth

Non-fatal findings:

- Docker auto-creates the bind-mount parent (observed as
  `/home/claude/.codex/` under the v1 image) as root, blocking
  codex's config writes when running as the unprivileged agent user.
  **The runtime image MUST pre-create the agent user's `.codex/`
  directory chowned to that user** — confirmed by experiment.
  (V2 image renames the Unix user from `claude` to `agent`; see the
  "Rename Unix user" item in concrete changes.)
- Codex emits a non-fatal warning during exec:
  `codex_core::shell_snapshot: Shell snapshot validation failed: …
  syntax error near unexpected token \`(\``. Doesn't affect agent
  output; cosmetic; chase later.

## Codex CLI surface (verified empirically with `codex-cli 0.128.0`)

| Concern | Claude | Codex |
|---|---|---|
| Headless invocation | `claude -p <prompt>` | `codex exec <prompt> < /dev/null` — **stdin MUST be closed**, else hangs on "Reading additional input from stdin..." |
| JSON streaming | `--output-format stream-json` `--verbose` | `--json` |
| Structured output | `--json-schema <inline-json>` | `--output-schema <FILE>` — schema must be in a file |
| Schema dialect | Permissive | **Strict OpenAI mode**: every object needs `additionalProperties:false`; every property in `required`; `default` rejected in some places |
| Envelope capture | Synthetic `StructuredOutput` `tool_use` block in an assistant message | `-o, --output-last-message <FILE>` writes the structured JSON directly; same content also appears in stream as `item.completed.item.text` |
| Session id | `system/init` event | `thread.started` event with `thread_id` |
| Resume | `--resume <session-id>` | `codex exec resume <thread_id>` |
| Sandbox bypass | `--dangerously-skip-permissions` | `--dangerously-bypass-approvals-and-sandbox` |
| Working directory | `--cwd <DIR>` (via `exec_run` `workdir=`) | `-C, --cd <DIR>` |
| Model | `--model <NAME>` | `-m, --model <NAME>` |
| Reasoning effort | `--effort <level>` | `-c reasoning_effort=<level>` (empirically raises `reasoning_output_tokens`) |
| Auth env | `CLAUDE_CODE_OAUTH_TOKEN` / `ANTHROPIC_API_KEY` | `OPENAI_API_KEY` (API billing) OR mounted `~/.codex/auth.json` (subscription) |
| Settings file | `/etc/claude-code/managed-settings.json` (JSON) | `~/.codex/config.toml` (TOML) |
| Role-instructions file | `~/.claude/CLAUDE.md` | `AGENTS.md` in the working dir |

### Codex stream event types observed

For a trivial prompt:

```
{"type":"thread.started","thread_id":"019e..."}
{"type":"turn.started"}
{"type":"item.completed","item":{"id":"item_0","type":"agent_message","text":"<final text or structured JSON>"}}
{"type":"turn.completed","usage":{"input_tokens":...,"output_tokens":...,"reasoning_output_tokens":...}}
```

Failure path:

```
{"type":"error","message":"<stringified JSON with code/status/message>"}
{"type":"turn.failed","error":{"message":"<same>"}}
```

Multi-turn / tool-using runs will emit more event types (tool
invocations, sandbox decisions). The parser has to be informed by a
real agent run, not a `2+2` smoke test.

## Codex auth (subscription path)

### Why a file rather than just an env var

Claude's `CLAUDE_CODE_OAUTH_TOKEN` is a long-lived bearer token —
fits in an env var. Codex's subscription auth is a true OAuth
refresh-token flow: refresh tokens rotate and have to be persisted.
That's an OpenAI/codex design choice, not something agent-foundry can
flatten. But the user-visible burden is ONE bind mount, nothing more.

### Self-contained design (lives entirely in agent-foundry)

New module `agent_foundry/engines/codex.py`:

```python
import os
from pathlib import Path

CODEX_AUTH_HOST_DEFAULT = "~/.codex/auth.json"
CODEX_AUTH_CONTAINER = "/home/agent/.codex/auth.json"

def codex_auth_volume() -> dict[str, dict[str, str]]:
    """Host-to-container mount for codex subscription auth.
    Empty dict if no auth file exists on the host."""
    host = Path(
        os.environ.get("AGENT_FOUNDRY_CODEX_AUTH_PATH", CODEX_AUTH_HOST_DEFAULT)
    ).expanduser()
    if not host.is_file():
        return {}
    return {str(host): {"bind": CODEX_AUTH_CONTAINER, "mode": "ro"}}
```

Auto-application: when `AgentAction.engine == "codex"`, the container
creator in `registry.py::get_or_create` automatically merges
`codex_auth_volume()` into the container's volumes. Products built on
agent-foundry get codex auth wired up for free; they don't reimplement
proxy/git/codex-auth helpers per product.

### User workflow

1. `codex login` once on the host (creates `~/.codex/auth.json`).
2. Set `engine="codex"` on an agent.

For API-key billing instead of subscription: set `OPENAI_API_KEY` in
the env. Agent-foundry forwards it via the existing env-passthrough
seam. No file needed; the codex_auth_volume() helper returns empty.

### Security

`auth.json` contains a refresh token — treat as a secret. Never bake
it into images, never log its contents. The bind mount keeps it on
the host filesystem; only the running container sees it, and only
read-only.

## Concrete changes to agent-foundry

### 1. Refactor existing image into `agent-runtime`

- Promote today's `Dockerfile.base` and engine-specific bits into a
  single `Dockerfile.agent-runtime` that installs OS + user + gosu +
  lockdown + platform contracts + BOTH claude and codex CLIs + each
  engine's settings/config scaffolding.
- Pre-create `/home/agent/.codex/` chowned to `agent` (required —
  see cohabitation evidence above).
- Drop the foundry-dev wheel-cache prewarm; it belongs in the leaf
  image, not in the runtime.
- Drop the `pyright-lsp` plugin install from runtime (or move it to
  leaf if the user's agent instructions depend on LSP). Open question:
  does codex have a comparable LSP plugin? If not, the agent
  instructions' LSP-first rule needs a fallback for codex agents.

### 1a. Rename Unix user `claude` → `agent`

The non-root user inside the container is currently named `claude`
— a legacy from when the image only ran Claude Code. With the
runtime hosting both engines, an engine-named user is confusing
(`/home/claude/.codex/` for a codex agent reads as a category
error). Rename to a neutral `agent`:

- Dockerfile: `groupadd -g 1000 agent && useradd -u 1000 -g 1000 agent`.
- Home directory: `/home/agent`. All path references migrate.
- Entrypoint: `gosu agent …` everywhere.
- `container_executor.py::_run_claude_turn` and `_run_codex_turn`:
  `gosu agent /home/agent/.local/bin/claude …` and
  `gosu agent codex exec …`.
- Engine-specific config directories sit under the new home:
  `/home/agent/.claude/` and `/home/agent/.codex/`.

Engine-specific file *names* (e.g., `~/.claude/CLAUDE.md` as the
role-instructions target for claude-engine runs) stay engine-named
— those are the engine's own conventions, not the OS user's.
Only the Unix user identity changes.

### 2. Generalize entrypoint — `entrypoint.sh`

Single entrypoint that:
- Validates **at least one** engine's credentials present:
  - Claude path: `CLAUDE_CODE_OAUTH_TOKEN` xor `ANTHROPIC_API_KEY`.
  - Codex path: `OPENAI_API_KEY` set, OR
    `/home/agent/.codex/auth.json` exists (mounted).
- Appends role instructions to the engine-specific target file:
  CLAUDE.md for claude-engine runs, AGENTS.md in workspace for
  codex-engine runs. The target is signalled by an
  `AGENT_FOUNDRY_ENGINE=<claude|codex>` env var set by the
  orchestrator at container creation.
- Preserves: git identity defaults, supplementary GIDs, lockdown,
  `AGENT_HOST_DRIVEN` idle mode, container-ready marker file.

### 3. New turn runner — `_run_codex_turn` in `container_executor.py`

Parallel to `_run_claude_turn`. Same `RunTurn` signature so it can be
injected via the existing seam.

Command shape:

```python
cmd = [
    "sh", "-c",
    "codex exec --json "
    f"--output-schema {schema_path} "
    f"-o {last_msg_path} "
    "--dangerously-bypass-approvals-and-sandbox "
    f"-m {model} "
    + (f"-c reasoning_effort={effort} " if effort else "")
    + (f"-C {cwd} " if cwd else "")
    + ("resume " + resume_session_id + " " if resume_session_id else "")
    + f"{shlex.quote(prompt)} < /dev/null",
]
```

The `sh -c '… < /dev/null'` wrapper is the simplest way to guarantee
stdin closure (codex hangs otherwise). Verified working in the
cohabitation test.

Per-turn artifacts:

- **Schema file:** written to a workspace-mounted location before
  exec; cleaned up after.
- **Last-message file:** read after exec to obtain the envelope JSON.
  Avoids parsing the stream for the structured payload.

Parsing the stream:

- Pull `thread_id` from the first `thread.started` event → record as
  session id.
- Read `last_msg_path` for the envelope JSON.
- If the last event before exit was `turn.failed` or `error`, parse
  the stringified-JSON `error.message` to extract `code`/`status`/
  human message; populate `AgentExecFailedError.api_error_status`
  and `api_error_message`.

### 4. New schema mapper — `to_codex_output_schema` in `schema_tools.py`

Walks the JSON Schema produced from a Pydantic envelope and:

- Sets `additionalProperties: false` on every object.
- Adds every property name into the object's `required` array
  (codex/OpenAI strict mode requires all properties be required —
  optional fields must be expressed as `["string", "null"]` unions).
- Strips `default` values (rejected in strict mode in some positions).
- Iterate as codex/OpenAI returns more strict-mode complaints.

### 5. Engine selection at runtime (not at image-build time)

Add `engine: Literal["claude", "codex"] = "claude"` to `AgentAction`.
In `run_agent_in_container`, dispatch on `agent_action.engine` to
either `_run_claude_turn` or `_run_codex_turn`. The image stays the
same — only the per-turn CLI invocation differs.

When `engine == "codex"`, the registry's container creator merges
`codex_auth_volume()` into extra_volumes automatically (see Codex
auth section).

### 6. New package — `agent_foundry/engines/`

A new top-level package whose modules house per-engine helpers,
keeping engine concerns out of `agents/` (which is image/platform
infrastructure):

- `engines/codex.py` — `codex_auth_volume()`, schema-file writer,
  last-message reader, stream parser. Self-contained; no
  archipelago-side code required.
- `engines/claude.py` — extracted claude-specific helpers (any that
  currently live inline in `orchestration/container_executor.py`
  or elsewhere). The point is symmetry: claude and codex are
  siblings, not "claude is built-in / codex is the bolt-on."

### 7. Retry classifier widening

The existing retry path in `container_executor.py:714` keys on
claude's `api_error_status` and `api_error_message`. For codex,
parse the `turn.failed`/`error` event's stringified JSON, extract
`error.code` (or HTTP `status`), and feed those into the same
classifier. Same set of retryable statuses (`429`, `5xx`) should
apply.

## User-facing image build tool

Users build the leaf `agent-runtime-<repo-slug>` themselves. Provide
a CLI + declarative spec to make this trivial.

### `foundry image build`

```bash
cd /path/to/my-repo
foundry image build
# → builds agent-runtime-my-repo:latest from a templated Dockerfile
```

Under the hood:
1. Picks the base (`agent-runtime:latest`).
2. Detects language from lockfile (`pdm.lock` → python+pdm,
   `pnpm-lock.yaml` → node+pnpm, `Cargo.toml` → rust, etc.).
3. Generates a Dockerfile from a template: language toolchain install
   + dependency prewarm + optional pre-commit hook env cache.
4. Runs `docker build`, returns the tag.

### `agent-foundry.toml` declarative spec

```toml
[image]
language = "python"            # explicit override; auto-detected if omitted
base = "agent-runtime:latest"  # rarely needed
tag = "agent-runtime-my-repo"

[prewarm]
deps = true                    # auto from lockfile
pre-commit-hooks = true        # auto from .pre-commit-config.yaml
native = ["cryptography"]      # extra wheels to prebuild
generated = ["python -m grpc_tools.protoc ..."]

# Invocation contract — what the agent runs for testing, formatting, etc.
# Replaces today's hardcoded `pdm test-unit` in agent instructions.
[commands]
test = "pdm test-unit"
test-all = "pdm test-all"
format = "pdm run ruff format"
type-check = "pdm run pyright"

# Escape hatch: bypass templating entirely.
custom-dockerfile = ".agent-foundry/Dockerfile"
```

### Validation at build time

The CLI sanity-checks that the declared `[commands]` exist in the
built image (`docker run <tag> which pdm` etc.) and refuses to tag a
broken image. Prevents the class of bug where the agent instructions
invoke a command the image doesn't have.

## Open risks / spike before committing

- **Stream completeness.** Real codex agent runs (multi-turn,
  tool-using, sandbox-mediated) will emit event types the
  trivial-prompt sample didn't show. Capture one real run end-to-end
  before finalizing the parser.
- **stdin handling alternative.** If `sh -c '… < /dev/null'` interacts
  badly with anything (signal handling, exit code propagation, prompt
  escaping in long prompts), fall back to the lower-level
  `exec_create(stdin=False)` + `exec_start` path. Wrapper proven
  working in the cohabitation test.
- **Schema transform edge cases.** Discriminated unions, nullable
  fields, nested optional payloads — the
  `additionalProperties:false` + all-required-properties transform
  may need per-case handling. Iterate against codex's actual error
  messages.
- **codex shell-snapshot warning.** Cosmetic but noisy — investigate
  root cause (likely zsh-specific syntax in some inherited shell
  init file).
- **Invocation contract enforcement.** The `agent-foundry.toml`
  `[commands]` block has to be actually consulted by agent instructions
  (or by a small in-agent shim). Without enforcement, the contract
  is documentation, not protection.
- **LSP capability gap.** Claude has the `pyright-lsp` plugin
  (and others). Codex doesn't have an equivalent. If the role
  markdown's LSP-first rule is load-bearing, codex agents need a
  fallback navigation primitive or an accepted capability gap.

## Folder structure during parallel development

V1 (the current claude-only image + orchestration paths) and v2 (the
new agent-runtime + dual-engine orchestration) coexist until v1 is
retired. The v2 work splits into three places, not a single parallel
package — most Python in `agents/` is engine-agnostic and doesn't
need duplication.

**1. `src/agent_foundry/agents/docker_v2/`** — image assets

- `Dockerfile.agent-runtime` (the new combined image)
- Generalized `entrypoint.sh`
- Engine-specific config files (claude managed-settings, codex
  defaults / AGENTS.md template)
- Lives alongside the existing `docker/` until v1 is retired.

**2. `src/agent_foundry/engines/`** — engine helpers (new top-level
package)

- `engines/codex.py`, `engines/claude.py` (see §6 above).
- Engine concerns are orchestration-side Python, not docker assets —
  they belong here rather than under `docker_v2/`.

**3. `src/agent_foundry/orchestration/`** — version-by-call-site, no
parallel package

- `container_executor.py` gains `_run_codex_turn` alongside
  `_run_claude_turn`; dispatch picks based on `AgentAction.engine`.
- `registry.py` accepts the new image tag and auto-mounts
  `codex_auth_volume()` when engine is codex.
- No `orchestration_v2`. Both code paths additive in the same files.

### Switch-over strategy

- `AgentAction.engine` defaults to `"claude"` — existing call sites
  unaffected.
- New runs opt in: `engine="codex"`.
- When the v2 path is proven across all archipelago agent roles, the
  default flips and the v1 docker assets (`agents/docker/`, the old
  image tags) are deleted in one focused commit.

### Why not `agents_v2/`?

Most files in `agents/` (`agent_turn_envelope.py`, `errors.py`,
`lifecycle.py`, `mcp_settings.py`, `schema_tools.py`) are engine- and
image-agnostic and won't change in v2. Cloning the whole package
would duplicate stable code and create drift risk during the
parallel-dev period. The few real Python changes for v2 — UID
constant in `__init__.py` if renaming the Unix user, path strings
in `mcp_settings.py` — are small Edits, applied at switch-over
time.

## Suggested sequencing

1. **Refactor today's `agent-worker-foundry-dev` → `agent-runtime`.**
   Drop the repo-specific prewarm; add codex install; pre-create
   `/home/agent/.codex/`. Keep the existing image in place for
   archipelago's current runs until the leaf-build tooling lands.
2. **Spike: real codex turn against the agent-foundry repo.**
   Use the cohabit-test image. Run a complete designer turn (or
   equivalent) end-to-end. Capture the full stream and inventory
   event types. Output: a known-shape sample for the parser.
3. **Engine-selection seam.** Add the `engine` field on `AgentAction`
   and dispatch in `run_agent_in_container`, with `_run_codex_turn`
   as a stub that raises `NotImplementedError`. No codex needed for
   this; safe refactor.
4. **Codex helpers module.** Implement `agent_foundry/engines/codex.py`
   with `codex_auth_volume()`, schema-file writer, stream parser
   stubs. Wire `codex_auth_volume()` into registry auto-merge.
5. **Schema mapper.** Implement `to_codex_output_schema`. Unit-test
   against the Pydantic envelope types currently used by the
   archipelago agents.
6. **`_run_codex_turn`.** Implement the runner. Smoke-test against
   the simplest agent (designer) before letting it loose on
   implementer or pr_creator.
7. **`foundry image build` CLI + `agent-foundry.toml` schema.**
   Implement the leaf-image builder. Migrate archipelago's image
   from the hand-maintained `agent-worker-foundry-dev` to a
   tool-generated `agent-runtime-archipelago`.
8. **Per-agent engine wiring in archipelago.** Pick one role to run
   on codex first (designer is the lowest-blast-radius choice) and
   compare runs.

## Out of scope for this document

- Whether codex is "better" or "worse" than claude for any given
  agent role. The point of this work is to make the question
  answerable, not to answer it.
- A managed-settings deployment story for codex (config.toml). Use
  defaults until a real settings need surfaces.
- Polyglot leaf images. Single-language is the right default;
  multi-language leafs are user-built on demand.
