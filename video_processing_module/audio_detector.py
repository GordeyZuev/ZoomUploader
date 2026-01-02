import asyncio
import json

from logger import get_logger

logger = get_logger()


class AudioDetector:
    """Детектор звука для определения границ контента."""

    def __init__(self, silence_threshold: float = -30.0, min_silence_duration: float = 2.0):
        self.silence_threshold = silence_threshold
        self.min_silence_duration = min_silence_duration

    async def detect_audio_boundaries(self, video_path: str) -> tuple[float | None, float | None]:
        """Определение границ звука в видео."""
        try:
            logger.info(f"🔍 Анализ звука в видео: {video_path}")

            # Сначала проверяем, что файл существует и не поврежден
            if not await self._validate_video_file(video_path):
                logger.error(f"Файл видео поврежден или недоступен: {video_path}")
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

            stdout, stderr = await process.communicate()

            if process.returncode != 0:
                error_msg = stderr.decode()
                logger.error(f"Ошибка детекции звука: {error_msg}")

                # Проверяем специфичные ошибки FFmpeg
                if "Invalid data found when processing input" in error_msg:
                    logger.error("Файл поврежден или не является корректным видео")
                elif "moov atom not found" in error_msg:
                    logger.error("Файл не содержит необходимые метаданные видео")
                elif "No such file or directory" in error_msg:
                    logger.error("Файл не найден")

                return None, None

            silence_periods = self._parse_silence_detection(stderr.decode())

            if not silence_periods:
                logger.info("Звук обнаружен на протяжении всего видео")
                return 0.0, None  # Весь файл содержит звук

            first_sound = self._find_first_sound(silence_periods)
            last_sound = await self._find_last_sound(silence_periods, video_path)

            logger.info(f"🎵 Границы звука: {first_sound:.1f}s - {last_sound:.1f}s")
            return first_sound, last_sound

        except Exception as e:
            logger.error(f"Ошибка детекции звука: {e}")
            return None, None

    def _parse_silence_detection(self, ffmpeg_output: str) -> list[tuple[float, float]]:
        """Парсинг вывода ffmpeg для извлечения периодов тишины."""
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
        """Нахождение времени первого звука."""
        if not silence_periods:
            return 0.0

        first_silence_start = silence_periods[0][0]
        if first_silence_start > 0.1:
            return 0.0
        return silence_periods[0][1]

    async def _find_last_sound(self, silence_periods: list[tuple[float, float]], video_path: str) -> float | None:
        """Нахождение времени последнего звука."""
        if not silence_periods:
            return None  # Весь файл содержит звук

        duration = await self._get_video_duration(video_path)
        if duration is None:
            return None

        last_silence_end = silence_periods[-1][1]
        if last_silence_end < duration - 0.1:
            return duration
        return silence_periods[-1][0]

    async def _get_video_duration(self, video_path: str) -> float | None:
        """Получение длительности видео."""
        try:
            cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", video_path]

            process = await asyncio.create_subprocess_exec(
                *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )

            stdout, stderr = await process.communicate()

            if process.returncode == 0:
                data = json.loads(stdout.decode())
                return float(data["format"]["duration"])

        except Exception as e:
            logger.error(f"Ошибка получения длительности видео: {e}")

        return None

    async def _validate_video_file(self, video_path: str) -> bool:
        """
        Валидация видео файла перед обработкой.

        Args:
            video_path: Путь к видео файлу

        Returns:
            True если файл валиден, False иначе
        """
        try:
            import os
            from pathlib import Path

            # Проверяем существование файла
            if not os.path.exists(video_path):
                logger.error(f"Файл не существует: {video_path}")
                return False

            # Проверяем размер файла
            file_size = os.path.getsize(video_path)
            if file_size < 1024:  # Меньше 1 КБ
                logger.error(f"Файл слишком мал: {file_size} байт")
                return False

            # Проверяем, не является ли файл HTML
            with open(video_path, "rb") as f:
                first_chunk = f.read(1024)
                if b"<html" in first_chunk.lower() or b"<!doctype html" in first_chunk.lower():
                    logger.error("Файл является HTML страницей, а не видео")
                    return False

                # Для MP4 проверяем заголовок
                if Path(video_path).suffix.lower() == ".mp4":
                    if not (
                        first_chunk.startswith(b"\x00\x00\x00") or b"ftyp" in first_chunk or b"moov" in first_chunk
                    ):
                        logger.error("Файл не является корректным MP4 видео")
                        return False

            return True

        except Exception as e:
            logger.error(f"Ошибка при валидации видео файла {video_path}: {e}")
            return False
