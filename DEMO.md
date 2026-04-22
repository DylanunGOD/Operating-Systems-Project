# DEMO.md — Step-by-Step Demonstration

This script walks through a complete demonstration of the distributed multimedia
processing platform, suitable for an academic presentation.

---

## Prerequisites

- Docker Desktop 24+ with Docker Compose v2
- 8 GB RAM available
- 10 GB free disk space (images + media files)
- Python 3.11+ with `pip` (for client scripts)
- `ffmpeg` installed locally and on PATH (only for generating test files)
- `gh` CLI optional (only needed to open a PR)

Verify `ffmpeg` is available:

```bash
ffmpeg -version
```

---

## 1. Setup

```bash
# Clone the repository
git clone https://github.com/DylanunGOD/Operating-Systems-Project.git
cd Operating-Systems-Project

# Copy environment template — defaults work as-is for local demo
cp .env.example .env

# Build all images (takes 2–5 minutes on first run)
docker compose build

# Start all 11 services in the background
docker compose up -d
```

Wait for services to become healthy (~30-60 seconds):

```bash
docker compose ps
```

All services should show `healthy` or `running`. If `coordinator` or `postgres` shows
`starting`, wait a few more seconds and run `docker compose ps` again.

---

## 2. Verify the Stack

```bash
# Coordinator health
curl http://localhost:8000/health
```

Expected response:

```json
{"status": "healthy", "service": "coordinator"}
```

```bash
# List available chaos scenarios
curl http://localhost:8000/chaos/scenarios
```

Open the following URLs in a browser:

| URL                         | What you see                           |
|-----------------------------|----------------------------------------|
| http://localhost:8000/docs  | Interactive API (Swagger UI)           |
| http://localhost:3000       | React dashboard                        |
| http://localhost:3001       | Grafana (user: `admin`, pass: `admin`) |
| http://localhost:9090       | Prometheus                             |

In Grafana, navigate to **Dashboards → Multimedia Distributed** to see the pre-provisioned
dashboard with 5 panels.

---

## 3. Generate Test Files

This step requires `ffmpeg` on your local PATH.

```bash
# Install client dependencies
pip install -r client/requirements.txt

# Generate 30 synthetic MP4 files, 5 seconds each
python client/generate_test_files.py --count 30 --duration 5 --output-dir ./test_files
```

Expected output:

```
[1/30] generated test_001.mp4 (5s, 320x240)
[2/30] generated test_002.mp4 (5s, 320x240)
...
[30/30] generated test_030.mp4 (5s, 320x240)
```

---

## 4. Submit a Batch of Jobs

```bash
# Submit all 30 files as convert_video jobs (10 concurrent by default)
python client/submit_jobs.py \
  --dir ./test_files \
  --type convert_video \
  --concurrency 10
```

Expected output:

```
Found 30 file(s) in './test_files'. Submitting to http://localhost:8000 ...
[30/30] submitted | 0 failed

--- Summary ---
Total files  : 30
Succeeded    : 30
Failed       : 0
Elapsed      : 2.45s
```

You can also submit a single job via curl:

```bash
curl -X POST http://localhost:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "type": "thumbnail",
    "input_path": "/media/input/test_001.mp4",
    "params": {"output_path": "/media/output/thumb_001.jpg"}
  }'
```

---

## 5. Watch Processing in the Dashboard

Open http://localhost:3000.

What to expect:
- **Queue** counter shows jobs waiting (will count down as workers consume them).
- **Procesando** counter shows active jobs (up to 3 simultaneously, one per worker).
- **Completados** counter increments as jobs finish.
- **Workers section** shows worker-1, worker-2, worker-3 with their current job and status.

The dashboard polls the coordinator every 2-3 seconds. It does not yet use the WebSocket
stream for live updates — that integration is a work in progress.

Check job status via API:

```bash
# List all jobs (default limit: 100)
curl "http://localhost:8000/jobs" | python -m json.tool

# List only processing jobs
curl "http://localhost:8000/jobs?status=processing" | python -m json.tool

# Check workers
curl http://localhost:8000/workers | python -m json.tool
```

---

## 6. Watch Metrics in Grafana

Open http://localhost:3001, log in with `admin` / `admin`.

Navigate to **Dashboards → Multimedia Distributed**. During job processing, observe:

| Panel                       | What to show                                           |
|-----------------------------|--------------------------------------------------------|
| **Queue Depth**             | Rises after submission, then falls as workers consume  |
| **Jobs by Status**          | `processing` spikes, `completed` accumulates           |
| **Worker Jobs Processed Rate** | Each worker shows a non-zero rate while busy        |
| **Request Latency p95**     | Should stay under 100 ms for API calls                 |
| **Container Logs**          | Live log stream from all containers                    |

Prometheus raw metrics are available at:

```bash
curl http://localhost:9090/api/v1/query?query=coordinator_queue_depth
curl http://localhost:9090/api/v1/query?query=worker_jobs_processed_total
```

---

## 7. Chaos Engineering Demo

### List available scenarios

```bash
curl http://localhost:8000/chaos/scenarios | python -m json.tool
```

Four scenarios are available:

| ID                   | What it does                                                   |
|----------------------|----------------------------------------------------------------|
| `worker_overload`    | Floods the queue with 30 fake jobs, then marks two workers offline |
| `redis_outage`       | Simulates Redis outage by clearing the queue key for 10 s      |
| `cascading_failures` | Injects 50% error rate while flooding the queue                |
| `slow_network`       | Adds 2 s artificial delay to all jobs for 15 s                 |

### Run worker_overload scenario

First, submit a fresh batch so there is work in flight:

```bash
python client/submit_jobs.py --dir ./test_files --type thumbnail --concurrency 5
```

Then trigger the chaos scenario:

```bash
curl -X POST http://localhost:8000/chaos/runs \
  -H "Content-Type: application/json" \
  -d '{"scenario_id": "worker_overload"}'
```

Expected response:

```json
{"run_id": "<uuid>"}
```

Watch in the dashboard: queue depth jumps as 30 fake jobs are injected, then two workers
go offline. The remaining worker continues processing. After 30 s, the scenario completes
and the workers are restored to `idle`.

### Monitor the run

```bash
# Replace <run_id> with the value from the start response
curl http://localhost:8000/chaos/runs/<run_id> | python -m json.tool
```

### Run cascading_failures scenario

```bash
curl -X POST http://localhost:8000/chaos/runs \
  -H "Content-Type: application/json" \
  -d '{"scenario_id": "cascading_failures"}'
```

Watch **Jobs by Status** in Grafana — the `failed` line rises sharply.

### Cancel a running scenario

```bash
curl -X DELETE http://localhost:8000/chaos/runs/<run_id>
```

---

## 8. Teardown

```bash
# Stop all containers and remove volumes (clears DB and media files)
docker compose down -v

# Or keep volumes (preserves job history and media)
docker compose down
```

---

## Common Demo Issues

**Workers are not processing jobs — jobs stay in `queued` status.**
The workers write to `/media/input` but the test files are on the host. Mount `./test_files`
to `/media/input` inside the workers, or generate files directly into the Docker volume:

```bash
docker compose run --rm worker-1 \
  python /media/input/generate_test_files.py --count 5 --output-dir /media/input
```

Alternatively, use a job with an `input_path` that already exists inside the volume
(such as a path generated from a previous run).

**Port 3000 is already in use.**
Another application (e.g. a local Node dev server) is using port 3000. Either stop it or
change the dashboard host port in `docker-compose.yml`:

```yaml
ports:
  - '3010:3000'    # change 3010 to any free port
```

**First `docker compose build` takes a long time.**
Python image layers and `pip install` steps are not cached on a fresh machine. Subsequent
builds use the layer cache and are much faster (under 30 s).

**Grafana shows "No data" in panels.**
Prometheus needs at least one scrape interval (15 s) after the coordinator starts before
data appears in Grafana. Wait 30 s after the stack is up, then refresh the dashboard and
set the time range to "Last 5 minutes".

**Chaos scenario returns 409 Conflict.**
A previous scenario is still running. Either wait for it to complete or cancel it:

```bash
# Find the active run
curl http://localhost:8000/chaos/runs | python -m json.tool

# Cancel it
curl -X DELETE http://localhost:8000/chaos/runs/<run_id>
```
