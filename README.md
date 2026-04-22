# multimedia-distributed

A distributed multimedia processing platform that distributes workload across multiple
coordinated nodes, processing hundreds of video and audio files in parallel with real-time
monitoring and fault tolerance.

Academic project developed in the context of Operating Systems. Demonstrates concurrent
processes, task queues, scheduling, inter-process communication, and distributed systems
using FastAPI, Redis, PostgreSQL, Docker, Prometheus, and Grafana.

---

## Architecture

```
                 ┌──────────────────────────────────────────────────┐
                 │                  backend network                  │
                 │                                                   │
  Client CLI ──► │  Coordinator (FastAPI :8000)                      │
                 │    ├── REST API (/jobs, /workers, /metrics)       │
                 │    ├── WebSocket /ws  (fanout to dashboard)       │
                 │    ├── Chaos runner   (/chaos/*)                  │
                 │    └── Prometheus metrics (/metrics)              │
                 │          │               │                        │
                 │       Redis :6379     PostgreSQL :5432            │
                 │    jobs:queue (LIST)   jobs / workers / events    │
                 │    jobs:progress (pub/sub)                        │
                 │          │                                        │
                 │  Worker-1 Worker-2 Worker-3  (BLPOP loop)        │
                 │    └── ffmpeg subprocess                          │
                 │    └── Prometheus :9100                           │
                 └──────────────────────────────────────────────────┘
                          │                       │
              ┌──────────────────┐   ┌────────────────────────┐
              │ frontend network  │   │    monitoring network  │
              │  Dashboard :3000  │   │  Prometheus  :9090     │
              │  (React + Vite)   │   │  Grafana     :3001     │
              └──────────────────┘   │  Loki        :3100     │
                                     └────────────────────────┘
```

---

## Stack

| Component       | Technology              | Purpose                                    |
|-----------------|-------------------------|--------------------------------------------|
| Coordinator     | FastAPI + Uvicorn       | REST API, job queue management, WebSocket  |
| ORM             | SQLAlchemy async 2.0    | Async DB access compatible with FastAPI    |
| Queue           | Redis 7 (LIST + pub/sub)| Distributed task queue and progress events |
| Database        | PostgreSQL 15           | Persistent job, worker and event records   |
| Workers         | Python + ffmpeg         | Video conversion, audio extraction, thumbs |
| Dashboard       | React 18 + Vite 5       | Browser UI polling the coordinator API     |
| Client CLI      | Python + httpx          | Batch job submission and test file gen     |
| Metrics         | Prometheus + Grafana    | Time-series metrics and dashboards         |
| Logs            | Loki + Promtail         | Structured log aggregation                 |
| CI              | GitHub Actions          | Lint (ruff+black), test, Docker build      |

---

## Quick Start

**Prerequisites:** Docker Desktop 24+, Docker Compose v2, 8 GB RAM available.

```bash
# 1. Clone
git clone https://github.com/DylanunGOD/Operating-Systems-Project.git
cd Operating-Systems-Project

# 2. Configure environment (defaults work for local dev)
cp .env.example .env

# 3. Build and start all services
docker compose up -d --build
```

Wait ~60 s for services to become healthy, then verify:

```bash
# Health check
curl http://localhost:8000/health

# Submit a test job
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"type":"thumbnail","input_path":"/media/input/test.mp4","params":{}}'

# List jobs
curl http://localhost:8000/jobs
```

| URL                          | What                          |
|------------------------------|-------------------------------|
| http://localhost:8000/docs   | Interactive API (Swagger UI)  |
| http://localhost:3000        | React dashboard               |
| http://localhost:3001        | Grafana (admin / admin)       |
| http://localhost:9090        | Prometheus                    |

---

## Directory Layout

```
.
├── coordinator/        FastAPI app — REST API, WebSocket, metrics, chaos runner
├── worker/             Worker service — BLPOP loop, ffmpeg handler, Prometheus :9100
├── dashboard/          React + Vite frontend (polling; WebSocket hook exists but unused)
├── client/             CLI tools: submit_jobs.py and generate_test_files.py
├── chaos/              Shared chaos scenario definitions (also used by coordinator)
├── tests/              Unit tests (84 total: 63 coordinator, 21 worker)
├── infra/
│   ├── postgres/       init.sql — DDL for jobs, workers, events tables
│   ├── redis/          redis.conf
│   ├── grafana/        Provisioned datasources and main.json dashboard
│   └── prometheus/     prometheus.yml — scrape config for coordinator and workers
├── docker-compose.yml  Full stack: 11 services
├── .env.example        Environment variable template
└── pytest.ini          Test configuration
```

---

## API Endpoints

### Jobs

| Method   | Path              | Description                                        |
|----------|-------------------|----------------------------------------------------|
| `POST`   | `/jobs`           | Create a job (`type`, `input_path`, `params`)      |
| `GET`    | `/jobs`           | List jobs (query: `status`, `worker_id`, `limit`)  |
| `GET`    | `/jobs/{id}`      | Get job detail                                     |
| `PATCH`  | `/jobs/{id}`      | Update job (`status`, `progress`, `error_msg`, …)  |
| `DELETE` | `/jobs/{id}`      | Cancel a pending job                               |

### Workers / Metrics / System

| Method   | Path              | Description                                        |
|----------|-------------------|----------------------------------------------------|
| `GET`    | `/workers`        | List all workers with status and resource usage    |
| `GET`    | `/workers/{id}`   | Get a single worker                                |
| `GET`    | `/metrics`        | Prometheus text format metrics                     |
| `GET`    | `/health`         | `{"status":"healthy"}`                             |

### Chaos

| Method   | Path                    | Description                                  |
|----------|-------------------------|----------------------------------------------|
| `GET`    | `/chaos/scenarios`      | List available preset scenarios              |
| `POST`   | `/chaos/runs`           | Start a scenario (`{"scenario_id": "..."}`)  |
| `GET`    | `/chaos/runs`           | List all runs (active + historical)          |
| `GET`    | `/chaos/runs/{run_id}`  | Get run status                               |
| `DELETE` | `/chaos/runs/{run_id}`  | Cancel a running scenario                    |

### WebSocket

| Protocol | Path | Description                                             |
|----------|------|---------------------------------------------------------|
| `WS`     | `/ws` | Real-time event stream (job progress + queue snapshots) |

**Note:** The old README listed `POST /chaos/{scenario}` — the actual API is
`POST /chaos/runs` with a JSON body. The old docs also listed 6 scenario IDs; the actual
presets are 4: `worker_overload`, `redis_outage`, `cascading_failures`, `slow_network`.

---

## Development

### Running tests

```bash
# Install test dependencies
pip install -r coordinator/requirements.txt -r worker/requirements.txt
pip install pytest pytest-asyncio fakeredis httpx

# Run all unit tests
pytest tests/ -q

# With coverage
pytest tests/ --cov=coordinator --cov=worker --cov-report=term-missing
```

84 unit tests total (63 coordinator, 21 worker). Integration tests (`tests/test_integration.py`)
require a live Docker stack and are a work in progress.

### Lint

```bash
black . && ruff check .
```

CI runs lint, tests (with postgres + redis services), and `docker build` on every push to
`main` or `develop`.

### Local setup without Docker

```bash
# Start only the infrastructure
docker compose up -d postgres redis

# Run coordinator
cd coordinator && pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Run a worker in another terminal
cd worker && pip install -r requirements.txt
WORKER_ID=worker-local python main.py
```

---

## Observability

### Grafana (http://localhost:3001, admin/admin)

The `infra/grafana/dashboards/main.json` dashboard is provisioned automatically with 5 panels:

| Panel                      | Type       | What it shows                              |
|----------------------------|------------|--------------------------------------------|
| Queue Depth                | timeseries | `coordinator_queue_depth` over time        |
| Jobs by Status             | timeseries | `coordinator_jobs_total` by status label   |
| Worker Jobs Processed Rate | timeseries | `worker_jobs_processed_total` rate         |
| Request Latency p95        | timeseries | `coordinator_request_duration_seconds`     |
| Container Logs             | logs       | Loki log stream from all containers        |

### Prometheus (http://localhost:9090)

Coordinator metrics scraped from `:8000/metrics`:

- `coordinator_jobs_total{status}` — job count by status
- `coordinator_workers_total{status}` — worker count by status (online/busy)
- `coordinator_queue_depth` — current Redis queue length
- `coordinator_requests_total{method,path,status_code}` — HTTP request counter
- `coordinator_request_duration_seconds{method,path}` — request latency histogram

Worker metrics scraped from each worker's `:9100/metrics`:

- `worker_jobs_processed_total{job_type,status}` — jobs processed counter
- `worker_job_duration_seconds{job_type}` — processing time histogram
- `worker_heartbeat_timestamp` — last heartbeat Unix timestamp
- `worker_active` — 1 if processing, 0 if idle

### Loki

Access via Grafana Explore. Example LogQL query:

```
{container="worker-1"} | json
```

---

## Running the Demo

See [DEMO.md](DEMO.md) for the full step-by-step demonstration script.

---

## Troubleshooting

**Port already in use (8000, 3000, 3001, 9090)**
Another process is using those ports. Find and stop it, or edit the host-side port
mappings in `docker-compose.yml`.

**Dashboard shows no data / workers not registered**
Workers register in PostgreSQL only after they pick up their first job. Submit at least
one job and wait a few seconds before checking `/workers`.

**ffmpeg not found when generating test files**
`generate_test_files.py` requires `ffmpeg` installed locally on your PATH (not inside
Docker). Install it with `brew install ffmpeg` (macOS) or `apt install ffmpeg` (Debian/Ubuntu).

**First `docker compose up --build` is slow**
The coordinator and worker images pull Python 3.11-slim and install dependencies from
scratch. Subsequent builds use the layer cache and are much faster.

---

## Operating Systems Concepts Demonstrated

- **Concurrent processes:** multiple workers execute ffmpeg in parallel via `asyncio` and `subprocess`
- **Task queues:** Redis as a distributed scheduling structure with atomic BLPOP
- **Scheduling:** dynamic job assignment to the first available worker via BLPOP
- **IPC:** REST API, WebSocket, and Redis pub/sub between independent components
- **Resource monitoring:** CPU, memory, and throughput per node via `psutil` and Prometheus
- **Fault tolerance:** worker crash recovery, reconnection logic, error injection via chaos scenarios

---

## License

MIT

## Contributing

Open a PR against `main`. Run `black . && ruff check .` and `pytest tests/ -q` before pushing.
