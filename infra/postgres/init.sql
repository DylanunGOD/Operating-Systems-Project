-- PostgreSQL schema initialization for multimedia-distributed

CREATE TYPE job_status AS ENUM ('pending', 'queued', 'processing', 'completed', 'failed');
CREATE TYPE job_type AS ENUM (
    'convert_video',
    'extract_audio',
    'thumbnail',
    'extract_metadata',
    'classify_output'
);

CREATE TABLE jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type            job_type NOT NULL,
    status          job_status NOT NULL DEFAULT 'pending',
    priority        TEXT NOT NULL DEFAULT 'normal',
    input_path      TEXT NOT NULL,
    output_path     TEXT,
    params          JSONB DEFAULT '{}',
    result_metadata JSONB DEFAULT '{}',
    worker_id       TEXT,
    progress        INTEGER DEFAULT 0,
    error_msg       TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    retry_count     INTEGER DEFAULT 0
);

CREATE TABLE workers (
    id          TEXT PRIMARY KEY,
    status      TEXT DEFAULT 'idle',
    current_job UUID REFERENCES jobs(id),
    cpu_percent FLOAT,
    mem_percent FLOAT,
    jobs_done   INTEGER DEFAULT 0,
    last_seen   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE events (
    id          SERIAL PRIMARY KEY,
    job_id      UUID REFERENCES jobs(id),
    worker_id   TEXT,
    event_type  TEXT NOT NULL,
    payload     JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_jobs_status   ON jobs(status);
CREATE INDEX idx_jobs_priority ON jobs(priority);
CREATE INDEX idx_jobs_worker   ON jobs(worker_id);
CREATE INDEX idx_events_job    ON events(job_id);
