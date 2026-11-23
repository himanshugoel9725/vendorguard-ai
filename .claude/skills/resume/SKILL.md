---
name: resume
description: Resume VendorGuard AI work exactly where the last session stopped. Use at the start of every session and after /clear or /compact.
---

# Resume work

1. Read `docs/PROGRESS.md` (Status, Environment facts, unchecked tasks, In-progress notes) and the section of
   `docs/PLAN.md` §11 for the next task.
2. Run `git status` and `git log --oneline -5`.
   - If there are uncommitted changes, work out which task they belong to (In-progress notes + commit
     history). Finish that task or checkpoint it before anything else.
3. If `src/` exists, run `make check`. If it fails, fixing it is the next task (record that in PROGRESS).
4. Report to the user in at most 8 lines:
   - current phase and last completed task
   - next task: ID, title, slot and minutes, and its "Done when"
   - anything the user must do by hand (👤 tasks) with exact commands
5. Then start the next task. If it is a 👤 task, give the exact commands and wait for the user.
