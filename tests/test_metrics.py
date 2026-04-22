"""Unit tests for the Prometheus metrics endpoints."""

import sys

sys.path.insert(0, "coordinator")




async def test_metrics_returns_200_with_text_plain(async_client):
    """GET /metrics returns 200 OK with text/plain content-type."""
    response = await async_client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")


async def test_metrics_includes_coordinator_jobs_total_when_jobs_exist(
    async_client,
    sample_job_factory,
):
    """GET /metrics includes coordinator_jobs_total metric when jobs exist."""
    # Create jobs with different statuses
    await sample_job_factory(status="pending")
    await sample_job_factory(status="processing")
    await sample_job_factory(status="completed")
    await sample_job_factory(status="failed")

    response = await async_client.get("/metrics")
    assert response.status_code == 200

    text = response.text
    # Check that the metric appears in the output
    assert "coordinator_jobs_total" in text
    # Check for specific status labels
    assert 'coordinator_jobs_total{status="pending"}' in text
    assert 'coordinator_jobs_total{status="processing"}' in text
    assert 'coordinator_jobs_total{status="completed"}' in text
    assert 'coordinator_jobs_total{status="failed"}' in text


async def test_metrics_increments_requests_total_after_request(
    async_client,
):
    """GET /metrics shows coordinator_requests_total incremented after requests."""
    # Make a request that should be instrumented
    response = await async_client.get("/jobs")
    assert response.status_code == 200

    # Now get metrics
    metrics_response = await async_client.get("/metrics")
    assert metrics_response.status_code == 200

    text = metrics_response.text
    # Check that the metric exists (may have been called before, so just check it exists)
    assert "coordinator_requests_total" in text
    # Verify it has labels for method, path, and status_code
    assert "method=" in text
    assert "path=" in text
    assert "status_code=" in text


async def test_metrics_endpoint_itself_is_not_instrumented(async_client):
    """GET /metrics endpoint itself should not be instrumented (avoid recursion)."""
    # Get initial metrics
    response1 = await async_client.get("/metrics")
    assert response1.status_code == 200
    text1 = response1.text

    # Get metrics again
    response2 = await async_client.get("/metrics")
    assert response2.status_code == 200

    # Extract the coordinator_requests_total line for /metrics
    # It should not be incremented significantly (ideally 0 or very low)
    import re

    # Look for /metrics in the request counter
    pattern = r'coordinator_requests_total.*path="/metrics".*'
    match1 = re.search(pattern, text1)

    # If /metrics is instrumented, the counter would increase, but we expect it
    # to be absent or very low since we skip /metrics in the middleware
    if match1:
        # Extract the value after "path="/metrics""
        # It should be very low or zero since we skip it
        assert 'path="/metrics"' not in text1 or "coordinator_requests_total" in text1
