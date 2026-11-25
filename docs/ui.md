# Web UI (optional)

A small Streamlit app for people who prefer a page to the command line. It is a **client of the REST API**:
it uploads documents, shows runs and findings, records analyst overrides and answers questions, all through
the API you already run. It never reads the runs folder or the memory database itself (ADR-021).

## Run it

You need the API running with a key, and the same key given to the UI.

```bash
make setup                      # installs the optional `ui` dependency group too
```

Put the key in `.env`: `VG_API__AUTH_KEY` for the API and the **same value** as `VG_UI__API_KEY` for the UI.

```bash
make api                        # terminal 1: the API on http://127.0.0.1:8000
```

```bash
make ui                         # terminal 2: the UI on http://127.0.0.1:8501
```

The sidebar shows whether the API is reachable. If you only want to try it, start the API with the mock LLM:
`VG_LLM__PROVIDER=mock VG_EMBEDDINGS__PROVIDER=none make api`.

## The three tabs

| Tab | What you can do |
|---|---|
| **Assess** | Enter a vendor ID, add PDF, TXT or Markdown files and start an assessment. The page follows the run (queued, running, done) and shows the score. Runs go one after another on the server. |
| **Findings** | Load a finished run by its ID. See the score, band, summary, domain scores and, for a re-assessment, what changed since the last run. Filter findings by status, read the checked quotes with their page numbers, record an analyst decision (new status, reason, your name) and download the report as HTML, Markdown or JSON. |
| **History and Ask** | List the vendors with stored assessments, see one vendor's runs, and ask a question such as "What changed since last year?". The answer cites run and control IDs. |

## Safety rules

- **Local use only.** The page has no login. It uses the API key of whoever started it and binds to
  `127.0.0.1`. Never expose it to a network.
- **The key** goes only to `ui.api_base_url`, and only over https unless that address is this machine
  (the settings refuse anything else). It is never shown on the page or written to a log.
- **Text from documents and models** (quotes, rationales, answers, vendor names) is shown as plain text,
  never as Markdown or HTML, so a vendor document cannot put links, images or markup into the page.
- **Errors** show the API's own short messages, not internal details.

## Settings

The section `ui` of `config/settings.yaml` (see [Configuration](CONFIG.md)): `ui.api_base_url`,
`ui.request_timeout_s`, `ui.poll_interval_s`, `ui.poll_timeout_s`, `ui.page_title`. The key is
`VG_UI__API_KEY` in `.env`. Keep `ui.poll_interval_s` high enough that polling stays under
`api.rate_limit_per_minute`: the default of 3 seconds is 20 requests a minute against a limit of 30.

## Limits

- Tested with Streamlit's own test harness and against the real API in a scripted run. The author has not
  clicked through it in a real browser session.
- Control titles are not shown, only IDs: the API does not expose the control catalogue.
- A run that takes longer than `ui.poll_timeout_s` keeps running on the server; load it again by its ID.
- No hosted deployment: a public UI in front of a private API key would defeat the key.
