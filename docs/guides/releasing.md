# Releasing

Agent Foundry uses PDM's SCM dynamic versioning. Release versions come from
Git tags that match `vX.Y.Z`.

## Release Steps

1. Move relevant `CHANGELOG.md` entries from `Unreleased` into a new version
   section.
2. Commit the release change to `main`.
3. Push `main` and wait for CI to pass.
4. Tag the release commit:

   ```bash
   git tag v0.11.1
   git push origin v0.11.1
   ```

5. Confirm the tag workflow builds distributions with the matching version.

## Changelog

Keep `CHANGELOG.md` focused on release-facing changes:

- public API additions, changes, deprecations, and removals
- compatibility fixes
- packaging and release-process changes
- migration notes for downstream users

Internal-only refactors do not need changelog entries unless they change
observable behavior.

When preparing a release, rename the relevant `Unreleased` entries to the target
version and date:

```md
## 0.11.2 - 2026-07-04
```

Start a fresh `Unreleased` section above the new version if more work is already
in progress.

## Versioning

The package version is derived from the nearest `v*` tag:

- on `v0.11.1`: `0.11.1`
- one commit after `v0.11.1`: `0.11.2.dev1+g<hash>`

Do not add a static `[project].version`.

## Publishing

The release workflow currently validates tags and builds distributions. PyPI
publishing should be added after the package publishing target and credentials
are ready.
