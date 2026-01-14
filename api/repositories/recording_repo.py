"""Recording repository"""

from typing import Any

from database.manager import DatabaseManager
from models import MeetingRecording, ProcessingStatus


class RecordingRepository:
    """Recording repository"""

    def __init__(self, db: DatabaseManager):
        self.db = db

    async def find_all(
        self,
        status: ProcessingStatus | None = None,
        failed: bool | None = None,
    ) -> list[MeetingRecording]:
        """Получение всех записей с фильтрацией."""
        recordings = await self.db.get_recordings()

        # Фильтрация по статусу
        if status is not None:
            recordings = [r for r in recordings if r.status == status]

        # Фильтрация по failed
        if failed is not None:
            recordings = [r for r in recordings if r.failed == failed]

        return recordings

    async def find_by_id(self, id: int) -> MeetingRecording | None:
        """Получение записи по ID."""
        recordings = await self.db.get_recordings_by_ids([id])
        return recordings[0] if recordings else None

    async def save(self, recording: MeetingRecording) -> MeetingRecording:
        """Сохранение записи."""
        await self.db.update_recording(recording)
        return recording

    async def update_preferences(self, recording_id: int, preferences: dict[str, Any]) -> MeetingRecording | None:
        """Обновление настроек обработки."""
        recording = await self.find_by_id(recording_id)
        if not recording:
            return None

        recording.processing_preferences = preferences
        await self.save(recording)
        return recording
