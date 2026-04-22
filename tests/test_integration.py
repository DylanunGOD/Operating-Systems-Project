"""End-to-end integration tests — require docker-compose stack running.

Run with:
    docker compose -f docker-compose.yml -f docker-compose.test.yml up -d
    RUN_INTEGRATION_TESTS=1 pytest tests/test_integration.py -v
"""

import os
import subprocess
import time
from datetime import datetime, timezone

import httpx
import pytest

RUN_INTEGRATION = os.environ.get("RUN_INTEGRATION_TESTS") == "1"
pytestmark = pytest.mark.skipif(
    not RUN_INTEGRATION,
    reason="Integration tests require RUN_INTEGRATION_TESTS=1 and live stack",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def coordinator_url() -> str:
    """Base URL for the coordinator service."""
    return os.environ.get("COORDINATOR_URL", "http://localhost:8000")


@pytest.fixture(scope="session")
def tmp_media_dir(tmp_path_factory) -> str:
    """Path to a temporary media directory for test video files."""
    media_dir = tmp_path_factory.mktemp("test_media")
    return str(media_dir)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_coordinator_health(coordinator_url: str) -> None:
    """GET /health returns 200 with status=healthy."""
    with httpx.Client(base_url=coordinator_url, timeout=10.0) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("status") == "healthy"


@pytest.mark.integration
def test_submit_thumbnail_job_end_to_end(
    coordinator_url: str, tmp_media_dir: str
) -> None:
    """Submit a thumbnail job and poll until completed (timeout 60s)."""
    # Generate a 1-second test video using ffmpeg
    test_video = os.path.join(tmp_media_dir, "test_input.mp4")
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:size=320x240:duration=1:rate=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            test_video,
        ],
        capture_output=True,
        timeout=30,
    )
    # If local ffmpeg is unavailable, use a synthetic path and rely on the worker
    if result.returncode != 0:
        test_video = "/media/test_input.mp4"

    with httpx.Client(base_url=coordinator_url, timeout=15.0) as client:
        # Submit the job
        resp = client.post(
            "/jobs",
            json={"type": "thumbnail", "input_path": test_video},
        )
        assert resp.status_code == 200, f"Job creation failed: {resp.text}"
        job_id = resp.json()["id"]

        # Poll until completed or timeout
        deadline = time.monotonic() + 60.0
        job_data = None
        while time.monotonic() < deadline:
            poll = client.get(f"/jobs/{job_id}")
            assert poll.status_code == 200
            job_data = poll.json()
            if job_data["status"] in ("completed", "failed"):
                break
            time.sleep(2)

    assert job_data is not None, "No job data received"
    assert job_data["status"] == "completed", (
        f"Job did not complete: status={job_data['status']}, "
        f"error={job_data.get('error_msg')}"
    )
    assert job_data["progress"] == 100
    assert job_data.get("output_path") is not None


@pytest.mark.integration
def test_worker_heartbeat_reflected_in_workers_endpoint(
    coordinator_url: str,
) -> None:
    """GET /workers returns at least one worker with a recent last_seen timestamp."""
    with httpx.Client(base_url=coordinator_url, timeout=10.0) as client:
        resp = client.get("/workers")
    assert resp.status_code == 200
    body = resp.json()
    workers = body.get("workers", [])
    assert len(workers) >= 1, "Expected at least one registered worker"

    worker = workers[0]
    assert worker.get("status") in {
        "idle",
        "busy",
    }, f"Unexpected worker status: {worker.get('status')}"

    # last_seen should be a recent timestamp (within 60 seconds)
    last_seen_str = worker.get("last_seen")
    assert last_seen_str is not None, "Worker missing last_seen field"
    last_seen = datetime.fromisoformat(last_seen_str.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    age_seconds = (now - last_seen).total_seconds()
    assert age_seconds < 60, f"Worker last_seen is too old: {age_seconds:.1f}s ago"


@pytest.mark.integration
def test_metrics_endpoint_prometheus_format(coordinator_url: str) -> None:
    """GET /metrics returns 200 and valid Prometheus text format."""
    with httpx.Client(base_url=coordinator_url, timeout=10.0) as client:
        resp = client.get("/metrics")
    assert resp.status_code == 200
    body = resp.text
    # Prometheus exposition format always begins with # HELP lines
    assert (
        "# HELP" in body or "coordinator_jobs_total" in body
    ), f"Response does not look like Prometheus format. First 200 chars: {body[:200]}"


@pytest.mark.integration
def test_chaos_spike_queue_increases_queue_depth(coordinator_url: str) -> None:
    """POST /chaos/runs with worker_overload then verify queue depth metric rises."""
    run_id = None
    with httpx.Client(base_url=coordinator_url, timeout=15.0) as client:
        # Start chaos scenario
        resp = client.post(
            "/chaos/runs",
            json={"scenario_id": "worker_overload"},
        )
        assert (
            resp.status_code == 200
        ), f"Failed to start chaos run: {resp.status_code} {resp.text}"
        run_id = resp.json()["run_id"]

        # Give the spike a moment to populate the queue
        time.sleep(2)

        # Check queue depth metric
        metrics_resp = client.get("/metrics")
        assert metrics_resp.status_code == 200
        metrics_body = metrics_resp.text

        # coordinator_queue_depth gauge should appear and be > 0
        assert (
            "coordinator_queue_depth" in metrics_body
        ), "coordinator_queue_depth metric not found in /metrics output"

        # Extract the value of the gauge (it appears as "coordinator_queue_depth N")
        depth = None
        for line in metrics_body.splitlines():
            if line.startswith("coordinator_queue_depth") and not line.startswith("#"):
                try:
                    depth = float(line.split()[-1])
                except ValueError:
                    pass
                break

        assert depth is not None, "Could not parse coordinator_queue_depth value"
        assert depth > 0, f"Expected queue depth > 0 after spike, got {depth}"

        # Cleanup: stop the chaos run
        if run_id:
            client.delete(f"/chaos/runs/{run_id}")


@pytest.mark.integration
def test_invalid_job_type_returns_422(coordinator_url: str) -> None:
    """POST /jobs with an invalid type returns HTTP 422 (FastAPI validation)."""
    with httpx.Client(base_url=coordinator_url, timeout=10.0) as client:
        resp = client.post(
            "/jobs",
            json={"type": "invalid_type", "input_path": "/x"},
        )
    assert (
        resp.status_code == 422
    ), f"Expected 422 for invalid job type, got {resp.status_code}: {resp.text}"
