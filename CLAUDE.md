# Agent Foundry

A reusable agentic workflow platform built on LangGraph (orchestration) using LangChain as a component library (models, tools, retrieval, structured outputs, integrations). The platform is designed to develop various agentic systems.

## Archipelago

An autonomous softare development system that uses a system of autonomous AI agents. Archipelago is built on Agent Foundry. 

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
- src/agent_foundry : source code agent foundry
- tests/agent_foundry : tests for agent foundry
- src/archipelago : source code for archipelago
- tests/archipelago : tests for archipelago

## Commands

- `pdm add <package>`: Add a dependency
- `pdm run pytest`: Run tests
- `pdm docker-base`: build docker image for claude-agent
- `pdm docker-archipelago`: build docker image for archipelago

## work-status.md

`work-status.md` at the project root is the source of truth for ongoing work on the archipelago subsystem. Always use the `work-status` skill (via the Skill tool) to update it — never edit the file directly.
