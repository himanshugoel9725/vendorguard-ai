# REST API

The API is a FastAPI application. Start it with:

```bash
make api
```

It listens on `api.host` and `api.port` (default `127.0.0.1:8000`). Interactive docs are at
`http://127.0.0.1:8000/docs` while `api.docs_enabled` is true. The examples below use `$KEY` for the API key
and `$BASE` for `http://127.0.0.1:8000`.

## Authentication

Set a random key in `.env` (the variable name is in `.env.example`):

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

Put the result in `.env` as `VG_API__AUTH_KEY`. Send it in the `X-API-Key` header on every request except
`/health` (and the docs pages when enabled).

```bash
export BASE=http://127.0.0.1:8000
curl -s -H "X-API-Key: $KEY" $BASE/version
```

Start-up checks (the API refuses to start otherwise):

- With `api.auth_enabled: true` the key must be at least `api.auth_key_min_chars` (16) characters, have no
  surrounding spaces, and contain at least `api.auth_key_min_distinct_chars` (8) different characters.
- With auth disabled, `api.host` must be `127.0.0.1`, `::1` or `localhost`.

Keys are compared in constant time. Every key failure gets the same 401 message.

## Limits

| Limit | Setting | Default |
|---|---|---|
| Requests per minute per principal | `api.rate_limit_per_minute` | 30 |
| Upload size per file | `api.max_upload_mb` | 20 |
| Files per request | `api.max_files_per_request` | 5 |
| Non-file form fields | `api.max_form_fields` | 20 |
| JSON body size (all other routes) | `api.max_json_body_kb` | 64 |
| Assessments waiting for the worker | `api.max_queued_jobs` | 5 |
| Override reason length | `api.max_override_reason_chars` | 1000 |
| Override analyst length | `api.max_override_analyst_chars` | 100 |

Repeated wrong keys from one client address are answered with 429 and a `Retry-After` header, which slows
guessing. A correct key is never refused for that reason, so someone guessing from a shared address (a proxy,
Docker's network) cannot lock the real users out. Body sizes are counted as bytes arrive, whatever `Content-Length` claims. All of these are
in [Configuration](CONFIG.md).

## Endpoints

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/health` | Liveness (no key needed) |
| `GET` | `/version` | Name and version |
| `GET` | `/metrics` | Prometheus text metrics |
| `POST` | `/v1/assessments` | Upload documents, start an assessment |
| `GET` | `/v1/assessments/{run_id}` | Status, and the result once done |
| `GET` | `/v1/assessments/{run_id}/report?format=html\|md\|json` | The report |
| `PATCH` | `/v1/assessments/{run_id}/findings/{control_id}` | Analyst override |
| `GET` | `/v1/vendors` | Vendors with run count and latest band |
| `GET` | `/v1/vendors/{id}/history` | A vendor's runs, newest first |
| `POST` | `/v1/vendors/{id}/ask` | Question about a vendor |

### Start an assessment

Multipart form with `vendor_id` and one or more `files` (`.pdf`, `.txt`, `.md`). The type, the file header
and the text encoding are checked. Files are stored under server-chosen names in a private folder and deleted
after the run.

```bash
curl -s -H "X-API-Key: $KEY" \
  -F vendor_id=quillfield \
  -F files=@data/samples/quillfield.pdf \
  $BASE/v1/assessments
```

The answer is `202` with `run_id`, `status` and `status_url`. The run ID depends on the documents and the
settings, so the same upload gives the same ID. If that run is already queued or running, the existing job is
returned and the new upload is dropped. One worker runs assessments one after another.

### Poll

```bash
curl -s -H "X-API-Key: $KEY" $BASE/v1/assessments/$RUN_ID
```

`status` is `queued`, `running`, `done` or `failed`. When done, `result` holds the full result. A failed run
shows the error class only. A run recorded as running with no job in this process (the server stopped) is
reported as `failed` with the error `interrupted`.

### Report

```bash
curl -s -H "X-API-Key: $KEY" "$BASE/v1/assessments/$RUN_ID/report?format=md"
```

`format` is `html` (default), `md` or `json`. The answer is 409 until the run is done. HTML is served with
`Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; sandbox`.

### Override a finding

```bash
curl -s -X PATCH -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"status": "partial", "reason": "Policy reviewed, MFA not enforced for admins", "analyst": "A. Analyst"}' \
  $BASE/v1/assessments/$RUN_ID/findings/IAM-02
```

`status` is `met`, `partial`, `not_met` or `no_evidence`. The control ID is case-insensitive. The answer holds
the updated finding and the recomputed score. The reports are rewritten.

### Vendors, history, ask

```bash
curl -s -H "X-API-Key: $KEY" $BASE/v1/vendors
curl -s -H "X-API-Key: $KEY" $BASE/v1/vendors/nimbara-hr/history
curl -s -X POST -H "X-API-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"question": "What changed for nimbara-hr?"}' \
  $BASE/v1/vendors/nimbara-hr/ask
```

The answer cites run and control IDs that exist. The question is limited by `memory.ask_max_question_chars`.
Each ask calls the configured LLM synchronously.

## Errors

Error bodies are `{"detail": "..."}`. Provider, ingest and storage errors get a fixed message; their own text
is never sent.

| Status | When |
|---|---|
| 400 | Our own message about the request: unknown ID, refused override, question too long |
| 401 | Missing or wrong `X-API-Key` |
| 404 | Unknown run, control or vendor |
| 409 | Report or override requested before the run is done |
| 413 | Body, file, too many files or too many form fields over the limit |
| 415 | File type, file header or text encoding not accepted |
| 422 | Missing or invalid field (the answer never echoes the input); a document could not be read |
| 429 | Rate limit, failed-key lockout, or the cost budget used up. Rate limits send `Retry-After` |
| 500 | Memory store failed, or an internal error |
| 502 | A model provider failed |
| 503 | The job queue is full; sends `Retry-After` (`api.retry_after_s`) |

## Security notes

- Every response carries `X-Content-Type-Options: nosniff` and `Cache-Control: no-store`.
- Path IDs (run, vendor, control) are validated against patterns before any file path is built.
- CORS allows only the origins in `api.cors_origins`, only `GET`, `POST` and `PATCH`, no credentials.
  `*` is refused.
- `X-Forwarded-For` is ignored unless `api.trust_proxy_headers` is true. Turn that on only behind a proxy you
  control.
- `/docs`, `/redoc` and `/openapi.json` need no key while `api.docs_enabled` is true. The Docker image sets it to
  false; set it to false yourself if the port is reachable by others.
- The API has no TLS. Put a reverse proxy with TLS in front before exposing it.
- The rate limiter and the job registry live in the process. Run one worker process; with more, the limits
  multiply.
- Known gaps: uploads are read into memory per request (up to 20 MB per file, 5 files), there is no
  retention or disk quota for the runs folder, and the ask route has no limit on concurrent LLM calls.

## Docker

!!! note "What has been verified"
    The release workflow (`.github/workflows/release.yml`) builds the image on a GitHub runner (linux/amd64)
    and smoke-tests it before anything is pushed. The test starts the container with the same hardening as
    `docker-compose.yml` (read-only root, no capabilities, no new privileges), the mock LLM and a random API key,
    and checks that it becomes healthy, runs as the unprivileged user, refuses a request without a key, accepts
    an upload, finishes the assessment and serves the HTML report.

    Not verified: `docker compose up` itself, running on Docker Desktop for macOS, and talking to a real Ollama
    from inside the container (`host.docker.internal`). The image contains no model.

`docker-compose.yml` defines one service, `api`, under the profile `api`. It needs a `.env` with
`VG_API__AUTH_KEY`.

```bash
make docker-up
```

This runs `docker compose --profile api up --build -d` (detached). Then open `http://127.0.0.1:8000/docs`. Stop it with:

```bash
make docker-down
```

What the compose file sets:

| Item | Value |
|---|---|
| Port | Published on `127.0.0.1:8000` only |
| Ollama | On the host, reached at `http://host.docker.internal:11434` (override with `VG_LLM__BASE_URL` and `VG_EMBEDDINGS__BASE_URL`) |
| Data | Named volume `vendorguard-data` mounted at `/data` (runs, memory, cache) |
| Hardening | Non-root user, read-only root filesystem, `/tmp` as a 256 MB tmpfs, 2 GB memory limit, all capabilities dropped, `no-new-privileges` |
| Secrets | Read from `.env` at run time; none are in the image |

The container uses the host's Ollama, with no GPU. On Linux the host Ollama must listen on an address the
container can reach. There is no Letta service (ADR-019).

## Data handling and privacy

- **By default nothing leaves the machine.** The default setup uses a local Ollama server or the mock LLM, and
  the rule decider. The API makes no outbound call of its own.
- **If you enable a hosted model or Jev, document text leaves your control.** With `llm.provider` set to
  `openai`, `groq` or `openai_compat`, the retrieved excerpts of the vendor documents, the intake text and Ask
  questions are sent to that provider, under its terms. With `decision.provider: jev`, the excerpts and the
  questions of the triage and verify gates are sent to the Jev service. Use hosted services only with documents
  you are allowed to share with them. The evaluation and the demo in this repository use synthetic documents only.
- **Results stay on disk, unencrypted.** Each run keeps quotes from the documents, an audit log and reports in
  the runs folder, and the memory database keeps the results. There is no retention policy: delete
  `data/runs` and `.vendorguard/` (or the Docker volume) when you no longer need them.
- **One key, one tenant.** Every holder of the API key can read and write every vendor. There is no per-user
  authorisation. Keep `.env` private (`chmod 600 .env`; `vg doctor` warns if it is readable by others).
- **Leftover uploads.** Uploaded files are deleted after each run. If the process is killed mid-run, uploads
  older than `api.stale_upload_max_age_s` are removed at the next start.
