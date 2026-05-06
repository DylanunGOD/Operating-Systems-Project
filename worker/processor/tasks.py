import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .ffmpeg_handler import FFmpegHandler
from .reporter import ProgressReporter
from metrics import worker_jobs_processed_total, worker_job_duration_seconds

logger = logging.getLogger(__name__)


def _classify_by_format(ext: str) -> str:
    """Bucket a file extension into a coarse format family for organisation."""
    ext = (ext or "").lower().lstrip(".")
    if ext in {"mp4", "mkv", "webm", "mov", "avi"}:
        return "video"
    if ext in {"mp3", "wav", "flac", "ogg", "m4a", "aac"}:
        return "audio"
    if ext in {"jpg", "jpeg", "png", "webp", "gif"}:
        return "image"
    if ext == "json":
        return "metadata"
    return "other"


def _classify_by_duration(duration_seconds: Optional[float]) -> str:
    """Coarse duration bucket: short / medium / long."""
    if duration_seconds is None:
        return "unknown"
    if duration_seconds < 30:
        return "short"
    if duration_seconds < 300:
        return "medium"
    return "long"


class TaskProcessor:
    """Executes media processing tasks"""

    def __init__(
        self,
        ffmpeg: FFmpegHandler,
        reporter: ProgressReporter,
    ):
        self.ffmpeg = ffmpeg
        self.reporter = reporter

    def process_convert_video(
        self,
        job_id: str,
        worker_id: str,
        input_path: str,
        output_path: str,
        params: Dict[str, Any],
    ) -> bool:
        """Convert video to target format"""
        logger.info(f"Starting video conversion: {job_id}")

        format_target = params.get("format", "mp4")
        quality = params.get("quality", "medium")

        def progress_callback(progress: int):
            self.reporter.report_progress(job_id, worker_id, progress)

        try:
            success = self.ffmpeg.convert_video(
                input_path=input_path,
                output_path=output_path,
                format=format_target,
                quality=quality,
                progress_callback=progress_callback,
            )

            if success:
                self.reporter.report_completed(job_id, worker_id, output_path)
                logger.info(f"Video conversion completed: {job_id}")
            else:
                error = f"FFmpeg conversion failed for {input_path}"
                self.reporter.report_failed(job_id, worker_id, error)
                logger.error(error)

            return success

        except Exception as e:
            error = f"Unexpected error during conversion: {str(e)}"
            self.reporter.report_failed(job_id, worker_id, error)
            logger.error(error)
            return False

    def process_extract_audio(
        self,
        job_id: str,
        worker_id: str,
        input_path: str,
        output_path: str,
        params: Dict[str, Any],
    ) -> bool:
        """Extract audio as MP3"""
        logger.info(f"Starting audio extraction: {job_id}")

        def progress_callback(progress: int):
            self.reporter.report_progress(job_id, worker_id, progress)

        try:
            success = self.ffmpeg.extract_audio(
                input_path=input_path,
                output_path=output_path,
                progress_callback=progress_callback,
            )

            if success:
                self.reporter.report_completed(job_id, worker_id, output_path)
                logger.info(f"Audio extraction completed: {job_id}")
            else:
                error = f"FFmpeg audio extraction failed for {input_path}"
                self.reporter.report_failed(job_id, worker_id, error)
                logger.error(error)

            return success

        except Exception as e:
            error = f"Unexpected error during audio extraction: {str(e)}"
            self.reporter.report_failed(job_id, worker_id, error)
            logger.error(error)
            return False

    def process_thumbnail(
        self,
        job_id: str,
        worker_id: str,
        input_path: str,
        output_path: str,
        params: Dict[str, Any],
    ) -> bool:
        """Generate thumbnail at timestamp"""
        logger.info(f"Starting thumbnail generation: {job_id}")

        timestamp = params.get("timestamp", 1)

        try:
            self.reporter.report_progress(job_id, worker_id, 50)

            success = self.ffmpeg.thumbnail(
                input_path=input_path,
                output_path=output_path,
                timestamp=timestamp,
            )

            if success:
                self.reporter.report_progress(job_id, worker_id, 100)
                self.reporter.report_completed(job_id, worker_id, output_path)
                logger.info(f"Thumbnail generation completed: {job_id}")
            else:
                error = f"FFmpeg thumbnail generation failed for {input_path}"
                self.reporter.report_failed(job_id, worker_id, error)
                logger.error(error)

            return success

        except Exception as e:
            error = f"Unexpected error during thumbnail generation: {str(e)}"
            self.reporter.report_failed(job_id, worker_id, error)
            logger.error(error)
            return False

    def process_extract_metadata(
        self,
        job_id: str,
        worker_id: str,
        input_path: str,
        output_path: str,
        params: Dict[str, Any],
    ) -> bool:
        """Run ffprobe and persist metadata as a JSON sidecar + DB column.

        The metadata dict is also forwarded with the completion event so the
        coordinator stores it on ``jobs.result_metadata``. The on-disk JSON
        artefact lets clients consume it via ``GET /jobs/{id}/result``.
        """
        logger.info("Starting metadata extraction: %s", job_id)

        try:
            self.reporter.report_progress(job_id, worker_id, 25)
            metadata = self.ffmpeg.probe_metadata(input_path)

            if isinstance(metadata, dict) and metadata.get("error"):
                error = (
                    f"ffprobe failed for {input_path}: "
                    f"{metadata.get('message') or metadata.get('stderr')}"
                )
                self.reporter.report_failed(job_id, worker_id, error)
                logger.error(error)
                return False

            self.reporter.report_progress(job_id, worker_id, 75)

            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as fh:
                json.dump(metadata, fh, indent=2, default=str)

            self.reporter.report_progress(job_id, worker_id, 100)
            self.reporter.report_completed(
                job_id, worker_id, output_path, result_metadata=metadata
            )
            logger.info("Metadata extraction completed: %s", job_id)
            return True

        except Exception as e:
            error = f"Unexpected error during metadata extraction: {e}"
            self.reporter.report_failed(job_id, worker_id, error)
            logger.error(error)
            return False

    def process_classify_output(
        self,
        job_id: str,
        worker_id: str,
        input_path: str,
        output_path: str,
        params: Dict[str, Any],
    ) -> bool:
        """Move/copy a media artefact into format/duration buckets.

        Used as a downstream task after a conversion: the worker organizes
        finished outputs into ``/media/output/by_format/{family}/{ext}/`` and
        optionally ``/media/output/by_duration/{bucket}/`` so curators can
        find them without grep-ing the flat dump.
        """
        logger.info("Starting classify_output: %s", job_id)

        try:
            self.reporter.report_progress(job_id, worker_id, 25)

            src = Path(input_path)
            if not src.exists() or not src.is_file():
                error = f"classify_output: source missing: {input_path}"
                self.reporter.report_failed(job_id, worker_id, error)
                return False

            ext = src.suffix.lstrip(".")
            family = _classify_by_format(ext)

            metadata = self.ffmpeg.probe_metadata(str(src))
            duration_bucket = _classify_by_duration(
                metadata.get("duration_seconds")
                if isinstance(metadata, dict)
                else None
            )

            base_dir = Path(output_path).parent if output_path else Path("/media/output")
            move = bool(params.get("move", False))

            format_target = base_dir / "by_format" / family / (ext or "unknown")
            duration_target = base_dir / "by_duration" / duration_bucket
            format_target.mkdir(parents=True, exist_ok=True)
            duration_target.mkdir(parents=True, exist_ok=True)

            placed_paths: list[str] = []

            primary = format_target / src.name
            if move:
                shutil.move(str(src), str(primary))
                src = primary
            else:
                shutil.copy2(str(src), str(primary))
            placed_paths.append(str(primary))

            secondary = duration_target / src.name
            shutil.copy2(str(src), str(secondary))
            placed_paths.append(str(secondary))

            self.reporter.report_progress(job_id, worker_id, 90)

            manifest = {
                "format_family": family,
                "format_extension": ext,
                "duration_bucket": duration_bucket,
                "duration_seconds": metadata.get("duration_seconds")
                if isinstance(metadata, dict)
                else None,
                "placed_paths": placed_paths,
            }
            primary_path = placed_paths[0]

            if output_path:
                Path(output_path).parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, "w", encoding="utf-8") as fh:
                    json.dump(manifest, fh, indent=2)

            self.reporter.report_progress(job_id, worker_id, 100)
            self.reporter.report_completed(
                job_id, worker_id, output_path or primary_path, result_metadata=manifest
            )
            logger.info("classify_output completed: %s", job_id)
            return True

        except Exception as e:
            error = f"Unexpected error during classify_output: {e}"
            self.reporter.report_failed(job_id, worker_id, error)
            logger.error(error)
            return False

    def execute(
        self,
        job_id: str,
        job_type: str,
        worker_id: str,
        input_path: str,
        output_path: str,
        params: Dict[str, Any],
    ) -> bool:
        """Execute task by type"""
        self.reporter.report_started(job_id, worker_id)

        start_time = time.perf_counter()
        success = False

        try:
            if job_type == "convert_video":
                success = self.process_convert_video(
                    job_id, worker_id, input_path, output_path, params
                )
            elif job_type == "extract_audio":
                success = self.process_extract_audio(
                    job_id, worker_id, input_path, output_path, params
                )
            elif job_type == "thumbnail":
                success = self.process_thumbnail(
                    job_id, worker_id, input_path, output_path, params
                )
            elif job_type == "extract_metadata":
                success = self.process_extract_metadata(
                    job_id, worker_id, input_path, output_path, params
                )
            elif job_type == "classify_output":
                success = self.process_classify_output(
                    job_id, worker_id, input_path, output_path, params
                )
            else:
                error = f"Unknown job type: {job_type}"
                self.reporter.report_failed(job_id, worker_id, error)
                logger.error(error)
                success = False

            duration = time.perf_counter() - start_time
            worker_job_duration_seconds.labels(job_type=job_type).observe(duration)

            status = "success" if success else "failed"
            worker_jobs_processed_total.labels(
                job_type=job_type,
                status=status,
            ).inc()

            return success

        except Exception:
            duration = time.perf_counter() - start_time
            worker_job_duration_seconds.labels(job_type=job_type).observe(duration)
            worker_jobs_processed_total.labels(
                job_type=job_type,
                status="failed",
            ).inc()
            raise
