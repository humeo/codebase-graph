# Releasing codebase-graph

## Preconditions

Before cutting a release:

- Ensure the git working tree is clean.
- Verify the package version is aligned in both `pyproject.toml` and `src/codebase_graph/__init__.py`.
- Run the test suite:

```bash
uv run pytest -v --tb=short
```

- Build the release artifacts locally:

```bash
uv build
```

## Create The Public Repository

If the GitHub repository has not been created yet:

```bash
gh repo create humeo/codebase-graph --public --source=. --remote=origin --push
```

## Cut A Release

After confirming the version matches the intended release:

```bash
git tag v0.1.0
git push origin v0.1.0
```

Pushing the version tag triggers the GitHub Actions release workflow, which verifies the tag version, runs tests, builds `dist/*`, and publishes a GitHub Release with the generated artifacts.

## After Tag Push

- Watch the release workflow in GitHub Actions until it completes successfully.
- Confirm the GitHub Release contains the built wheel and source distribution assets.
- Verify the public install command works against the published release:

```bash
curl -fsSL https://raw.githubusercontent.com/humeo/codebase-graph/main/scripts/install.sh | bash
cg --version
```
