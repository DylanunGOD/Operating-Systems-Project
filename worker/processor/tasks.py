import logging
from typing import Callable, Optional, Dict, Any
from .ffmpeg_handler import FFmpegHandler
from .reporter import ProgressReporter

logger = logging.getLogger(__name__)


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

        if job_type == "convert_video":
            return self.process_convert_video(
                job_id, worker_id, input_path, output_path, params
            )
        elif job_type == "extract_audio":
            return self.process_extract_audio(
                job_id, worker_id, input_path, output_path, params
            )
        elif job_type == "thumbnail":
            return self.process_thumbnail(
                job_id, worker_id, input_path, output_path, params
            )
        else:
            error = f"Unknown job type: {job_type}"
            self.reporter.report_failed(job_id, worker_id, error)
            logger.error(error)
            return False
