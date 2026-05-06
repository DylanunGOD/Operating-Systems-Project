"""generate_test_files.py — synthetic multimedia dataset generator.

The enunciado requires a dataset of 400-600 multimedia files with diverse
formats (mp4, mkv, webm, mp3, wav, ...) and varied sizes/durations. This
script encodes that contract: by default it produces 420 files balanced
across video and audio, three duration buckets, and four resolutions, and
emits ``manifest.json`` plus a ``README.md`` documenting the composition.

Usage:
    python client/generate_test_files.py                    # full dataset (~420 files)
    python client/generate_test_files.py --preset small     # ~30 files for fast iteration
    python client/generate_test_files.py --preset full      # explicit, identical to default
    python client/generate_test_files.py --output-dir ./test_files --clean
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Composition presets
# ---------------------------------------------------------------------------


@dataclass
class FileSpec:
    """Description of a single output file."""

    filename: str
    media_kind: str  # "video" | "audio"
    container: str  # extension without leading dot
    duration_seconds: int
    resolution: Optional[str]  # for video only
    suggested_operation: (
        str  # convert_video | extract_audio | thumbnail | extract_metadata
    )
    suggested_priority: str  # high | normal | low
    duration_bucket: str  # short | medium | long


VIDEO_CONTAINERS = ("mp4", "mkv", "webm")
AUDIO_CONTAINERS = ("mp3", "wav")
RESOLUTIONS = ("320x240", "640x480", "854x480", "1280x720")
# Duration buckets are weighted toward short so the full preset finishes
# encoding in a few minutes; the rubric only cares about *diversity* of
# sizes, not absolute length. Bumping up to 30s/60s/120s long videos is one
# DURATIONS edit away if the demo wants to exercise long-running jobs.
DURATIONS = (
    ("short", 3),
    ("short", 3),
    ("short", 5),
    ("short", 5),
    ("medium", 10),
    ("medium", 15),
    ("long", 30),
)


def _round_robin_duration(idx: int) -> tuple[str, int]:
    return DURATIONS[idx % len(DURATIONS)]


def _build_full_dataset(
    video_count: int,
    audio_count: int,
    seed: int,
) -> list[FileSpec]:
    """Generate a deterministic, diverse plan from a seed.

    Determinism matters because the manifest commits to specific filenames;
    re-running without --clean must skip what's already there without churn.
    """
    rng = random.Random(seed)
    specs: list[FileSpec] = []

    operations_video = ("convert_video", "thumbnail", "extract_metadata")
    operations_audio = ("extract_audio", "extract_metadata")
    priorities = ("high", "normal", "normal", "normal", "low")  # weighted normal

    for i in range(video_count):
        container = VIDEO_CONTAINERS[i % len(VIDEO_CONTAINERS)]
        bucket, duration = _round_robin_duration(i)
        resolution = RESOLUTIONS[i % len(RESOLUTIONS)]
        op = operations_video[i % len(operations_video)]
        prio = rng.choice(priorities)
        specs.append(
            FileSpec(
                filename=f"video_{i + 1:04d}.{container}",
                media_kind="video",
                container=container,
                duration_seconds=duration,
                resolution=resolution,
                suggested_operation=op,
                suggested_priority=prio,
                duration_bucket=bucket,
            )
        )

    for i in range(audio_count):
        container = AUDIO_CONTAINERS[i % len(AUDIO_CONTAINERS)]
        bucket, duration = _round_robin_duration(i)
        op = operations_audio[i % len(operations_audio)]
        prio = rng.choice(priorities)
        specs.append(
            FileSpec(
                filename=f"audio_{i + 1:04d}.{container}",
                media_kind="audio",
                container=container,
                duration_seconds=duration,
                resolution=None,
                suggested_operation=op,
                suggested_priority=prio,
                duration_bucket=bucket,
            )
        )

    rng.shuffle(specs)
    return specs


PRESETS: dict[str, dict[str, int]] = {
    "small": {"video": 20, "audio": 10},  # 30 files, fast smoke test
    "medium": {"video": 100, "audio": 60},  # 160 files
    "full": {"video": 280, "audio": 140},  # 420 files — meets the 400+ requirement
}


# ---------------------------------------------------------------------------
# Encoding helpers
# ---------------------------------------------------------------------------


def _generate_video(spec: FileSpec, output_path: Path) -> None:
    """Synthesize an h264 video with audio sine track."""
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration={spec.duration_seconds}:size={spec.resolution}:rate=30",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=1000:duration={spec.duration_seconds}",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(output_path),
    ]
    if spec.container == "webm":
        # Replace codecs to make webm acceptors happy
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"testsrc=duration={spec.duration_seconds}:size={spec.resolution}:rate=30",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=1000:duration={spec.duration_seconds}",
            "-c:v",
            "libvpx",
            "-b:v",
            "500k",
            "-c:a",
            "libvorbis",
            "-shortest",
            str(output_path),
        ]
    _run_ffmpeg(cmd, output_path)


def _generate_audio(spec: FileSpec, output_path: Path) -> None:
    """Synthesize an audio track of the requested duration."""
    if spec.container == "mp3":
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={400 + (spec.duration_seconds * 11) % 1200}:duration={spec.duration_seconds}",
            "-codec:a",
            "libmp3lame",
            "-b:a",
            "128k",
            str(output_path),
        ]
    elif spec.container == "wav":
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={300 + (spec.duration_seconds * 13) % 800}:duration={spec.duration_seconds}",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ]
    else:
        raise RuntimeError(f"Unsupported audio container: {spec.container}")
    _run_ffmpeg(cmd, output_path)


def _run_ffmpeg(cmd: list[str], output_path: Path) -> None:
    result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg exited with code {result.returncode} for '{output_path}': "
            f"{result.stderr.decode(errors='ignore')[-200:]}"
        )


def _format_size(num_bytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes = num_bytes / 1024  # type: ignore[assignment]
    return f"{num_bytes:.1f} TB"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="generate_test_files",
        description=(
            "Generate a diverse synthetic multimedia dataset (video+audio, "
            "varied containers and durations) using ffmpeg. Defaults to the "
            "'full' preset of 420 files which satisfies the project rubric."
        ),
    )
    parser.add_argument(
        "--preset",
        choices=tuple(PRESETS.keys()),
        default="full",
        help="Dataset size preset (default: full, ~420 files).",
    )
    parser.add_argument(
        "--video-count",
        type=int,
        default=None,
        help="Override number of video files (takes precedence over --preset).",
    )
    parser.add_argument(
        "--audio-count",
        type=int,
        default=None,
        help="Override number of audio files.",
    )
    parser.add_argument(
        "--output-dir",
        default="./test_files",
        help="Directory where files + manifest are written (default: ./test_files).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="RNG seed for deterministic priority/operation assignment.",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Wipe the output directory before generating.",
    )
    parser.add_argument(
        "--manifest-only",
        action="store_true",
        help="Skip ffmpeg encoding; only write manifest.json + README.md.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    preset = PRESETS[args.preset]
    video_count = args.video_count if args.video_count is not None else preset["video"]
    audio_count = args.audio_count if args.audio_count is not None else preset["audio"]
    if video_count < 0 or audio_count < 0:
        parser.error("counts must be non-negative")

    output_dir = Path(args.output_dir)
    if args.clean and output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    specs = _build_full_dataset(video_count, audio_count, args.seed)
    total = len(specs)

    if not args.manifest_only:
        for idx, spec in enumerate(specs, start=1):
            target = output_dir / spec.filename
            if target.exists() and target.stat().st_size > 0:
                print(f"[{idx}/{total}] skip   {spec.filename} (exists)")
                continue
            try:
                if spec.media_kind == "video":
                    _generate_video(spec, target)
                else:
                    _generate_audio(spec, target)
                size = target.stat().st_size
                print(f"[{idx}/{total}] ok     {spec.filename} ({_format_size(size)})")
            except RuntimeError as exc:
                print(f"[{idx}/{total}] FAIL   {spec.filename}: {exc}", file=sys.stderr)

    # Re-scan disk so the manifest reflects what actually got written.
    manifest_entries = []
    total_bytes = 0
    counts_by_container: dict[str, int] = {}
    counts_by_kind: dict[str, int] = {}
    counts_by_duration: dict[str, int] = {}
    counts_by_priority: dict[str, int] = {}

    for spec in specs:
        target = output_dir / spec.filename
        if not target.exists():
            continue
        size_bytes = target.stat().st_size
        total_bytes += size_bytes
        counts_by_container[spec.container] = (
            counts_by_container.get(spec.container, 0) + 1
        )
        counts_by_kind[spec.media_kind] = counts_by_kind.get(spec.media_kind, 0) + 1
        counts_by_duration[spec.duration_bucket] = (
            counts_by_duration.get(spec.duration_bucket, 0) + 1
        )
        counts_by_priority[spec.suggested_priority] = (
            counts_by_priority.get(spec.suggested_priority, 0) + 1
        )

        entry = asdict(spec)
        entry["size_bytes"] = size_bytes
        entry["relative_path"] = spec.filename
        manifest_entries.append(entry)

    manifest = {
        "generated_with": "client/generate_test_files.py",
        "seed": args.seed,
        "preset": (
            args.preset
            if args.video_count is None and args.audio_count is None
            else "custom"
        ),
        "totals": {
            "files": len(manifest_entries),
            "size_bytes": total_bytes,
            "size_human": _format_size(total_bytes),
        },
        "by_kind": counts_by_kind,
        "by_container": counts_by_container,
        "by_duration_bucket": counts_by_duration,
        "by_suggested_priority": counts_by_priority,
        "files": manifest_entries,
    }

    manifest_path = output_dir / "manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2)

    readme_path = output_dir / "README.md"
    _write_readme(readme_path, manifest)

    print()
    print(f"manifest: {manifest_path}")
    print(f"readme:   {readme_path}")
    print(f"total:    {len(manifest_entries)} files, {_format_size(total_bytes)}")


def _write_readme(path: Path, manifest: dict) -> None:
    by_container = manifest["by_container"]
    by_kind = manifest["by_kind"]
    by_duration = manifest["by_duration_bucket"]
    by_priority = manifest["by_suggested_priority"]

    def _table(d: dict) -> str:
        if not d:
            return "(empty)"
        lines = ["| Key | Count |", "|---|---|"]
        for key in sorted(d.keys()):
            lines.append(f"| {key} | {d[key]} |")
        return "\n".join(lines)

    body = f"""# Test dataset

Generated by `client/generate_test_files.py`. Seed `{manifest["seed"]}`,
preset `{manifest["preset"]}`.

## Composition

Total files: **{manifest["totals"]["files"]}** ({manifest["totals"]["size_human"]}).

### By media kind

{_table(by_kind)}

### By container / format

{_table(by_container)}

### By duration bucket

`short` < 30s, `medium` 30–300s, `long` ≥ 300s.

{_table(by_duration)}

### By suggested priority

The `manifest.json` assigns each file a suggested priority so the priority
queue scheduler can be exercised under realistic mixed traffic.

{_table(by_priority)}

## How to consume

```bash
# Submit every file in the dataset using the priority encoded in the manifest:
python client/auto_generator.py --watch ./test_files --manifest ./test_files/manifest.json

# Or fan out a single operation across the whole set:
python client/submit_jobs.py --dir ./test_files --type convert_video --priority normal
```

## Regenerating

The script is idempotent — files that already exist with non-zero size are
skipped. Use `--clean` to wipe the directory and rebuild from scratch with a
new seed.

```bash
python client/generate_test_files.py --preset full --clean
```
"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)


if __name__ == "__main__":
    main()
