---
title: Code review, trunk based development and technical debt
minutes: 50
objectives:
  - Run effective code reviews and pair programming sessions
  - Practise trunk based development with short lived branches and feature flags
  - Decide between a monorepo and many repositories
  - Measure and pay down technical debt deliberately
---
How a team moves code from one head to the shared mainline determines its delivery speed more than any tool. These practices are what the DORA research associates with high performance.

@concept Why and how to review code
@plain
A **code review** is a colleague reading a change before it merges. The goal is shared understanding and catching problems early, not gatekeeping.
@problem
Unreviewed changes carry defects and hidden knowledge in one head. Slow, harsh or huge reviews push people to bypass the process.
@does
- Keep changes small. A review of about 200 to 400 changed lines is far more effective than one of 2000.
- Reviewers look at design, correctness, tests, security, readability and operability (logs, metrics, rollback).
- Automate the mechanical parts (formatting, lint, tests, scans) so humans discuss judgement.
- Agree a response target such as first review within one working day.
@diagram flow
caption: A healthy review loop
numbered: true
nodes:
  - "Author self review|read your own diff first|plain"
  - "CI checks|format, tests, scan|cp"
  - "Reviewer|design, risk, clarity|app"
  - "Revise|small follow up commits|info"
  - "Merge|and monitor|ok"
@h Review checklist
```yaml title=".github/pull_request_template.md as data"
what_and_why: One sentence on the change and the reason
how_tested: Unit tests added, manual check in staging
risk_and_rollback: Low, revert the commit; feature flag shop.new_checkout is off by default
operability: New metric checkout_errors_total and alert linked
screenshots_or_logs: attach if relevant
```
@check
Why automate formatting and linting in review? || So reviewers spend attention on design and risk rather than style.
@end

@concept Giving and receiving review feedback
@plain
Review comments are about the code, not the person. The tone decides whether a team learns from review or avoids it.
@problem
Blunt or ambiguous comments cause conflict and stalled pull requests.
@does
- Ask questions rather than issue orders: "What happens if the list is empty?"
- Mark intent with prefixes: `nit:` (optional), `question:`, `suggestion:`, `blocker:`.
- Explain the reason and link to guidance. Praise good solutions.
- Authors assume good intent, answer every comment, and avoid defensiveness. If a thread passes three rounds, talk by voice and record the outcome.
@diagram cmp
caption: Comment style
cards:
  - {h: "Less helpful", kind: bad, items: ["This is wrong", "Why would you do this", "Rewrite it"]}
  - {h: "More helpful", kind: ok, items: ["blocker: this skips auth when token is empty, see line 42", "question: could a map avoid the nested loop", "nit: rename to orderCount"]}
@h Tooling help
```bash title="Review locally" lab
git fetch origin && git switch -c review-tmp origin/main 2>/dev/null || true
git diff --stat origin/main...HEAD | tail -3        # size of the change
git log --oneline origin/main..HEAD                 # commits to review
git diff origin/main...HEAD -- '*.yaml' | head -30  # focus on config changes
```
@end

@concept Pair and mob programming
@plain
In **pair programming** two people work on one task at one screen: a driver types, a navigator thinks ahead. In **mob programming** the whole team does this together.
@problem
Knowledge silos, long review queues and unfamiliar code slow teams. Pairing spreads knowledge and finds defects as they are written.
@does
- Rotate roles every 15 to 25 minutes. Swap pairs daily or per task.
- Good for onboarding, tricky design, incident follow ups and unfamiliar areas; not needed for every trivial change.
- Remote tools: shared terminal (`tmux`), VS Code Live Share, screen sharing.
- Pair-written code often needs lighter review, since a second person already saw every line.
@diagram flow
caption: Pairing roles
nodes:
  - "Driver|types, focuses on the line|app"
  - "Navigator|thinks about direction and risk|info"
  - "Swap|every 20 minutes|ok"
@h Shared terminal
```bash title="Pair on a remote host with tmux" lab
tmux new-session -d -s pair 'bash'
tmux ls
# partner: ssh to the same host as the same user, then tmux attach -t pair
tmux kill-session -t pair
```
@check
When is pairing most valuable? || Onboarding, complex design and unfamiliar code where shared knowledge pays back.
@end

@concept Trunk based development
@plain
Everyone integrates into one main branch (the trunk) at least daily. Branches live for hours or a day or two. Unfinished features hide behind feature flags.
@problem
Long-lived branches diverge, so merging becomes a painful event, integration bugs appear late, and releases are a gamble.
@does
- Small commits to trunk, protected by fast CI (minutes, not hours).
- Feature flags decouple deploy from release; delete flags after rollout.
- Release from trunk with tags, or from short-lived release branches cut from trunk for hotfixes.
- DORA research links trunk based development with higher delivery performance. Check the current DORA reports for the practices they measure.
@diagram cmp
caption: Long branches versus trunk
cards:
  - {h: "Long-lived branches", kind: bad, items: ["Weeks of divergence", "Big bang merges", "Late surprises"]}
  - {h: "Trunk based", kind: ok, items: ["Integrate daily", "Flags hide unfinished work", "Always releasable main"]}
@h Flag guarded change
```python title="Flag checked at run time" lab
FLAGS = {"new_checkout": False}          # in real life from a flag service

def checkout(cart):
    if FLAGS["new_checkout"]:
        return f"new flow for {len(cart)} items"
    return f"old flow for {len(cart)} items"

print(checkout(["a", "b"]))
FLAGS["new_checkout"] = True              # release without a deploy
print(checkout(["a", "b"]))
```
@check
How do you merge half-finished work to trunk safely? || Behind a feature flag that is off until the feature is ready.
@end

@concept Branch protection and merge strategies
@plain
Rules on the main branch keep it releasable: required reviews, required passing checks, no force pushes. Merge strategy controls the history shape.
@problem
A broken main blocks everyone. Without rules, tired people push straight to main.
@does
- Require status checks, at least one approval, linear history if you want it, and signed commits if policy needs it.
- **Squash merge**: one commit per pull request. **Rebase merge**: replays commits. **Merge commit**: preserves branches.
- A **merge queue** tests the combination of queued pull requests so main stays green when many merge at once.
- CODEOWNERS routes reviews to the right team.
@diagram flow
caption: Guard rails around main
nodes:
  - "Pull request|small change|app"
  - "Required checks|tests, lint, scan|cp"
  - "Approval|CODEOWNERS|info"
  - "Merge queue|test combined result|warn"
  - "main|always green|ok"
@h Configure with the GitHub CLI
```bash title="Branch protection through the API" nocheck
gh api -X PUT repos/ORG/REPO/branches/main/protection \
  -H "Accept: application/vnd.github+json" \
  --input - <<'EOF'
{
  "required_status_checks": {"strict": true, "contexts": ["build", "test"]},
  "enforce_admins": true,
  "required_pull_request_reviews": {"required_approving_review_count": 1},
  "restrictions": null
}
EOF
```
```text title=".github/CODEOWNERS"
*            @org/platform
/payments/   @org/payments-team
*.tf         @org/infra
```
:::note
GitHub also offers rulesets, which are the newer way to express these rules. Check the current GitHub documentation.
:::
@end

@concept Monorepo versus many repositories
@plain
A **monorepo** holds many projects in one repository. A **polyrepo** setup gives each project its own. Both work; each has costs.
@problem
Choosing by fashion leads to either tangled dependencies across dozens of repositories or a monorepo whose builds take an hour.
@does
- Monorepo benefits: atomic cross project changes, one version of every dependency, easy refactoring, shared tooling. Costs: needs build caching and selective builds (Bazel, Nx, Turborepo, Pants), careful CODEOWNERS, and large-repo performance work.
- Polyrepo benefits: clear ownership, independent release, simple CI per repo. Costs: version skew, cross-repo changes need coordination, duplicated tooling.
- In CI, build only what changed using path filters or a build graph.
@diagram cmp
caption: Trade offs
cards:
  - {h: "Monorepo", kind: app, items: ["Atomic changes across services", "Shared tooling", "Needs smart builds and caching"]}
  - {h: "Polyrepo", kind: info, items: ["Clear ownership", "Independent releases", "Dependency drift to manage"]}
@choose Repository layout
Monorepo | tightly related services, shared libraries, one team or strong platform tooling | very large unrelated codebases with no build tooling
Polyrepo | independent teams, separate release cadence, strong API contracts | frequent cross-service changes
@h Build only what changed
```yaml title=".github/workflows/ci.yml"
name: ci
on:
  pull_request:
    paths:
      - "services/orders/**"
      - "libs/common/**"
jobs:
  orders:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: make -C services/orders test
```
```bash title="Which projects did this change touch" lab
git diff --name-only origin/main...HEAD 2>/dev/null | cut -d/ -f1-2 | sort -u
```
@check
What lets a monorepo stay fast? || Selective builds and caching, so only affected projects are built and tested.
@end

@concept What technical debt is and how to measure it
@plain
**Technical debt** is the future cost of shortcuts and outdated design. Like financial debt it has principal (work to fix) and interest (extra effort every time you touch the area).
@problem
Ignored, interest compounds: simple changes take weeks, outages repeat, and engineers leave. Treated as a vague complaint, it never gets prioritised.
@does
- Types: deliberate or accidental, prudent or reckless (Fowler's quadrant). Examples: no tests, outdated libraries, manual deploy steps, unclear ownership.
- Make it visible: record debt items with an estimate of cost, the interest they cost per month, and what they block.
- Signals: lead time for changes rising, change failure rate rising, many hotfixes in one module, build time creeping up, dependency age.
- Example priority: a flaky test costing 5 developers 10 minutes a day is about 4.2 hours a week (5 x 10 x 5 / 60); fixing it in 1 day pays back in two weeks.
@diagram cmp
caption: The debt quadrant
cards:
  - {h: "Deliberate, prudent", kind: ok, items: ["Ship now, fix next sprint", "Logged and scheduled"]}
  - {h: "Deliberate, reckless", kind: bad, items: ["We have no time for design"]}
  - {h: "Inadvertent, prudent", kind: info, items: ["Now we know how we should have built it"]}
  - {h: "Inadvertent, reckless", kind: warn, items: ["What is layering?"]}
@h Rank by interest
```python title="Debt backlog ranked by payback" lab
items = [
    # name, people affected, minutes lost per person per day, days to fix
    ("flaky integration test", 5, 10, 1),
    ("manual release checklist", 8, 6, 3),
    ("old base image", 12, 1, 2),
]
for name, people, minutes, days in items:
    hours_week = people * minutes * 5 / 60
    payback_weeks = days * 8 / hours_week
    print(f"{name:26s} loses {hours_week:4.1f} h/week, payback {payback_weeks:4.1f} weeks")
```
Expected: the flaky test loses 4.2 hours a week with a payback of 1.9 weeks.
@check
What is the "interest" of technical debt? || The extra time and risk paid every time the area is changed or operated.
@end

@concept Paying down debt deliberately
@plain
Debt is managed, not eliminated. Reserve capacity for it, tie it to goals, and make the improvement boy-scout small where possible.
@problem
Big rewrites fail, and "we will fix it later" never arrives without a mechanism.
@does
- Reserve a share of capacity (commonly 15 to 20 percent) for debt and operability work, and protect it in planning.
- Prefer incremental patterns: the strangler fig (route traffic piece by piece to the new implementation), branch by abstraction, and leaving code cleaner than you found it.
- Attach debt work to feature work in the same area, and to SLO or DORA goals so its value is visible.
- Automate guards: dependency update bots (Renovate, Dependabot), lint rules, complexity limits, architecture tests.
@diagram flow
caption: Strangler fig migration
numbered: true
nodes:
  - "Facade|route all traffic through a proxy|cp"
  - "Build new piece|behind the facade|app"
  - "Shift traffic|10, 50, 100 percent|warn"
  - "Retire old code|delete it|ok"
@h Automate dependency freshness
```yaml title="renovate.json"
{
  "extends": ["config:recommended"],
  "schedule": ["before 6am on monday"],
  "packageRules": [
    {"matchUpdateTypes": ["minor", "patch"], "automerge": true},
    {"matchUpdateTypes": ["major"], "labels": ["breaking"], "automerge": false}
  ]
}
```
:::tip
Count a repaid debt as an outcome ("deploy time from 40 to 12 minutes"), not as an activity. It makes the next negotiation easier.
:::
@check
Why use a strangler pattern instead of a rewrite? || It delivers value incrementally, keeps the old system working and limits risk.
@end
