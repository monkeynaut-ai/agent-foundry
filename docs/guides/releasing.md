# Releasing

Agent Foundry uses PDM's SCM dynamic versioning. Release versions come from
Git tags that match `vX.Y.Z`.

## Release Steps

1. Commit the release change to `main`.
2. Push `main` and wait for CI to pass.
3. Tag the release commit:

   ```bash
   git tag v0.11.1
   git push origin v0.11.1
   ```

4. Confirm the tag workflow builds distributions with the matching version.

## Versioning

The package version is derived from the nearest `v*` tag:

- on `v0.11.1`: `0.11.1`
- one commit after `v0.11.1`: `0.11.2.dev1+g<hash>`

Do not add a static `[project].version`.

## Publishing

The release workflow currently validates tags and builds distributions. PyPI
publishing should be added after the package publishing target and credentials
are ready.
