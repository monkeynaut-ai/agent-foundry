# Changelog

All notable changes to Agent Foundry are documented here.

Agent Foundry is pre-1.0. Public APIs may still change, but release notes should
call out compatibility-impacting changes and migration paths.

## Unreleased

### Added

- Added GitHub Actions CI for quality checks, unit tests, package builds, and
  release-tag validation.
- Added release documentation for tag-based SCM versioning.

### Changed

- Polished package metadata for public distribution readiness.

## 0.11.1 - 2026-07-04

### Added

- Exposed containerized-agent contracts through `agent_foundry.agents`,
  including `ContainerConfig`, `NetworkMode`, `ContainerManagerBase`, and
  `AgentTurnEnvelope`.

### Migration Notes

- Prefer public imports from `agent_foundry.agents`:
  `from agent_foundry.agents import ContainerConfig, NetworkMode`
- Avoid deep imports from `agent_foundry.agents.lifecycle` in application code.

## 0.11.0 - 2026-07-04

### Added

- Switched Agent Foundry to SCM-derived dynamic package versioning.
- Added `vX.Y.Z` tag-based release versioning.

### Changed

- Removed the transitional version formatter after creating the first release
  tag.
