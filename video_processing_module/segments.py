import os
from dataclasses import dataclass
from datetime import datetime

from logger import get_logger

logger = get_logger()


@dataclass
class VideoSegment:
    """Video segment"""

    start_time: float  # start time in seconds
    end_time: float  # end time in seconds
    duration: float  # duration in seconds
    title: str  # segment title
    description: str  # segment description
    output_path: str  # output file path
    processed: bool = False
    processing_time: datetime | None = None

    def __post_init__(self):
        """Validate segment."""
        if self.start_time < 0:
            raise ValueError("start_time cannot be negative")

        if self.end_time <= self.start_time:
            raise ValueError("end_time must be greater than start_time")

        if self.duration != (self.end_time - self.start_time):
            self.duration = self.end_time - self.start_time

    def format_duration(self) -> str:
        """Format duration in readable format."""
        minutes = int(self.duration // 60)
        seconds = int(self.duration % 60)
        return f"{minutes:02d}:{seconds:02d}"

    def to_dict(self) -> dict:
        """Convert to dictionary."""
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
    """Video segment processor."""

    def __init__(self, config):
        self.config = config

    def create_segments_from_duration(self, video_duration: float, title: str) -> list[VideoSegment]:
        """Create segments based on video duration."""
        segments = []
        segment_duration_sec = self.config.segment_duration * 60
        overlap_sec = self.config.overlap_duration * 60

        current_start = 0
        segment_index = 1

        while current_start < video_duration:
            current_end = min(current_start + segment_duration_sec, video_duration)
            segment_title = f"{title} - Part {segment_index}"
            segment_description = f"Segment {segment_index} of {title}"

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
        """Create segments based on timestamps."""
        segments = []

        for i, (start_time, end_time, segment_title) in enumerate(timestamps, 1):
            if not segment_title:
                segment_title = f"{title} - Part {i}"

            output_filename = f"{title}_part_{i:02d}.{self.config.output_format}"
            output_path = os.path.join(self.config.output_dir, output_filename)

            segment = VideoSegment(
                start_time=start_time,
                end_time=end_time,
                duration=end_time - start_time,
                title=segment_title,
                description=f"Segment {i} of {title}",
                output_path=output_path,
            )

            segments.append(segment)

        return segments

    def create_single_segment(self, start_time: float, end_time: float, title: str) -> VideoSegment:
        """Create a single segment."""
        output_filename = f"{title}.{self.config.output_format}"
        output_path = os.path.join(self.config.output_dir, output_filename)

        return VideoSegment(
            start_time=start_time,
            end_time=end_time,
            duration=end_time - start_time,
            title=title,
            description=f"Processed segment {title}",
            output_path=output_path,
        )
