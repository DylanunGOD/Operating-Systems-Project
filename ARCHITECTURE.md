# ARCHITECTURE.md

## Overview

The platform is a classic coordinator-worker distributed system layered over two shared
data stores: a PostgreSQL database for durable state and a Redis instance used both as
a job queue (LIST) and a real-time event bus (pub/sub).

The **coordinator** is a FastAPI application that owns the HTTP/WebSocket surface. Clients
submit jobs via REST; the coordinator writes each job to PostgreSQL and appends its
serialised payload to the Redis `jobs:queue` LIST. Independently, a background task inside
the coordinator subscribes to the `jobs:progress` Redis channel and fans out every message
to all connected WebSocket clients after normalising the field names.

Each **worker** is an independent Python process that blocks on `BLPOP jobs:queue`. When
a job arrives, the worker calls the appropriate ffmpeg handler, publishes progress events
to `jobs:progress`, and updates the job record in PostgreSQL directly. Three worker
containers run by default; scaling is additive — a fourth worker needs only a new entry in
`docker-compose.yml` using the same image.

The **observability stack** (Prometheus, Grafana, Loki/Promtail) runs in a separate
monitoring network. Prometheus scrapes the coordinator on `:8000/metrics` and each worker
on `:9100/metrics`. Loki ingests all container logs via Promtail. Grafana is pre-provisioned
with a dashboard and both datasources.

---

## Component Diagram

```
 ┌────────────────────────────────────────────────────────────────┐
 │                        backend network                         │
 │                                                                │
 │  ┌─────────────────────────────────────────────────────────┐  │
 │  │              Coordinator  (FastAPI :8000)                │  │
 │  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐  │  │
 │  │  │ /jobs    │  │/workers  │  │/metrics  │  │/chaos  │  │  │
 │  │  │ CRUD     │  │GET       │  │Prometheus│  │runner  │  │  │
 │  │  └──────────┘  └──────────┘  └──────────┘  └────────┘  │  │
 │  │                                                          │  │
 │  │  ┌──────────────────────────────────────────────────┐   │  │
 │  │  │  WebSocket /ws                                    │   │  │
 │  │  │   pubsub listener ──► normalize ──► broadcast     │   │  │
 │  │  │   heartbeat loop  ──► queue_snapshot every 5s     │   │  │
 │  │  └──────────────────────────────────────────────────┘   │  │
 │  └───────────────┬──────────────────────┬───────────────────┘  │
 │                  │                      │                       │
 │          ┌───────▼──────┐      ┌────────▼───────┐              │
 │          │  Redis :6379  │      │ PostgreSQL:5432 │              │
 │          │  LIST         │      │ jobs           │              │
 │          │  jobs:queue   │      │ workers        │              │
 │          │  pub/sub      │      │ events         │              │
 │          │  jobs:progress│      └────────────────┘              │
 │          └───┬──────▲───┘                                       │
 │              │      │  BLPOP / PUBLISH                          │
 │   ┌──────────▼──────┴──────────────────────────────────────┐   │
 │   │  Worker-1   Worker-2   Worker-3   (replicas)            │   │
 │   │  BLPOP loop → ffmpeg subprocess → progress reporter     │   │
 │   │  Prometheus HTTP server :9100                           │   │
 │   └─────────────────────────────────────────────────────────┘   │
 └────────────────────────────────────────────────────────────────┘
           │ frontend network                │ monitoring network
   ┌───────▼──────────────┐   ┌─────────────▼─────────────────────┐
   │  Dashboard :3000      │   │  Prometheus  :9090                 │
   │  React + Vite         │   │  Grafana     :3001                 │
   │  polling /jobs,       │   │  Loki        :3100                 │
   │  /workers, /metrics   │   │  Promtail    (Docker socket)       │
   └───────────────────────┘   └───────────────────────────────────┘
```

---

## Data Flow — Job Lifecycle

1. **Client submits a job** via `POST /jobs` with `{"type":"convert_video","input_path":"/media/input/video.mp4","params":{}}`.
   The `output_path` field is not accepted at top level by `JobCreate`; clients that need
   to control the output path embed it inside `params` (e.g. `{"output_path":"/media/output/video.mp4"}`).

2. **Coordinator persists** a `Job` row in PostgreSQL with `status=pending`, then calls
   `JobScheduler.enqueue_job()` which serialises the job to JSON and calls `RPUSH jobs:queue`.
   The status is updated to `queued` atomically before the HTTP response is returned.

3. **Worker unblocks** on `BLPOP jobs:queue` (timeout=5 s). It parses the JSON payload and
   dispatches to `TaskProcessor.execute()` which selects `FFmpegHandler` based on `job_type`.

4. **Worker updates DB** directly via SQLAlchemy — setting `status=processing`, `worker_id`,
   and `started_at` at start; `status=completed/failed` and `completed_at` at the end.

5. **Worker publishes progress** to `jobs:progress` pub/sub channel. Each message uses the
   field `event` (not `type`) and `error_msg` (not `error`):
   ```json
   {"event": "job_progress", "job_id": "...", "worker_id": "worker-1", "progress": 42}
   {"event": "job_failed",   "job_id": "...", "worker_id": "worker-1", "error_msg": "..."}
   ```

6. **Coordinator normalises and fans out.** The `_pubsub_listener` background task reads
   from `jobs:progress`, calls `_normalize_worker_event()` which renames `event` → `type`
   and `error_msg` → `error`, then broadcasts via `ConnectionManager.broadcast()` to all
   WebSocket clients.

7. **Coordinator emits `queue_snapshot`** every 5 seconds (the heartbeat loop), aggregating
   `queue_length` and worker counts from DB. This is the only heartbeat event; there is no
   separate `worker_heartbeat` event published to the pub/sub channel.

8. **Dashboard** receives both event types over WebSocket. The `useWebSocket` hook exists
   and handles reconnect with exponential backoff, but `JobsTable` and `WorkersStatus`
   components currently use `setInterval` polling (every 2-3 s) and do not consume the
   WebSocket messages. The hook is wired but not integrated into the components.

---

## Database Schema

Three tables defined in `infra/postgres/init.sql` (raw SQL) and mirrored in
`coordinator/models/job.py` (SQLAlchemy ORM). There are no Alembic migrations; the schema
is applied by the `init.sql` script on first container startup.

### `jobs`

| Column         | Type              | Notes                                              |
|----------------|-------------------|----------------------------------------------------|
| `id`           | UUID PK           | Generated by `gen_random_uuid()`                   |
| `type`         | `job_type` enum   | `convert_video`, `extract_audio`, `thumbnail`      |
| `status`       | `job_status` enum | `pending` → `queued` → `processing` → `completed/failed` |
| `input_path`   | TEXT NOT NULL     | Absolute path inside the shared `media_volume`     |
| `output_path`  | TEXT              | Populated from `params.output_path` by the worker  |
| `params`       | JSONB             | Arbitrary extra parameters, including `output_path`|
| `worker_id`    | TEXT              | Set when a worker picks up the job                 |
| `progress`     | INTEGER           | 0-100                                              |
| `error_msg`    | TEXT              | Set on failure                                     |
| `retry_count`  | INTEGER           | Incremented on retry (manual — no auto-retry loop) |
| `created_at`   | TIMESTAMPTZ       | Auto set on insert                                 |
| `started_at`   | TIMESTAMPTZ       | Set when worker begins processing                  |
| `completed_at` | TIMESTAMPTZ       | Set when job finishes (success or failure)         |

### `workers`

| Column        | Type      | Notes                                                 |
|---------------|-----------|-------------------------------------------------------|
| `id`          | TEXT PK   | e.g. `worker-1` — set via `WORKER_ID` env var         |
| `status`      | TEXT      | `idle` or `processing` (or `offline` under chaos)     |
| `current_job` | UUID FK   | References `jobs.id`, nullable                        |
| `cpu_percent` | FLOAT     | Updated by worker periodically                        |
| `mem_percent` | FLOAT     | Updated by worker periodically                        |
| `jobs_done`   | INTEGER   | Cumulative count                                      |
| `last_seen`   | TIMESTAMPTZ | Updated on each heartbeat                           |

### `events`

Audit log for job lifecycle and chaos actions.

| Column       | Type        | Notes                                              |
|--------------|-------------|----------------------------------------------------|
| `id`         | SERIAL PK   |                                                    |
| `job_id`     | UUID FK     | References `jobs.id`, nullable (system events)     |
| `worker_id`  | TEXT        |                                                    |
| `event_type` | TEXT        | e.g. `job_started`, `job_completed`                |
| `payload`    | JSONB       | Arbitrary event data                               |
| `created_at` | TIMESTAMPTZ |                                                    |

Indexes: `idx_jobs_status`, `idx_jobs_worker`, `idx_events_job`.

---

## Messaging

### Redis LIST — job queue

Key: `jobs:queue` (configurable via `REDIS_QUEUE_KEY`).

- **Enqueue:** coordinator calls `RPUSH jobs:queue <json_payload>` (right push).
- **Dequeue:** workers call `BLPOP jobs:queue 5` (left pop, 5 s timeout). BLPOP is atomic —
  each payload is delivered to exactly one worker even with N workers competing.

The chaos `spike_queue` action uses `LPUSH` (left push) to prepend fake jobs so they are
processed first by the next available worker.

### Redis pub/sub — progress events

Channel: `jobs:progress` (configurable via `REDIS_PROGRESS_CHANNEL`).

Workers publish with `event` (not `type`) and `error_msg` (not `error`). The coordinator
WebSocket layer normalises this before broadcasting to dashboard clients:

| Wire field (worker publishes) | Dashboard contract (WebSocket sends) |
|-------------------------------|--------------------------------------|
| `"event": "job_progress"`     | `"type": "job_progress"`             |
| `"error_msg": "..."`          | `"error": "..."`                     |
| all other fields              | unchanged                            |

Event types published by workers: `job_started`, `job_progress`, `job_completed`, `job_failed`.

### WebSocket — dashboard fanout

Endpoint: `ws://localhost:8000/ws`.

Two message types are broadcast:

- **Normalised worker events** — forwarded from `jobs:progress` after field renaming.
- **`queue_snapshot`** — emitted every 5 s by the coordinator heartbeat loop:
  ```json
  {
    "type": "queue_snapshot",
    "queue_length": 12,
    "workers_online": 3,
    "workers_idle": 1,
    "workers_busy": 2
  }
  ```

There is **no** separate `worker_heartbeat` event on pub/sub; only the coordinator
broadcasts the aggregate snapshot.

---

## Concurrency Model

**Workers — BLPOP atomicity.** Redis guarantees that `BLPOP` delivers each list element to
exactly one blocking client. Multiple workers can safely block on the same key without
coordination — Redis itself serialises the dequeue. There are no application-level locks
around the queue.

**Coordinator — asyncio event loop.** FastAPI runs on a single asyncio event loop (Uvicorn).
All DB and Redis calls use async drivers (`asyncpg`, `aioredis`). The WebSocket listener,
heartbeat loop, and HTTP request handlers all run as coroutines on the same loop; Python's
GIL is not a concern because I/O-bound tasks yield the loop voluntarily.

**Shared media volume.** All services mount the same Docker volume (`media_volume`) at
`/media`. Workers write output files there directly; no result transfer over the network.

---

## Failure Modes

**Worker crashes during a job.**
The job remains `status=processing` in PostgreSQL with no automatic transition. A crashed
worker does not re-enqueue the job. Manual intervention (PATCH the job back to `queued` or
delete and resubmit) is required. The `retry_count` column exists but there is no automatic
retry loop in the current codebase.

**Redis restarts.**
Workers lose their BLPOP connection and enter an exception handler that sleeps 1 s and
retries. The coordinator WebSocket listener has its own reconnect loop with a 3 s delay.
Any jobs that were in the queue but not yet consumed are lost (Redis is configured without
AOF/RDB persistence by default). Jobs in `status=queued` in PostgreSQL can be manually
re-enqueued.

**PostgreSQL is unreachable.**
Coordinator requests that need the DB fail with HTTP 500. Workers that try to update job
status will log errors and continue their BLPOP loop. Existing in-flight ffmpeg subprocesses
are unaffected.

**Dashboard connection loss.**
The `useWebSocket` hook retries up to 5 times with exponential backoff (1 s → 30 s cap).
The polling intervals in `JobsTable` (2 s) and `WorkersStatus` (3 s) fall back to HTTP
polling, so the UI continues working even if WebSocket is unavailable.

---

## Observability Stack

Prometheus scrapes metrics every 15 s (configured in `infra/prometheus/prometheus.yml`):

- `coordinator:8000/metrics` — job counters, queue depth, HTTP latency
- `worker-1:9100/metrics`, `worker-2:9100`, `worker-3:9100` — per-worker job counters,
  duration histograms, heartbeat timestamps, active gauge

Workers expose metrics via `prometheus_client.start_http_server(9100)`. This runs a
separate HTTP server thread inside the worker process — workers do not have a FastAPI web
server; the Prometheus HTTP thread is the only network listener beyond the Redis connection.

Loki ingests all container logs via Promtail reading from the Docker socket. Logs are
labelled by container name. Grafana datasources (`infra/grafana/datasources.yml`) and the
main dashboard (`infra/grafana/dashboards/main.json`) are provisioned at startup.

---

## Chaos Engineering

The `ChaosRunner` executes preset scenarios as asyncio tasks. Only one scenario can run at
a time. Scenarios are defined in `coordinator/chaos/scenarios.py`; the runner is in
`coordinator/chaos/runner.py`.

### Preset scenarios

| ID                   | Duration | Description                                              |
|----------------------|----------|----------------------------------------------------------|
| `worker_overload`    | 30 s     | Push 30 fake jobs at t=0; mark worker-1 and worker-2 offline at t=10 |
| `redis_outage`       | 20 s     | Clear the queue key at t=5 (simulates outage); log reconnect at t=15 |
| `cascading_failures` | 25 s     | 50% error rate + 40 fake jobs at t=0; clear error rate at t=20 |
| `slow_network`       | 15 s     | Set 2000 ms artificial delay on all jobs; clear at t=15  |

### Action types

| Action type       | Mechanism                                                              |
|-------------------|------------------------------------------------------------------------|
| `kill_worker`     | Sets `workers.status = 'offline'` in DB; restored to `idle` on cleanup |
| `spike_queue`     | Pushes N fake job JSON objects via `LPUSH jobs:queue`                  |
| `redis_disconnect`| Clears the `jobs:queue` LIST key (does NOT close the connection)       |
| `slow_job`        | Sets `chaos:slow_job_delay_ms` Redis key; workers read and sleep       |
| `inject_errors`   | Sets `chaos:error_rate` Redis key; workers read and randomly fail jobs |

**Important:** `redis_disconnect` does not actually close or disconnect the Redis TCP
connection — that would crash the coordinator. Instead it deletes the queue key, making it
appear empty to workers for the duration of the outage window. On "reconnect", it only logs
a message; the queue is empty and workers wait on BLPOP until new jobs arrive.

Chaos keys (`chaos:slow_job_delay_ms`, `chaos:error_rate`) are deleted during the
`_cleanup()` phase regardless of whether the scenario completed, was cancelled, or failed.

---

## Design Trade-offs

**Redis over RabbitMQ or Kafka.**
BLPOP provides work-queue semantics in a single command with no broker configuration,
persistent subscriptions, or consumer group state. For this scale (hundreds of jobs, three
workers), Redis is sufficient and dramatically simpler to operate. The trade-off is loss of
durability guarantees: if Redis restarts with `appendonly no`, queued items are lost.

**SQLAlchemy async over Django ORM.**
FastAPI's native async model requires an async-compatible ORM. SQLAlchemy 2.0 with
`asyncpg` integrates cleanly with FastAPI's dependency injection system and `asynccontextmanager`
lifespan. Django ORM is synchronous and would require `sync_to_async` wrappers.

**WebSocket + pub/sub over SSE or polling.**
Server-Sent Events would require a separate long-poll connection per update type. Direct
HTTP polling by the dashboard introduces latency proportional to the poll interval (2-5 s
currently). WebSocket allows the coordinator to push messages immediately on Redis events.
The current dashboard components still poll over HTTP as a fallback; the `useWebSocket`
hook exists but is not yet wired into the table and status components.

**Separate Prometheus HTTP server in the worker.**
Workers are plain Python processes without a web framework. Starting a dedicated
`prometheus_client.start_http_server()` thread is the lowest-overhead way to expose metrics
without adding FastAPI or Flask to the worker. The Prometheus thread is daemon-like and does
not affect the BLPOP loop's blocking behaviour.
