---
title: Git essentials
minutes: 20
objectives:
  - Describe how Git stores history and what a branch is
  - Use the everyday commands and recover from common mistakes
  - Explain pull requests and the branching strategies teams use
---
Git is the system of record for code, infrastructure and pipelines in everything that follows.

@concept Commits and the object model
@plain
Git stores your project as a chain of **commits**. Each commit is a snapshot with a message, an author and a pointer to its parent.
@problem
Copying folders called "final", "final2" and "final-really" does not scale, cannot show who changed what, and makes merging two people's work painful.
@does
- Every commit has a unique ID computed from its content, so history cannot be changed silently.
- A **branch** is just a movable label pointing at a commit; creating one costs almost nothing.
- `HEAD` is the label for where you are now.
@diagram flow
caption: Commits form a chain; a branch is a label
nodes:
  - "A|initial|plain"
  - "B|add cart|plain"
  - "C|fix bug|plain"
  - "main|points at C|ok"
@body
```bash title="The daily loop"
git status                      # what changed
git add -p                      # choose hunks to stage
git commit -m "Add cart total rounding"
git log --oneline --graph --decorate -10
git diff main..feature/cart     # compare two branches
```
@check
What does a branch contain? || Only a pointer to one commit; the history is in the commits themselves.
@end

@concept Branching and merging
@plain
You work on a **branch** so unfinished work does not disturb the main line. When ready you **merge** it back.
@problem
Several people editing the same project at once would overwrite each other. Branches isolate work; merging combines it and flags real conflicts.
@does
- A merge joins two lines of history with a merge commit, or fast-forwards if no new work exists on the target.
- **Rebase** replays your commits on top of another branch for a straight history; never rebase commits others already pulled.
- A **conflict** happens when both sides changed the same lines; you choose the result and commit it.
@diagram cmp
caption: Merge and rebase compared
cards:
  - {h: "Merge", kind: ok, items: ["Keeps the true history", "Adds a merge commit", "Safe on shared branches"]}
  - {h: "Rebase", kind: app, items: ["Straight, tidy history", "Rewrites commits", "Only for your own branches"]}
  - {h: "Squash merge", kind: env, items: ["One commit per pull request", "Hides the working steps", "Easy to revert a feature"]}
@choose Merge, rebase or squash
Merge commit | you want full history preserved | the branch has noisy fix-up commits
Rebase | you are updating your own feature branch | other people already based work on it
Squash merge | each pull request is one logical change | you need the individual commits for audit
@end

@concept Pull requests and review
@plain
A **pull request** (PR) asks to merge a branch and gives teammates a place to review, comment and run automated checks first.
@problem
Merging directly to the main branch lets mistakes reach production unseen. Review catches defects, shares knowledge and creates a record of why a change was made.
@does
- A PR runs the pipeline (tests, linting, security scan) before anyone merges.
- **Branch protection** can require passing checks, approvals and no direct pushes.
- Small PRs are reviewed faster and break less.
@diagram flow
caption: A pull request is the gate before main
numbered: true
nodes:
  - "Branch|your change|app"
  - "Open PR|describe why|info"
  - "Checks|tests, lint, scan|warn"
  - "Review|approval|env"
  - "Merge|main updated|ok"
@end

@concept Branching strategies
@plain
A strategy is a team agreement about which branches exist and how code moves from them to production.
@problem
Without an agreement, people merge in different ways, releases become unpredictable and hot fixes get lost.
@does
- **Trunk-based development**: short-lived branches merge to `main` many times a day, behind feature flags.
- **GitHub Flow**: branch, PR, merge to `main`, deploy from `main`.
- **GitFlow**: long-lived `develop` and `release` branches; suited to scheduled releases.
@diagram cmp
caption: Three common strategies
cards:
  - {h: "Trunk-based", kind: ok, items: ["Branches live hours", "Flags hide unfinished work", "Best fit for continuous delivery"]}
  - {h: "GitHub Flow", kind: app, items: ["One main branch", "PR for every change", "Deploy after merge"]}
  - {h: "GitFlow", kind: vm, items: ["develop, release, hotfix branches", "Heavy process", "Fits boxed or versioned products"]}
@choose Picking a strategy
Trunk-based | you ship often and have good automated tests | you cannot test automatically yet
GitHub Flow | small team, web service, simple needs | you maintain several released versions at once
GitFlow | you support multiple versions, such as installed software | you want continuous deployment
@end

@concept Fixing mistakes safely
@plain
Git can undo almost anything, if you pick the right tool for how far the mistake went.
@problem
Fear of breaking history makes people avoid Git features or force-push over shared work.
@does
- Not committed yet: `git restore <file>` discards edits.
- Committed, not pushed: `git commit --amend` or `git reset --soft HEAD~1`.
- Already shared: `git revert <commit>` adds a new commit that undoes it, so history stays intact.
- `git reflog` lists where HEAD has been, which rescues "lost" commits.
@diagram flow
caption: How far did the mistake travel?
nodes:
  - "Edited only|restore|ok"
  - "Committed locally|amend or reset|info"
  - "Pushed and shared|revert|warn"
  - "Secret leaked|rotate the secret first|bad"
@body
:::danger
If a password or key was committed, rewriting history is not enough. Treat it as exposed: revoke and replace it first, then clean the repository.
:::
@end
