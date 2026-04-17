# Evaluate RNA (Repo-Native Alignment) for Agent Containers

## Context

RNA is an MCP server that provides semantic code search, dependency graph traversal, and LSP enrichment in a single binary. It could improve code analysis quality in agent containers by giving agents `search()` — a single tool that combines tree-sitter parsing, LSP enrichment, embedding-based search, and graph traversal. Currently under evaluation for inclusion in the ACP base image.

## What RNA provides

- **Semantic search**: `search("payment processing")` finds relevant code by meaning, not just text match
- **Graph traversal**: `search(node="<id>", mode="impact")` returns transitive blast radius in one call
- **LSP enrichment**: Internally runs language servers (auto-detects Pyright, rust-analyzer, etc.) to build call graphs and type hierarchies
- **Business context**: `.oh/` directory for outcomes, signals, guardrails, learnings
- **4 MCP tools**: `search()`, `repo_map()`, `outcome_progress()`, `list_roots()`

## Integration plan

### 1. Add RNA binary to base image

In `src/agent_foundry/agents/docker/Dockerfile.base`:

```dockerfile
# Install RNA for semantic code analysis
RUN curl -L https://github.com/open-horizon-labs/repo-native-alignment/releases/download/v0.1.7/repo-native-alignment-linux-x86_64.tar.gz \
    | tar xz -C /home/claude/.local/bin/
```

### 2. Configure as MCP server

In `src/agent_foundry/agents/docker/settings.json`, add:

```json
{
  "mcpServers": {
    "rna": {
      "type": "stdio",
      "command": "repo-native-alignment",
      "args": ["--repo", "/workspace"]
    }
  }
}
```

Or in Claude Code's MCP config file (`.mcp.json`).

### 3. Initial scan at container start

In `src/agent_foundry/agents/docker/entrypoint.sh`, after repo clone and before adapter launch:

```sh
# Index workspace for semantic search (if RNA is installed and workspace has code)
if command -v repo-native-alignment >/dev/null 2>&1 && [ -d /workspace/.git ]; then
  repo-native-alignment scan --full --repo /workspace || true
fi
```

### 4. Verify Pyright interaction

RNA auto-detects language servers on PATH. Since we install Pyright in the base image, RNA should discover and use it for Python LSP enrichment automatically. Need to verify no conflicts with the Claude Code Pyright plugin.

## Open questions to resolve before implementation

1. **Scan time**: How long does initial `scan --full` take on a typical repo (100-500 files)? This adds to container startup latency.
2. **Index persistence**: Does `.oh/.cache/` in the workspace volume persist across container restarts? If yes, subsequent starts skip the full scan.
3. **Pyright conflict**: Does RNA running Pyright internally conflict with the Claude Code Pyright plugin? Both would try to start a Pyright server.
4. **Image size**: 50MB binary is significant. Is it worth it for all containers, or should it be a product overlay choice?
5. **MCP server startup**: Does the MCP server need to be running before Claude Code starts? Or does Claude Code launch it on demand via the stdio config?

## Verification

1. Build base image with RNA binary
2. Start a container with a Python repo workspace
3. Verify `repo-native-alignment scan --full` completes
4. Verify Claude Code sees the RNA MCP tools in its tool list
5. Test `search()` on a known symbol and compare results with Grep
6. Check that Pyright LSP plugin still works alongside RNA

## Decision criteria

- If scan adds <30s to startup: include in base image
- If scan adds >30s: make it a product overlay choice or run in background
- If Pyright conflicts: investigate configuration to avoid double-server
- If image size is a concern: product overlay instead of base
