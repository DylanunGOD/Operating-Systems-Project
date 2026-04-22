"""Chaos scenario definitions and preset catalog."""

from typing import Any, Literal
from pydantic import BaseModel


class ScenarioAction(BaseModel):
    """A single step within a chaos scenario."""

    type: Literal[
        "kill_worker",
        "spike_queue",
        "redis_disconnect",
        "slow_job",
        "inject_errors",
    ]
    params: dict[str, Any]
    at_second: int


class Scenario(BaseModel):
    """A named chaos scenario with an ordered list of actions."""

    id: str
    name: str
    description: str
    duration_seconds: int
    actions: list[ScenarioAction]


# ---------------------------------------------------------------------------
# Preset scenarios
# ---------------------------------------------------------------------------

_WORKER_OVERLOAD = Scenario(
    id="worker_overload",
    name="Worker Overload",
    description=(
        "Flood the queue with 30 jobs at t=0, then mark two workers offline "
        "at t=10 to simulate capacity collapse."
    ),
    duration_seconds=30,
    actions=[
        ScenarioAction(
            type="spike_queue",
            params={"num_jobs": 30, "job_type": "convert_video"},
            at_second=0,
        ),
        ScenarioAction(
            type="kill_worker",
            params={"worker_id": "worker-1"},
            at_second=10,
        ),
        ScenarioAction(
            type="kill_worker",
            params={"worker_id": "worker-2"},
            at_second=10,
        ),
    ],
)

_REDIS_OUTAGE = Scenario(
    id="redis_outage",
    name="Redis Outage",
    description=(
        "Simulate a Redis outage by disconnecting at t=5 and reconnecting "
        "at t=15, lasting a total of 20 seconds."
    ),
    duration_seconds=20,
    actions=[
        ScenarioAction(
            type="redis_disconnect",
            params={"action": "disconnect"},
            at_second=5,
        ),
        ScenarioAction(
            type="redis_disconnect",
            params={"action": "reconnect"},
            at_second=15,
        ),
    ],
)

_CASCADING_FAILURES = Scenario(
    id="cascading_failures",
    name="Cascading Failures",
    description=(
        "Inject a 50 % error rate for 20 seconds while simultaneously "
        "flooding the queue, triggering a cascade of failed jobs."
    ),
    duration_seconds=25,
    actions=[
        ScenarioAction(
            type="inject_errors",
            params={"error_rate": 0.5},
            at_second=0,
        ),
        ScenarioAction(
            type="spike_queue",
            params={"num_jobs": 40, "job_type": "extract_audio"},
            at_second=0,
        ),
        ScenarioAction(
            type="inject_errors",
            params={"error_rate": 0.0},
            at_second=20,
        ),
    ],
)

_SLOW_NETWORK = Scenario(
    id="slow_network",
    name="Slow Network",
    description=(
        "Add an artificial 2-second delay to all job processing for 15 "
        "seconds to simulate a degraded network link."
    ),
    duration_seconds=15,
    actions=[
        ScenarioAction(
            type="slow_job",
            params={"delay_ms": 2000},
            at_second=0,
        ),
        ScenarioAction(
            type="slow_job",
            params={"delay_ms": 0},
            at_second=15,
        ),
    ],
)

_PRESETS: list[Scenario] = [
    _WORKER_OVERLOAD,
    _REDIS_OUTAGE,
    _CASCADING_FAILURES,
    _SLOW_NETWORK,
]


def get_available_scenarios() -> list[Scenario]:
    """Return the full list of built-in chaos scenarios."""
    return list(_PRESETS)


def get_scenario_by_id(scenario_id: str) -> Scenario | None:
    """Look up a preset scenario by its slug, or return None."""
    return next((s for s in _PRESETS if s.id == scenario_id), None)
