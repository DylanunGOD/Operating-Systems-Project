import subprocess
import re
import logging
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class FFmpegHandler:
    """Wrapper for ffmpeg with progress tracking"""

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
        """Extract progress percentage from ffmpeg stderr"""
        match = re.search(r"out_time_ms=(\d+)", output)
        if match:
            return int(match.group(1))
        return None

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
            "-i", input_path,
            "-c:v", "libx264",
            "-crf", crf,
            "-c:a", "aac",
            "-progress", "pipe:1",
            "-loglevel", "error",
            output_path,
        ]

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
            )

            duration = None
            for line in process.stderr:
                if "Duration:" in line and duration is None:
                    duration = FFmpegHandler._parse_duration(line)

            for line in process.stdout:
                out_time_ms = FFmpegHandler._parse_progress(line)
                if out_time_ms is not None and duration and duration > 0:
                    progress = int((out_time_ms / (duration * 1000)) * 100)
                    progress = min(100, max(0, progress))
                    if progress_callback:
                        progress_callback(progress)

            process.wait()
            return process.returncode == 0

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
            "-i", input_path,
            "-vn",
            "-acodec", "libmp3lame",
            "-ab", "192k",
            "-progress", "pipe:1",
            "-loglevel", "error",
            output_path,
        ]

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True,
            )

            duration = None
            for line in process.stderr:
                if "Duration:" in line and duration is None:
                    duration = FFmpegHandler._parse_duration(line)

            for line in process.stdout:
                out_time_ms = FFmpegHandler._parse_progress(line)
                if out_time_ms is not None and duration and duration > 0:
                    progress = int((out_time_ms / (duration * 1000)) * 100)
                    progress = min(100, max(0, progress))
                    if progress_callback:
                        progress_callback(progress)

            process.wait()
            return process.returncode == 0

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
            "-ss", str(timestamp),
            "-i", input_path,
            "-vframes", "1",
            "-q:v", "2",
            "-loglevel", "error",
            output_path,
        ]

        try:
            process = subprocess.run(cmd, capture_output=True)
            return process.returncode == 0

        except Exception as e:
            logger.error(f"Thumbnail generation failed: {e}")
            return False
