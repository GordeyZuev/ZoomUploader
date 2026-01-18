import asyncio
import json
import os
import shutil
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from logger import get_logger
from utils.formatting import normalize_datetime_string, sanitize_filename

from .audio_detector import AudioDetector
from .config import ProcessingConfig
from .segments import SegmentProcessor, VideoSegment

logger = get_logger()


class VideoProcessor:
    """Video processor for trimming and post-processing"""

    def __init__(self, config: ProcessingConfig):
        self.config = config
        self.segment_processor = SegmentProcessor(config)
        self.audio_detector = AudioDetector(
            silence_threshold=config.silence_threshold,
            min_silence_duration=config.min_silence_duration,
        )
        self._ensure_directories()

    def _ensure_directories(self):
        """Create necessary directories."""
        for directory in [self.config.input_dir, self.config.output_dir, self.config.temp_dir]:
            Path(directory).mkdir(parents=True, exist_ok=True)


    async def get_video_info(self, video_path: str) -> dict[str, Any]:
        """Get video information."""
        cmd = [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            video_path,
        ]

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                raise RuntimeError(f"FFprobe error: {stderr.decode()}")

            info = json.loads(stdout.decode())
            video_stream = next((s for s in info["streams"] if s["codec_type"] == "video"), None)
            audio_stream = next((s for s in info["streams"] if s["codec_type"] == "audio"), None)

            return {
                "duration": float(info["format"]["duration"]),
                "size": int(info["format"]["size"]),
                "width": int(video_stream["width"]) if video_stream else 0,
                "height": int(video_stream["height"]) if video_stream else 0,
                "fps": eval(video_stream["r_frame_rate"]) if video_stream else 0,
                "video_codec": video_stream["codec_name"] if video_stream else None,
                "audio_codec": audio_stream["codec_name"] if audio_stream else None,
                "bitrate": int(info["format"]["bit_rate"]) if "bit_rate" in info["format"] else 0,
            }

        except Exception as e:
            raise RuntimeError(f"Error getting video information: {e}") from e

    async def trim_video(self, input_path: str, output_path: str, start_time: float, end_time: float) -> bool:
        """Trim video by time."""
        duration = end_time - start_time

        # Ensure paths are strings
        input_path = str(input_path)
        output_path = str(output_path)

        cmd = [
            "ffmpeg",
            "-i",
            input_path,
            "-ss",
            str(start_time),
            "-t",
            str(duration),
            "-c:v",
            self.config.video_codec,
            "-c:a",
            self.config.audio_codec,
        ]

        if self.config.video_bitrate != "original":
            cmd.extend(["-b:v", self.config.video_bitrate])
        if self.config.audio_bitrate != "original":
            cmd.extend(["-b:a", self.config.audio_bitrate])
        if self.config.video_codec != "copy" and self.config.fps > 0:
            cmd.extend(["-r", str(self.config.fps)])
        if self.config.resolution != "original":
            cmd.extend(["-s", self.config.resolution])

        cmd.extend(["-y", output_path])

        try:
            logger.info(f"🔧 Команда FFmpeg: {' '.join(cmd)}")

            logger.info("🔧 Starting FFmpeg for video processing...")

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            # Wait for the process to complete
            await process.wait()

            if process.returncode != 0:
                logger.error(f"❌ FFmpeg finished with code {process.returncode}")
                stderr_output = await process.stderr.read()
                logger.error(f"❌ FFmpeg error: {stderr_output.decode()}")
                return False

            if Path(output_path).exists():
                file_size = Path(output_path).stat().st_size
                logger.info(f"✅ File created: {output_path} ({file_size} bytes)")
                return True
            logger.error(f"❌ File not created: {output_path}")
            return False

        except Exception as e:
            logger.error(f"❌ Exception during video trimming: {e}")
            logger.error(f"❌ Traceback: {traceback.format_exc()}")
            return False

    async def process_segment(self, segment: VideoSegment, input_path: str) -> bool:
        """Process a single segment."""
        try:
            start_time = segment.start_time
            end_time = segment.end_time

            if self.config.remove_intro and start_time == 0:
                start_time = self.config.intro_duration

            if self.config.remove_outro:
                video_info = await self.get_video_info(input_path)
                max_time = video_info["duration"]
                end_time = min(max_time - self.config.outro_duration, end_time)

            os.makedirs(Path(segment.output_path).parent, exist_ok=True)
            success = await self.trim_video(input_path, segment.output_path, start_time, end_time)

            if success:
                segment.processed = True
                segment.processing_time = datetime.now()
                return True
            return False

        except Exception as e:
            logger.info(f"Error processing segment {segment.title}: {e}")
            return False

    async def process_video(
        self, video_path: str, title: str, custom_segments: list[tuple] | None = None
    ) -> list[VideoSegment]:
        """Main video processing function."""
        try:
            video_info = await self.get_video_info(video_path)
            duration = video_info["duration"]

            logger.info(f"📹 Processing video: {title}")
            logger.info(f"   Duration: {duration / 60:.1f} minutes")
            logger.info(f"   Size: {video_info['size'] / 1024 / 1024:.1f} MB")
            logger.info(f"   Resolution: {video_info['width']}x{video_info['height']}")

            if custom_segments:
                segments = self.segment_processor.create_segments_from_timestamps(custom_segments, title)
            else:
                segments = self.segment_processor.create_segments_from_duration(duration, title)

            logger.info(f"   Created segments: {len(segments)}")

            processed_segments = []
            for i, segment in enumerate(segments, 1):
                logger.info(f"   Обработка сегмента {i}/{len(segments)}: {segment.title}")

                success = await self.process_segment(segment, video_path)
                if success:
                    processed_segments.append(segment)
                    logger.info(f"   ✅ Segment processed: {segment.output_path}")
                else:
                    logger.info(f"   ❌ Error processing segment: {segment.title}")

            logger.info(f"✅ Processing completed: {len(processed_segments)}/{len(segments)} segments")
            return processed_segments

        except Exception as e:
            logger.info(f"❌ Ошибка обработки видео {title}: {e}")
            return []

    async def process_video_with_audio_detection(
        self, video_path: str, title: str, start_time: str | None = None
    ) -> tuple[bool, str | None]:
        """Обработка видео с автоматической обрезкой по звуку.

        Args:
            video_path: Путь к исходному видео файлу
            title: Название видео
            start_time: Дата начала записи в формате Zoom API (например, "2025-11-25T18:00:15Z")
                       Используется для создания уникального имени файла
        """
        try:
            logger.info(f"🎬 Обработка видео с детекцией звука: {title}")

            if not Path(video_path).exists():
                logger.error(f"❌ Файл не найден: {video_path}")
                return False, None

            logger.info(f"🔍 Детекция звука для: {title}")
            first_sound, last_sound = await self.audio_detector.detect_audio_boundaries(video_path)

            if first_sound is None and last_sound is None:
                logger.warning(f"⚠️ Не удалось определить границы звука для {title}")
                return False, None

            if first_sound is None:
                logger.warning(f"⚠️ Не удалось определить начало звука для {title}")
                return False, None

            # Если звук есть на всем протяжении видео, не обрезаем и используем исходный файл
            if last_sound is None and first_sound == 0.0:
                logger.info("🔊 Звук на всем протяжении видео, пропускаем обрезку и используем исходный файл")
                return True, os.path.abspath(video_path)

            if last_sound is None:
                logger.warning(f"⚠️ Не удалось определить конечную границу звука для {title}")
                return False, None

            logger.info(f"🎵 Найденные границы звука: {first_sound:.1f}s - {last_sound:.1f}s")

            start_time_trim = max(0, first_sound - self.config.padding_before)
            end_time = last_sound + self.config.padding_after

            logger.info(
                f"✂️ Обрезка с {start_time_trim:.1f}s по {end_time:.1f}s (отступы: -{self.config.padding_before}s, +{self.config.padding_after}s)"
            )

            safe_title = sanitize_filename(title)

            # Добавляем дату и время в имя файла для уникальности
            date_suffix = ""
            if start_time:
                try:
                    normalized_time = normalize_datetime_string(start_time)
                    date_obj = datetime.fromisoformat(normalized_time)
                    date_suffix = f"_{date_obj.strftime('%y-%m-%d_%H-%M')}"
                except Exception as e:
                    logger.warning(f"⚠️ Error parsing date '{start_time}' for filename: {e}")

            output_filename = f"{safe_title}{date_suffix}_processed.mp4"
            output_path = Path(self.config.output_dir) / output_filename

            os.makedirs(Path(output_path).parent, exist_ok=True)
            logger.info("🎬 Запуск FFmpeg для обрезки...")
            success = await self.trim_video(video_path, output_path, start_time_trim, end_time)

            if success:
                logger.info(f"✅ Video processed: {output_path}")
                return True, str(output_path)
            logger.error(f"❌ Error trimming video: {title}")
            return False, None

        except Exception as e:
            logger.error(f"❌ Exception during video processing {title}: {e}")
            logger.error(f"❌ Traceback: {traceback.format_exc()}")
            return False, None

    async def batch_process(self, video_files: list[str]) -> dict[str, list[VideoSegment]]:
        """Batch processing multiple videos."""
        results = {}

        for video_path in video_files:
            if not Path(video_path).exists():
                logger.info(f"❌ File not found: {video_path}")
                continue

            title = Path(video_path).stem

            segments = await self.process_video(video_path, title)
            results[video_path] = segments

        return results

    def cleanup_temp_files(self):
        """Cleaning up temporary files."""
        if not self.config.keep_temp_files:
            temp_dir = Path(self.config.temp_dir)
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
                logger.info(f"🧹 Temporary files cleaned up: {temp_dir}")

    def get_processing_statistics(self, results: dict[str, list[VideoSegment]]) -> dict[str, Any]:
        """Getting processing statistics."""
        total_videos = len(results)
        total_segments = sum(len(segments) for segments in results.values())
        processed_segments = sum(len([s for s in segments if s.processed]) for segments in results.values())

        total_duration = 0
        for segments in results.values():
            for segment in segments:
                if segment.processed:
                    total_duration += segment.duration

        return {
            "total_videos": total_videos,
            "total_segments": total_segments,
            "processed_segments": processed_segments,
            "success_rate": (processed_segments / total_segments * 100) if total_segments > 0 else 0,
            "total_processed_duration": total_duration,
            "total_processed_duration_formatted": f"{total_duration / 60:.1f} minutes",
        }
