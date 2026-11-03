---
title: Trunk-based development and release flows
minutes: 45
objectives:
  - Compare trunk-based development, GitHub flow and Gitflow
  - Use short-lived branches, required checks and merge queues
  - Tag and version releases so artifacts can be traced to a commit
---
The branching model decides how often code integrates and how releases are cut. Pipelines are designed around it, so pick the model first.
@concept Trunk-based development
@plain
Everyone commits to one main branch (the trunk), either directly or through very short-lived branches that last hours or a day or two. Unfinished work is hidden behind feature flags.
@problem
Long-lived branches diverge from main. The longer they live, the harder and riskier the merge, and the less often anyone tests the combined result.
@does
- Small pull requests merge to main several times per day.
- Main is always releasable, protected by required checks.
- Incomplete features ship dark behind a flag, so merging is separated from releasing.
- Research on delivery performance (DORA) links trunk-based practice to higher deployment frequency.
@diagram flow
caption: Short branches back into one trunk
nodes:
  - "Branch|lives under two days|plain"
  - "Pull request|checks run|info"
  - "Main|trunk, always releasable|ok"
  - "Release|tag or deploy from main|app"
@h Daily flow
```bash title="Short-lived branch" lab
git switch main && git pull --ff-only
git switch -c fix/timeout-retry
# ...small change...
git commit -am "Retry upstream call once on timeout"
git push -u origin fix/timeout-retry    # open a pull request, merge when green
```
@check
How can unfinished work live on main safely? || Behind a feature flag that is off, so the code is deployed but not active.
@end

@concept GitHub flow
@plain
GitHub flow is a light version of trunk-based work. Branch from main, open a pull request, get review and green checks, merge, and deploy from main.
@problem
Teams need a simple, shared rule for how changes reach production without the ceremony of release branches.
@does
- One long-lived branch (main). Everything else is a feature branch.
- The pull request is the place for review, discussion and automated checks.
- Merge triggers deployment, often to staging first.
@diagram seq
caption: One change from branch to production
actors: ["Developer|local|app", "GitHub|PR and checks|cp", "Pipeline|CI and CD|env"]
steps:
  - "0>1: push branch, open PR | req"
  - "1>2: run required checks | req"
  - "2>1: green | resp"
  - "note 1..1: review approved, merge"
  - "1>2: deploy from main | req"
@h Branch protection as code
```bash title="Require checks on main with the GitHub CLI" nocheck
gh api -X PUT repos/ORG/REPO/branches/main/protection --input - <<'JSON'
{
  "required_status_checks": {"strict": true, "contexts": ["test"]},
  "enforce_admins": true,
  "required_pull_request_reviews": {"required_approving_review_count": 1},
  "restrictions": null
}
JSON
```
:::note
Rulesets are the newer way to express the same rules in GitHub. Check the current docs for syntax.
:::
@end

@concept Gitflow and release branches
@plain
Gitflow uses long-lived `develop` and `main` branches plus feature, release and hotfix branches. It suits software shipped in versions that several supported releases must coexist.
@problem
Some products (installed software, libraries, firmware) must patch version 2.3 while building 3.0. A single trunk cannot express that.
@does
- Release branches stabilise a version while new work continues on develop.
- Hotfixes branch from the released tag, then merge back.
- It adds merge overhead and delays integration, which is why web services usually avoid it.
@diagram cmp
caption: When each model fits
cards:
  - {h: "Trunk-based", kind: ok, items: ["SaaS and internal services", "Deploy many times a day", "Needs feature flags"]}
  - {h: "GitHub flow", kind: app, items: ["Small teams, simple rules", "Deploy from main", "PR is the gate"]}
  - {h: "Gitflow", kind: warn, items: ["Versioned products", "Several supported releases", "Heavy merge work"]}
@h A release branch for a supported version
```bash title="Cut and patch a release branch" lab
git switch -c release/2.3 v2.3.0       # start from the released tag
git cherry-pick 4f3a9c1                # take the fix from main
git tag v2.3.1 && git push origin release/2.3 v2.3.1
```
@check
When is a release branch justified? || When you must keep supporting an older version while developing the next one.
@end

@concept Required checks and branch protection
@plain
Branch protection lets the platform refuse a merge until named checks pass and reviewers approve. It turns the pipeline from advice into a gate.
@problem
If checks are optional, a rushed merge on a Friday skips them, and the next person inherits a broken main.
@does
- Required status checks must be green and up to date with the target branch.
- Reviews can be required from code owners listed in a `CODEOWNERS` file.
- Force pushes and deletion of main can be blocked, and administrators can be included in the rules.
- Signed commits can be required where the audit policy needs it.
@diagram flow
caption: Gates between a branch and main
nodes:
  - "Pull request|opened|plain"
  - "Required checks|build, test, scan|info"
  - "Code owner review|CODEOWNERS|warn"
  - "Merge|allowed|ok"
@h CODEOWNERS
```text title=".github/CODEOWNERS"
# last matching pattern wins
*                    @org/platform-team
/deploy/             @org/sre
/.github/workflows/  @org/security
```
:::tip
Make changes to workflow files require review from the security or platform team. The pipeline is a privileged place.
:::
@check
Why mark a check as required rather than just visible? || Only required checks block the merge button.
@end

@concept Merge queues
@plain
A merge queue tests each pull request combined with the ones ahead of it before merging, so main never receives a combination that was not tested.
@problem
Two pull requests can each pass alone and break main together. On busy repositories, forcing authors to rebase and rerun checks repeatedly wastes hours.
@does
- Pull requests join a queue, the platform builds a temporary branch of main plus queued changes, and runs the required checks.
- On success it merges automatically, on failure it removes the pull request and continues.
- In GitHub Actions the workflow must also listen to the `merge_group` event.
@diagram flow
caption: Queue testing the combined result
nodes:
  - "PR A|approved|plain"
  - "PR B|approved|plain"
  - "Temp branch|main plus A plus B|info"
  - "Checks|run on combined code|warn"
  - "Main|fast-forwarded|ok"
@h Workflow that supports the queue
```yaml title="Listen to merge_group as well"
name: ci
on:
  pull_request:
  merge_group:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: make test
```
:::warn
If the required check does not run on `merge_group`, the queue waits forever. This is a common setup mistake.
:::
@end

@concept Versioning and tagging
@plain
A version number and a tag give a release a name that humans and machines can refer to. Semantic versioning uses MAJOR.MINOR.PATCH, where MAJOR breaks compatibility, MINOR adds features and PATCH fixes bugs.
@problem
Without a name, nobody can say which commit runs in production, or what changed between two releases.
@does
- Git tags such as `v1.4.2` point at a commit. Annotated tags carry a message and author.
- Image tags can include both the version and commit, for example `1.4.2` and `sha-4f3a9c1`.
- Conventional commits (`feat:`, `fix:`) let tools compute the next version and the changelog automatically.
@diagram flow
caption: From commit to named release
nodes:
  - "Merge to main|conventional commit|plain"
  - "Tool computes version|feat means minor|info"
  - "Tag v1.5.0|annotated|app"
  - "Release notes|changelog|ok"
@h Tagging and building from the tag
```yaml title="Release workflow triggered by tags"
name: release
on:
  push:
    tags: ["v*.*.*"]
jobs:
  release:
    runs-on: ubuntu-latest
    permissions:
      contents: write
    steps:
      - uses: actions/checkout@v4
      - run: echo "Releasing ${GITHUB_REF_NAME}"
```
@check
What should an image tag tell you? || Which commit and which version it was built from, so production can be traced to source.
@end

@concept Monorepo and polyrepo pipelines
@plain
A monorepo holds many services in one repository, a polyrepo gives each service its own. Each choice changes how pipelines decide what to build.
@problem
In a monorepo, building and testing everything for every change is slow. In a polyrepo, shared pipeline logic gets copied and drifts.
@does
- Path filters run a workflow only when relevant directories change.
- Build tools with caches and affected-target detection (Bazel, Nx, Turborepo) skip unchanged work.
- Polyrepos share logic through reusable workflows or templates stored in one platform repository.
@diagram cmp
caption: Trade-offs in repository layout
cards:
  - {h: "Monorepo", kind: app, items: ["Atomic cross-service change", "Needs path filters or affected builds", "One place for tooling"]}
  - {h: "Polyrepo", kind: info, items: ["Clear ownership boundaries", "Pipeline logic must be shared", "Cross-repo changes are slower"]}
@h Path filters
```yaml title="Run only when this service changes"
name: orders-ci
on:
  pull_request:
    paths:
      - "services/orders/**"
      - ".github/workflows/orders-ci.yml"
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: make -C services/orders test
```
:::warn
A required check that is skipped by path filters stays pending and can block merges. Use a small always-running job that aggregates results, or check the platform docs for skipped-check behaviour.
:::
@end
