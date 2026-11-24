-- VendorGuard memory store (SQLite). Parameterised SQL only; WAL mode is set by the store.
-- result_json is the canonical JSON of the AssessmentResult and is the source of truth: the other
-- tables are queryable copies that the store rewrites together with it.

CREATE TABLE IF NOT EXISTS vendors (
    vendor_id TEXT PRIMARY KEY,
    name      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS assessments (
    run_id      TEXT PRIMARY KEY,
    vendor_id   TEXT NOT NULL REFERENCES vendors(vendor_id),
    created_at  TEXT NOT NULL,
    overall     REAL NOT NULL,
    band        TEXT NOT NULL,
    result_hash TEXT NOT NULL,
    result_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS assessments_by_vendor ON assessments(vendor_id, created_at, run_id);

CREATE TABLE IF NOT EXISTS findings (
    run_id           TEXT NOT NULL REFERENCES assessments(run_id) ON DELETE CASCADE,
    control_id       TEXT NOT NULL,
    status           TEXT NOT NULL,
    effective_status TEXT NOT NULL,
    PRIMARY KEY (run_id, control_id)
);

CREATE TABLE IF NOT EXISTS overrides (
    run_id     TEXT NOT NULL REFERENCES assessments(run_id) ON DELETE CASCADE,
    control_id TEXT NOT NULL,
    analyst    TEXT NOT NULL,
    new_status TEXT NOT NULL,
    reason     TEXT NOT NULL,
    at         TEXT NOT NULL,
    PRIMARY KEY (run_id, control_id)
);

-- Letta Cloud message counter per UTC day (task 7.6).
CREATE TABLE IF NOT EXISTS letta_usage (
    day      TEXT PRIMARY KEY,
    messages INTEGER NOT NULL
);
