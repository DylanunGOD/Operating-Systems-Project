"""auto_generator.py — automatic job submission from a folder + manifest.

The enunciado distinguishes two ingestion mechanisms: manual (handled by
``submit_jobs.py``) and *automatic* — a process that scans a directory plus
its associated metadata and enqueues jobs without human intervention. This
script implements the second. It polls a folder, consults ``manifest.json``
(or applies a default operation if no manifest is present), submits each
unprocessed file via ``POST /jobs``, then records the file in
``.processed.log`` so it isn't re-submitted on the next pass.

Usage:
    python client/auto_generator.py --watch ./test_files
    python client/auto_generator.py --watch ./incoming --manifest ./incoming/manifest.json --interval 10
    python client/auto_generator.py --watch ./test_files --once   # one pass then exit
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("auto_generator")


VIDEO_EXTENSIONS = {".mov", ".mp4", ".mkv", ".avi", ".webm"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac"}


def _default_operation_for(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in VIDEO_EXTENSIONS:
        return "convert_video"
    if ext in AUDIO_EXTENSIONS:
        return "extract_metadata"
    return "extract_metadata"


def _load_manifest(manifest_path: Optional[Path]) -> Dict[str, Dict[str, Any]]:
    """Return a mapping ``filename -> manifest entry`` (empty if no manifest)."""
    if manifest_path is None or not manifest_path.exists():
        return {}
    try:
        with open(manifest_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read manifest %s: %s", manifest_path, exc)
        return {}

    files = data.get("files") if isinstance(data, dict) else None
    if not isinstance(files, list):
        return {}

    by_filename: Dict[str, Dict[str, Any]] = {}
    for entry in files:
        if not isinstance(entry, dict):
            continue
        name = entry.get("filename") or entry.get("relative_path")
        if isinstance(name, str):
            by_filename[name] = entry
    return by_filename


def _read_processed(log_path: Path) -> set[str]:
    if not log_path.exists():
        return set()
    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            return {line.strip() for line in fh if line.strip()}
    except OSError:
        return set()


def _append_processed(log_path: Path, filename: str) -> None:
    try:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(filename + "\n")
    except OSError as exc:
        logger.warning("Could not write to %s: %s", log_path, exc)


async def _submit(
    client: httpx.AsyncClient,
    coordinator: str,
    payload: Dict[str, Any],
) -> Optional[str]:
    response = await client.post(f"{coordinator}/jobs", json=payload, timeout=30.0)
    if response.status_code in (200, 201):
        data = response.json()
        return str(data.get("id", ""))
    raise RuntimeError(f"HTTP {response.status_code}: {response.text[:200]}")


async def run_one_pass(
    watch_dir: Path,
    manifest: Dict[str, Dict[str, Any]],
    coordinator: str,
    default_operation: Optional[str],
    default_priority: str,
    processed: set[str],
    log_path: Path,
) -> tuple[int, int]:
    """Submit every new file once. Returns (submitted, failed)."""
    submitted = 0
    failed = 0

    candidates = sorted(p for p in watch_dir.iterdir() if p.is_file())
    if not candidates:
        return 0, 0

    async with httpx.AsyncClient() as client:
        for path in candidates:
            if path.name in processed:
                continue
            ext = path.suffix.lower()
            if ext not in VIDEO_EXTENSIONS | AUDIO_EXTENSIONS:
                # Skip non-media files (e.g. manifest.json itself)
                continue

            entry = manifest.get(path.name, {})
            operation = (
                entry.get("suggested_operation")
                or default_operation
                or _default_operation_for(path)
            )
            priority = entry.get("suggested_priority") or default_priority

            input_path = f"/media/input/{path.name}"
            payload = {
                "type": operation,
                "input_path": input_path,
                "priority": priority,
                "params": entry.get("params", {}) or {},
            }

            try:
                job_id = await _submit(client, coordinator, payload)
                logger.info(
                    "submitted %s -> %s [%s, priority=%s]",
                    path.name,
                    job_id,
                    operation,
                    priority,
                )
                processed.add(path.name)
                _append_processed(log_path, path.name)
                submitted += 1
            except (httpx.RequestError, RuntimeError) as exc:
                logger.error("submit failed for %s: %s", path.name, exc)
                failed += 1

    return submitted, failed


async def main_async(args: argparse.Namespace) -> int:
    watch_dir = Path(args.watch)
    if not watch_dir.is_dir():
        logger.error("watch path is not a directory: %s", watch_dir)
        return 2

    manifest_path = Path(args.manifest) if args.manifest else watch_dir / "manifest.json"
    log_path = Path(args.processed_log) if args.processed_log else watch_dir / ".processed.log"

    manifest = _load_manifest(manifest_path if manifest_path.exists() else None)
    if manifest:
        logger.info(
            "loaded manifest with %d entries from %s", len(manifest), manifest_path
        )
    else:
        logger.info("no manifest found; falling back to extension-based defaults")

    processed = _read_processed(log_path)
    logger.info(
        "watching %s every %ds (already processed: %d)",
        watch_dir,
        args.interval,
        len(processed),
    )

    total_submitted = 0
    total_failed = 0

    while True:
        submitted, failed = await run_one_pass(
            watch_dir=watch_dir,
            manifest=manifest,
            coordinator=args.coordinator,
            default_operation=args.default_operation,
            default_priority=args.default_priority,
            processed=processed,
            log_path=log_path,
        )
        total_submitted += submitted
        total_failed += failed
        if submitted or failed:
            logger.info("pass: submitted=%d failed=%d", submitted, failed)

        if args.once:
            break

        try:
            await asyncio.sleep(args.interval)
        except asyncio.CancelledError:
            break

    logger.info(
        "auto_generator finished: submitted=%d failed=%d", total_submitted, total_failed
    )
    return 0 if total_failed == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="auto_generator",
        description=(
            "Automatic job submitter: watches a folder + manifest and enqueues "
            "jobs without manual intervention."
        ),
    )
    parser.add_argument("--watch", required=True, help="Directory to scan.")
    parser.add_argument(
        "--manifest",
        default=None,
        help="Path to manifest.json (default: <watch>/manifest.json).",
    )
    parser.add_argument(
        "--processed-log",
        default=None,
        help="Path to processed-files log (default: <watch>/.processed.log).",
    )
    parser.add_argument(
        "--coordinator",
        default="http://localhost:8000",
        help="Coordinator base URL (default: http://localhost:8000).",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=10,
        help="Polling interval in seconds (default: 10).",
    )
    parser.add_argument(
        "--default-operation",
        default=None,
        help=(
            "Operation to apply when manifest doesn't specify one "
            "(default: extension-based: convert_video for video, extract_metadata for audio)."
        ),
    )
    parser.add_argument(
        "--default-priority",
        default="normal",
        choices=["high", "normal", "low"],
        help="Priority used when manifest doesn't specify one (default: normal).",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single pass and exit (useful for cron / CI).",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        rc = asyncio.run(main_async(args))
    except KeyboardInterrupt:
        rc = 0
    sys.exit(rc)


if __name__ == "__main__":
    main()
