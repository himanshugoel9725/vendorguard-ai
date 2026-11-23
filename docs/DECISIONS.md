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
