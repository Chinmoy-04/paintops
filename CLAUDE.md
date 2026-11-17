# PaintOps — project instructions

PaintOps is a learning project built phase by phase. These rules apply in every chat.

## Before doing anything

1. Read `docs/MASTER_PLAN.md` (the approved plan) and `docs/PROGRESS.md` (what is done,
   known gaps, and "Next phase: start here").
2. Build **only the one phase** the user asks for.
3. Check out `main`, pull, and verify that `main` contains the previous phase's merged PR.
   If it does not, stop and tell the user. Then confirm in one short message what this
   phase will build before starting.

## Follow the plan strictly

- Do not add, drop, reorder, or substitute features, libraries, or services.
- If something is wrong or impossible, stop and ask. Record any agreed change in
  `docs/MASTER_PLAN.md` and `docs/PROGRESS.md`.
- Each phase: branch from `main` with the branch name in the plan, write and verify the
  basics lab first, then the phase scope, then the lesson note in `docs/learn/`.

## Tests

```bash
.venv/Scripts/python.exe -m pytest -q
```

All tests must pass before a commit. Before saying something works, run it.

## Finishing a phase

- The phase's final commit updates `docs/PROGRESS.md` (status, what was built, decisions,
  known gaps, and the next phase's "start here" notes).
- Push, then open the PR. `gh` is not installed: open the PR in the built-in browser pane
  (signed in to GitHub) using the compare URL with title and body prefilled. If the pane
  can't be used, give the user the link.
- Then **stop**. Never continue into the next phase in the same chat, even if asked to
  "keep going": tell the user to open a new chat.

## No attribution

Never add `Co-Authored-By` lines for Claude, "Generated with Claude Code" lines, or list
Claude as a collaborator anywhere (commits, PRs, docs, code).
