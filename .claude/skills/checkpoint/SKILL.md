---
name: checkpoint
description: Save progress after finishing a VendorGuard task - run checks, update docs/PROGRESS.md, commit. Use after every completed task ID and before /compact or /clear.
---

# Checkpoint

1. Run `make check` (and `bash scripts/check_no_hf.sh` once it exists). If anything is red, fix it first.
   If it cannot be fixed now, record it under **Blockers** and **In-progress notes** instead of committing
   broken code.
2. Update `docs/PROGRESS.md`:
   - tick the finished task
   - Status: current phase, next task, last completed task, today's date as "Last updated", blockers
   - In-progress notes: anything the next session must know
   - Session log: add a row (date, task IDs, notes or deviations)
   - Environment facts, if something changed
3. If a design decision was made or changed, append an ADR to `docs/DECISIONS.md`.
4. Stage and verify that no secret is staged:
   - `git add -A`
   - `git diff --cached --name-only` must not list `.env` or any key file. If it does, unstage it and fix
     `.gitignore`.
5. Commit: `git commit -m "[T<id>] <imperative summary>"`.
6. If this task completes a phase:
   - run the `code-reviewer` sub-agent first and fix blockers (separate commit)
   - `git tag phase-<n>-done`
   - ask the user to push (`git push && git push --tags`) and to confirm that CI is green
7. Print: finished task, next task (ID, title, minutes), and any 👤 action needed.
