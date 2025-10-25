import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from config.unified_config import AppConfig, load_app_config
from logger import get_logger
from utils.formatting import normalize_datetime_string

logger = get_logger()


@dataclass
class MappingResult:
    """Результат маппинга названия."""

    youtube_title: str
    description: str
    thumbnail_path: str
    youtube_playlist_id: str | None = None
    vk_album_id: str | None = None
    matched_rule: dict[str, Any] | None = None


class TitleMapper:
    """Класс для маппинга названий записей Zoom в названия для YouTube."""

    def __init__(self, app_config: AppConfig | None = None):
        """Инициализация маппера."""
        self.logger = logger
        self.app_config = app_config or load_app_config()
        self.mapping_config = self.app_config.video_title_mapping

    def map_title(self, original_title: str, start_time: str, duration: int = 0) -> MappingResult:
        """Маппинг названия записи в название для YouTube."""
        matched_rule = self._find_matching_rule(original_title)

        if matched_rule:
            result = self._apply_rule(matched_rule, original_title, start_time, duration)
            self.logger.info(
                f"Найдено правило для '{original_title}': {matched_rule['pattern']} -> '{result.youtube_title}'"
            )
            return result
        else:
            self.logger.info(f"Правило для '{original_title}' не найдено")
            return MappingResult(
                youtube_title="",  # Пустое название означает "не найдено правило"
                description="",
                thumbnail_path="",
                youtube_playlist_id=None,
                vk_album_id=None,
                matched_rule=None,
            )

    def _find_matching_rule(self, title: str) -> dict[str, Any] | None:
        """Поиск подходящего правила для названия."""
        for rule in self.mapping_config.mapping_rules:
            pattern = rule.get("pattern", "")

            if pattern == title:
                return rule

            if pattern.startswith("^") and pattern.endswith("$"):
                try:
                    if re.match(pattern, title):
                        return rule
                except re.error:
                    continue

        return None

    def _apply_rule(
        self, rule: dict[str, Any], original_title: str, start_time: str, duration: int
    ) -> MappingResult:
        """Применение правила маппинга."""

        variables = self._prepare_variables(original_title, start_time, duration)

        youtube_title = self._format_template(
            rule.get("youtube_title_template", "{original_title} ({date})"), variables
        )

        description = f"Запись от {variables['date']}"

        thumbnail_path = rule.get("thumbnail", "thumbnails/default_thumbnail.jpg")

        youtube_playlist_id = rule.get("youtube_playlist_id", "")
        vk_album_id = rule.get("vk_album_id", "")

        return MappingResult(
            youtube_title=youtube_title,
            description=description,
            thumbnail_path=thumbnail_path,
            youtube_playlist_id=youtube_playlist_id if youtube_playlist_id else None,
            vk_album_id=vk_album_id if vk_album_id else None,
            matched_rule=rule,
        )

    def _prepare_variables(
        self, original_title: str, start_time: str, duration: int
    ) -> dict[str, str]:
        """Подготовка переменных для подстановки в шаблоны."""

        try:
            normalized_time = normalize_datetime_string(start_time)
            dt = datetime.fromisoformat(normalized_time)
            date_str = dt.strftime('%d.%m.%Y')
        except Exception as e:
            self.logger.warning(f"Ошибка парсинга даты {start_time}: {e}")
            date_str = "неизвестная дата"

        hours = duration // 60
        minutes = duration % 60
        if hours > 0:
            duration_str = f"{hours}ч {minutes}м"
        else:
            duration_str = f"{minutes}м"

        return {"date": date_str, "original_title": original_title, "duration": duration_str}

    def _format_template(self, template: str, variables: dict[str, str]) -> str:
        """Форматирование шаблона с подстановкой переменных."""
        try:
            return template.format(**variables)
        except KeyError as e:
            self.logger.warning(f"Неизвестная переменная в шаблоне: {e}")
            return template
        except Exception as e:
            self.logger.error(f"Ошибка форматирования шаблона '{template}': {e}")
            return template

    def get_available_patterns(self) -> list[str]:
        """Получение списка доступных паттернов."""
        return [rule.get("pattern", "") for rule in self.mapping_config.mapping_rules]

    def add_rule(self, pattern: str, youtube_title_template: str, thumbnail: str) -> bool:
        """Добавление нового правила маппинга."""
        try:
            new_rule = {
                "pattern": pattern,
                "youtube_title_template": youtube_title_template,
                "thumbnail": thumbnail,
            }

            self.mapping_config.mapping_rules.append(new_rule)

            self._save_config()

            self.logger.info(f"Добавлено новое правило маппинга: {pattern}")
            return True

        except Exception as e:
            self.logger.error(f"Ошибка добавления правила маппинга: {e}")
            return False

    def _save_config(self) -> bool:
        """Сохранение конфигурации в файл."""
        try:
            from config.unified_config import get_config_loader

            loader = get_config_loader()
            return loader.save_config(self.app_config)

        except Exception as e:
            self.logger.error(f"Ошибка сохранения конфигурации маппинга: {e}")
            return False

    def test_mapping(
        self, title: str, start_time: str = "2025-10-10T15:00:00Z", duration: int = 120
    ) -> MappingResult:
        """Тестирование маппинга для заданного названия."""
        return self.map_title(title, start_time, duration)


# Глобальный экземпляр маппера для использования в других модулях
_title_mapper = None


def get_title_mapper() -> TitleMapper:
    """Получение глобального экземпляра TitleMapper."""
    global _title_mapper
    if _title_mapper is None:
        _title_mapper = TitleMapper()
    return _title_mapper


def map_video_title(original_title: str, start_time: str, duration: int = 0) -> MappingResult:
    """Удобная функция для маппинга названия видео."""
    mapper = get_title_mapper()
    return mapper.map_title(original_title, start_time, duration)
