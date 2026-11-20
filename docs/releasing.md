# Releasing

This is the runbook for cutting a release. `pyproject.toml` is the single
source of truth for the version; the tag must match it or `build` fails.

## 1. Bump and document

1. `version = "X.Y.Z"` in `pyproject.toml`.
2. Add a `## [X.Y.Z] - YYYY-MM-DD` section to `CHANGELOG.md` (Keep a Changelog
   style; `[Unreleased]` stays at the top and empty).
3. Open a PR, let CI go green, merge. `main` is protected, so no direct pushes.

## 2. Tag

```bash
git -c user.name=LUgABeEEE -c user.email=LUgABeEEE@users.noreply.github.com \
  tag -a vX.Y.Z -m "vX.Y.Z - <one line>"
git push origin vX.Y.Z
```

The tag starts `.github/workflows/release.yml`:

`build` → version/tag check, sdist + wheel, `twine check`, wheel smoke test
→ `publish` (PyPI, only when enabled) → `github-release` (always).

## 3. PyPI (one-time setup, then per release)

Publishing uses **Trusted Publishing** (OIDC). There is no API token and no
secret in this repository.

### One-time, on pypi.org

1. Sign in, open <https://pypi.org/manage/account/publishing/>.
2. For the first release choose **Add a new pending publisher**; the fields must
   match this repository exactly:

   | Field | Value |
   |---|---|
   | PyPI Project Name | `blender-automation-skill` |
   | Owner | `LUgABeEEE` |
   | Repository name | `blender-automation-skill` |
   | Workflow name | `release.yml` |
   | Environment name | `pypi` |

3. Save. The publisher becomes a regular trusted publisher after the first
   successful upload.

### Enable it for the repository

```bash
gh variable set PYPI_PUBLISH --body true --repo LUgABeEEE/blender-automation-skill
```

The `publish` job is gated on `vars.PYPI_PUBLISH == 'true'`, so a tag pushed
before the PyPI side exists still produces a GitHub Release instead of failing
the whole run.

### Publish (or re-publish) an existing tag

```bash
gh workflow run release.yml --ref vX.Y.Z
```

The `github-release` job is idempotent: if the release already exists it only
uploads the new assets.

## 4. Verify

```bash
gh release view vX.Y.Z                       # notes + assets
curl -sSf https://pypi.org/pypi/blender-automation-skill/json | head -c 200
pip install "blender-automation-skill[mcp]==X.Y.Z"
blender-automation-skill --version
```

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `invalid-publisher` / 403 from PyPI | the five fields do not match exactly | re-check spelling, including `release.yml` and `pypi` |
| `File already exists` | the version is already on PyPI | bump the version; do not re-tag |
| `tag vX does not match pyproject version` | tag/version drift | fix the tag or the version, then push again |
| publish job skipped | `PYPI_PUBLISH` is not `true` | `gh variable set PYPI_PUBLISH --body true` |
| publish job waits forever | the `pypi` environment has required reviewers | approve the deployment, or drop the rule |
