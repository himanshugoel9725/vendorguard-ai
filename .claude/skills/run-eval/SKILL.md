---
name: run-eval
description: Run the VendorGuard evaluation matrix (deciders x embeddings x LLM) on the synthetic sample vendors and update docs/EVALUATION.md. Use in Phase 9 and after any prompt, decider or retrieval change.
---

# Run the evaluation

1. Pre-flight: `uv run vg doctor` must show Ollama reachable. Jev configs run only if
   `VG_DECISION__JEV__API_KEY` is set (doctor shows set/unset); otherwise they are skipped with a note.
   Never print key values.
2. Make sure the sample data exists: `make sample` (it is deterministic; there should be no git diff).
3. Run `make eval` (or `uv run vg eval --configs <names>` for a subset). This is machine time: on a laptop
   each config can take several minutes. Tell the user the estimate before starting.
4. Results go to `docs/evaluation/results.json`. Check that every config has: accuracy, macro-F1,
   per-status precision/recall, citation validity, human-review rate, triage skip rate, LLM calls,
   generative tokens, decider calls, wall time and estimated cost.
5. Determinism: confirm the replay run is 100 % identical and report the cache-off repeat agreement.
6. Regenerate charts (`eval/charts.py`) and ask the `docs-writer` sub-agent to update `docs/EVALUATION.md`
   and the README evaluation section, using only numbers from `results.json`. Always mention that the data is
   synthetic.
7. `make check`, then `/checkpoint`.
