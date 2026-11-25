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

- **Local use only.** The page has no login. It uses the API key of whoever started it, so anyone who can
  reach the page can do what the key can do. `make ui` and `.streamlit/config.toml` bind it to `127.0.0.1`;
  if you start it any other way, check that it is not listening on your network. Never expose it.
- **DNS rebinding.** A hostile web page can make your browser reach a local server under the page's own name.
  The UI therefore answers only when the request's `Host` header is one of `ui.allowed_hosts`
  (`127.0.0.1`, `localhost`, `[::1]`); under any other name it draws one refusal message and calls nothing.
  This is the same check that stops a request arriving from another machine on your network.
- **The key** goes only to `ui.api_base_url`, and only over https unless that address is this machine
  (the settings refuse anything else). It is never shown on the page or written to a log, and redirects are
  not followed.
- **Text from documents and models** (quotes, rationales, summaries, answers) is shown with `st.text` and
  `st.code`, never as Markdown or HTML. The few widgets that always render Markdown (error boxes, labels) only
  receive API strings after they have been escaped, and table cells that start with `=`, `+`, `-` or `@` get a
  leading quote so an exported CSV cannot run as a spreadsheet formula.
- **Identifiers** (run, vendor and control IDs) are checked against the server's patterns before they are
  placed in a request path.
- **Errors** show the API's own short messages (cut to `ui.max_detail_chars`), not internal details.

## Settings

The section `ui` of `config/settings.yaml` (see [Configuration](CONFIG.md)): `ui.api_base_url`,
`ui.request_timeout_s`, `ui.poll_interval_s`, `ui.poll_timeout_s`, `ui.refresh_ttl_s`, `ui.max_detail_chars`,
`ui.allowed_hosts`, `ui.page_title`. The key is `VG_UI__API_KEY` in `.env`. The upload limits (file types,
size, number of files) are read from the same file's `ingest` and `api` sections, so the page and the API agree.

## What to expect

- Every click reruns the page. A run being followed is picked up again after a click, and the vendor list and
  history are fetched at most every `ui.refresh_ttl_s` seconds, but two browser tabs each polling a run share
  the API's per-key limit (`api.rate_limit_per_minute`, 30 by default). The UI backs off when the API answers
  429.
- Streamlit itself accepts uploads up to 200 MB per file; the page checks your files against the API's limit
  (20 MB, 5 files) before reading them.
- Control titles are not shown, only IDs: the API does not expose the control catalogue.
- A run that takes longer than `ui.poll_timeout_s` keeps running on the server; load it again by its ID.
- No hosted deployment: a public UI in front of a private API key would defeat the key.

## How it was tested

Streamlit's own test harness drives the real pages against a fake client; the HTTP client is tested against
mocked responses; a layering test keeps the UI from importing server code. The author also ran the client once
against the real API in a scripted check (upload, override, reports, history, ask), which is not part of the
test suite, and started the real Streamlit server to confirm it answers on `127.0.0.1` only. Nobody has yet
clicked through it in a real browser session, so rendering details such as table export are untested.
