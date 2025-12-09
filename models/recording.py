from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any


class ProcessingStatus(Enum):
    """Статусы обработки видео записи"""

    INITIALIZED = "initialized"  # Инициализировано (загружено из Zoom API)
    DOWNLOADING = "downloading"  # В процессе загрузки
    DOWNLOADED = "downloaded"  # Загружено
    PROCESSING = "processing"  # В процессе обработки
    PROCESSED = "processed"  # Обработано
    TRANSCRIBING = "transcribing"  # В процессе транскрибации
    TRANSCRIBED = "transcribed"  # Транскрибировано
    UPLOADING = "uploading"  # В процессе выгрузки
    UPLOADED = "uploaded"  # Выгружено в API
    FAILED = "failed"  # Ошибка обработки
    SKIPPED = "skipped"  # Пропущено
    EXPIRED = "expired"  # Устарело (очищено)


class SourceType(Enum):
    """Тип источника видео."""

    ZOOM = "zoom"
    LOCAL_FILE = "local_file"
    YOUTUBE = "youtube"
    VK = "vk"
    HTTP_LINK = "http_link"
    YANDEX_DISK_API = "yandex_disk_api"


class TargetType(Enum):
    """Тип вывода/публикации."""

    YOUTUBE = "youtube"
    VK = "vk"
    YANDEX_DISK = "yandex_disk"
    LOCAL = "local"
    WEBHOOK = "webhook"
    GDRIVE = "gdrive"


class TargetStatus(Enum):
    """Статусы загрузки на выходные площадки."""

    NOT_UPLOADED = "not_uploaded"
    UPLOADING = "uploading"
    UPLOADED = "uploaded"
    FAILED = "failed"


class OutputTarget:
    """Отдельный таргет вывода (YouTube, VK, диск и т.д.)."""

    def __init__(
        self,
        target_type: TargetType,
        status: TargetStatus = TargetStatus.NOT_UPLOADED,
        target_meta: dict[str, Any] | None = None,
        uploaded_at: datetime | None = None,
    ):
        self.target_type = target_type
        self.status = status
        self.target_meta: dict[str, Any] = target_meta or {}
        self.uploaded_at = uploaded_at

    def get_link(self) -> str | None:
        return self.target_meta.get("target_link") or self.target_meta.get("video_url")

    def mark_uploaded(self, link: str | None = None, meta: dict[str, Any] | None = None):
        if link:
            self.target_meta["target_link"] = link
        if meta:
            self.target_meta.update(meta)
        self.status = TargetStatus.UPLOADED
        self.uploaded_at = datetime.utcnow()


class MeetingRecording:
    """
    Класс для представления записи Zoom встречи

    Содержит всю необходимую информацию о записи и методы для управления
    статусом обработки видео.
    """

    def __init__(self, meeting_data: dict[str, Any]):
        self.db_id: int | None = None
        self.display_name: str = meeting_data.get("display_name") or meeting_data.get("topic", "")
        self.start_time: str = meeting_data.get("start_time", "")
        self.duration: int = meeting_data.get("duration", 0)
        self.status: ProcessingStatus = meeting_data.get("status", ProcessingStatus.INITIALIZED)
        self.is_mapped: bool = bool(meeting_data.get("is_mapped", False))
        self.expire_at: datetime | None = meeting_data.get("expire_at")

        # Источник
        source_type_raw = meeting_data.get("source_type") or SourceType.ZOOM.value
        self.source_type: SourceType = (
            source_type_raw if isinstance(source_type_raw, SourceType) else SourceType(source_type_raw)
        )
        self.source_key: str = meeting_data.get("source_key") or str(meeting_data.get("id", ""))
        self.source_metadata: dict[str, Any] = meeting_data.get("source_metadata", {}) or {}

        # Файлы/пути (относительно media_dir)
        self.local_video_path: str | None = meeting_data.get("local_video_path")
        self.processed_video_path: str | None = meeting_data.get("processed_video_path")
        self.processed_audio_dir: str | None = meeting_data.get("processed_audio_dir")
        self.transcription_dir: str | None = meeting_data.get("transcription_dir")
        self.downloaded_at: datetime | None = meeting_data.get("downloaded_at")

        # Доп. инфо по файлам и скачиванию (для источников типа Zoom)
        self.video_file_size: int | None = meeting_data.get("video_file_size")
        self.video_file_download_url: str | None = meeting_data.get("video_file_download_url")
        self.download_access_token: str | None = meeting_data.get("download_access_token")
        self.password: str | None = meeting_data.get("password")
        self.recording_play_passcode: str | None = meeting_data.get("recording_play_passcode")

        # Сырые данные транскрибации и темы
        self.transcription_info: Any | None = meeting_data.get("transcription_info")
        self.topic_timestamps: list[dict[str, Any]] | None = meeting_data.get("topic_timestamps")
        self.main_topics: list[str] | None = meeting_data.get("main_topics")

        # Выходы
        raw_targets = meeting_data.get("output_targets", []) or []
        self.output_targets: list[OutputTarget] = []
        for raw in raw_targets:
            if isinstance(raw, OutputTarget):
                self.output_targets.append(raw)
            elif isinstance(raw, dict) and "target_type" in raw:
                try:
                    target_type = (
                        raw["target_type"]
                        if isinstance(raw["target_type"], TargetType)
                        else TargetType(raw["target_type"])
                    )
                    status_raw = raw.get("status", TargetStatus.NOT_UPLOADED)
                    status = status_raw if isinstance(status_raw, TargetStatus) else TargetStatus(status_raw)
                    self.output_targets.append(
                        OutputTarget(
                            target_type=target_type,
                            status=status,
                            target_meta=raw.get("target_meta"),
                            uploaded_at=raw.get("uploaded_at"),
                        )
                    )
                except Exception:
                    continue

        # Вспомогательные атрибуты для обратной совместимости с Zoom
        self.meeting_id: str = meeting_data.get("id", "") or self.source_metadata.get("meeting_id", "")
        self.account: str = meeting_data.get("account", "default") or self.source_metadata.get("account", "default")

        # Обрабатываем файлы записи (для Zoom API входных данных)
        self._process_recording_files(meeting_data.get("recording_files", []))

    def _process_recording_files(self, recording_files: list[dict[str, Any]]) -> None:
        """
        Обработка файлов записи из API ответа Zoom.

        Args:
            recording_files: Список файлов записи из API
        """
        # Приоритеты для выбора MP4 файла (чем выше приоритет, тем лучше)
        mp4_priorities = {
            'shared_screen_with_speaker_view': 3,  # Лучший вариант - экран + спикер
            'shared_screen': 2,                    # Хороший вариант - только экран
            'active_speaker': 1,                   # Базовый вариант - только спикер
        }

        best_mp4_file = None
        best_priority = 0

        for file_data in recording_files:
            file_type = file_data.get('file_type', '')
            file_size = file_data.get('file_size', 0)
            download_url = file_data.get('download_url', '')
            recording_type = file_data.get('recording_type', '')

            if file_type == 'MP4':
                # Определяем приоритет этого MP4 файла
                priority = mp4_priorities.get(recording_type, 0)

                # Если это лучший файл, сохраняем его
                if priority > best_priority:
                    best_priority = priority
                    best_mp4_file = {
                        'file_size': file_size,
                        'download_url': download_url,
                        'recording_type': recording_type
                    }
            elif file_type == 'CHAT':
                # Файл чата (пока не обрабатываем)
                pass
            elif file_type == 'TRANSCRIPT':
                # Транскрипт (пока не обрабатываем)
                pass

        # Сохраняем лучший MP4 файл
        if best_mp4_file:
            self.video_file_size = best_mp4_file['file_size']
            self.video_file_download_url = best_mp4_file['download_url']

    def update_status(self, new_status: ProcessingStatus) -> None:
        """
        Обновление статуса записи.

        Args:
            new_status: Новый статус
        """
        self.status = new_status

    def has_video(self) -> bool:
        """Проверка наличия видео файла"""
        return self.video_file_download_url is not None

    def has_chat(self) -> bool:
        """Проверка наличия чата"""
        return False  # Пока не реализовано

    def is_processed(self) -> bool:
        """Проверка, обработана ли запись"""
        return self.status in [ProcessingStatus.PROCESSED, ProcessingStatus.UPLOADED]

    def is_failed(self) -> bool:
        """Проверка, завершилась ли обработка с ошибкой"""
        return self.status == ProcessingStatus.FAILED

    def is_long_enough(self, min_duration_minutes: int = 30) -> bool:
        """Проверка, достаточно ли длинная запись"""
        return self.duration >= min_duration_minutes

    def is_downloaded(self) -> bool:
        """Проверка, скачана ли запись"""
        return self.status in [
            ProcessingStatus.DOWNLOADED,
            ProcessingStatus.PROCESSED,
            ProcessingStatus.UPLOADED,
        ]

    def is_ready_for_processing(self) -> bool:
        """Проверка, готова ли запись для обработки"""
        return self.status == ProcessingStatus.DOWNLOADED and self.local_video_path is not None

    def is_ready_for_upload(self) -> bool:
        """Проверка, готова ли запись для загрузки"""
        return self.status == ProcessingStatus.PROCESSED and self.processed_video_path is not None

    # --- Работа с таргетами ---
    def get_target(self, target_type: TargetType) -> OutputTarget | None:
        for target in self.output_targets:
            if target.target_type == target_type:
                return target
        return None

    def ensure_target(self, target_type: TargetType) -> OutputTarget:
        existing = self.get_target(target_type)
        if existing:
            return existing
        new_target = OutputTarget(target_type=target_type)
        self.output_targets.append(new_target)
        return new_target

    def set_primary_audio(self, audio_path: str) -> None:
        """Сохранить основной аудиофайл и зафиксировать директорию."""
        if audio_path:
            self.processed_audio_dir = str(Path(audio_path).parent)
            info = self.transcription_info or {}
            if not isinstance(info, dict):
                info = {}
            info["primary_audio"] = audio_path
            self.transcription_info = info

    def get_primary_audio_path(self) -> str | None:
        """Получить основной аудиофайл из сохранённой директории или transcription_info."""
        # Приоритет: явный путь в transcription_info
        if isinstance(self.transcription_info, dict):
            path = self.transcription_info.get("primary_audio")
            if path and Path(path).exists():
                return path

        if self.processed_audio_dir:
            audio_dir = Path(self.processed_audio_dir)
            if audio_dir.exists():
                for ext in ("*.mp3", "*.wav", "*.m4a"):
                    files = sorted(audio_dir.glob(ext))
                    if files:
                        return str(files[0])
        return None

    def targets_summary(self) -> dict[str, Any]:
        summary = {}
        for target in self.output_targets:
            summary[target.target_type.value] = {
                "status": target.status.value,
                "link": target.get_link(),
            }
        return summary

    def get_processing_progress(self) -> dict[str, Any]:
        """
        Получение информации о прогрессе обработки.

        Returns:
            Словарь с информацией о прогрессе
        """
        progress = {
            'status': self.status.value,
            'downloaded': self.is_downloaded(),
            'processed': self.is_processed(),
        }

        # Добавляем пути к файлам, если они есть
        if self.local_video_path:
            progress['local_file'] = self.local_video_path
        if self.processed_video_path:
            progress['processed_file'] = self.processed_video_path
        if self.processed_audio_dir:
            progress['processed_audio_dir'] = self.processed_audio_dir
        if self.transcription_dir:
            progress['transcription_dir'] = self.transcription_dir

        # Добавляем информацию о транскрипции
        if self.topic_timestamps:
            progress['topics_count'] = len(self.topic_timestamps)
        if self.main_topics:
            progress['main_topics'] = self.main_topics

        # Добавляем информацию о таргетах
        if self.output_targets:
            progress['outputs'] = self.targets_summary()

        return progress

    def reset_to_initial_state(self) -> None:
        """Сброс записи к начальному состоянию"""
        self.local_video_path = None
        self.processed_video_path = None
        self.processed_audio_dir = None
        self.downloaded_at = None
        self.transcription_dir = None
        self.topic_timestamps = None
        self.main_topics = None

    @staticmethod
    def format_duration(minutes: int) -> str:
        """
        Форматирование длительности в читаемый вид.

        Args:
            minutes: Длительность в минутах

        Returns:
            Отформатированная строка
        """
        if minutes < 60:
            return f"{minutes} мин"
        else:
            hours = minutes // 60
            remaining_minutes = minutes % 60
            if remaining_minutes == 0:
                return f"{hours} ч"
            else:
                return f"{hours} ч {remaining_minutes} мин"
