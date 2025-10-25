from datetime import datetime
from enum import Enum
from typing import Any


class ProcessingStatus(Enum):
    """Статусы обработки видео записи"""

    INITIALIZED = "initialized"  # Инициализировано (загружено из Zoom API)
    DOWNLOADING = "downloading"  # В процессе загрузки
    DOWNLOADED = "downloaded"  # Загружено
    PROCESSING = "processing"  # В процессе обработки
    PROCESSED = "processed"  # Обработано
    UPLOADING = "uploading"  # В процессе выгрузки
    UPLOADED = "uploaded"  # Выгружено в API
    FAILED = "failed"  # Ошибка обработки
    SKIPPED = "skipped"  # Пропущено
    EXPIRED = "expired"  # Устарело (очищено)


class PlatformStatus(Enum):
    """Статусы загрузки на платформы"""

    NOT_UPLOADED = "not_uploaded"
    UPLOADING_YOUTUBE = "uploading_youtube"
    UPLOADED_YOUTUBE = "uploaded_youtube"
    FAILED_YOUTUBE = "failed_youtube"
    UPLOADING_VK = "uploading_vk"
    UPLOADED_VK = "uploaded_vk"
    FAILED_VK = "failed_vk"


class ProcessingMetadata:
    """Метаданные пост-обработки видео"""

    def __init__(self):
        self.processing_notes: str = ""  # Заметки обработчика
        self.processing_time: datetime | None = None  # Время обработки


class MeetingRecording:
    """
    Класс для представления записи Zoom встречи

    Содержит всю необходимую информацию о записи и методы для управления
    статусом обработки видео.
    """

    def __init__(self, meeting_data: dict[str, Any]):
        self.db_id: int | None = None
        self.topic: str = meeting_data.get('topic', '')
        self.start_time: str = meeting_data.get('start_time', '')
        self.duration: int = meeting_data.get('duration', 0)
        self.meeting_id: str = meeting_data.get('id', '')
        self.account: str = meeting_data.get('account', 'default')

        # Информация о файлах записи
        self.video_file_size: int | None = None
        self.video_file_download_url: str | None = None
        self.download_access_token: str | None = None
        self.password: str | None = None
        self.recording_play_passcode: str | None = None

        # Маппинг и статусы обработки
        self.is_mapped: bool = False
        self.status: ProcessingStatus = ProcessingStatus.INITIALIZED
        self.local_video_path: str | None = None
        self.processed_video_path: str | None = None
        self.downloaded_at: datetime | None = None

        # Статусы загрузки на платформы
        self.youtube_status: PlatformStatus = PlatformStatus.NOT_UPLOADED
        self.youtube_url: str | None = None
        self.vk_status: PlatformStatus = PlatformStatus.NOT_UPLOADED
        self.vk_url: str | None = None

        # Метаданные обработки
        self.processing_notes: str = ""
        self.processing_time: datetime | None = None

        # Обрабатываем файлы записи
        self._process_recording_files(meeting_data.get('recording_files', []))

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

    def update_status(self, new_status: ProcessingStatus, notes: str = "") -> None:
        """
        Обновление статуса записи.

        Args:
            new_status: Новый статус
            notes: Дополнительные заметки
        """
        self.status = new_status
        if notes:
            self.processing_notes = notes

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

    def update_platform_status(
        self, platform: str, status: PlatformStatus, url: str | None = None
    ) -> None:
        """
        Обновление статуса загрузки на платформу.

        Args:
            platform: Название платформы ('youtube' или 'vk')
            status: Новый статус
            url: URL загруженного видео
        """
        if platform.lower() == 'youtube':
            self.youtube_status = status
            if url:
                self.youtube_url = url
        elif platform.lower() == 'vk':
            self.vk_status = status
            if url:
                self.vk_url = url

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
            'youtube_uploaded': self.youtube_status == PlatformStatus.UPLOADED_YOUTUBE,
            'vk_uploaded': self.vk_status == PlatformStatus.UPLOADED_VK,
        }

        # Добавляем пути к файлам, если они есть
        if self.local_video_path:
            progress['local_file'] = self.local_video_path
        if self.processed_video_path:
            progress['processed_file'] = self.processed_video_path

        # Добавляем URL, если они есть
        if self.youtube_url:
            progress['youtube_url'] = self.youtube_url
        if self.vk_url:
            progress['vk_url'] = self.vk_url

        return progress

    def reset_to_initial_state(self) -> None:
        """Сброс записи к начальному состоянию"""
        self.local_video_path = None
        self.processed_video_path = None
        self.downloaded_at = None
        self.youtube_status = PlatformStatus.NOT_UPLOADED
        self.youtube_url = None
        self.vk_status = PlatformStatus.NOT_UPLOADED
        self.vk_url = None
        self.processing_notes = ""
        self.processing_time = None

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
