# CLI

The command is `vg` (run it as `uv run vg ...`). `uv run vg --help` and `uv run vg <command> --help` list the
options. Defaults come from `config/settings.yaml` (see [Configuration](CONFIG.md)); any setting can also be
set with an environment variable `VG_<SECTION>__<KEY>`.

| Command | Purpose |
|---|---|
| `vg doctor` | Show the active configuration, which keys are set, and whether local services answer |
| `vg samples` | List the synthetic sample vendors (`make sample` creates them) |
| `vg assess` | Run an assessment |
| `vg report RUN_ID` | (Re)write the reports of a finished run |
| `vg review RUN_ID CONTROL` | Override one control's status |
| `vg runs list` / `vg runs show RUN_ID` | Browse finished runs |
| `vg vendors list` / `vg vendors history ID` | Vendors and their runs, from the memory store |
| `vg ask VENDOR "question"` | Answer from the stored assessments |
| `vg eval` | Run the evaluation matrix |
| `vg determinism` | Repeat one config with the cache off and count identical results |
| `vg charts` | Draw the evaluation charts from `docs/evaluation/results.json` |

## vg doctor

Prints the configuration summary and every secret as `set` or `unset` (values are never shown). It calls the
Ollama server (`/api/tags`) only if the LLM or embeddings use Ollama.

```bash
uv run vg doctor
```

## vg samples

```bash
make sample
uv run vg samples
```

## vg assess

Give either `--sample` or `--vendor` with `--docs`.

| Option | Meaning |
|---|---|
| `--vendor ID` | Vendor ID (required with `--docs`) |
| `--docs FILE` | A vendor document (`.pdf`, `.txt`, `.md`); repeat for several |
| `--sample STEM` | A synthetic sample, for example `quillfield`. Takes the vendor ID from its spec and the document from `data/samples/` |
| `--llm NAME` | `ollama`, `openai`, `groq`, `openai_compat` or `mock` |
| `--decider NAME` | `rule`, `llm_judge`, `jev` or `mock` |
| `--embeddings NAME` | `ollama` or `none` (BM25 only) |
| `--controls A,B` | Comma-separated control IDs; default is all |
| `--cache MODE` | `off`, `read_write` or `read_only` |

The options become settings overrides; a bad value is a configuration error naming the key.

```bash
uv run vg assess --sample quillfield --llm mock --embeddings none
```

```bash
uv run vg assess --vendor acme --docs policies.pdf --docs soc2-excerpt.pdf
```

```bash
uv run vg assess --sample nimbara-hr --llm mock --embeddings none --controls IAM-01,IAM-02
```

`nimbara-hr-y2` is the same vendor as `nimbara-hr` in a later year. Assess both to get a re-assessment diff.

The command prints the run ID, vendor, score and band, status counts, cost and the run folder.

## vg report

```bash
uv run vg report <run_id> --format html --open
```

`--format` is `json`, `md` or `html`; without it all configured formats are written. `--open` opens the HTML
report in a browser.

## vg review

Records an analyst override. The run must be finished. The status can be `met`, `partial`, `not_met` or
`no_evidence`. The score, the summary and the reports are recomputed, and the original system status stays in
the finding.

```bash
uv run vg review <run_id> IAM-02 --status partial --reason "Policy reviewed, MFA not enforced for admins" --analyst "A. Analyst"
```

## vg runs

```bash
uv run vg runs list
uv run vg runs list --vendor nimbara-hr
uv run vg runs show <run_id>
```

These read the run folders on disk.

## vg vendors

```bash
uv run vg vendors list
uv run vg vendors history nimbara-hr
```

These read the memory store (`memory.sqlite_path`), so only runs saved there appear.

## vg ask

Answers from stored assessments. The answer cites run and control IDs that exist. Without a stored run for the
vendor it says so without calling a model. Questions are cleaned and limited by `memory.ask_max_question_chars`.

```bash
uv run vg ask nimbara-hr "What changed since last year?" --llm mock
```

A runnable offline demo of year 1, year 2, the diff and a question: `make demo-memory`.

## vg eval, determinism, charts

```bash
uv run vg eval --configs keyword-baseline
uv run vg determinism
uv run vg charts
```

`vg eval` runs the configs listed in `eval.configs` over every sample vendor and writes
`docs/evaluation/results.json`. Real-model configs need a running Ollama and take a long time on a CPU. Method
and results: [Evaluation](EVALUATION.md). `vg charts` needs the dev dependencies (`make setup`).

## Run folder

Each assessment writes `paths.runs_dir/<run_id>/` (default `data/runs/<run_id>/`). The run ID is derived from the
vendor, the input hashes and the config fingerprint, so the same inputs and settings reuse the same folder.
Re-running replaces the audit log, manifest and result of that run, but a run that has analyst overrides
is refused.

| File | Content |
|---|---|
| `audit.jsonl` | One JSON line per event |
| `manifest.json` | Status, config fingerprint, prompt hashes, models, input hashes, result hash |
| `result.json` | The full result |
| `report.html`, `report.md`, `report.json` | The reports |

Input documents are not copied into the folder; the manifest holds their hashes.

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 2 | Usage, configuration or input error (bad option value, unreadable document) |
| 1 | Any other failure (provider error, budget exceeded, memory store error) |

Errors print one `error:` line and no traceback.
