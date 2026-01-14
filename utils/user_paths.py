"""User file path utilities"""

import os
from pathlib import Path


class UserPathManager:
    """Path manager for per-user file isolation"""

    def __init__(self, base_media_dir: str = "media"):
        """
        Initialize the path manager.
        """
        self.base_media_dir = Path(base_media_dir)

    def get_user_root(self, user_id: int) -> Path:
        """Get the root directory for the user."""
        return self.base_media_dir / f"user_{user_id}"

    def get_video_dir(self, user_id: int) -> Path:
        """Get the directory for video."""
        return self.get_user_root(user_id) / "video"

    def get_unprocessed_video_dir(self, user_id: int) -> Path:
        """Get the directory for unprocessed video."""
        return self.get_video_dir(user_id) / "unprocessed"

    def get_processed_video_dir(self, user_id: int) -> Path:
        """Get the directory for processed video."""
        return self.get_video_dir(user_id) / "processed"

    def get_temp_processing_dir(self, user_id: int) -> Path:
        """Get the temporary directory for processing."""
        return self.get_video_dir(user_id) / "temp_processing"

    def get_audio_dir(self, user_id: int) -> Path:
        """Get the directory for audio."""
        return self.get_user_root(user_id) / "processed_audio"

    def get_transcription_dir(self, user_id: int, recording_id: int | None = None) -> Path:
        """Get the directory for transcriptions."""
        trans_dir = self.get_user_root(user_id) / "transcriptions"
        if recording_id:
            trans_dir = trans_dir / str(recording_id)
        return trans_dir

    def ensure_user_directories(self, user_id: int) -> None:
        """Create all necessary directories for the user."""
        directories = [
            self.get_user_root(user_id),
            self.get_unprocessed_video_dir(user_id),
            self.get_processed_video_dir(user_id),
            self.get_temp_processing_dir(user_id),
            self.get_audio_dir(user_id),
            self.get_transcription_dir(user_id),
        ]

        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

    def get_recording_video_path(
        self,
        user_id: int,
        recording_id: int,
        filename: str,
        processed: bool = False,
    ) -> Path:
        """Get the path for the video file of the recording."""
        if processed:
            return self.get_processed_video_dir(user_id) / f"{recording_id}_{filename}"
        return self.get_unprocessed_video_dir(user_id) / f"{recording_id}_{filename}"

    def get_recording_audio_path(
        self,
        user_id: int,
        recording_id: int,
        filename: str,
    ) -> Path:
        """Get the path for the audio file of the recording."""
        return self.get_audio_dir(user_id) / f"{recording_id}_{filename}"

    def get_relative_path(self, absolute_path: Path) -> str:
        """Get the relative path from the base directory."""
        try:
            return str(absolute_path.relative_to(self.base_media_dir))
        except ValueError:
            # If the path is not relative to base_media_dir, return as is
            return str(absolute_path)

    def check_user_access(self, user_id: int, file_path: str | Path) -> bool:
        """
        Check if the user has access to the file.
        """
        file_path = Path(file_path)
        user_root = self.get_user_root(user_id)

        try:
            # Check if the file is inside the user's directory
            file_path.resolve().relative_to(user_root.resolve())
            return True
        except ValueError:
            return False

    def get_user_storage_size(self, user_id: int) -> int:
        """
        Get the size of the user's storage in bytes.
        """
        user_root = self.get_user_root(user_id)

        if not user_root.exists():
            return 0

        total_size = 0
        for dirpath, _dirnames, filenames in os.walk(user_root):
            for filename in filenames:
                file_path = Path(dirpath) / filename
                try:
                    total_size += file_path.stat().st_size
                except (OSError, FileNotFoundError):
                    continue

        return total_size

    def get_user_storage_size_gb(self, user_id: int) -> float:
        """
        Get the size of the user's storage in gigabytes.
        """
        bytes_size = self.get_user_storage_size(user_id)
        return bytes_size / (1024 ** 3)


# Global instance of the path manager
_path_manager: UserPathManager | None = None


def get_path_manager(base_media_dir: str = "media") -> UserPathManager:
    """Get the global instance of the path manager."""
    global _path_manager
    if _path_manager is None:
        _path_manager = UserPathManager(base_media_dir)
    return _path_manager
