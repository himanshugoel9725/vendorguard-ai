# Architecture Decision Records

> One entry per decision. New decisions go at the bottom with the next number.
> Format: Status · Context · Decision · Consequences.

## ADR-001: Deterministic orchestration, LLMs as bounded workers

- **Status:** accepted
- **Context:** Risk assessments must be explainable, repeatable and auditable. Letting LLM agents choose the
  control flow makes results hard to reproduce.
- **Decision:** A plain-Python orchestrator owns the flow. LLM agents do bounded tasks with schema-validated
  JSON output. Scores, bands, diffs and reports are computed in Python.
- **Consequences:** Fewer "autonomous" behaviours, but every result can be traced and reproduced.

## ADR-002: No Hugging Face; local models through Ollama

- **Status:** accepted
- **Context:** Hugging Face cannot be used in this project, and cost must stay near zero.
- **Decision:** Generation and embeddings run on Ollama (`qwen2.5` family, `nomic-embed-text`). BM25 works
  without any model. A CI script fails the build if HF packages or model IDs appear.
- **Consequences:** Quality depends on local model size; an OpenAI-compatible provider is available as an
  opt-in alternative.

## ADR-003: One parameter file; secrets only in the environment

- **Status:** accepted
- **Context:** The system must be cheap now and easy to scale later without code edits.
- **Decision:** All tunables live in `config/settings.yaml`, overridable with `VG_<SECTION>__<KEY>` env vars.
  Secrets live only in `.env` / the environment, as `SecretStr`. Config models have no tunable defaults.
- **Consequences:** One place to look and change; a missing key fails fast at startup.

## ADR-004: Pluggable decision layer; Jev optional, used only for single-record gates

- **Status:** accepted
- **Context:** Gates must decide whether a mapped finding can be trusted. Jev is a low-cost decision model,
  but it is a commercial, recently released service, and published work reports it is weaker on multi-record
  judgments.
- **Decision:** `Decider` interface with `rule` (default, $0), `llm_judge` (local), `jev` (optional) and
  `mock`. Jev is used only for the triage and verify gates (one control at a time), with automatic fallback.
  Vendor-level aggregation is done by the rules engine.
- **Consequences:** The system runs with no paid services; Phase 9 measures whether Jev improves accuracy
  or LLM token use.

## ADR-005: Letta as the memory and Q&A layer; SQLite as the system of record

- **Status:** accepted
- **Context:** Vendor history must persist across assessments; Letta credits are limited (about $16).
- **Decision:** SQLite stores every assessment (default). The optional Letta provider keeps one stateful
  agent per vendor, whose memory blocks and archival passages are written programmatically after each run.
  Self-hosted Letta (Docker + Ollama) is the default Letta mode; Letta Cloud is opt-in with a daily cap.
- **Consequences:** $0 development; Letta Cloud credits are spent only for the final showcase.

## ADR-006: Record/replay cache for every model call

- **Status:** accepted
- **Context:** CI and the public demo must be deterministic and free, with no model server available.
- **Decision:** LLM, embedding and decider calls go through a cache keyed by a hash of provider, model,
  prompt version, inputs and parameters. CI runs in `read_only` mode against committed JSONL cassettes.
- **Consequences:** Prompt or schema changes require re-recording (`make record`).

## ADR-007: Backend first; no frontend in Goal 1

- **Status:** accepted
- **Context:** Limited time; the value is in the decision pipeline.
- **Decision:** Goal 1 ships CLI, REST API (Swagger UI), HTML reports and a GitHub Pages site with docs and
  replayed demo reports. A UI is an optional Phase 12.
- **Consequences:** The demo relies on Swagger and the HTML reports.

## ADR-008: Synthetic sample vendors with known ground truth

- **Status:** accepted
- **Context:** Real vendor documents are copyrighted or confidential and have no labelled answers.
- **Decision:** A deterministic generator writes fictional vendor documents from specs that state each
  control's true status, producing golden labels and evidence maps for evaluation.
- **Consequences:** Measured accuracy is on synthetic data and must be reported with that caveat; real
  public documents can be tried through `data/inbox/` (git-ignored).

## ADR-009: Settings split into a `config_models/` package; provider names as Literals

- **Status:** accepted
- **Context:** One `config.py` holding all 19 section models would pass the 250-line hard limit in
  `CLAUDE.md`. PLAN section 5 also asks for provider names to be validated against the factory registries,
  which do not exist until task 4.8.
- **Decision:** `config.py` holds the root `Settings`, loading and fingerprint. Section models live in
  `config_models/{base,core,providers,scoring}.py`. Provider names are `Literal` types in
  `config_models/base.py`. Task 4.8 must add a test that every registry key equals its Literal. The config
  file location comes from `VENDORGUARD_CONFIG` (not a `VG_` name, so it never collides with `.env` keys) or
  defaults to `config/settings.yaml` in the repository. Entries in `.env` that are not `VG_` settings are
  ignored; unknown keys inside the YAML are errors.
- **Consequences:** Adding a provider means editing one Literal plus the registry. A mistyped top-level
  `VG_` variable (for example `VG_LLMM__MODEL`) is silently ignored; mistyped section keys are rejected.

## ADR-010: Data-contract details for the models package

- **Status:** accepted
- **Context:** `docs/PLAN.md` section 7 lists the contracts but leaves some details open, and `CLAUDE.md`
  forbids hard-coded tunables.
- **Decision:** (1) Bounds that appear in a schema sent to the LLM (at most 3 citations, 60-word rationale,
  20 items and 200 characters per profile field) are constants next to the model, not settings, because
  changing them changes the JSON schema and therefore needs a new prompt version and re-recorded
  cassettes. Quote length is still checked against `verification.max_quote_chars` by the citation checker.
  (2) The LLM returns `DraftCitation(chunk_id, quote)`; `Citation` extends it with document, page, validity
  and similarity after checking, so the model is not shown fields it must not fill. (3) `StatusChange` uses
  `from_status` / `to_status` because `from` is a Python keyword. (4) The citation gate is traced as a
  `Decision` with provider `citation_check`. (5) All contracts are frozen with `extra="forbid"`, datetimes
  must be timezone-aware, and `AssessmentResult` rejects findings that are unsorted or duplicated.
  (6) `models/llm.py` (`ChatMessage`, `Usage`, `LLMResult`) stays a stub until task 4.1.
  (7) `ControlSet` also carries the optional `description` that `baseline_v1.yaml` has; controls must have
  at least one keyword, IDs must start with their domain code, and IDs must be unique.
- **Consequences:** Prompt-facing schemas stay small; the diff and manifest shapes are fixed early.

## ADR-011: Sample generator design (task 2.4)

- **Status:** accepted
- **Context:** The sample documents must be byte-reproducible, must make the keyword baseline able to reach
  the golden labels, and must stay comparable between year 1 and year 2.
- **Decision:** (1) The phrasing is chosen by SHA-256 of (base vendor, control, state), where the base vendor
  is `based_on` or `vendor_id`; a control whose state is unchanged keeps its wording in year 2, a changed one
  draws from another list. This refines the plan's "hash(vendor, control)". (2) Pages are composed in code
  (line budget, one domain per page, paragraphs never split) and the PDF is drawn from that composition with
  manual wrapping at spaces, so evidence sentences never straddle a page or a hyphen break; the text twin
  has the same pages joined by form feeds. (3) Section headings and the cover avoid control keywords, so only a control's own sentence decides its
  status, with one exception: the certification names (`SOC 2 Type II`) on the cover match TPR-02, so that
  line is written only when the spec has TPR-02 met. The cover states data categories through the neutral
  wording in `phrases.yaml`. (4) One definition of a keyword match (`utils/keywords.py`: whole word,
  case-insensitive) is shared with the future mock LLM and rule decider. (5) The generator refuses to write
  anything unless the phrase bank lints clean, a keyword reading of each document equals its spec, and
  pypdf finds every evidence sentence on its recorded page. (6) PDF layout and the creation date live in a
  new `samples:` section of `config/settings.yaml`; PDFs use core fonts, no compression, a fixed file ID.
  (7) Small layout constants (footer size and offset, line costs of titles and headings, the injection
  position after the second control paragraph, the certification control ID) are named constants in the
  modules, not settings. (8) The outputs (about 110 KB) are committed, marked as binary in `.gitattributes`, and a test fails when they drift from a fresh generation.
- **Consequences:** Upgrading fpdf2 can change PDF bytes; run `make sample`, review and commit. Documents are
  short (9 pages): they test mapping and verification, not long-document performance.

## ADR-012: BM25 with the Lucene IDF, tokenizer settings in config

- **Status:** accepted
- **Context:** `rank-bm25`'s default Okapi IDF is negative for terms found in more than half of the chunks,
  and makes every match negative in a very small corpus (a one-page upload would never produce a hit).
  Its `BM25Plus` variant adds its `delta` bonus to chunks that do not contain the term at all.
- **Decision:** `Bm25Index` uses `BM25Okapi` with the library's own IDF hook overridden by the
  Lucene/Elasticsearch IDF `log(1 + (N - df + 0.5) / (df + 0.5))`. Scores are rounded to the 6 decimals of
  canonical JSON and ordered by `(-score, chunk_id)`. `k1`, `b` and the stop-word list live in
  `retrieval:` in `config/settings.yaml` (stop words are quoted, because unquoted `on`/`no` are YAML
  booleans); `not` and `no` are deliberately not stop words.
- **Consequences:** Scores are never negative and a chunk without a query term scores exactly 0. The
  `rank-bm25` classes are subclassed through a documented extension point and must be re-checked when the
  library is upgraded (the tests pin the behaviour).

## ADR-013: Zero-floored score scaling, raw signals, and ingestion limits (Phase 3 review)

- **Status:** accepted
- **Context:** The Phase 3 review showed that min-max scaling turned the weakest real BM25 match into 0.0,
  which `min_score` then discarded (hidden on 9-chunk samples), that scaled scores carry no absolute
  meaning, that digit-masked repeated-line stripping could delete body text in short documents, and that
  ingestion had no cap on extracted text and let control characters through.
- **Decision:** (1) Signals are scaled by their best value with a floor of `min(0, lowest)`, not min-max:
  BM25 is divided by its maximum (zero stays zero), cosine is only shifted when some values are negative,
  all-equal positive scores become 1.0. (2) `ScoredChunk` also carries `bm25_raw` and `vector_raw`; `score`
  and `min_score` are relative to the best chunk of a query, and deciders that need absolute relevance
  (triage, task 5.5) must use the raw values or keyword hits. (3) Only the first and last
  `ingest.repeated_line_scan_lines` lines of a page can be removed as headers or footers. (4) New
  `ingest.max_text_chars` caps extracted text (PDF extraction stops as soon as it is exceeded) and file
  reads are bounded by `max_file_mb` instead of trusting `stat()`. (5) Control characters (C0, C1, DEL),
  lone surrogates and invisible bidirectional or zero-width characters are removed at load time; NUL
  still rejects a text file. (6) A cache write failure is logged (class name only) and never loses
  computed vectors; a cached vector that is not a non-empty list of finite numbers is treated as a miss.
- **Consequences:** The scaled score is a ranking aid only. Cleaning and loading can no longer produce text
  that cannot be hashed or encoded.

## ADR-014: Named hosted-LLM profiles, a shared HTTP retry helper, and 429 handling

- **Status:** accepted
- **Context:** The plan has one `llm.openai_compat` block and one key slot, but the project uses two hosted
  providers (OpenAI, paid; Groq, free plan) and wants to switch with one line. Groq's free plan has tight rate
  limits (tokens per minute and per day), so HTTP 429 is routine, not exceptional.
- **Decision:** (1) `llm.openai`, `llm.groq` and the generic `llm.openai_compat` are separate profiles (base URL,
  model, response format, token-limit field name, parameters to omit, key), selected by `llm.provider`; one class,
  `OpenAICompatLLM(name, llm, profile)`, serves all three and the profile name is the provider name. Keys:
  `VG_LLM__OPENAI__API_KEY`, `VG_LLM__GROQ__API_KEY`, `VG_LLM__OPENAI_COMPAT__API_KEY`. (2) Defaults were chosen from
  the providers' official pages on 2026-11-23: OpenAI `gpt-6-luna` ($0.10 / $0.50 per 1M tokens; the cheaper
  `gpt-5-nano` is deprecated) and Groq `openai/gpt-oss-20b` ($0.075 / $0.30 list, $0 on the free plan, documented
  strict structured outputs). OpenAI does not document JSON-schema support for `gpt-6-luna` on those pages, so
  `response_format` and `omit_params` are settings and the repair loop covers a miss. (3) `json_schema` is sent
  best-effort (not `strict`), because strict mode rejects schemas with defaults or bounds; validation and the
  repair loop enforce the contract. (4) `providers/llm/_http.py` is the one place for retries: connection
  errors and 5xx always, HTTP 429 for hosted providers; the pause is the longer of `llm.retry_backoff_s` and the
  server's `Retry-After`, and a `Retry-After` above `llm.max_retry_wait_s` fails at once (a daily quota should not
  put a run to sleep). Read timeouts and other 4xx are never retried. (5) A 401/403 reports only the status and the
  variable to check, never the server text (providers echo masked keys); other server messages are redacted.
  Keys travel only in the `Authorization` header. (6) Live tests are marked `hosted`, are skipped by default and
  by `make test-live`, and run only with `make test-hosted`.
- **Consequences:** Switching provider is `llm.provider: groq`. A free-plan run will be slow rather than failing.
  Prices must be kept in `cost.prices_per_million_tokens` (keys `openai/<model>`, `groq/<model>`).

### ADR-014 addendum (Phase 4 review)

- **Spend is always charged.** A call that fails after paid attempts (invalid replies that were re-asked, or a
  later HTTP error) carries `paid_usage` on its exception and the budget guard charges it. A call that crosses
  a limit still returns its paid answer (so the cache can keep it) and the NEXT call is refused. Overspend is
  bounded, not zero: calls in flight (one per worker), HTTP retries inside a call and repair re-asks can each
  spend beyond the cap before `ensure_budget` refuses.
- **The mock is free and not counted:** it is neither cached nor budgeted, so a keyword-baseline run reports
  0 LLM calls (as the README table says) and `max_llm_calls_per_run` can never stop a mock run.
- **A reply cut off at `llm.max_output_tokens`** (`finish_reason: length` / Ollama `done_reason: length`) is a
  clear, non-retried `LLMError` (reasoning models count reasoning tokens against that limit).
- **Retry pauses double** each attempt (`retry_backoff_s`, then 2x, 4x ...), never beyond
  `max_retry_wait_s`, with no jitter so runs stay deterministic. `Retry-After` still wins when longer.
- **Keys only travel over `https`** (or to a loopback host): any other `base_url` is a ConfigError.
- **Cache writes never lose a paid answer:** a failing write is logged (class name only) in `CachedLLM`, as
  it already was in `CachedEmbedder`. JSONL cassettes are compacted through a temporary file and an atomic
  rename, and the JSONL cache has a lock. `json_repair_attempts` is part of the cache key.

## ADR-015: Rule triage floor uses raw cosine similarity, not BM25 (task 5.5)

- **Context.** PLAN 5.5 says triage passes on "keyword hits >= `triage_min_keyword_hits` OR top score >=
  `triage_min_retrieval_score`" (0.15, a probability). Raw BM25 is unbounded and the fused `score` is scaled so
  the top chunk is always 1.0, so neither can meet a 0..1 floor. Measured on the 4 samples with BM25-only
  retrieval: controls the document does not cover still reach a raw BM25 of up to 20, while keyword hits
  separate perfectly (covered controls 2-4 hits, uncovered 0). With the BM25 floor, triage skipped nothing.
- **Decision.** The floor applies to the best raw cosine similarity (`ScoredChunk.vector_raw`, 0 when there
  are no embeddings). Without embeddings the keyword rule alone decides: 15 of 100 control checks are skipped
  without a model call, 0 of them wrongly. With embeddings the floor is mostly met (cosines are high), so fewer
  skips: the safe direction.
- **One formula.** `verification/rule_logic.py` holds triage and verify for both `RuleDecider` and the mock
  judge (which gained an optional `top_score` hint). Verify reads the WHOLE quote with `read_status` and has
  confidence 1.0 (binary rules); triage confidence is 0.5 + 0.5 * hits / keywords when addressed, 0.5 for a
  near miss, 1.0 for a clean miss.
