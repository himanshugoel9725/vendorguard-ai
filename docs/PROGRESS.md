# Progress

> Updated by `/checkpoint` after every task and imported into every Claude Code session through `CLAUDE.md`.
> Task details and "Done when" criteria: `docs/PLAN.md` §11.

## Status

| Field | Value |
|---|---|
| Current phase | 2: Domain models, controls, synthetic vendors |
| Next task | 2.5 |
| Last completed task | 2.4 |
| Last updated | 2026-11-23 |
| Blockers | none |

## Environment facts (fill in during Phase 0)

| Fact | Value |
|---|---|
| Mac RAM | 16 GB, Intel x86_64 (CPU-only Ollama, slow) |
| Local LLM (`llm.model`) | qwen2.5:3b pulled (Intel CPU-only; settings.yaml still says 7b, change at Phase 4) |
| Embedding model | nomic-embed-text |
| Docker Desktop installed | no (needed only for self-hosted Letta, Phase 7) |
| Jev access route | none yet (TypeSafe console / OpenRouter / Vercel AI Gateway / Cloudflare) |
| Letta mode | self_hosted (cloud only for the final demo) |
| Hosted LLM fallback | OpenAI (paid) and Groq (free), keys in .env; use synthetic docs only |

## Checklist

### Phase 0: Setup 👤 (77 min)
- [x] 0.1 Install git, gh, uv, ollama; VS Code + Claude Code
- [x] 0.2 Pull Ollama models (qwen2.5:7b or 3b, nomic-embed-text)
- [x] 0.3 Smoke-test the model
- [x] 0.4 Connect the folder to the GitHub repo
- [x] 0.5 Unzip the starter kit, create `.env`
- [x] 0.6 Fix the repo description and topics
- [x] 0.7 First commit and push
- [ ] 0.8 Install Docker Desktop
- [x] 0.9 (Optional) Jev access, Letta Cloud key, both in `.env` only
- [x] 0.10 Open Claude Code and send the first message

### Phase 1: Foundation (125 min)
- [x] 1.1 pyproject, uv, dependencies, no-HF guard
- [x] 1.2 Package skeleton
- [x] 1.3 config.py (YAML + env + .env, validation, fingerprint)
- [x] 1.4 errors.py + logging_setup.py (redaction)
- [x] 1.5 utils: hashing, jsonio, ids, timeutil
- [x] 1.6 Makefile, ruff, mypy, pytest, pre-commit
- [x] 1.7 conftest + tests (test-writer)
- [x] 1.8 CI workflow + Dependabot
- [x] 1.9 Checkpoint, push, CI green, tag phase-1-done

### Phase 2: Models, controls, synthetic vendors (125 min)
- [x] 2.1 Pydantic data contracts
- [x] 2.2 Control-set loader
- [x] 2.3 Vendor specs (nimbara-hr, quillfield, brightdock, nimbara-hr-y2)
- [x] 2.4 Phrase bank + deterministic PDF/TXT generator + evidence maps
- [ ] 2.5 Golden labels
- [ ] 2.6 Tests (test-writer)
- [ ] 2.7 Checkpoint, tag phase-2-done

### Phase 3: Ingestion and retrieval (130 min)
- [ ] 3.1 Loaders (dispatch, PDF, text)
- [ ] 3.2 Text cleaner
- [ ] 3.3 Chunker
- [ ] 3.4 Tokenizer + BM25 index
- [ ] 3.5 Embedders (Ollama, null, cached)
- [ ] 3.6 Vector index, query builder, hybrid retriever
- [ ] 3.7 Tests (3 parallel test-writers) + coverage gate 80 %
- [ ] 3.8 Checkpoint, tag phase-3-done

### Phase 4: LLM providers, cache, cost guard (150 min)
- [ ] 4.1 LLM models + interfaces
- [ ] 4.2 Ollama LLM provider
- [ ] 4.3 OpenAI-compatible provider
- [ ] 4.4 Mock provider (keyword baseline)
- [ ] 4.5 Cache keys, SQLite/JSONL backends, CachedLLM
- [ ] 4.6 Cost tracker + budget guard
- [ ] 4.7 Prompt loader
- [ ] 4.8 Factory registries
- [ ] 4.9 Tests (parallel test-writers)
- [ ] 4.10 Checkpoint, tag phase-4-done

### Phase 5: Agents and decision layer (240 min)
- [ ] 5.1 BaseAgent
- [ ] 5.2 Intake Agent + inherent risk
- [ ] 5.3 Mapper Agent
- [ ] 5.4 Citation checker
- [ ] 5.5 Rule decider
- [ ] 5.6 LLM-judge decider
- [ ] 5.7 Jev decider + fallback
- [ ] 5.8 Reviewer Agent
- [ ] 5.9 Rules engine + bands
- [ ] 5.10 Reporter Agent + summary guard + fallback summary
- [ ] 5.11 Tests (parallel test-writers)
- [ ] 5.12 Code review + checkpoint, tag phase-5-done

### Phase 6: Orchestrator, CLI, reports, first real run (180 min)
- [ ] 6.1 Audit log, run manifest, metrics
- [ ] 6.2 RunContext, control cascade, orchestrator
- [ ] 6.3 JSON / Markdown / HTML reports
- [ ] 6.4 CLI commands
- [ ] 6.5 Analyst override flow
- [ ] 6.6 Integration test (mock, golden)
- [ ] 6.7 First real Ollama run + record cassettes + replay test
- [ ] 6.8 Checkpoint, tag phase-6-done

### Phase 7: Memory, re-assessment, Letta (160 min)
- [ ] 7.1 SQLite memory store
- [ ] 7.2 Re-assessment diff + vendor history
- [ ] 7.3 Ask Agent + `vg ask`
- [ ] 7.4 👤 Start self-hosted Letta
- [ ] 7.5 Letta memory store + assistant
- [ ] 7.6 Letta Cloud credit guard
- [ ] 7.7 Tests
- [ ] 7.8 Memory demo (y1 → y2 → diff → ask)
- [ ] 7.9 Code review + checkpoint, tag phase-7-done

### Phase 8: REST API and Docker (115 min)
- [ ] 8.1 App factory + system routes
- [ ] 8.2 API security (security-auditor)
- [ ] 8.3 Assessment and vendor routes
- [ ] 8.4 Background jobs
- [ ] 8.5 API tests
- [ ] 8.6 Dockerfile + compose api service
- [ ] 8.7 Checkpoint, tag phase-8-done

### Phase 9: Evaluation (150 min)
- [ ] 9.1 Metrics
- [ ] 9.2 Eval runner + `vg eval`
- [ ] 9.3 Determinism check + test
- [ ] 9.4 Full matrix run with Ollama
- [ ] 9.5 Charts + EVALUATION.md (docs-writer)
- [ ] 9.6 Checkpoint, tag phase-9-done

### Phase 10: CI/CD, docs site, demo (128 min)
- [ ] 10.1 Final CI
- [ ] 10.2 MkDocs site + generated CONFIG.md (docs-writer)
- [ ] 10.3 Pages workflow with replay demo reports
- [ ] 10.4 👤 Enable GitHub Pages
- [ ] 10.5 Release workflow (GHCR)
- [ ] 10.6 (Optional) Render API demo
- [ ] 10.7 Final README pass (docs-writer)
- [ ] 10.8 Checkpoint, tag phase-10-done

### Phase 11: Hardening and release (80 min)
- [ ] 11.1 Security audit + fixes
- [ ] 11.2 👤 Record the demo video
- [ ] 11.3 Tag v1.0.0
- [ ] 11.4 👤 Submission form
- [ ] 11.5 Final checkpoint

### Phase 12 (optional): UI (140 min)
- [ ] 12.1 Choose the UI stack (ADR)
- [ ] 12.2 UI skeleton + API client
- [ ] 12.3 Upload and run page
- [ ] 12.4 Findings and override page
- [ ] 12.5 History, diff and ask page
- [ ] 12.6 Deploy
- [ ] 12.7 Checkpoint

## In-progress notes

Half-finished work, uncommitted changes, or things the next session must know:

- 1.4: `setup_logging(app, secrets)` is called by cli/ and api/ with `collect_secrets(settings)`. Redaction also pattern-matches `Bearer`, `sk-` and `gsk_` tokens; secrets stored under non-`VG_` names are only caught by those patterns.
- 1.5: `canonical_json` refuses SecretStr, NaN/inf and unknown types on purpose. `make_run_id(vendor_id, input_hashes, config_fingerprint, deterministic=...)`; pass `pipeline.deterministic_run_ids`. In 1.6, consider a ruff banned-api rule so only `utils/timeutil.py` reads the clock (`datetime.now`, `time.time`).
- 1.6: `make check` = ruff + ruff format --check + mypy strict + pytest. Ruff excludes `*.md` (0.17 reformats code blocks in docs). `make api` calls `python -m vendorguard.api.app` (implement `__main__` reading host/port from settings in 8.1); `make record` expects `vg assess` and `data/samples/specs/*.yaml` (Phases 2 and 6). Coverage gate (`fail_under = 80`) still to be enabled in 3.7. `tests/unit/test_smoke.py` is a trivial import test.
- 1.7: 206 tests, 83 % coverage. pytest uses `--import-mode=importlib` (duplicate test basenames are fine). `settings_override(**nested_overrides)` fixture in `tests/conftest.py` is hermetic (mock LLM, temp paths, never reads .env); overrides deep-merge with the YAML, so a nested dict cannot empty a table.
- 1.8: CI = `.github/workflows/ci.yml` (frozen sync, no-HF guard, ruff, format check, mypy, pytest with coverage report). gitleaks and the Python 3.12/3.13 matrix arrive in 10.1. Actions pinned to full commit SHAs with the version in a comment (setup-uv publishes no floating major tag, so `@v10` failed on GitHub); Dependabot bumps them. CI has not run on GitHub yet (nothing pushed since the T0 commit).
- 1.9 review (code-reviewer, verdict: ready, no blockers). Fixed: YAML secret guard now covers lists and blank strings; fingerprint uses `hash_obj` and drops `SecretStr` by type; more redaction patterns (Gemini AIza, Basic, URL credentials, key=value); canonical_json rejects str-key collisions. **Deferred (do before Phase 4/10):** (a) pin pre-commit revs to commit SHAs (Actions already pinned); (b) the redaction filter is attached to the handler from `setup_logging` only, so any new handler (file, server) must add `RedactingFilter` too, and `extra=` record attributes are not redacted; (c) `DEFAULT_CONFIG` and `env_file=".env"` are cwd/editable-install relative (fine locally; revisit for Docker in 8.6); (d) unknown top-level `VG_` env vars are silently ignored; (e) secrets shorter than 4 chars would mangle logs (real keys never are).
- Tag `phase-1-done` is on GitHub at 9def0f5 (its CI run failed on the action pin); the green commit is 2841032. Moving it needs a force push, which `.claude/settings.json` denies; the user can run `git tag -f phase-1-done 2841032 && git push --force origin phase-1-done` themselves.
- 2.4: `make sample` writes `data/samples/<stem>.{pdf,txt,evidence.json}` (12 files, committed, ADR-011). Code: `src/vendorguard/eval/sample_gen/`; settings: new `samples:` section. Specs' summaries were reworded to avoid the keyword `personal data`. The evidence JSON has 25 entries per vendor (`state`, `page`, `sentence`, `variant`; null when the control is missing). For 3.6: gold sentences come from `evidence.json`. For 4.4: use `utils/keywords.py` for matching and read `data_category_phrases` in `phrases.yaml` for the intake mock. Generator tests (determinism, drift, pypdf, y2 wording) are in `tests/unit/eval/sample_gen/`; 2.6 adds the rest.
- ENVIRONMENT (macOS + iCloud Drive): the project is in ~/Documents, which iCloud syncs, and iCloud kept setting the `hidden` flag on files inside `.venv`; Python 3.12 ignores hidden `.pth` files, so `import vendorguard` failed. Fix applied: the environment is `.venv.nosync/` (iCloud ignores `.nosync`) with a `.venv` symlink to it. If it breaks after a rebuild, run `rm -rf .venv .venv.nosync && UV_PROJECT_ENVIRONMENT=.venv.nosync uv sync --all-groups && ln -s .venv.nosync .venv`. Moving the repo out of ~/Documents (for example to ~/code) is safer still, especially for `.git`.
- 2.3: specs live in `data/samples/specs/*.yaml`, parsed by `vendorguard.eval.specs` (`load_spec`, `check_covers`, `SampleState.to_status()`; `missing` maps to `no_evidence`). The y2 spec keeps `vendor_id: nimbara-hr` (same vendor, new period) and declares `changes.fixed` / `changes.new_gaps` for the 7.2 diff test. Brightdock has data category `none`, so its inherent tier is low. Tests: `tests/unit/eval/test_specs.py` (16).
- 2.2: `load_controls(path)` returns a `ControlSet` sorted by ID; `ControlSet.subset(ids)` returns only those controls (empty list gives an empty set, so the orchestrator must treat `pipeline.controls_subset: []` as all). Errors are `ConfigError` naming the control. Tests in 2.6.
- 2.1: models in `src/vendorguard/models/` (see ADR-010). Tests for them come in 2.6.
- Task 4.8 must add a registry-vs-Literal test (ADR-009).

## Session log

| Date | Tasks completed | Notes / deviations |
|---|---|---|
| 2026-11-23 | Phase 0, 1.1-1.9, 2.1-2.4 | Docker deferred to Phase 7. Intel Mac: prefer Groq/OpenAI via openai_compat for real runs. OpenAI+Groq need two key profiles (ADR pending, Phase 4). |
