# Agent Foundry

A platform for defining, running, and managing agent systems.

## Authentication

ACP containers require exactly one of these environment variables:

**Option 1: OAuth token (Claude Pro/Max subscription)**
```bash
claude setup-token          # generates a long-lived token
export CLAUDE_CODE_OAUTH_TOKEN="sk-ant-oat01-..."
```

**Option 2: API key (API billing)**
```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

The `DEFAULT_ENV_ALLOWLIST` in `acp/container.py` passes these from the host environment into containers. The entrypoint script validates that exactly one auth method is present and rejects the container if both or neither are set.
