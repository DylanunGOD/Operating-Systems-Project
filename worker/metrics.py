"""Prometheus metrics for worker."""

from prometheus_client import Counter, Histogram, Gauge

# Worker job processing metrics
worker_jobs_processed_total = Counter(
    "worker_jobs_processed_total",
    "Total number of jobs processed",
    labelnames=["job_type", "status"],
)

worker_job_duration_seconds = Histogram(
    "worker_job_duration_seconds",
    "Duration of job processing in seconds",
    labelnames=["job_type"],
)

# Worker status metrics
worker_heartbeat_timestamp = Gauge(
    "worker_heartbeat_timestamp",
    "Timestamp of the last worker heartbeat",
)

worker_active = Gauge(
    "worker_active",
    "1 if worker is actively processing a job, 0 if idle",
)
