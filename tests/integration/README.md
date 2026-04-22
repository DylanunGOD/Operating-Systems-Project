# Integration Tests

End-to-end tests that exercise the real coordinator + worker + Redis + PostgreSQL
stack running inside Docker.

## Prerequisites

- Docker Engine >= 24
- Docker Compose plugin (`docker compose`) or standalone `docker-compose` v2
- Python 3.11 with `pytest` and `httpx` installed (see below)
- No conflicting services on ports `5432`, `6379`, or `8000`

## Step-by-step

### 1. Build and start the stack

```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml build coordinator worker-1
docker compose -f docker-compose.yml -f docker-compose.test.yml up -d
```

### 2. Wait for the coordinator to become healthy

```bash
for i in $(seq 1 30); do
  curl -sf http://localhost:8000/health && break
  echo "Waiting... ($i/30)"
  sleep 2
done
```

### 3. Install Python test dependencies

```bash
pip install pytest httpx
```

### 4. Run the integration tests

```bash
RUN_INTEGRATION_TESTS=1 pytest tests/test_integration.py -v
```

### 5. Teardown

```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml down -v
```

## Interpreting failures

| Failure pattern | Likely cause |
|-----------------|--------------|
| `Connection refused` on port 8000 | Coordinator did not start; check `docker compose logs coordinator` |
| `test_submit_thumbnail_job_end_to_end` timeout | Worker did not pick up the job; check `docker compose logs worker-1` |
| `test_worker_heartbeat` assertion error | Worker never registered; it may still be starting — wait 10s and retry |
| `test_chaos_spike_queue_increases_queue_depth` fails | Stack may have leftover state; use a fresh `docker compose down -v` before retesting |
| HTTP 500 on job creation | Database migration may not have run; check coordinator logs |

## Known limitations

- The stack must be started fresh (`down -v` removes volumes) to avoid stale state
  from a previous run interfering with queue-depth assertions.
- `test_submit_thumbnail_job_end_to_end` requires `ffmpeg` to be baked into the
  worker image; if the image does not include ffmpeg the job will fail.
- Tests run against `localhost:8000` by default. Override with
  `COORDINATOR_URL=http://<host>:<port>` when the stack is on a remote host.
- The default CI pipeline (`ci.yml`) does **not** run these tests. They are
  opt-in via `RUN_INTEGRATION_TESTS=1`.
