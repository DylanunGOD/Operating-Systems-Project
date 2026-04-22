"""submit_jobs.py — CLI for batch job submission to the coordinator API.

Usage:
    python client/submit_jobs.py --dir /media/input --type convert_video
    python client/submit_jobs.py --dir ./test_files --type thumbnail --concurrency 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Optional

import httpx

# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

VIDEO_EXTENSIONS = {".mov", ".mp4", ".mkv", ".avi", ".webm"}
AUDIO_EXTENSIONS = {".mp3", ".wav"}


def discover_files(directory: str, job_type: str) -> list[Path]:
    """Return all matching files in *directory* for the given *job_type*."""
    base = Path(directory)
    if not base.is_dir():
        raise SystemExit(f"Error: '{directory}' is not a directory or does not exist.")

    if job_type in ("convert_video", "thumbnail"):
        extensions = VIDEO_EXTENSIONS
    elif job_type == "extract_audio":
        extensions = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS
    else:
        extensions = VIDEO_EXTENSIONS | AUDIO_EXTENSIONS

    return sorted(
        p for p in base.iterdir() if p.is_file() and p.suffix.lower() in extensions
    )


# ---------------------------------------------------------------------------
# Async submission
# ---------------------------------------------------------------------------


async def submit_one(
    client: httpx.AsyncClient,
    coordinator: str,
    job_type: str,
    input_path: str,
    output_dir: str,
    params: dict,
) -> tuple[bool, Optional[str]]:
    """Submit a single job. Returns (success, job_id_or_error_msg)."""
    filename = Path(input_path).name
    output_path = str(Path(output_dir) / filename)

    payload = {
        "type": job_type,
        "input_path": input_path,
        "params": {**params, "output_path": output_path},
    }

    try:
        response = await client.post(f"{coordinator}/jobs", json=payload, timeout=30.0)
        if response.status_code in (200, 201):
            data = response.json()
            return True, str(data.get("id", ""))
        return False, f"HTTP {response.status_code}: {response.text[:120]}"
    except httpx.RequestError as exc:
        return False, f"RequestError: {exc}"


async def submit_batch(
    files: list[Path],
    coordinator: str,
    job_type: str,
    output_dir: str,
    params: dict,
    concurrency: int,
    show_progress: bool,
) -> tuple[list[str], list[tuple[str, str]]]:
    """Submit all files with bounded concurrency.

    Returns (succeeded_ids, failed_pairs) where failed_pairs is a list of
    (input_path, error_message).
    """
    succeeded: list[str] = []
    failed: list[tuple[str, str]] = []
    total = len(files)
    sem = asyncio.Semaphore(concurrency)

    async def bounded(file: Path) -> None:
        async with sem:
            ok, msg = await submit_one(
                client, coordinator, job_type, str(file), output_dir, params
            )
            if ok:
                succeeded.append(msg or "")
            else:
                failed.append((str(file), msg or "unknown error"))
            done = len(succeeded) + len(failed)
            if show_progress:
                line = f"\r[{done}/{total}] submitted | {len(failed)} failed   "
                sys.stderr.write(line)
                sys.stderr.flush()

    async with httpx.AsyncClient() as client:
        await asyncio.gather(*(bounded(f) for f in files))

    if show_progress:
        sys.stderr.write("\n")
        sys.stderr.flush()

    return succeeded, failed


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="submit_jobs",
        description="Submit a batch of multimedia jobs to the coordinator API.",
    )
    parser.add_argument(
        "--dir",
        required=True,
        metavar="PATH",
        help="Directory of input files to scan and submit.",
    )
    parser.add_argument(
        "--type",
        required=True,
        dest="job_type",
        choices=["convert_video", "extract_audio", "thumbnail"],
        metavar="TYPE",
        help="Job type: convert_video | extract_audio | thumbnail",
    )
    parser.add_argument(
        "--coordinator",
        default="http://localhost:8000",
        metavar="URL",
        help="Coordinator base URL (default: http://localhost:8000).",
    )
    parser.add_argument(
        "--params-json",
        default="{}",
        metavar="JSON",
        help='Extra params passed through to the job (default: "{}"). Must be a JSON object.',
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=10,
        metavar="N",
        help="Max concurrent submissions (default: 10).",
    )
    parser.add_argument(
        "--output-dir",
        default="/media/output",
        metavar="PATH",
        help="Output directory written into job params (default: /media/output).",
    )
    parser.add_argument(
        "--no-progress",
        action="store_true",
        default=False,
        help="Disable the live progress line.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    # Parse extra params
    try:
        params = json.loads(args.params_json)
        if not isinstance(params, dict):
            raise ValueError("params-json must be a JSON object")
    except (json.JSONDecodeError, ValueError) as exc:
        parser.error(f"--params-json: {exc}")

    # Discover files
    files = discover_files(args.dir, args.job_type)
    if not files:
        print(
            f"No matching files found in '{args.dir}' for job type '{args.job_type}'."
        )
        sys.exit(0)

    print(
        f"Found {len(files)} file(s) in '{args.dir}'. Submitting to {args.coordinator} ..."
    )

    start = time.monotonic()

    succeeded, failed = asyncio.run(
        submit_batch(
            files=files,
            coordinator=args.coordinator,
            job_type=args.job_type,
            output_dir=args.output_dir,
            params=params,
            concurrency=args.concurrency,
            show_progress=not args.no_progress,
        )
    )

    elapsed = time.monotonic() - start

    # Summary
    total = len(files)
    print("\n--- Summary ---")
    print(f"Total files  : {total}")
    print(f"Succeeded    : {len(succeeded)}")
    print(f"Failed       : {len(failed)}")
    print(f"Elapsed      : {elapsed:.2f}s")

    if failed:
        print("\nFailed jobs (first 10):")
        for path, err in failed[:10]:
            print(f"  {path}  ->  {err}")

    sys.exit(0 if not failed else 1)


if __name__ == "__main__":
    main()
