# Agent Foundry Documentation

Start with the [project README](../README.md) for what Agent Foundry is and how to install it.

## Guides — start here

- [Getting started](guides/getting-started.md) — define state models, compose constructs, run a process, extend with custom constructs
- [Agent containers](guides/agent-containers.md) — running AI agents in Docker containers with structured communication

## Vision

- [Vision & motivation](vision.md) — what we believe, the builder journey, where the platform is headed

## Architecture

- [Ontology](architecture/agent-foundry-ontology.md) — the conceptual model: System → Process → Construct → Run, with Topology as the structural axis and Participant/Role as the meaning of action constructs
- [Platform / product separation](architecture/agent-foundry-separation-spec.md) — the boundary between Agent Foundry and the products built on it
- ADRs: [typed communication model](architecture/adr_typed_communication_model.md) · [markdown template model shape](architecture/adr_markdown_template_model_shape.md)

## Reference

- [Agent containers reference](reference/agent-containers.md) — protocol, adapters, lifecycle, error taxonomy
- [Claude Code CLI reference](reference/claude-code-cli-reference.md) — the CLI surface the executor depends on
- [CLAUDE.md layering](reference/claude-md-layering.md) — how instruction layers compose

## Design

Subsystem design docs live in [`design/`](design/) — resilience, telemetry, container
permissions, executor failure handling, and the Codex agent path.

## Internal

[`internal/`](internal/) holds dev notes — audits, completed implementation processes, and
research. These are working artifacts, not user-facing documentation. See
[`internal/README.md`](internal/README.md).
