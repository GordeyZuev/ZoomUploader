"""Recording repository"""

from datetime import datetime
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
        """Get all recordings with filtering."""
        recordings = await self.db.get_recordings()

        # Filter by status
        if status is not None:
            recordings = [r for r in recordings if r.status == status]

        # Filter by failed
        if failed is not None:
            recordings = [r for r in recordings if r.failed == failed]

        return recordings

    async def find_by_id(self, id: int) -> MeetingRecording | None:
        """Get recording by ID."""
        recordings = await self.db.get_recordings_by_ids([id])
        return recordings[0] if recordings else None

    async def find_by_ids(self, ids: list[int]) -> list[MeetingRecording]:
        """Get recordings by IDs."""
        return await self.db.get_recordings_by_ids(ids)

    async def get_older_than(self, cutoff_date: datetime) -> list[MeetingRecording]:
        """Get recordings older than cutoff date."""
        return await self.db.get_records_older_than(cutoff_date)

    async def save(self, recording: MeetingRecording) -> MeetingRecording:
        """Save recording."""
        await self.db.update_recording(recording)
        return recording

    async def save_batch(self, recordings: list[MeetingRecording]) -> int:
        """Save batch of recordings."""
        return await self.db.save_recordings(recordings)

    async def update_preferences(self, recording_id: int, preferences: dict[str, Any]) -> MeetingRecording | None:
        """Update processing preferences."""
        recording = await self.find_by_id(recording_id)
        if not recording:
            return None

        recording.processing_preferences = preferences
        await self.save(recording)
        return recording
