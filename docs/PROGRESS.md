# Progress

> Updated by `/checkpoint` after every task and imported into every Claude Code session through `CLAUDE.md`.
> Task details and "Done when" criteria: `docs/PLAN.md` §11.

## Status

| Field | Value |
|---|---|
| Current phase | 5: Agents and the decision layer |
| Next task | 5.8 |
| Last completed task | 5.7 |
| Last updated | 2026-11-23 |
| Blockers | none |

## Environment facts (fill in during Phase 0)

| Fact | Value |
|---|---|
| Mac RAM | 16 GB, Intel x86_64 (CPU-only Ollama, slow) |
| Local LLM (`llm.model`) | qwen2.5:3b (settings.yaml now says 3b; Intel CPU-only, about 6 s per short request) |
| Embedding model | nomic-embed-text |
| Docker Desktop installed | no (needed only for self-hosted Letta, Phase 7) |
| Jev access route | none yet (TypeSafe console / OpenRouter / Vercel AI Gateway / Cloudflare) |
| Letta mode | self_hosted (cloud only for the final demo) |
| Hosted LLM | OpenAI `gpt-6-luna` (paid) and Groq `openai/gpt-oss-20b` (free plan); keys in .env as VG_LLM__OPENAI__API_KEY / VG_LLM__GROQ__API_KEY (the user must rename theirs if needed); synthetic docs only |

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
- [x] 2.5 Golden labels
- [x] 2.6 Tests (test-writer)
- [x] 2.7 Checkpoint, tag phase-2-done

### Phase 3: Ingestion and retrieval (130 min)
- [x] 3.1 Loaders (dispatch, PDF, text)
- [x] 3.2 Text cleaner
- [x] 3.3 Chunker
- [x] 3.4 Tokenizer + BM25 index
- [x] 3.5 Embedders (Ollama, null, cached)
- [x] 3.6 Vector index, query builder, hybrid retriever
- [x] 3.7 Tests (3 parallel test-writers) + coverage gate 80 %
- [x] 3.8 Checkpoint, tag phase-3-done

### Phase 4: LLM providers, cache, cost guard (150 min)
- [x] 4.1 LLM models + interfaces
- [x] 4.2 Ollama LLM provider
- [x] 4.3 OpenAI-compatible provider
- [x] 4.4 Mock provider (keyword baseline)
- [x] 4.5 Cache keys, SQLite/JSONL backends, CachedLLM
- [x] 4.6 Cost tracker + budget guard
- [x] 4.7 Prompt loader
- [x] 4.8 Factory registries
- [x] 4.9 Tests (parallel test-writers)
- [x] 4.10 Checkpoint, tag phase-4-done

### Phase 5: Agents and decision layer (240 min)
- [x] 5.1 BaseAgent
- [x] 5.2 Intake Agent + inherent risk
- [x] 5.3 Mapper Agent
- [x] 5.4 Citation checker
- [x] 5.5 Rule decider
- [x] 5.6 LLM-judge decider
- [x] 5.7 Jev decider + fallback
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
- 5.7: ADR-016. `providers/decide/jev_client.py` `JevClient(settings.decision.jev, settings.llm)` (OpenRouter Decisions API, alpha; `ask(state, questions) -> (P(yes) per question, Usage)`), `jev.py` `JevDecider(client, jev, audit, cost)` (one `noul` question per gate; audit stage `jev.triage`/`jev.verify`; counts toward `max_calls_per_run`; cost kind `decider`), `fallback.py` `FallbackDecider(primary|None, fallback, audit, primary_name=, unavailable=)`, `mock.py` `MockDecider` (= rules named `mock`). `DECIDERS` now has rule, mock, llm_judge, jev (the registry test is EQUALITY now). `build_decider(settings, deps)` for `jev` needs `DeciderDeps` (audit + cost) and returns a FallbackDecider even without a key (done-when: the run completes with one warning). settings.yaml: `decision.jev.base_url` is now `https://openrouter.ai/api/alpha`, model `typesafe/jev-1.13`. Fixture is hand-written, NOT recorded; the `jev` live test is skipped without a key. 👤 (optional, later): put `VG_DECISION__JEV__API_KEY` (an OpenRouter key) in `.env`, then `uv run pytest -o addopts='' -m jev tests/live` and replace `tests/fixtures/jev/*.json` with real replies. The Jev HTTP client is not closed by `Providers.close()` (decider is built separately): 6.2 should close it if it holds the decider's client. 5.8 reviewer is next.
- 5.6: `prompts/judge.v1.md` (one prompt, `task` = triage|verify; documents in `<document>` tags; the signal phrases come from `decision.rule.*`) + `providers/decide/llm_judge.py` `LlmJudgeDecider(llm, prompts, audit, cost, settings.decision.rule)`, name `llm_judge`; an internal `BaseAgent` (`name='judge'`) so every call writes ONE audit event (stage `judge`, control_id). The label comes from `JudgeOutput`; a label of the wrong kind degrades safely (triage -> addressed at confidence 0 so nothing is skipped; verify -> unsupported so the Reviewer looks). On the mock it agrees 100 % with the rule decider (same `rule_logic`). FACTORY CHANGE: `DECIDERS` builders are now `(settings, deps: DeciderDeps | None)`; `build_decider(settings, deps=None)`; `DeciderDeps(llm, prompts, audit, cost)`; `llm_judge` without deps is a ConfigError, so the orchestrator (6.2) must pass deps. Not tried on a real model yet (use `make test-live`/hosted later; a prompt change = judge.v2 + `make record`). 5.7: jev and mock deciders are still missing from the registry (tighten the equality test then).
- 5.5: `verification/rule_logic.py` (`triage_verdict`, `verify_verdict`, `Verdict`) is the ONE rule formula; `providers/decide/rule.py` `RuleDecider(settings.decision.rule)` and the mock LLM judge both call it (mock hint `top_score` optional). Registered in `DECIDERS['rule']`; 4.8's equality test for the decider registry still to be tightened when 5.7 registers the last entry (llm_judge 5.6, jev 5.7, mock 5.7). ADR-015: the retrieval floor uses raw cosine (`vector_raw`), NOT BM25 (unbounded). MEASURED on the 4 samples (BM25-only, mock mapper): triage skips 15 of 100 control checks, 0 wrongly; verify supports every mock draft (0 unsupported). The Decision thresholds `triage_threshold`/`verify_threshold` are applied by the cascade (6.2), not by the decider. 5.6 LLM judge must follow the same labels; 5.11 adds edge tests.
- 5.4: `verification/text_normalize.py` `normalize_text` (NFKC, curly quotes/dashes to ASCII, casefold, whitespace collapsed) and `verification/citation_check.py` `CitationChecker(settings.verification).check(status, draft_citations, chunks) -> CitationReport(citations, ok, problems)`. Exact normalised substring = 1.0; else best-window difflib ratio (window aligned from the matching blocks) >= `citation_min_similarity`; unknown chunk_id or quote longer than `max_quote_chars` = invalid; doc_id/page attached; `ok` is false if any quote is invalid OR the status is in `require_citation_for` and no quote is valid. `problems` hold no quote text (safe for audit/reviewer flags). The cascade (6.2) must pass the SAME chunks the Mapper saw (plus the Reviewer's extra chunks). Tests: `tests/unit/verification/test_citation_check.py` (8); 5.11 adds edge/property tests. Not yet wired into a factory or audit event (cascade, 6.2).
- 5.3: `prompts/mapper.v1.md` + `agents/mapper.py` `MapperAgent(llm, prompts, audit, cost, settings.verification, settings.decision.rule).map(control, evidence: Sequence[ScoredChunk]) -> DraftFinding`. No evidence -> `no_evidence` finding WITHOUT a model call or audit event. Chunks are sent sorted by chunk_id in `<document>` tags; the negative/partial signal phrases in the prompt come from `decision.rule.*_signal_phrases` (one list for prompt and rule decider). Mock hints `{keywords, chunks, max_quote_chars}`. Mock mapper matches the golden labels 100 % on all 4 samples (target 85 %). Not yet tried on a real model; citations are verified in 5.4.
- 5.2: `prompts/intake.v1.md` (first prompt file; still v1 because nothing has been recorded against it: once cassettes exist, never edit in place, add v2), `agents/intake.py` `IntakeAgent(llm, prompts, audit, cost, settings.intake).extract(chunks) -> VendorProfile` (sorts chunks by id, sends the first `intake.max_chunks` inside `<document chunk_id page>` tags; prompt variables `chunks, max_items, max_chars, categories`; mock hints `{text}`), `scoring/inherent_risk.py` `inherent_risk(profile, settings.scoring.inherent_risk) -> InherentRisk(tier, reasons)` (high if any category in `high_if_any`, else medium if in `medium_if_any`, else low; reasons name the deciding categories, sorted). Done-when verified on the mock: nimbara-hr and nimbara-hr-y2 HIGH, quillfield MEDIUM, brightdock LOW, every spec fact recovered. LIVE with real qwen2.5:3b (CPU, 22-41 s per vendor): the 'report only what the text states' rule works (no invented facts any more; names, services, certifications, period copied exactly), BUT data categories are unreliable on a 3B model (nimbara-hr got customer_content+credentials instead of pii+financial: tier high for the wrong reason; quillfield missed pii and once a certification). Do not tune the prompt further for a 3B model: measure with OpenAI/Groq (`make test-hosted` first) and in Phase 9; IF hosted models also under-report categories, consider a deterministic cross-check that unions keyword-detected categories into the profile (inherent risk drives the score multiplier, so understating is the dangerous direction).
- 5.1: `agents/base.py` `BaseAgent[OutT]` (PEP 695 generic): a subclass sets `name` (the prompt file name, the LLM `purpose` and the audit stage) and `output_model`, then `run(variables, hints=None, control_id=None) -> OutT` renders `prompts.render(name, **variables)`, calls `llm.complete_json(messages, output_model, purpose=name, hints=hints)` and writes EXACTLY ONE audit event: `stage=name` with the SHA-256 of the rendered messages and of the output, tokens, `usd` (from `CostTracker.cost_of`, 0 for cache replays), latency, cached; on `VendorGuardError` it writes `stage='<name>.failed'` (tokens from `paid_usage`, output_hash = hash of the error class) and re-raises; a missing prompt variable (ConfigError) and unexpected exceptions write nothing. New `interfaces/audit.py` `AuditSink.record(*, stage, actor, input_hash, output_hash, tokens_in, tokens_out, usd, latency_ms, cached, control_id=None, decision=None) -> AuditEvent`: task 6.1's `AuditLog` must implement it and add run_id, seq and ts (via `utils/timeutil`). New `CostTracker.cost_of(provider, model, usage)`. Constructor: `Agent(llm, prompts, audit, cost)`. Concrete agents (5.2+) only build prompt variables and mock hints (contract in the `MockLLM` docstring) and stay under 80 lines.
- 4.10 review (code-reviewer, verdict: ready, no blockers; security summary clean: keys are never in a log, cache key/entry, cassette, error text or fingerprint, redirects off, TLS on). FIXED (ADR-014 addendum): paid-but-failed calls and over-cap calls are charged and not lost (`paid_usage` on exceptions, BudgetedLLM defers the stop to the next call), the mock is not budgeted or counted, truncated replies are a clear error, exponential backoff, https-only keys, atomic + locked JSONL cassettes, CachedLLM survives cache write failures, `json_repair_attempts` in the cache key, mock malformed hints -> LLMError, word-boundary change words, settings comments, Makefile note. 1644 tests, 97.8 %. FOR LATER: (a) TASK 5.5 must make the rule decider and the mock judge share ONE confidence formula and read the WHOLE quote for signals (today the mock reads the first keyword sentence and ignores `triage_min_retrieval_score`): reuse `verification/keyword_reading.py`; (b) `make record` is not runnable until the CLI of Phase 6 exists, and 6.x must call `Providers.close()` in a `finally` and fix `--vendor` for the y2 spec; (c) the cassette folder must be written by one process at a time; (d) the prompt sandbox still allows large `str.ljust/center/format` widths (templates are repo-trusted, variables never evaluated); (e) `CachedLLM.hits/misses` counters are not locked; (f) `.vendorguard/cache.db` uses WAL files: keep `paths.state_dir` outside an iCloud folder if the repo stays in one; (g) NO hosted provider has been called for real: run `make test-hosted` and, if the model rejects `temperature`/`seed`/json_schema, set `omit_params` / `response_format: json_object`; if replies are cut off, raise `llm.max_output_tokens`.
- 4.9: 1603 tests, 97.8 % coverage. Three test-writer agents (about 250 new tests) for `providers/llm/` (+ keyword_reading), `providers/cache/` + cost tracker + LLM models, and prompt loader + factory + embedder modes. FIXED (found by the prompt-security tests): `Prompt.render` leaked raw `TypeError` (`{% import/include/extends %}`: no loader) and `OverflowError` (`range(10**9)`); any template failure is now a `ConfigError` naming only the exception class, and the sandbox caps `*` (100000 items) and `**` (exponent 1000) so `{{ 'a' * 10**10 }}` is refused instantly instead of exhausting memory. DOCUMENTED BEHAVIOURS (tests pin them; not bugs): SQLite get/put after close raise `sqlite3.ProgrammingError`; TWO PROCESSES RECORDING INTO ONE CASSETTE FOLDER CONCURRENTLY LOSE ENTRIES (last `save()` wins), so `make record` must stay sequential (it is); a key present in two purpose files: the later file name wins; `CachedLLM` has no single-flight (racing threads may each call the client, one entry results) and a failing cache `put` propagates after the client call; the mock `ask` fails with SchemaValidationError if more than 30 control IDs are cited (`AskOutput` allows 30; 25 controls today, revisit if the control set grows); Ollama has no 429 retry (hosted providers do); a UTF-8 BOM at the start of a prompt file gives 'missing front-matter'; duplicate YAML keys in front-matter: last wins; `settings.prompts` versions must match `^v\d+$`. Unit tests never touch `.venv*` or `.env`.
- 4.8: `vendorguard/factory.py`, the ONLY place concrete providers are created: registries `LLM_PROVIDERS` (ollama, openai, groq, openai_compat, mock), `EMBEDDERS` (ollama, none), `CACHE_BACKENDS` (sqlite, jsonl), `DECIDERS` and `MEMORY_STORES` (EMPTY until Phase 5 / Phase 7: `build_decider` / `build_memory_store` raise ConfigError 'not implemented yet'). `build_providers(settings) -> Providers(llm, embedder, cache, tracker, closers)` with `.close()` (call it at the end of every run: it closes HTTP clients and makes the JSONL cache write its sorted cassettes). Nesting: LLM = `CachedLLM(BudgetedLLM(client), on_hit=tracker.record_cache_hit)`; the mock is budgeted but NEVER cached; embedder = `CachedEmbedder(client, mode=cache.mode)` except `none`; `cache.enabled: false` gives no cache. `llm_cache_params(settings)` = generation settings (+ hosted profile options) for the cache key. `CachedEmbedder` gained modes (`off`, `read_write`, `read_only` raising CacheMissError). ADR-009 promise kept: tests assert the registries equal the config Literals for llm/embeddings/cache; for decider and memory they only assert subset, so TASKS 5.x AND 7.x MUST TIGHTEN `test_decider_and_memory_registries_only_contain_allowed_names` to equality when they register their last entry. Every registered entry builds with default (mock-style) settings (hosted ones with a fake key).
- 4.7: `utils/prompt_loader.py`: `PromptLoader(settings.paths.prompts_dir, settings.prompts)`, `.load(name) -> Prompt` (cached; `.meta` = id/version/output_model, `.prompt_hash` = SHA-256 of the template file with LF newlines, for the run manifest) and `.render(name, **variables) -> RenderedPrompt(messages, prompt_hash)`. File `prompts/<name>.<version>.md`, version from `settings.prompts`; front-matter `id`/`version`/`output_model` must match the file; sections `## system` / `## user` in file order. Jinja runs in a SANDBOX with StrictUndefined (missing variable or attribute = ConfigError naming it; variable contents such as document text are never interpreted; `__class__`-style access is blocked; no HTML escaping; trim_blocks/lstrip_blocks). Errors are ConfigError with the file name and line. The `prompts/` folder does not exist yet: the first files (mapper.v1.md etc., PLAN section 8) are written with the agents in Phase 5 (use `/add-agent`).
- 4.6: `observability/cost_tracker.py` `CostTracker(settings.cost)`: `price_for(provider, model)` (glob on `provider/model`, most specific pattern wins, no match = ConfigError so a paid model can never run unpriced), `ensure_budget(provider, model, kind)` (call BEFORE a model call: raises `BudgetExceededError` if `cost.max_llm_calls_per_run` or `max_usd_per_run` is already used up), `record(provider, model, usage, cached=, kind=llm|decider)` (raises if the call pushed the run over a limit), `record_cache_hit()`, `summary() -> CostSummary`. Dollars are exact decimals (1000 one-token calls sum to exactly $0.0001); decider calls are counted separately and do not use the LLM call cap; one warning each at `warn_at_fraction`; thread-safe. `providers/llm/budgeted.py` `BudgetedLLM(client, tracker)` applies it per call. WIRING FOR 4.8/6.2 (important): nest as `CachedLLM(BudgetedLLM(client, tracker), cache, mode, params, on_hit=tracker.record_cache_hit)` so only REAL calls are checked and paid and replays still work after the budget is spent (the first design, guard outside the cache, refused replays once the call budget was reached: found by a test). Mock and Ollama are priced 0 and share the same path.
- 4.5: `providers/cache/`: `keys.py` (`llm_key(provider, model, purpose, messages, schema, params, hints)` = SHA-256 of canonical JSON; the rendered messages are IN the key, so any prompt or input change forces a re-record, which makes the plan's separate `prompt_hash` redundant; `embedding_key(model, prefix, text)`, now used by `CachedEmbedder`), `SqliteCache(path)` (one lock, parameterised SQL, WAL, canonical JSON values, `close()`), `JsonlCache(dir)` (one `<purpose>.jsonl` per purpose, `put` appends, `save()`/`close()` rewrite sorted by key but ONLY if something was recorded, so a replay never touches cassettes; purposes must match `^[a-z][a-z0-9_]{0,31}$`; corrupt lines raise ConfigError; `tests/cassettes/**` is `-text` in .gitattributes). `providers/llm/cached.py` `CachedLLM(inner, cache, mode, params)`: `off` (cache untouched, no counters), `read_write`, `read_only` (miss raises `CacheMissError(... run make record)`, the client is never called); a replay has `cached=True` and ZERO usage; a damaged entry is a miss; failures are never cached; `.hits`/`.misses` count lookups. FOR 4.8 (factory): build the backend from `settings.cache` (enabled false -> no cache), pass `params` = {temperature, seed, top_p, max_output_tokens, context_window (+ response_format for hosted)}, never wrap the mock, and call `cache.close()` at the end of a recording run (JSONL only writes sorted on close). Entries hold model outputs that may quote documents: `.vendorguard/cache.db` is git-ignored; only cassettes recorded from the synthetic samples may be committed. Embedding vectors are large (about 15 KB each): record embeddings cassettes only if CI really needs `embeddings.provider=ollama`.
- 4.4: `MockLLM(settings.decision.rule)` (`providers/llm/mock.py`, helpers `mock_intake.py`, `mock_reports.py`): deterministic keyword baseline, zero usage, no network, ignores the chat messages and answers from `hints` (JSON-like dicts; the CONTRACT the Phase 5 agents must follow is in the module docstring: intake `{text}`; mapper `{keywords, chunks:[{chunk_id,text}], max_quote_chars?}` (scans chunks in document order, quotes the first keyword sentence verbatim, status via `read_status`); judge triage `{task,keywords,evidence}` / verify `{task,keywords,status,quotes}`; reporter `{vendor_name, overall, band, counts, gaps}`; ask `{question, runs[newest first]}`). New shared `verification/keyword_reading.py` (`split_sentences`, `signals`, `read_status`, `first_sentence_with`) is now the single definition used by the sample generator's self-check, the mock and (5.5) the rule decider. New LLM output models `models/outputs.py`: `JudgeOutput(label, confidence, reason)`, `SummaryOutput(summary)`, `AskOutput(text, cited_run_ids, cited_control_ids)` (5.6, 5.10, 7.3 should use them). MEASURED on the 4 samples with BM25-only retrieval: mock mapper accuracy 100/100 vs golden (5.3 target 85 %); mock intake reproduces every spec fact (vendor, services, hosting, certifications, suppliers, period, data categories) for all four; a too-loose `credentials` cue was caught and narrowed. Caveat: the samples were generated with exactly this vocabulary, so 100 % shows the pipeline is consistent, not that keywords generalise to real documents (Phase 9 and the Ollama/OpenAI runs measure that).
- 4.3: `OpenAICompatLLM(name, settings.llm, settings.llm.<name>)` for `llm.openai` / `llm.groq` / `llm.openai_compat` (ADR-014; endpoint `{base_url}/chat/completions`, Bearer key from `VG_LLM__<NAME>__API_KEY`, `response_format` json_schema (best effort) or json_object, token-limit field and omitted params per profile, usage from `usage.prompt_tokens/completion_tokens`). Shared `providers/llm/_http.py` (`post_json`): retries connect errors/5xx (+429 for hosted), honours `Retry-After` capped by `llm.max_retry_wait_s` (longer = fail at once), never retries read timeouts or other 4xx; `OllamaLLM` was refactored onto it (its 40 tests unchanged). 401/403 messages never contain server text or the key. Prices added to `cost.prices_per_million_tokens` (`openai/gpt-6-luna` 0.10/0.50, `groq/openai/gpt-oss-20b` 0). NOT VERIFIED LIVE: no hosted call has been made. The user runs `make test-hosted` (one tiny call per provider with a key set; OpenAI costs a fraction of a cent). Open risks: OpenAI's pages do not say whether `gpt-6-luna` supports json_schema or accepts temperature/seed (if the first call fails, set `llm.openai.response_format: json_object` and/or `omit_params`); Groq free-plan limits are unclear (8K TPM vs 250K TPM) so expect 429s.
- 4.2: `OllamaLLM(settings.llm).complete_json(messages, output_model, purpose=, hints=)` (POST /api/chat, `format` = the model's JSON schema, options from settings, usage from prompt_eval_count/eval_count). Retries (tenacity, `llm.max_retries`, `llm.retry_backoff_s`) only for connect errors/timeouts and 5xx; a read timeout and 4xx are NOT retried; invalid output is re-asked `llm.json_repair_attempts` times with the problem (no values) and the tokens are summed; then `SchemaValidationError`. Shared helper `providers/llm/_json.py` (`complete_with_repair`, `extract_json`, ...) is for 4.3 too. `utils/timeutil.monotonic_s()` added (latency). LIVE FINDINGS with real qwen2.5:3b: (1) Ollama accepts the real `DraftFinding`/`VendorProfile` schemas ($defs/$ref are fine). (2) Determinism: at temperature 0 + seed the FIRST call after a model load (cold prompt evaluation) can differ from later calls, which agree with each other; so exactness must come from the record/replay cache (L1), and the Phase 9 cache-off determinism numbers will show this (document it in EVALUATION.md). (3) qwen2.5:3b invents facts on thin input (it reported financial data and on-premises hosting for a one-line document): use OpenAI/Groq for real assessments, keep Ollama for free dev runs. Live tests: `tests/live/test_ollama_llm.py` (3, about 35 s).
- 4.1: `models/llm.py` has `ChatMessage(role system|user|assistant, content)`, `Usage(tokens_in, tokens_out)` and generic `LLMResult[T](parsed, usage, provider, model, cached, latency_ms)`. `interfaces/` now has `LLMClient`, `Decider`, `MemoryStore`, `MemoryAssistant` besides `Embedder` and `CacheBackend`; a test pins every protocol's members and signatures to PLAN section 6. NEXT (4.2/4.3 design, to confirm with the user): OpenAI and Groq both use the OpenAI-compatible client, so the plan's single `llm.openai_compat` block becomes named profiles `llm.openai` and `llm.groq` (plus the generic `openai_compat`), each with its own base_url, model and key, selected by `llm.provider`; env vars `VG_LLM__OPENAI__API_KEY`, `VG_LLM__GROQ__API_KEY`; real prices for OpenAI in `cost.prices_per_million_tokens`; Groq priced 0. ADR to be written with 4.3. The user must verify current model names (the settings file says so) and rename the keys in `.env` (names unknown to me; I never read .env).
- 3.8 review (code-reviewer, verdict: ready, no blockers). FIXED (ADR-013): min-max scaling dropped weak real matches -> zero-floored scaling + `bm25_raw`/`vector_raw` on `ScoredChunk`; header/footer stripping limited to the first/last `repeated_line_scan_lines` (3) lines of a page; `ingest.max_text_chars` cap + bounded file read; control characters/surrogates/bidi controls removed at load; `CachedEmbedder` validates cached vectors and survives cache write failures; negative `top_k` raises; vector problems raise `EmbeddingError`; OverflowError in embedding parsing; Markdown table rules (`---`) no longer joined by de-hyphenation. 1026 tests, 96 % coverage. FOR LATER: (a) task 5.5 triage must use `bm25_raw`/keyword hits, not the scaled score; (b) task 8.2 (API upload): `load_document` follows symlinks (fine for the CLI), so uploads must be saved under a server-chosen name in a private folder first; (c) the orchestrator must decide what happens when the embedder fails at `HybridRetriever` construction (recommended: log, fall back to BM25 only, record `decider_fallback`-style audit event); (d) repeated query tokens count per occurrence in BM25 (deterministic, standard); (e) chunk IDs sort lexicographically only up to 999 pages/chunks (max_pages is 300); (f) `sanitize_filename` loses non-ASCII letters (`r_sum_.pdf`).
- 3.7: 984 tests, 96 % coverage; the gate `fail_under = 80` is ON (pyproject `[tool.coverage.report]`; verified to fail at 14 %). Three test-writer agents added ~290 tests: ingest 107 (coverage 88 -> 100 %), retrieval 147 (property tests over 12 seeds; already 100 %), embed 34 (100 %). One hardening fix came out of it: `OllamaEmbedder` now rejects NaN/Infinity in vectors (Python's json accepts them). Documented behaviours, not bugs: NFC vs NFD text tokenise differently (the cleaner's NFKC runs first); stop words are not whitespace-stripped; a CachedEmbedder counts hits before an inner failure and propagates cache `get()` errors.
- 3.6: `HybridRetriever(chunks, tokenizer, embedder_or_None, settings.retrieval)` with `.retrieve(query, top_k)` and `.for_control(control, top_k)` (query = title + requirement + keywords via `build_query`); returns `ScoredChunk` (score = weighted mean of the min-max-normalised BM25 and cosine signals, or BM25 alone when there is no embedder / the vectors are empty; `bm25` and `vector` hold the normalised parts; filtered by `min_score`, ties by chunk id; default `top_k` from settings, the Reviewer should ask for `top_k + review_extra_chunks`). `VectorIndex` is numpy cosine. min-max of equal positive scores is 1.0 (a bug found by a test: a one-chunk document would otherwise lose its only match). Measured on the 4 samples (85 controls with evidence): BM25-only recall@4 100 % (rank-1 98 %), hybrid with real nomic-embed-text recall@4 100 % (rank-1 100 %), vector-only recall@4 100 % (rank-1 96 %). Caveat: documents are 9 chunks, so recall@4 is easier than on long real documents. With vectors a lexical miss is still returned (similarity is always positive); the triage gate decides relevance.
- 3.5: `Embedder` and `CacheBackend` protocols now exist in `interfaces/` (as in PLAN section 6; 4.1 adds llm/decider/memory). `OllamaEmbedder(settings.embeddings)` (POST /api/embed, `batch_size`, doc/query prefixes, every failure an `EmbeddingError`), `NullEmbedder` (empty vectors; 3.6 must skip the vector signal when `embeddings.provider == none`), `CachedEmbedder(inner, cache, doc_prefix, query_prefix)` with `.hits/.misses` (key = hash of model + prefix + SHA-256 of text; only misses reach the inner embedder; damaged entries are recomputed). Tests use respx (33) plus one live test `tests/live/test_ollama_embeddings.py` (run with `uv run pytest -o addopts="" -m ollama tests/live`; passed against local nomic-embed-text). The real cache backends and `keys.py` are 4.5; they must accept `put(key, {"embedding": [...]}, purpose="embedding")`.
- 3.4: `Tokenizer(settings.retrieval.stop_words).tokenize(text)` and `Bm25Index(chunks, tokenizer, settings.retrieval)` with `.scores(query)` (all chunks, 0.0 for misses, rounded to 6 dp) and `.search(query, top_k)` (positive scores only, sorted by (-score, chunk_id)). ADR-012: Lucene IDF on top of rank-bm25's BM25Okapi (Okapi's own IDF and BM25Plus were both unusable, found by tests). New settings `retrieval.bm25_k1`, `bm25_b`, `stop_words` (quoted in YAML on purpose). mypy ignores rank_bm25 (no stubs).
- 3.3: `chunk_document(cleaned_doc, settings.chunking)` returns `Chunk`s (id `<doc_id[:12]>:p<page:03d>:c<n:03d>`, page 1-based, n 0-based per page; `char_start/char_end` index the CLEANED page text; `text == page_text[start:end]`). Sentence spans split at `. ! ?` + space or a blank line; sentence-granular overlap <= `overlap_chars`; a sentence longer than `chunk_chars` is cut at spaces. `chunk_chars` is a SOFT limit: a page's last chunk adding fewer than `min_chunk_chars` of new text is merged into the previous one (which can exceed `chunk_chars` by < `min_chunk_chars`); the first version of this rule was unreachable dead code, caught by a test. The samples give 1 chunk per page (9 per document). 300 pages / 10 MB chunk in about 0.6 s.
- 3.2: `clean_document(doc, settings.ingest)` returns the document with cleaned page text (hash and doc_id still describe the original bytes). Rules, in order: NFKC; drop lines repeated on >= `ingest.repeated_line_min_ratio` of pages (digit runs masked so `Page 2 of 9` matches `Page 3 of 9`; needs >= 2 pages; switch `ingest.strip_repeated_lines`); de-hyphenate line-break hyphens using the document's own vocabulary (compounds such as `multi-factor` keep their hyphen when they occur intact elsewhere; unknown lower-case continuations are joined; soft hyphens removed); collapse whitespace (soft line breaks joined, paragraphs kept). Known trade-off: body lines that differ only in digits on most pages are treated as running headers. Chunk offsets in 3.3 refer to the CLEANED page text. The orchestrator must call load_document then clean_document.
- 3.1: `load_document(path, settings.ingest)` returns a `Document` (doc_id = first 16 hex of the SHA-256 of the bytes; file name sanitised to its base name with safe characters; raw text, cleaning is 3.2). Refuses: type not in `ingest.allowed_extensions` (case-insensitive), not a file, larger than `max_file_mb`, wrong `%PDF-` header, encrypted or corrupt PDF, image-only PDF (no text), more than `max_pages`, non-UTF-8 or NUL-containing text, empty text. Text/Markdown pages split at form feeds (a trailing one is ignored). New setting `ingest.max_filename_chars`. Only the sample-loading test exists so far; the full ingest tests are 3.7.
- 2.7 review (code-reviewer, verdict: ready, no blockers). Fixed: cover certification line only when TPR-02 is met (ADR-011 corrected); filler/DAT-01 wording that contradicted some vendors; `MIN_OWN_KEYWORDS` now comes from `decision.rule.triage_min_keyword_hits`; `.gitattributes` keeps samples byte-exact; comments on intentional spec gaps. Left as is: DAT-04 mentions GDPR for brightdock (business contact details are still personal data); hosting providers are not listed as subprocessors where TPR-01 is missing (the document is silent about suppliers); `render_pdf` loop could be split into a helper (cosmetic).
- 2.6: 535 tests, 93 % coverage. Three test-writer agents added tests for `models/`, `controls/loader`, `utils/keywords`, spec edge cases and the `sample_gen` modules; they found two source bugs, both fixed: `NonEmptyStr` accepted whitespace-only strings (now needs a non-blank character, value not stripped) and `_paginate` could strand a heading at a tiny `lines_per_page` (a heading now always shares a page with its first paragraph). Committed samples did not change.
- 2.5: golden labels in `data/golden/<stem>.json` (vendor_id, stem, report_period, expected_inherent_tier, controls{id: met|partial|not_met|no_evidence}), written by `make sample` through `vendorguard.eval.golden` (`build_golden`, `write_golden`, `load_golden`); a test fails when they drift from the specs. NOTE for 6.7: `make record` passes the spec file stem as `--vendor`, so nimbara-hr-y2 would become a separate vendor; it must use the spec's `vendor_id` (`nimbara-hr`) for the memory/diff demo.
- 2.4: `make sample` writes `data/samples/<stem>.{pdf,txt,evidence.json}` (12 files, committed, ADR-011). Code: `src/vendorguard/eval/sample_gen/`; settings: new `samples:` section. Specs' summaries were reworded to avoid the keyword `personal data`. The evidence JSON has 25 entries per vendor (`state`, `page`, `sentence`, `variant`; null when the control is missing). For 3.6: gold sentences come from `evidence.json`. For 4.4: use `utils/keywords.py` for matching and read `data_category_phrases` in `phrases.yaml` for the intake mock. Generator tests (determinism, drift, pypdf, y2 wording) are in `tests/unit/eval/sample_gen/`; 2.6 adds the rest.
- ENVIRONMENT (macOS + iCloud Drive): the project is in ~/Documents, which iCloud syncs. iCloud flagged files in `.venv` as hidden (Python 3.12 then ignores the editable-install `.pth`), renamed a `.venv` symlink to `.venv 2`, and stalled deletes. FINAL SETUP: there is NO `.venv`. The environment is `.venv.nosync/` (iCloud ignores `.nosync`). `make` sets `UV_PROJECT_ENVIRONMENT=.venv.nosync`; outside make run `export UV_PROJECT_ENVIRONMENT=.venv.nosync` (and `uv run --no-sync` for speed), and point the editor at `.venv.nosync/bin/python`. Never create `.venv`. Leftovers `.venv-broken.nosync` and `.venv-empty.nosync` can be deleted in Finder. To rebuild: `UV_PROJECT_ENVIRONMENT=.venv.nosync uv sync --all-groups`. Moving the repo out of ~/Documents (for example ~/code) is still the real fix and also protects `.git`.
- 2.3: specs live in `data/samples/specs/*.yaml`, parsed by `vendorguard.eval.specs` (`load_spec`, `check_covers`, `SampleState.to_status()`; `missing` maps to `no_evidence`). The y2 spec keeps `vendor_id: nimbara-hr` (same vendor, new period) and declares `changes.fixed` / `changes.new_gaps` for the 7.2 diff test. Brightdock has data category `none`, so its inherent tier is low. Tests: `tests/unit/eval/test_specs.py` (16).
- 2.2: `load_controls(path)` returns a `ControlSet` sorted by ID; `ControlSet.subset(ids)` returns only those controls (empty list gives an empty set, so the orchestrator must treat `pipeline.controls_subset: []` as all). Errors are `ConfigError` naming the control. Tests in 2.6.
- 2.1: models in `src/vendorguard/models/` (see ADR-010). Tests for them come in 2.6.
- Task 4.8 must add a registry-vs-Literal test (ADR-009).

## Session log

| Date | Tasks completed | Notes / deviations |
|---|---|---|
| 2026-11-23 | Phase 0, 1.1-1.9, 2.1-2.7, 3.1-3.8, 4.1-4.10, 5.1-5.7 | Docker deferred to Phase 7. Intel Mac: prefer Groq/OpenAI via openai_compat for real runs. OpenAI+Groq need two key profiles (ADR pending, Phase 4). |
