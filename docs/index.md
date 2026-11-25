# VendorGuard AI

VendorGuard AI is a multi-agent assistant for third-party (vendor) security risk assessment. It reads
vendor documents, maps them to a 25-control baseline, and produces a scored report in which every finding
is tied to a quote that the system has checked against the source text.

## The problem

An analyst assessing a vendor reads 50 to 200 pages of policies and audit excerpts, maps them to a control
framework by hand and writes up findings. This is slow, and two analysts rarely agree. VendorGuard AI does
the first pass and shows its work. The analyst keeps the final word.

## The flow in one paragraph

Documents (PDF, TXT, Markdown) are loaded, cleaned and split into page-aware chunks. A hybrid retriever
(BM25 plus embeddings) finds evidence for each control. An Intake agent extracts a vendor profile. Each control
then goes through a cascade: a triage gate, a Mapper agent that proposes a status with verbatim quotes, a
citation check against the source, a verify gate, and a Reviewer agent for anything the gates doubt. What is
still doubtful goes to a person. Python computes the score and band from the findings. A Reporter agent writes
a short summary from the structured result, and a guard checks its numbers. Reports are written as HTML,
Markdown and JSON, with an audit log and a run manifest.

See [Architecture](architecture.md) for details.

## Quickstart

Prerequisites: [uv](https://docs.astral.sh/uv/) and git. The commands below use the mock LLM, so Ollama is
not needed.

```bash
make setup
```

```bash
make sample
```

```bash
uv run vg assess --sample quillfield --llm mock --embeddings none
```

The command prints the run ID, the score and the folder with the reports (by default `data/runs/<run_id>/`).
Open the HTML report:

```bash
uv run vg report <run_id> --format html --open
```

The mock LLM is a deterministic keyword baseline. It checks that the pipeline works and is not a model result.
For a real local model, install [Ollama](https://ollama.com), pull the models named in `config/settings.yaml`
(`llm.model`, `embeddings.model`), check them with `uv run vg doctor` and run `vg assess` without `--llm`.

## Where to go next

| Page | Content |
|---|---|
| [Architecture](architecture.md) | Pipeline, agents, decision layer, determinism, memory, audit |
| [CLI](cli.md) | Every `vg` command and the run folder |
| [REST API](api.md) | Endpoints, authentication, limits, Docker |
| [Configuration](CONFIG.md) | Every setting (generated from `config/settings.yaml`) |
| [Demo reports](https://himanshugoel9725.github.io/vendorguard-ai/demo/) | Four synthetic vendors, replayed from a recorded run (live once GitHub Pages is enabled) |
| [Evaluation](EVALUATION.md) | Method and measured results |
| [Decisions](DECISIONS.md) | Architecture decision records |

## Limitations

!!! warning "Read this before relying on any number"
    - **Evaluation data is synthetic.** The four sample vendors are fictional and their true control statuses
      are known by construction. The results may not transfer to real vendor documents.
    - **One small local model was measured** (`qwen2.5:3b` on a CPU-only machine). No hosted LLM was measured.
      The small model often returns no quote, which shows up as a false `no_evidence`.
    - **The Docker image is smoke-tested only on a CI runner.** It builds and serves an assessment there with
      the mock LLM; it was not run on the author's machine, with `docker compose`, or with a real Ollama.
    - **Letta memory is not implemented** (ADR-019). Vendor memory uses SQLite only. The `letta` setting
      validates, but building the store fails with "not implemented yet".
    - **The API is single-process.** The rate limiter and the job queue live in memory, and assessments run
      one at a time.
    - VendorGuard AI is a first-pass aid. It does not replace professional judgement or audits. Control
      mappings to ISO/IEC 27001:2022 and NIST CSF 2.0 are indicative. Scanned (image-only) PDFs are not
      supported.
