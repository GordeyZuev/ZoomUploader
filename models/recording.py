from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar('T', bound=Enum)


def _normalize_enum(value: T | str, enum_class: type[T]) -> T:
    """Нормализация значения Enum: если уже Enum - возвращаем, иначе создаем из строки."""
    return value if isinstance(value, enum_class) else enum_class(value)


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
        self.source_type: SourceType = _normalize_enum(source_type_raw, SourceType)
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
                    target_type = _normalize_enum(raw["target_type"], TargetType)
                    status_raw = raw.get("status", TargetStatus.NOT_UPLOADED)
                    status = _normalize_enum(status_raw, TargetStatus)
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

        self.meeting_id: str = (
            meeting_data.get("uuid", "")
            or meeting_data.get("id", "")
            or self.source_metadata.get("meeting_uuid", "")
            or self.source_metadata.get("meeting_id", "")
        )
        self.account: str = meeting_data.get("account", "default") or self.source_metadata.get("account", "default")
        self.part_index: int | None = meeting_data.get("part_index")
        self.total_visible_parts: int | None = meeting_data.get("total_visible_parts")

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
        best_priority = -1
        best_size = -1

        for file_data in recording_files:
            file_type = file_data.get('file_type', '')
            file_size = file_data.get('file_size', 0)
            download_url = file_data.get('download_url', '')
            recording_type = file_data.get('recording_type', '')

            if file_type == 'MP4':
                priority = mp4_priorities.get(recording_type, 0)
                if priority > best_priority or (priority == best_priority and file_size > best_size):
                    best_priority = priority
                    best_size = file_size or 0
                    best_mp4_file = {
                        'file_size': file_size,
                        'download_url': download_url,
                        'recording_type': recording_type
                    }

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

    # --- Доступ к метаданным Zoom API ---

    def get_zoom_metadata(self, key: str, default: Any = None) -> Any:
        """
        Получить значение из метаданных Zoom API с fallback на zoom_api_response.

        Приоритет поиска:
        1. Прямое значение в source_metadata (если есть)
        2. Значение в zoom_api_response
        3. Значение в zoom_api_details
        4. default

        Args:
            key: Ключ для поиска (например, 'share_url', 'account_id', 'host_id')
            default: Значение по умолчанию, если ключ не найден

        Returns:
            Значение из метаданных или zoom_api_response, или default
        """
        if not self.source_metadata:
            return default

        # Сначала проверяем прямое значение в source_metadata
        if key in self.source_metadata:
            return self.source_metadata[key]

        # Затем проверяем в zoom_api_response
        zoom_response = self.source_metadata.get("zoom_api_response")
        if isinstance(zoom_response, dict) and key in zoom_response:
            return zoom_response[key]

        # И в zoom_api_details
        zoom_details = self.source_metadata.get("zoom_api_details")
        if isinstance(zoom_details, dict) and key in zoom_details:
            return zoom_details[key]

        return default

    @property
    def share_url(self) -> str | None:
        """Ссылка на просмотр записи в Zoom."""
        return self.get_zoom_metadata("share_url")

    @property
    def account_id(self) -> str | None:
        """ID аккаунта Zoom."""
        return self.get_zoom_metadata("account_id")

    @property
    def host_id(self) -> str | None:
        """ID хоста встречи."""
        return self.get_zoom_metadata("host_id")

    @property
    def timezone(self) -> str:
        """Часовой пояс встречи."""
        value = self.get_zoom_metadata("timezone")
        return value if value else "UTC"

    @property
    def total_size(self) -> int:
        """Общий размер всех файлов записи в байтах."""
        value = self.get_zoom_metadata("total_size")
        return value if value is not None else 0

    @property
    def recording_count(self) -> int:
        """Количество файлов записи."""
        value = self.get_zoom_metadata("recording_count")
        return value if value is not None else 0

    @property
    def auto_delete_date(self) -> str | None:
        """Дата автоматического удаления записи."""
        return self.get_zoom_metadata("auto_delete_date")

    @property
    def zoom_api_response(self) -> dict[str, Any] | None:
        """Полный ответ от Zoom API (get_recordings)."""
        if not self.source_metadata:
            return None
        response = self.source_metadata.get("zoom_api_response")
        return response if isinstance(response, dict) else None

    @property
    def zoom_api_details(self) -> dict[str, Any] | None:
        """Полный детальный ответ от Zoom API (get_recording_details)."""
        if not self.source_metadata:
            return None
        details = self.source_metadata.get("zoom_api_details")
        return details if isinstance(details, dict) else None

    def get_all_recording_files(self) -> list[dict[str, Any]]:
        """
        Получить все файлы записи из zoom_api_response.

        Returns:
            Список всех recording_files из полного ответа API (включая MP4, CHAT, TRANSCRIPT)
        """
        response = self.zoom_api_response
        if isinstance(response, dict):
            files = response.get("recording_files", [])
            return files if isinstance(files, list) else []
        return []

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
