# Contributing

## Commits and releases

This project uses [Conventional Commits](https://www.conventionalcommits.org/) and [release-please](https://github.com/googleapis/release-please) to bump versions, update `CHANGELOG.md`, and publish to PyPI.

### What to write

Use a type and description in the subject line:

| Type | When |
|------|------|
| `feat` | New feature (minor version bump) |
| `fix` | Bug fix (patch version bump) |
| `docs` | Documentation only |
| `ci` | CI / GitHub Actions |
| `test` | Tests |
| `chore` | Maintenance (often hidden in changelog) |
| `release` | Release PRs only (automation) |

Examples:

```
feat: add optional CARTESIA_ADMIN_API_KEY
fix: skip blank admin env in smoke test
```

### Pull requests

1. Open a PR with a **conventional title** (e.g. `feat: …`, `fix: …`).
2. Prefer **squash merge** so the PR title becomes the single commit on `main`.
3. Wait for the `Conventional Commits` and `Test` checks.
4. After merge, release-please opens a `release: x.y.z` PR; merge that to tag and publish.

If commits on `main` are not conventional, release-please will not create a release PR. You can still cut a release manually with a `release: x.y.z` PR that updates `pyproject.toml`, `cartesia_mcp/__init__.py`, `.release-please-manifest.json`, and `CHANGELOG.md`.
