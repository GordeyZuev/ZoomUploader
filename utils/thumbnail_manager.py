"""User thumbnails manager"""

import shutil
from pathlib import Path

from logger import get_logger

logger = get_logger()


class ThumbnailManager:
    """Thumbnail manager (global templates + user-specific)"""

    def __init__(self, base_media_dir: str = "media"):
        """
        Инициализация менеджера thumbnails.

        Args:
            base_media_dir: Базовая директория для медиа файлов
        """
        self.base_media_dir = Path(base_media_dir)
        self.templates_dir = self.base_media_dir / "templates" / "thumbnails"

    def get_user_thumbnails_dir(self, user_id: int) -> Path:
        """Получить директорию thumbnails пользователя."""
        return self.base_media_dir / f"user_{user_id}" / "thumbnails"

    def get_global_templates_dir(self) -> Path:
        """Получить директорию глобальных template thumbnails."""
        return self.templates_dir

    def ensure_user_thumbnails_dir(self, user_id: int) -> None:
        """Создать директорию thumbnails для пользователя."""
        user_thumbs_dir = self.get_user_thumbnails_dir(user_id)
        user_thumbs_dir.mkdir(parents=True, exist_ok=True)

    def initialize_user_thumbnails(self, user_id: int, copy_templates: bool = True) -> None:
        """
        Инициализировать thumbnails для нового пользователя.

        Args:
            user_id: ID пользователя
            copy_templates: Копировать ли глобальные templates в папку пользователя
        """
        user_thumbs_dir = self.get_user_thumbnails_dir(user_id)

        # Создать директорию
        self.ensure_user_thumbnails_dir(user_id)

        # Копировать templates если нужно
        if copy_templates and self.templates_dir.exists():
            copied_count = 0
            for template_file in self.templates_dir.glob("*.png"):
                target_file = user_thumbs_dir / template_file.name

                if not target_file.exists():
                    try:
                        shutil.copy2(template_file, target_file)
                        copied_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to copy template {template_file.name}: {e}")

            logger.info(f"Initialized thumbnails for user {user_id}: {copied_count} templates copied")
        else:
            logger.info(f"Created empty thumbnails directory for user {user_id}")

    def get_thumbnail_path(
        self,
        user_id: int,
        thumbnail_name: str,
        fallback_to_template: bool = True,
    ) -> Path | None:
        """
        Получить путь к thumbnail (сначала проверяется у пользователя, потом в templates).

        Args:
            user_id: ID пользователя
            thumbnail_name: Имя файла thumbnail (например, "ml_extra.png")
            fallback_to_template: Искать ли в глобальных templates если не найдено у пользователя

        Returns:
            Path к thumbnail или None если не найден
        """
        # Нормализовать имя файла (убрать префиксы путей если есть)
        thumbnail_name = Path(thumbnail_name).name

        # 1. Проверить у пользователя
        user_thumbnail = self.get_user_thumbnails_dir(user_id) / thumbnail_name
        if user_thumbnail.exists():
            logger.debug(f"Found user thumbnail: {user_thumbnail}")
            return user_thumbnail

        # 2. Fallback на глобальные templates
        if fallback_to_template:
            template_thumbnail = self.templates_dir / thumbnail_name
            if template_thumbnail.exists():
                logger.debug(f"Using template thumbnail: {template_thumbnail}")
                return template_thumbnail

        logger.warning(f"Thumbnail not found: {thumbnail_name} for user {user_id}")
        return None

    def list_user_thumbnails(self, user_id: int) -> list[Path]:
        """
        Получить список всех thumbnails пользователя.

        Args:
            user_id: ID пользователя

        Returns:
            Список путей к thumbnails
        """
        user_thumbs_dir = self.get_user_thumbnails_dir(user_id)

        if not user_thumbs_dir.exists():
            return []

        return sorted(user_thumbs_dir.glob("*.png"))

    def list_template_thumbnails(self) -> list[Path]:
        """
        Получить список всех глобальных template thumbnails.

        Returns:
            Список путей к templates
        """
        if not self.templates_dir.exists():
            return []

        return sorted(self.templates_dir.glob("*.png"))

    def upload_user_thumbnail(
        self,
        user_id: int,
        source_path: Path | str,
        thumbnail_name: str | None = None,
    ) -> Path:
        """
        Загрузить пользовательский thumbnail.

        Args:
            user_id: ID пользователя
            source_path: Путь к исходному файлу
            thumbnail_name: Имя для сохранения (если None - использовать оригинальное)

        Returns:
            Path к сохраненному thumbnail

        Raises:
            FileNotFoundError: Если исходный файл не найден
            ValueError: Если формат не поддерживается
        """
        source_path = Path(source_path)

        if not source_path.exists():
            raise FileNotFoundError(f"Source thumbnail not found: {source_path}")

        # Проверить формат
        if source_path.suffix.lower() not in [".png", ".jpg", ".jpeg"]:
            raise ValueError(f"Unsupported thumbnail format: {source_path.suffix}")

        # Определить имя файла
        if thumbnail_name is None:
            thumbnail_name = source_path.name

        # Убедиться что директория существует
        self.ensure_user_thumbnails_dir(user_id)

        # Сохранить файл
        target_path = self.get_user_thumbnails_dir(user_id) / thumbnail_name
        shutil.copy2(source_path, target_path)

        logger.info(f"Uploaded thumbnail for user {user_id}: {thumbnail_name}")
        return target_path

    def delete_user_thumbnail(self, user_id: int, thumbnail_name: str) -> bool:
        """
        Удалить пользовательский thumbnail.

        Args:
            user_id: ID пользователя
            thumbnail_name: Имя файла thumbnail

        Returns:
            True если удален успешно, False если не найден
        """
        thumbnail_name = Path(thumbnail_name).name
        thumbnail_path = self.get_user_thumbnails_dir(user_id) / thumbnail_name

        if not thumbnail_path.exists():
            logger.warning(f"Thumbnail not found for deletion: {thumbnail_path}")
            return False

        try:
            thumbnail_path.unlink()
            logger.info(f"Deleted thumbnail for user {user_id}: {thumbnail_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete thumbnail {thumbnail_path}: {e}")
            return False

    def get_thumbnail_info(self, thumbnail_path: Path) -> dict:
        """
        Получить информацию о thumbnail (размер и дата изменения).

        Args:
            thumbnail_path: Путь к thumbnail

        Returns:
            Словарь с информацией (size_bytes, size_kb, modified_at)
        """
        if not thumbnail_path.exists():
            return {
                "size_bytes": 0,
                "size_kb": 0.0,
                "modified_at": 0.0,
            }

        stat = thumbnail_path.stat()

        return {
            "size_bytes": stat.st_size,
            "size_kb": round(stat.st_size / 1024, 2),
            "modified_at": stat.st_mtime,
        }


# Глобальный экземпляр
_thumbnail_manager: ThumbnailManager | None = None


def get_thumbnail_manager(base_media_dir: str = "media") -> ThumbnailManager:
    """Получить глобальный экземпляр менеджера thumbnails."""
    global _thumbnail_manager
    if _thumbnail_manager is None:
        _thumbnail_manager = ThumbnailManager(base_media_dir)
    return _thumbnail_manager

