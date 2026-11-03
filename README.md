# DevOps & Cloud Architecture Path

A self-paced curriculum from first Linux command to architect-level decisions.
Open `index.html` in a browser (no server needed). Each topic folder has one interactive `index.html`
with a table of contents, Next / Prev / Start / Stop controls, a Topics menu, and a fixed concept layout:
**plain words, the problem it solves, what it does, a diagram**.

## Build

Create a virtual environment, install `tools/requirements-lint.txt`, install a Chromium for Playwright, then:

```bash
python tools/build.py          # content/*.md -> */index.html ; fails on any rule violation
python tools/lint_layout.py    # browser check for overlaps and clipping, plus the real A4 page count
python tools/status.py         # planned versus actual pages per topic
```

## Deploy to GitHub Pages

`.github/workflows/pages.yml` runs on every push and pull request, and deploys only from `main`.

1. Build with pinned dependencies (`tools/requirements-ci.txt`) and fail if the committed HTML differs from a fresh build.
2. Audit every code block (shellcheck, ruff, kubeconform, terraform fmt), render the Shop Kustomize overlays, run the layout lint, the browser tests for all 15 topics, the picker and practice, and the 10 simulator tests.
3. `tools/package_site.py` copies only pages, assets and simulators into `_site/` and fails on any broken relative link.
4. The deploy job publishes `_site/` with `actions/deploy-pages`.

One-time setup in the repository: **Settings > Pages > Source: GitHub Actions**. All links are relative, so the site works from a project path such as `https://<user>.github.io/<repo>/`.

Before pushing, run `python tools/build.py` and commit the regenerated HTML and `tools/pages.json`.

## Authoring

Write `content/<topic>/NN-name.md`. Blocks:

- `@concept` containing `@plain`, `@problem`, `@does` and at least one `@diagram <flow|rows|layers|cmp|seq>` (all required)
- optional `@choose`, `@check`, `@lab`, callouts `:::tip|note|warn|danger`, fenced code
- `{{v.key}}` for versions, read from `tools/versions.yaml`

The build rejects: missing tiles or diagrams, unknown version keys, YAML / JSON / Python / Bash / Terraform
that does not parse, and broken links or anchors.

## What was and was not verified

No cloud account or cluster was used. Syntax is machine-checked; behaviour is documented design.
Versions marked VERIFIED in `tools/versions.yaml` were read from upstream release indexes on the build date.
