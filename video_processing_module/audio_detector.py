import asyncio
import json

from logger import get_logger

logger = get_logger()


class AudioDetector:
    """Audio detector for content boundary detection"""

    def __init__(self, silence_threshold: float = -30.0, min_silence_duration: float = 2.0):
        self.silence_threshold = silence_threshold
        self.min_silence_duration = min_silence_duration

    async def detect_audio_boundaries(self, video_path: str) -> tuple[float | None, float | None]:
        """Determine audio boundaries in video."""
        try:
            logger.info(f"🔍 Analyzing audio in video: {video_path}")

            if not await self._validate_video_file(video_path):
                logger.error(f"Video file corrupted or inaccessible: {video_path}")
                return None, None

            cmd = [
                "ffmpeg",
                "-i",
                video_path,
                "-af",
                f"silencedetect=noise={self.silence_threshold}dB:d={self.min_silence_duration}",
                "-f",
                "null",
                "-",
            ]

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            _stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode()
                logger.error(f"Error detecting audio: {error_msg}")

                # Check specific FFmpeg errors
                if "Invalid data found when processing input" in error_msg:
                    logger.error("File corrupted or not a valid video")
                elif "moov atom not found" in error_msg:
                    logger.error("File does not contain necessary video metadata")
                elif "No such file or directory" in error_msg:
                    logger.error("File not found")

                return None, None

            silence_periods = self._parse_silence_detection(stderr.decode())

            if not silence_periods:
                logger.info("Sound detected throughout the video")
                return 0.0, None  # Entire file contains sound

            first_sound = self._find_first_sound(silence_periods)
            last_sound = await self._find_last_sound(silence_periods, video_path)

            logger.info(f"🎵 Audio boundaries: {first_sound:.1f}s - {last_sound:.1f}s")
            return first_sound, last_sound

        except Exception as e:
            logger.error(f"Error detecting audio: {e}")
            return None, None

    def _parse_silence_detection(self, ffmpeg_output: str) -> list[tuple[float, float]]:
        """Parsing ffmpeg output to extract silence periods."""
        silence_periods = []
        lines = ffmpeg_output.split("\n")

        for line in lines:
            if "silence_start" in line:
                try:
                    start_time = float(line.split("silence_start: ")[1].split()[0])
                except (IndexError, ValueError):
                    continue
            elif "silence_end" in line:
                try:
                    end_time = float(line.split("silence_end: ")[1].split()[0])
                    silence_periods.append((start_time, end_time))
                except (IndexError, ValueError, NameError):
                    continue

        return silence_periods

    def _find_first_sound(self, silence_periods: list[tuple[float, float]]) -> float:
        """Finding the time of the first sound."""
        if not silence_periods:
            return 0.0

        first_silence_start = silence_periods[0][0]
        if first_silence_start > 0.1:
            return 0.0
        return silence_periods[0][1]

    async def _find_last_sound(self, silence_periods: list[tuple[float, float]], video_path: str) -> float | None:
        """Finding the time of the last sound."""
        if not silence_periods:
            return None  # Entire file contains sound

        duration = await self._get_video_duration(video_path)
        if duration is None:
            return None

        last_silence_end = silence_periods[-1][1]
        if last_silence_end < duration - 0.1:
            return duration
        return silence_periods[-1][0]

    async def _get_video_duration(self, video_path: str) -> float | None:
        """Getting video duration."""
        try:
            cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", video_path]

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, _stderr = await process.communicate()

            if process.returncode == 0:
                data = json.loads(stdout.decode())
                return float(data["format"]["duration"])

        except Exception as e:
            logger.error(f"Error getting video duration: {e}")

        return None

    async def _validate_video_file(self, video_path: str) -> bool:
        """
        Validate video file before processing.
        """
        try:
            import os

            # Check if file exists
            if not os.path.exists(video_path):
                logger.error(f"File does not exist: {video_path}")
                return False

            # Check file size
            file_size = os.path.getsize(video_path)
            if file_size < 1024:  # Less than 1 KB
                logger.error(f"File too small: {file_size} bytes")
                return False

            # Check if file is HTML
            with open(video_path, "rb") as f:
                first_chunk = f.read(1024)
                if b"<html" in first_chunk.lower() or b"<!doctype html" in first_chunk.lower():
                    logger.error("File is an HTML page, not a video")
                    return False

            cmd = ["ffprobe", "-v", "error", "-show_entries", "format=format_name", "-of", "json", video_path]

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                logger.error(f"ffprobe could not process file: {stderr.decode()}")
                return False

            # Check if ffprobe recognized the format
            try:
                data = json.loads(stdout.decode())
                if "format" not in data or "format_name" not in data["format"]:
                    logger.error("File not recognized as video")
                    return False
                logger.info(f"Video format: {data['format']['format_name']}")
            except json.JSONDecodeError:
                logger.error("Could not parse ffprobe output")
                return False

            return True

        except Exception as e:
            logger.error(f"Error validating video file {video_path}: {e}")
            return False
