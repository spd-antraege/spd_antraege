-- PIS PostgreSQL schema bootstrap

-- Cron run tracking
CREATE TABLE IF NOT EXISTS cron_runs (
    id SERIAL PRIMARY KEY,
    job_name TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'running',  -- running | success | failed
    docs_processed INT DEFAULT 0,
    docs_skipped INT DEFAULT 0,
    error_message TEXT,
    run_manifest JSONB
);

CREATE INDEX IF NOT EXISTS idx_cron_runs_job ON cron_runs(job_name, started_at DESC);

-- Feed state tracking
CREATE TABLE IF NOT EXISTS feed_state (
    feed_url TEXT PRIMARY KEY,
    name TEXT,
    source_type TEXT,  -- inoreader | direct
    last_fetched TIMESTAMPTZ,
    last_item_date TIMESTAMPTZ,
    items_total INT DEFAULT 0,
    status TEXT DEFAULT 'active',  -- active | dead | proposed | rejected
    relevance_score FLOAT,
    added_at TIMESTAMPTZ DEFAULT NOW()
);

-- Taxonomy proposal tracking
CREATE TABLE IF NOT EXISTS taxonomy_proposals (
    id SERIAL PRIMARY KEY,
    proposed_at TIMESTAMPTZ DEFAULT NOW(),
    topic_id TEXT NOT NULL,
    domain_id TEXT NOT NULL,
    label_de TEXT NOT NULL,
    evidence_doc_ids TEXT[],
    status TEXT DEFAULT 'pending',  -- pending | approved | rejected
    decided_at TIMESTAMPTZ,
    decided_by TEXT
);

-- External signal storage
CREATE TABLE IF NOT EXISTS external_signals (
    id SERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    source_url TEXT,
    title TEXT,
    summary TEXT,
    topic_ids TEXT[],
    relevance_score FLOAT,
    local_angle TEXT,
    fetched_at TIMESTAMPTZ DEFAULT NOW(),
    stale_after TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_signals_topics ON external_signals USING GIN(topic_ids);
CREATE INDEX IF NOT EXISTS idx_signals_fetched ON external_signals(fetched_at DESC);
