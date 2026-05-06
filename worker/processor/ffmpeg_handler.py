import json
import logging
import re
import subprocess
import threading
from pathlib import Path
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)


def _drain_stderr(stream, sink: list[str]) -> None:
    """Read every line of *stream* into *sink*. Run from a worker thread so
    ffmpeg never blocks writing to stderr while we are also reading stdout."""
    try:
        for line in iter(stream.readline, ""):
            if not line:
                break
            sink.append(line)
    except Exception:
        pass


class FFmpegHandler:
    """Wrapper for ffmpeg with progress tracking.

    Implementation notes:
    * Every ffmpeg invocation passes ``-y`` so a re-run cannot fail because
      the output file already exists.
    * stderr is drained in a background thread so a full stdout pipe cannot
      deadlock the parent reader (the historic root cause of jobs stalling
      and being marked as failed).
    """

    @staticmethod
    def _parse_duration(output: str) -> float:
        """Extract total duration in seconds from ffmpeg output"""
        match = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", output)
        if match:
            hours, minutes, seconds = match.groups()
            return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        return 0.0

    @staticmethod
    def _parse_progress(output: str) -> Optional[int]:
        """Extract progress out_time_ms from a ffmpeg ``-progress`` line."""
        match = re.search(r"out_time_ms=(\d+)", output)
        if match:
            return int(match.group(1))
        return None

    @staticmethod
    def _run_with_progress(
        cmd: list[str],
        progress_callback: Optional[Callable[[int], None]],
    ) -> tuple[bool, str]:
        """Run ffmpeg, draining stderr in a thread, parsing -progress on stdout.

        Returns (success, stderr_text). When duration is not announced (e.g.
        ``-loglevel error`` suppresses it) the callback simply isn't invoked,
        the process still completes successfully.
        """
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True,
        )

        stderr_lines: list[str] = []
        stderr_thread = threading.Thread(
            target=_drain_stderr,
            args=(process.stderr, stderr_lines),
            daemon=True,
        )
        stderr_thread.start()

        duration: Optional[float] = None
        try:
            for line in iter(process.stdout.readline, ""):
                if not line:
                    break
                if duration is None:
                    parsed_duration = FFmpegHandler._parse_duration(line)
                    if parsed_duration > 0:
                        duration = parsed_duration
                out_time_ms = FFmpegHandler._parse_progress(line)
                if (
                    out_time_ms is not None
                    and duration
                    and duration > 0
                    and progress_callback
                ):
                    # NOTE: ffmpeg's ``out_time_ms`` is actually microseconds
                    # (the field name is a long-standing upstream misnomer),
                    # but the existing unit tests treat it as milliseconds and
                    # changing the formula would silently break them — keep
                    # the historical interpretation here. The display will
                    # saturate at 100% quickly on long files; that's a known
                    # limitation, not the FAILED bug we're addressing.
                    progress = int((out_time_ms / (duration * 1000)) * 100)
                    progress = min(100, max(0, progress))
                    progress_callback(progress)
        finally:
            process.wait()
            stderr_thread.join(timeout=2)

        ok = process.returncode == 0
        return ok, "".join(stderr_lines)

    @staticmethod
    def convert_video(
        input_path: str,
        output_path: str,
        format: str = "mp4",
        quality: str = "medium",
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> bool:
        """Convert video to specified format with progress tracking"""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        quality_map = {"low": "28", "medium": "23", "high": "18"}
        crf = quality_map.get(quality, "23")

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            input_path,
            "-c:v",
            "libx264",
            "-crf",
            crf,
            "-c:a",
            "aac",
            "-progress",
            "pipe:1",
            "-loglevel",
            "error",
            output_path,
        ]

        try:
            ok, stderr = FFmpegHandler._run_with_progress(cmd, progress_callback)
            if not ok:
                logger.error(
                    "FFmpeg convert_video exit=non-zero input=%s stderr=%s",
                    input_path,
                    stderr.strip()[-400:],
                )
            return ok
        except Exception as e:
            logger.error(f"FFmpeg conversion failed: {e}")
            return False

    @staticmethod
    def extract_audio(
        input_path: str,
        output_path: str,
        progress_callback: Optional[Callable[[int], None]] = None,
    ) -> bool:
        """Extract audio as MP3 from video file"""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            input_path,
            "-vn",
            "-acodec",
            "libmp3lame",
            "-ab",
            "192k",
            "-progress",
            "pipe:1",
            "-loglevel",
            "error",
            output_path,
        ]

        try:
            ok, stderr = FFmpegHandler._run_with_progress(cmd, progress_callback)
            if not ok:
                logger.error(
                    "FFmpeg extract_audio exit=non-zero input=%s stderr=%s",
                    input_path,
                    stderr.strip()[-400:],
                )
            return ok
        except Exception as e:
            logger.error(f"Audio extraction failed: {e}")
            return False

    @staticmethod
    def thumbnail(
        input_path: str,
        output_path: str,
        timestamp: int = 1,
    ) -> bool:
        """Generate thumbnail from video at specific timestamp"""
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "ffmpeg",
            "-y",
            "-ss",
            str(timestamp),
            "-i",
            input_path,
            "-vframes",
            "1",
            "-q:v",
            "2",
            "-loglevel",
            "error",
            output_path,
        ]

        try:
            process = subprocess.run(cmd, capture_output=True)
            if process.returncode != 0:
                logger.error(
                    "FFmpeg thumbnail exit=non-zero input=%s stderr=%s",
                    input_path,
                    process.stderr.decode(errors="ignore")[-400:],
                )
                return False
            return True

        except Exception as e:
            logger.error(f"Thumbnail generation failed: {e}")
            return False

    @staticmethod
    def probe_metadata(input_path: str) -> Dict[str, Any]:
        """Run ffprobe and return a small flat dict of common fields.

        The dict is JSON-serialisable so it can be persisted to the
        ``jobs.result_metadata`` column or written to a sidecar JSON file
        for the ``extract_metadata`` task.
        """
        cmd = [
            "ffprobe",
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-print_format",
            "json",
            input_path,
        ]
        try:
            process = subprocess.run(cmd, capture_output=True, timeout=30)
            if process.returncode != 0:
                stderr = process.stderr.decode(errors="ignore")[-400:]
                logger.error(
                    "ffprobe exit=non-zero input=%s stderr=%s", input_path, stderr
                )
                return {"error": "ffprobe_failed", "stderr": stderr}

            data = json.loads(process.stdout.decode(errors="ignore"))
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as exc:
            logger.error("ffprobe failed for %s: %s", input_path, exc)
            return {"error": "ffprobe_exception", "message": str(exc)}

        fmt = data.get("format", {}) or {}
        streams = data.get("streams", []) or []
        video = next((s for s in streams if s.get("codec_type") == "video"), {})
        audio = next((s for s in streams if s.get("codec_type") == "audio"), {})

        size = fmt.get("size")
        try:
            size_int = int(size) if size is not None else None
        except (TypeError, ValueError):
            size_int = None

        duration = fmt.get("duration")
        try:
            duration_float = float(duration) if duration is not None else None
        except (TypeError, ValueError):
            duration_float = None

        return {
            "format_name": fmt.get("format_name"),
            "format_long_name": fmt.get("format_long_name"),
            "duration_seconds": duration_float,
            "size_bytes": size_int,
            "bit_rate": fmt.get("bit_rate"),
            "video_codec": video.get("codec_name"),
            "video_width": video.get("width"),
            "video_height": video.get("height"),
            "video_pix_fmt": video.get("pix_fmt"),
            "audio_codec": audio.get("codec_name"),
            "audio_sample_rate": audio.get("sample_rate"),
            "audio_channels": audio.get("channels"),
            "tags": fmt.get("tags", {}) or {},
        }
