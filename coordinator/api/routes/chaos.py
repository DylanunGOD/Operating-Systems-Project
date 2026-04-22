"""REST endpoints for chaos scenario injection."""

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from chaos.scenarios import Scenario, get_available_scenarios
from chaos.runner import ChaosRunner

router = APIRouter(prefix="/chaos", tags=["chaos"])


# ---------------------------------------------------------------------------
# Dependency — runner is stored in a module-level variable so the *same*
# function object (``get_chaos_runner``) is always the dependency key.
# ``main.py`` calls ``set_chaos_runner()`` at startup; tests override via
# ``app.dependency_overrides[get_chaos_runner]``.
# ---------------------------------------------------------------------------

_runner_instance: Optional[ChaosRunner] = None


def set_chaos_runner(runner: ChaosRunner) -> None:
    """Store the application-level ChaosRunner (called from main.py lifespan)."""
    global _runner_instance
    _runner_instance = runner


def get_chaos_runner() -> ChaosRunner:
    """FastAPI dependency: return the current ChaosRunner instance."""
    if _runner_instance is None:  # pragma: no cover
        raise RuntimeError("ChaosRunner not initialised")
    return _runner_instance


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------


class StartRunRequest(BaseModel):
    scenario_id: str


class StartRunResponse(BaseModel):
    run_id: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/scenarios", response_model=list[Scenario])
async def list_scenarios() -> list[Scenario]:
    """Return all available preset chaos scenarios."""
    return get_available_scenarios()


@router.post("/runs", response_model=StartRunResponse, status_code=200)
async def start_run(
    body: StartRunRequest,
    runner: ChaosRunner = Depends(get_chaos_runner),
) -> StartRunResponse:
    """Start a chaos scenario run.

    Returns 404 if the scenario_id is unknown.
    Returns 409 if another scenario is already running.
    """
    from chaos.scenarios import get_scenario_by_id

    if get_scenario_by_id(body.scenario_id) is None:
        raise HTTPException(
            status_code=404, detail=f"Scenario '{body.scenario_id}' not found"
        )

    try:
        run_id = await runner.start(body.scenario_id)
    except ValueError as exc:
        msg = str(exc)
        if "already running" in msg:
            raise HTTPException(status_code=409, detail=msg)
        raise HTTPException(status_code=400, detail=msg)

    return StartRunResponse(run_id=run_id)


@router.get("/runs", response_model=list[dict[str, Any]])
async def list_runs(
    runner: ChaosRunner = Depends(get_chaos_runner),
) -> list[dict[str, Any]]:
    """List all chaos runs (active and historical)."""
    return runner.list_runs()


@router.get("/runs/{run_id}", response_model=dict[str, Any])
async def get_run(
    run_id: str,
    runner: ChaosRunner = Depends(get_chaos_runner),
) -> dict[str, Any]:
    """Return the status of a specific chaos run."""
    result = runner.status(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    return result


@router.delete("/runs/{run_id}", response_model=dict[str, Any])
async def stop_run(
    run_id: str,
    runner: ChaosRunner = Depends(get_chaos_runner),
) -> dict[str, Any]:
    """Cancel a running chaos scenario."""
    result = runner.status(run_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")

    stopped = await runner.stop(run_id)
    if not stopped:
        # Already completed or cancelled — return current status.
        return runner.status(run_id)  # type: ignore[return-value]

    return runner.status(run_id)  # type: ignore[return-value]
