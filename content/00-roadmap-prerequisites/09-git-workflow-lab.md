---
title: Beginner Git workflow lab
minutes: 40
objectives:
  - Create a repository and make a clean series of commits
  - Use branches and pull requests to change code safely
  - Resolve a merge conflict and undo mistakes without losing work
---
This is a hands-on page. Everything runs on your laptop in a scratch folder and needs only `git`. Commands marked as a lab are meant to be typed.

@concept Set up a scratch repository
@plain
A repository is a folder whose history Git records. You set your identity once, then create the repository and a first commit.
@problem
Commits carry an author name and email. Without them Git refuses to commit or records a wrong identity that is hard to fix later.
@does
- `git config --global` stores your name, email and default branch name.
- `git init` creates the hidden `.git` directory that holds the whole history.
- `git status` is the command you run most; it tells you what to do next.
@diagram flow
caption: The first steps
numbered: true
nodes:
  - "git config|name, email|info"
  - "git init|creates .git|app"
  - "Edit files|working directory|plain"
  - "git add|staging area|env"
  - "git commit|saved snapshot|ok"
@h Start
```bash title="Create the lab repository" lab
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
git config --global init.defaultBranch main
mkdir -p ~/git-lab && cd ~/git-lab && git init
printf '# Git lab\n' > README.md
git add README.md && git commit -m "Add README"
git status && git log --oneline
```
@check
What does git status tell you that git log does not? || The current uncommitted state: changed, staged and untracked files.
@end

@concept Staging and good commits
@plain
The **staging area** is where you assemble the next commit. A good commit is one logical change with a message saying why.
@problem
Giant commits titled "fix stuff" cannot be reviewed, reverted or searched. Small commits make `git bisect` and reverts cheap.
@does
- `git add -p` stages selected hunks so unrelated edits go into separate commits.
- The subject line is about 50 characters, imperative mood ("Add retry to client"). A body explains why.
- `git diff` shows unstaged changes; `git diff --staged` shows what will be committed.
@diagram layers
caption: Where a change lives
layers:
  - {label: "Working directory", nodes: ["Edited files|git diff compares to index|plain"]}
  - {label: "Staging area", nodes: ["Index|git add moves changes here|env"]}
  - {label: "Repository", nodes: ["Commits|git commit stores a snapshot|ok"]}
@h Practise
```bash title="Two logical commits from one edit session" lab
cd ~/git-lab
printf 'def add(a, b):\n    return a + b\n' > calc.py
printf '\n## Usage\nRun calc.py\n' >> README.md
git add calc.py && git commit -m "Add add() function"
git add README.md && git commit -m "Document usage"
git diff HEAD~2 --stat
```
:::tip
Write the message as if finishing the sentence "If applied, this commit will...".
:::
@end

@concept Branches
@plain
A **branch** is a movable label pointing at a commit. Creating one costs almost nothing, so every change gets its own.
@problem
Working directly on main means half-finished work blocks everyone and a mistake goes straight to production.
@does
- `git switch -c feature/subtract` creates and moves to a new branch.
- Commits on the branch do not affect main until you merge.
- `git branch -vv` lists branches and what they track.
@diagram flow
caption: A feature branch diverging from main
nodes:
  - "main|commit A, B|ok"
  - "feature branch|commits C, D|app"
  - "Merge|back into main|cp"
@h Practise
```bash title="Make a feature branch" lab
cd ~/git-lab
git switch -c feature/subtract
printf '\ndef sub(a, b):\n    return a - b\n' >> calc.py
git commit -am "Add sub() function"
git log --oneline --graph --all
git switch main && cat calc.py     # sub() is not here yet
```
@check
Why does main not contain sub() after the commit? || The commit exists only on the feature branch until it is merged.
@end

@concept Merging and fast-forward
@plain
**Merging** combines the history of one branch into another. If main has not moved, Git just advances its label, called a fast-forward. Otherwise it creates a merge commit.
@problem
You need a way to bring finished work together while keeping a record of what came from where.
@does
- `git merge feature/subtract` from main integrates the branch.
- `--no-ff` forces a merge commit even when a fast-forward is possible, keeping the branch visible.
- Teams may prefer rebase or squash merges for a linear history; follow the team's rule.
@diagram cmp
caption: Three ways to land a branch
cards:
  - {h: "Merge commit", kind: app, items: ["Keeps full history", "Shows the branch shape"]}
  - {h: "Squash merge", kind: ok, items: ["One commit on main", "Hides intermediate steps"]}
  - {h: "Rebase then fast-forward", kind: info, items: ["Linear history", "Rewrites branch commits"]}
@h Practise
```bash title="Merge the feature" lab
cd ~/git-lab
git switch main
git merge --no-ff feature/subtract -m "Merge feature/subtract"
git log --oneline --graph
git branch -d feature/subtract
```
@end

@concept Merge conflicts
@plain
A **conflict** happens when two branches change the same lines differently. Git stops and marks the file so a human decides.
@problem
Git cannot know which version of a line is right. Guessing would silently lose someone's work.
@does
- Conflict markers show both sides: `<<<<<<<` (yours), `=======`, `>>>>>>>` (theirs).
- You edit the file to the correct result, remove the markers, `git add` it and finish with `git commit` (or `git merge --continue`).
- `git merge --abort` returns to the state before the merge.
@diagram seq
caption: Resolving a conflict
actors: ["You|local clone|app", "Git|merge machinery|cp"]
steps:
  - "0>1: git merge other | req"
  - "1>0: CONFLICT in calc.py | bad"
  - "note 0..0: edit file, remove markers"
  - "0>1: git add, git commit | req"
  - "1>0: merge complete | resp"
@h Create and fix a conflict
```bash title="Conflict on purpose" lab
cd ~/git-lab
git switch -c left && sed -i.bak 's/Git lab/Left title/' README.md && rm README.md.bak && git commit -am "Left title"
git switch main && git switch -c right && sed -i.bak 's/Git lab/Right title/' README.md && rm README.md.bak && git commit -am "Right title"
git merge left          # reports a conflict in README.md
git status              # both modified
printf '# Merged title\n' > README.md     # simplified resolution for this lab only
git add README.md && git commit -m "Resolve title conflict"
```
:::note
The `sed -i.bak` form works on both macOS and Linux. In real work open the file and read both sides before choosing.
:::
@check
How do you cancel a merge that has gone wrong? || `git merge --abort`.
@end

@concept Remotes and pull requests
@plain
A **remote** is another copy of the repository, usually on GitHub or GitLab. You push your branch there and open a **pull request** (merge request) so teammates review it.
@problem
Review before merge catches bugs, shares knowledge and lets CI run on every change.
@does
- `git remote add origin <url>` links a remote; `git push -u origin branch` publishes the branch.
- The pull request shows the diff, comments and CI results. Protected branches can require approvals and green checks.
- `git pull` is fetch plus merge. `git fetch` alone is safe: it updates your view of the remote only.
@diagram flow
caption: The pull request loop
numbered: true
nodes:
  - "Branch|local commits|app"
  - "Push|to origin|info"
  - "Pull request|review and CI|cp"
  - "Approve and merge|into main|ok"
  - "Pull main|everyone syncs|plain"
@h Commands
```bash title="Publishing a branch" nocheck
git remote add origin git@github.com:YOUR-USER/git-lab.git
git push -u origin main
git switch -c feature/docs
git commit -am "Improve docs"
git push -u origin feature/docs        # then open the pull request in the web UI
git fetch origin && git log --oneline main..origin/main    # what arrived upstream
```
@check
Why prefer git fetch to git pull when unsure? || Fetch only downloads; it cannot change your working files or create a merge.
@end

@concept Undoing mistakes safely
@plain
Git rarely loses committed work. There is a safe tool for each kind of mistake, and a few dangerous ones.
@problem
Panic after a wrong command leads people to delete the repository and re-clone, losing local work that was recoverable.
@does
- Uncommitted file edit: `git restore file` discards it (permanent).
- Wrong last commit message or a missed file: `git commit --amend` (only before pushing).
- Bad commit already shared: `git revert <sha>` adds a new commit that undoes it.
- Lost commits after a reset: `git reflog` lists where HEAD has been; `git switch -c rescue <sha>` brings one back.
- `git reset --hard` and `git push --force` can destroy work; use `--force-with-lease` if you must.
@diagram cmp
caption: Pick the undo that matches the situation
cards:
  - {h: "Not committed", kind: warn, items: ["git restore file", "Discards edits for good"]}
  - {h: "Committed, not pushed", kind: info, items: ["git commit --amend", "git reset --soft HEAD~1"]}
  - {h: "Already pushed", kind: ok, items: ["git revert sha", "History stays intact"]}
  - {h: "Seems lost", kind: app, items: ["git reflog", "Recover by creating a branch"]}
@h Rescue drill
```bash title="Reset too far, then recover" lab
cd ~/git-lab
git switch main
git log --oneline | head -3
git reset --hard HEAD~1       # throws away the latest commit from the branch
git reflog | head -3          # the lost commit is still listed
git reset --hard HEAD@{1}     # go back to where you were
git log --oneline | head -3
```
:::warn
Reflog entries expire after weeks and exist only locally. Never rely on it for anything shared.
:::
@end

@concept A team workflow checklist
@plain
Teams agree on a small set of rules so history stays readable and main stays releasable.
@problem
Without conventions each person integrates differently, main breaks, and nobody knows what is deployed.
@does
- Branch from an up-to-date main, keep branches short lived (days, not weeks).
- Open small pull requests; run tests in CI before review.
- Protect main: require review, passing checks, and block force pushes.
- Add a `.gitignore` early; never commit secrets. If one leaks, rotate it, because deleting the commit does not make it secret again.
@diagram flow
caption: One change from idea to main
nodes:
  - "Issue|what and why|plain"
  - "Short branch|from main|app"
  - "PR plus CI|tests, lint, scan|cp"
  - "Review|one or two approvals|info"
  - "Merge|main stays green|ok"
@h Guard rails
```bash title="Ignore files and scan for secrets" lab
cd ~/git-lab
printf '.env\n*.pem\n__pycache__/\n' > .gitignore
git add .gitignore && git commit -m "Add gitignore"
git log -p --all -S'AKIA' --oneline | head      # search history for an AWS key prefix
git check-ignore -v .env
```
@check
A key was committed and then removed in the next commit. Is it safe? || No. It remains in history and clones; rotate the key.
@end
