import os
from dataclasses import dataclass
from datetime import datetime

from logger import get_logger

logger = get_logger()


@dataclass
class VideoSegment:
    """Сегмент видео."""

    start_time: float  # время начала в секундах
    end_time: float  # время окончания в секундах
    duration: float  # длительность в секундах
    title: str  # название сегмента
    description: str  # описание сегмента
    output_path: str  # путь к выходному файлу
    processed: bool = False
    processing_time: datetime | None = None

    def __post_init__(self):
        """Валидация сегмента."""
        if self.start_time < 0:
            raise ValueError("start_time не может быть отрицательным")

        if self.end_time <= self.start_time:
            raise ValueError("end_time должен быть больше start_time")

        if self.duration != (self.end_time - self.start_time):
            self.duration = self.end_time - self.start_time

    def format_duration(self) -> str:
        """Форматирование длительности в читаемый вид."""
        minutes = int(self.duration // 60)
        seconds = int(self.duration % 60)
        return f"{minutes:02d}:{seconds:02d}"

    def to_dict(self) -> dict:
        """Преобразование в словарь."""
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "title": self.title,
            "description": self.description,
            "output_path": self.output_path,
            "processed": self.processed,
            "processing_time": self.processing_time.isoformat() if self.processing_time else None,
        }


class SegmentProcessor:
    """Процессор для создания сегментов видео."""

    def __init__(self, config):
        self.config = config

    def create_segments_from_duration(self, video_duration: float, title: str) -> list[VideoSegment]:
        """Создание сегментов на основе длительности видео."""
        segments = []
        segment_duration_sec = self.config.segment_duration * 60
        overlap_sec = self.config.overlap_duration * 60

        current_start = 0
        segment_index = 1

        while current_start < video_duration:
            current_end = min(current_start + segment_duration_sec, video_duration)
            segment_title = f"{title} - Часть {segment_index}"
            segment_description = f"Сегмент {segment_index} из {title}"

            output_filename = f"{title}_part_{segment_index:02d}.{self.config.output_format}"
            output_path = os.path.join(self.config.output_dir, output_filename)

            segment = VideoSegment(
                start_time=current_start,
                end_time=current_end,
                duration=current_end - current_start,
                title=segment_title,
                description=segment_description,
                output_path=output_path,
            )

            segments.append(segment)

            current_start = current_end - overlap_sec
            segment_index += 1
            if current_start >= video_duration:
                break

        return segments

    def create_segments_from_timestamps(self, timestamps: list[tuple], title: str) -> list[VideoSegment]:
        """Создание сегментов на основе временных меток."""
        segments = []

        for i, (start_time, end_time, segment_title) in enumerate(timestamps, 1):
            if not segment_title:
                segment_title = f"{title} - Часть {i}"

            output_filename = f"{title}_part_{i:02d}.{self.config.output_format}"
            output_path = os.path.join(self.config.output_dir, output_filename)

            segment = VideoSegment(
                start_time=start_time,
                end_time=end_time,
                duration=end_time - start_time,
                title=segment_title,
                description=f"Сегмент {i} из {title}",
                output_path=output_path,
            )

            segments.append(segment)

        return segments

    def create_single_segment(self, start_time: float, end_time: float, title: str) -> VideoSegment:
        """Создание одного сегмента."""
        output_filename = f"{title}.{self.config.output_format}"
        output_path = os.path.join(self.config.output_dir, output_filename)

        return VideoSegment(
            start_time=start_time,
            end_time=end_time,
            duration=end_time - start_time,
            title=title,
            description=f"Обработанный сегмент {title}",
            output_path=output_path,
        )
