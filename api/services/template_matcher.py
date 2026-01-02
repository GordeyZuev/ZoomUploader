"""Сервис для сопоставления записей с шаблонами."""

import fnmatch
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from api.repositories.template_repos import RecordingTemplateRepository
from database.template_models import RecordingTemplateModel
from models import MeetingRecording


class TemplateMatcher:
    """Сервис для автоматического сопоставления записей с шаблонами."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = RecordingTemplateRepository(session)

    async def find_matching_template(
        self,
        recording: MeetingRecording,
        user_id: int,
    ) -> RecordingTemplateModel | None:
        """Найти подходящий шаблон для записи."""
        templates = await self.repo.find_active_by_user(user_id)

        for template in templates:
            if self._matches_template(recording, template):
                return template

        return None

    def _matches_template(
        self,
        recording: MeetingRecording,
        template: RecordingTemplateModel,
    ) -> bool:
        """Проверить, подходит ли запись под шаблон."""
        if not template.matching_rules:
            return False

        rules = template.matching_rules

        if "name_pattern" in rules:
            pattern = rules["name_pattern"]
            if not fnmatch.fnmatch(recording.display_name, pattern):
                return False

        if "source_type" in rules:
            expected_type = rules["source_type"]
            if recording.source and recording.source.source_type != expected_type:
                return False

        if "source_id" in rules:
            pass

        return True

    async def apply_template(
        self,
        recording: MeetingRecording,
        template: RecordingTemplateModel,
    ) -> MeetingRecording:
        """Применить шаблон к записи."""
        if template.processing_config:
            recording.processing_preferences = self._merge_configs(
                recording.processing_preferences or {},
                template.processing_config,
            )

        if template.metadata_config:
            metadata = self._apply_metadata_template(recording, template.metadata_config)
            if recording.processing_preferences is None:
                recording.processing_preferences = {}
            recording.processing_preferences["metadata"] = metadata

        if template.output_config:
            if recording.processing_preferences is None:
                recording.processing_preferences = {}
            recording.processing_preferences["output_config"] = template.output_config

        await self.repo.increment_usage(template)

        return recording

    def _merge_configs(self, base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
        """Глубокое слияние конфигураций (приоритет у override)."""
        result = base.copy()

        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_configs(result[key], value)
            else:
                result[key] = value

        return result

    def _apply_metadata_template(
        self,
        recording: MeetingRecording,
        metadata_config: dict[str, Any],
    ) -> dict[str, Any]:
        """Применить шаблон метаданных с заменой переменных."""
        result = {}
        variables = self._prepare_variables(recording)

        for key, value in metadata_config.items():
            if isinstance(value, str):
                result[key] = self._replace_variables(value, variables)
            elif isinstance(value, list):
                result[key] = [
                    self._replace_variables(item, variables) if isinstance(item, str) else item
                    for item in value
                ]
            else:
                result[key] = value

        return result

    def _prepare_variables(self, recording: MeetingRecording) -> dict[str, str]:
        """Подготовить переменные для подстановки."""
        variables = {
            "original_title": recording.display_name,
            "date": recording.start_time.strftime("%d.%m.%Y"),
            "duration": self._format_duration(recording.duration),
        }

        if recording.main_topics:
            topics_list = recording.main_topics
            if isinstance(topics_list, list) and topics_list:
                variables["topic"] = topics_list[0]
                variables["topics_list"] = self._format_topics_list(topics_list)
            else:
                variables["topic"] = ""
                variables["topics_list"] = ""
        else:
            variables["topic"] = ""
            variables["topics_list"] = ""

        if recording.source:
            variables["source_name"] = recording.source.source_type
        else:
            variables["source_name"] = "Unknown"

        return variables

    def _replace_variables(self, template: str, variables: dict[str, str]) -> str:
        """Заменить переменные в шаблоне."""
        result = template
        for var_name, var_value in variables.items():
            result = result.replace(f"{{{var_name}}}", var_value)
        return result

    def _format_duration(self, minutes: int) -> str:
        """Форматировать длительность."""
        hours = minutes // 60
        mins = minutes % 60
        if hours > 0:
            return f"{hours}ч {mins}м"
        return f"{mins}м"

    def _format_topics_list(self, topics: list[str]) -> str:
        """Форматировать список топиков."""
        if not topics:
            return ""
        return "\n".join(f"- {topic}" for topic in topics)

