"""generate_test_files.py — Generate synthetic test videos using ffmpeg.

Usage:
    python client/generate_test_files.py --count 10 --duration 5
    python client/generate_test_files.py --count 3 --output-dir ./my_files --resolution 640x480
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Core generation logic
# ---------------------------------------------------------------------------


def generate_video(
    output_path: Path,
    duration: int,
    resolution: str,
) -> None:
    """Run ffmpeg to create a synthetic test video at *output_path*."""
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={duration}:size={resolution}:rate=30",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=1000:duration={duration}",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-c:a",
        "aac",
        str(output_path),
    ]
    result = subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg exited with code {result.returncode} for '{output_path}'. "
            "Make sure ffmpeg is installed and on PATH."
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="generate_test_files",
        description="Generate N synthetic MP4 test files using ffmpeg.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=10,
        metavar="N",
        help="Number of test videos to generate (default: 10).",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=5,
        metavar="SECONDS",
        help="Duration of each video in seconds (default: 5).",
    )
    parser.add_argument(
        "--output-dir",
        default="./test_files",
        metavar="PATH",
        help="Directory where files are written (default: ./test_files).",
    )
    parser.add_argument(
        "--resolution",
        default="320x240",
        metavar="WxH",
        help="Video resolution (default: 320x240).",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.count < 1:
        parser.error("--count must be >= 1")
    if args.duration < 1:
        parser.error("--duration must be >= 1")
    if "x" not in args.resolution:
        parser.error("--resolution must be in WxH format, e.g. 320x240")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []

    for i in range(1, args.count + 1):
        filename = f"test_{i:03d}.mp4"
        output_path = output_dir / filename

        if output_path.exists():
            print(f"[{i}/{args.count}] skipped  {filename} (already exists)")
            continue

        try:
            generate_video(output_path, args.duration, args.resolution)
            print(
                f"[{i}/{args.count}] generated {filename} "
                f"({args.duration}s, {args.resolution})"
            )
        except RuntimeError as exc:
            print(f"[{i}/{args.count}] ERROR    {filename}: {exc}", file=sys.stderr)
            errors.append(filename)

    if errors:
        print(f"\n{len(errors)} file(s) failed to generate.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
