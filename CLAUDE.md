# Agent Foundry

A reusable agentic workflow platform built on LangGraph (orchestration) using LangChain as a component library (models, tools, retrieval, structured outputs, integrations). The platform is designed to develop various agentic systems.

## Development Practices

- **Test-Driven Development (TDD)**: Write tests before implementation. Red-green-refactor cycle. All code changes must be covered by tests.
- **Trunk-Based Development**: Work directly on `main` with short-lived branches. Keep commits small and atomic. No long-lived feature branches.

## Tech Stack

- **Python 3.14**
- **LangGraph**: Orchestration layer for agentic workflows
- **LangChain**: Component library (models, tools, retrieval, structured outputs, integrations)
- **Pydantic**: Data validation and settings management
- **Pytest**: Testing framework
- **PDM**: Package manager

## Project Structure

- `pyproject.toml`: Project configuration and dependencies (PDM)

## Commands

- `pdm add <package>`: Add a dependency
- `pdm run pytest`: Run tests

## Session Start Protocol

At the start of every session, ask:

> "Are we working on items in `work-status.md`, or something else?"

Then read `docs/demo-archipelago/work-status.md` and present the current item in progress and the top backlog items so we can confirm what to tackle.

## work-status.md

`docs/demo-archipelago/work-status.md` is the source of truth for ongoing work on the demo-archipelago subsystem.

Structure:
- **Completed** — done items with a one-line note on key decisions made
- **In Progress** — the single item currently being worked on
- **Backlog** — prioritized list of remaining items

Rules:
- Mark an item complete (with a decision note) and remove it from the Backlog before starting the next one
- When an item is completed, present the top 5 backlog items and ask what to work on next
- Keep the backlog prioritized — the top item is always what we'd work on next
- Update the file at the end of every session before stopping
