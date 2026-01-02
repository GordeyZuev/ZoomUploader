"""Утилиты для работы с путями файлов пользователей."""

import os
from pathlib import Path


class UserPathManager:
    """Менеджер путей для изоляции файлов по пользователям."""

    def __init__(self, base_media_dir: str = "media"):
        """
        Инициализация менеджера путей.

        Args:
            base_media_dir: Базовая директория для медиа файлов
        """
        self.base_media_dir = Path(base_media_dir)

    def get_user_root(self, user_id: int) -> Path:
        """Получить корневую директорию пользователя."""
        return self.base_media_dir / f"user_{user_id}"

    def get_video_dir(self, user_id: int) -> Path:
        """Получить директорию для видео."""
        return self.get_user_root(user_id) / "video"

    def get_unprocessed_video_dir(self, user_id: int) -> Path:
        """Получить директорию для необработанных видео."""
        return self.get_video_dir(user_id) / "unprocessed"

    def get_processed_video_dir(self, user_id: int) -> Path:
        """Получить директорию для обработанных видео."""
        return self.get_video_dir(user_id) / "processed"

    def get_temp_processing_dir(self, user_id: int) -> Path:
        """Получить временную директорию для обработки."""
        return self.get_video_dir(user_id) / "temp_processing"

    def get_audio_dir(self, user_id: int) -> Path:
        """Получить директорию для аудио."""
        return self.get_user_root(user_id) / "processed_audio"

    def get_transcription_dir(self, user_id: int, recording_id: int | None = None) -> Path:
        """Получить директорию для транскрипций."""
        trans_dir = self.get_user_root(user_id) / "transcriptions"
        if recording_id:
            trans_dir = trans_dir / str(recording_id)
        return trans_dir

    def get_thumbnail_dir(self, user_id: int) -> Path:
        """Получить директорию для миниатюр."""
        return self.get_user_root(user_id) / "thumbnails"

    def ensure_user_directories(self, user_id: int) -> None:
        """Создать все необходимые директории для пользователя."""
        directories = [
            self.get_user_root(user_id),
            self.get_unprocessed_video_dir(user_id),
            self.get_processed_video_dir(user_id),
            self.get_temp_processing_dir(user_id),
            self.get_audio_dir(user_id),
            self.get_transcription_dir(user_id),
            self.get_thumbnail_dir(user_id),
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
        """Получить путь для видео файла записи."""
        if processed:
            return self.get_processed_video_dir(user_id) / f"{recording_id}_{filename}"
        return self.get_unprocessed_video_dir(user_id) / f"{recording_id}_{filename}"

    def get_recording_audio_path(
        self,
        user_id: int,
        recording_id: int,
        filename: str,
    ) -> Path:
        """Получить путь для аудио файла записи."""
        return self.get_audio_dir(user_id) / f"{recording_id}_{filename}"

    def get_relative_path(self, absolute_path: Path) -> str:
        """Получить относительный путь от базовой директории."""
        try:
            return str(absolute_path.relative_to(self.base_media_dir))
        except ValueError:
            # Если путь не относительный к base_media_dir, возвращаем как есть
            return str(absolute_path)

    def check_user_access(self, user_id: int, file_path: str | Path) -> bool:
        """
        Проверить имеет ли пользователь доступ к файлу.

        Args:
            user_id: ID пользователя
            file_path: Путь к файлу

        Returns:
            True если пользователь имеет доступ, False иначе
        """
        file_path = Path(file_path)
        user_root = self.get_user_root(user_id)

        try:
            # Проверяем что файл находится внутри директории пользователя
            file_path.resolve().relative_to(user_root.resolve())
            return True
        except ValueError:
            return False

    def get_user_storage_size(self, user_id: int) -> int:
        """
        Получить размер хранилища пользователя в байтах.

        Args:
            user_id: ID пользователя

        Returns:
            Размер в байтах
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
        Получить размер хранилища пользователя в гигабайтах.

        Args:
            user_id: ID пользователя

        Returns:
            Размер в гигабайтах
        """
        bytes_size = self.get_user_storage_size(user_id)
        return bytes_size / (1024 ** 3)


# Глобальный экземпляр менеджера
_path_manager: UserPathManager | None = None


def get_path_manager(base_media_dir: str = "media") -> UserPathManager:
    """Получить глобальный экземпляр менеджера путей."""
    global _path_manager
    if _path_manager is None:
        _path_manager = UserPathManager(base_media_dir)
    return _path_manager

