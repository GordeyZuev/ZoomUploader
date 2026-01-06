from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T", bound=Enum)


def _normalize_enum(value: T | str, enum_class: type[T]) -> T:
    """Нормализация значения Enum: если уже Enum - возвращаем, иначе создаем из строки."""
    return value if isinstance(value, enum_class) else enum_class(value)


class ProcessingStatus(Enum):
    """Статусы обработки видео записи (агрегированный статус из processing_stages/outputs)"""

    INITIALIZED = "INITIALIZED"  # Инициализировано (загружено из Zoom API)
    DOWNLOADING = "DOWNLOADING"  # В процессе загрузки (runtime)
    DOWNLOADED = "DOWNLOADED"  # Загружено
    PROCESSING = "PROCESSING"  # В процессе обработки (runtime)
    PROCESSED = "PROCESSED"  # Обработано
    PREPARING = "PREPARING"  # Подготовка (транскрипция, топики, субтитры) - runtime
    TRANSCRIBING = "TRANSCRIBING"  # В процессе транскрибации (runtime, legacy)
    TRANSCRIBED = "TRANSCRIBED"  # Транскрибировано (все stages completed)
    UPLOADING = "UPLOADING"  # В процессе выгрузки (runtime)
    UPLOADED = "UPLOADED"  # Выгружено в API (legacy)
    READY = "READY"  # Готово (все этапы завершены, включая загрузку)
    SKIPPED = "SKIPPED"  # Пропущено
    EXPIRED = "EXPIRED"  # Устарело (очищено)
    # FAILED удален - используется recording.failed (boolean) + failed_reason


class SourceType(Enum):
    """Тип источника видео."""

    ZOOM = "ZOOM"
    LOCAL_FILE = "LOCAL_FILE"
    GOOGLE_DRIVE = "GOOGLE_DRIVE"
    YOUTUBE = "YOUTUBE"
    OTHER = "OTHER"


class TargetType(Enum):
    """Тип вывода/публикации."""

    YOUTUBE = "YOUTUBE"
    VK = "VK"
    LOCAL_STORAGE = "LOCAL_STORAGE"
    GOOGLE_DRIVE = "GOOGLE_DRIVE"
    OTHER = "OTHER"


class TargetStatus(Enum):
    """Статусы загрузки на выходные площадки."""

    NOT_UPLOADED = "NOT_UPLOADED"
    UPLOADING = "UPLOADING"
    UPLOADED = "UPLOADED"
    FAILED = "FAILED"


class ProcessingStageType(Enum):
    """Типы этапов ТРАНСКРИПЦИОННОГО пайплайна (детализация для ProcessingStatus.TRANSCRIBING/TRANSCRIBED)."""

    TRANSCRIBE = "TRANSCRIBE"  # Транскрибация аудио
    EXTRACT_TOPICS = "EXTRACT_TOPICS"  # Извлечение тем
    GENERATE_SUBTITLES = "GENERATE_SUBTITLES"  # Генерация субтитров
    # TRANSLATION = "TRANSLATION"  # Перевод


class ProcessingStageStatus(Enum):
    """Статусы отдельного этапа обработки."""

    PENDING = "PENDING"  # Ожидает выполнения
    IN_PROGRESS = "IN_PROGRESS"  # В процессе
    COMPLETED = "COMPLETED"  # Завершено успешно
    FAILED = "FAILED"  # Ошибка
    # Будущие значения (нужно добавить в БД через миграцию):
    # SKIPPED = "SKIPPED"  # Пропущено


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


class ProcessingStage:
    """Отдельный этап обработки записи (FSM модель)."""

    def __init__(
        self,
        stage_type: ProcessingStageType,
        status: ProcessingStageStatus = ProcessingStageStatus.PENDING,
        failed: bool = False,
        failed_at: datetime | None = None,
        failed_reason: str | None = None,
        retry_count: int = 0,
        stage_meta: dict[str, Any] | None = None,
        completed_at: datetime | None = None,
    ):
        self.stage_type = stage_type
        self.status = status
        self.failed = failed
        self.failed_at = failed_at
        self.failed_reason = failed_reason
        self.retry_count = retry_count
        self.stage_meta: dict[str, Any] = stage_meta or {}
        self.completed_at = completed_at

    def mark_completed(self, meta: dict[str, Any] | None = None):
        """Пометить этап как завершенный (FSM: переход в COMPLETED)."""
        self.status = ProcessingStageStatus.COMPLETED
        self.failed = False
        self.completed_at = datetime.utcnow()
        if meta:
            self.stage_meta.update(meta)

    def mark_in_progress(self):
        """Пометить этап как выполняющийся (FSM: переход в IN_PROGRESS)."""
        self.status = ProcessingStageStatus.IN_PROGRESS
        # Сбрасываем failed при новом запуске
        if self.failed:
            self.failed = False

    def mark_failed(self, reason: str):
        """Пометить этап как провалившийся (FSM: переход в FAILED)."""
        self.status = ProcessingStageStatus.FAILED
        self.failed = True
        self.failed_at = datetime.utcnow()
        self.failed_reason = reason
        self.retry_count += 1

    def mark_skipped(self):
        """Пометить этап как пропущенный (FSM: переход в SKIPPED)."""
        # TODO: Добавить SKIPPED в БД через миграцию
        # self.status = ProcessingStageStatus.SKIPPED
        # Пока используем PENDING
        self.status = ProcessingStageStatus.PENDING

    def can_retry(self, max_retries: int = 2) -> bool:
        """Проверить возможность retry этапа (FSM: проверка переходов)."""
        return self.failed and self.status == ProcessingStageStatus.FAILED and self.retry_count < max_retries

    def prepare_retry(self):
        """Подготовить этап к retry (FSM: переход из FAILED в IN_PROGRESS)."""
        if not self.can_retry():
            raise ValueError(f"Cannot retry stage {self.stage_type.value}: retry limit exceeded")
        self.status = ProcessingStageStatus.IN_PROGRESS
        # failed_at и failed_reason оставляем для истории


class MeetingRecording:
    """
    Класс для представления записи Zoom встречи

    Содержит всю необходимую информацию о записи и методы для управления
    статусом обработки видео.
    """

    def __init__(self, meeting_data: dict[str, Any]):
        self.db_id: int | None = None
        self.user_id: int | None = meeting_data.get("user_id")
        self.display_name: str = meeting_data.get("display_name") or meeting_data.get("topic", "")
        self.start_time: str = meeting_data.get("start_time", "")
        self.duration: int = meeting_data.get("duration", 0)
        self.status: ProcessingStatus = meeting_data.get("status", ProcessingStatus.INITIALIZED)
        self.is_mapped: bool = bool(meeting_data.get("is_mapped", False))
        self.expire_at: datetime | None = meeting_data.get("expire_at")

        self.failed: bool = bool(meeting_data.get("failed", False))
        self.failed_at: datetime | None = meeting_data.get("failed_at")
        self.failed_reason: str | None = meeting_data.get("failed_reason")
        self.failed_at_stage: str | None = meeting_data.get("failed_at_stage")
        self.retry_count: int = int(meeting_data.get("retry_count", 0))

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

        # Настройки обработки
        self.processing_preferences: dict[str, Any] | None = meeting_data.get("processing_preferences")

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

        raw_stages = meeting_data.get("processing_stages", []) or []
        self.processing_stages: list[ProcessingStage] = []
        for raw in raw_stages:
            if isinstance(raw, ProcessingStage):
                self.processing_stages.append(raw)
            elif isinstance(raw, dict) and "stage_type" in raw:
                try:
                    stage_type = _normalize_enum(raw["stage_type"], ProcessingStageType)
                    status_raw = raw.get("status", ProcessingStageStatus.PENDING)
                    status = _normalize_enum(status_raw, ProcessingStageStatus)
                    self.processing_stages.append(
                        ProcessingStage(
                            stage_type=stage_type,
                            status=status,
                            failed=bool(raw.get("failed", False)),
                            failed_at=raw.get("failed_at"),
                            failed_reason=raw.get("failed_reason"),
                            retry_count=int(raw.get("retry_count", 0)),
                            stage_meta=raw.get("stage_meta"),
                            completed_at=raw.get("completed_at"),
                        )
                    )
                except Exception:
                    continue

        self._process_recording_files(meeting_data.get("recording_files", []))

    def _process_recording_files(self, recording_files: list[dict[str, Any]]) -> None:
        """
        Обработка файлов записи из API ответа Zoom.

        Args:
            recording_files: Список файлов записи из API
        """
        # Приоритеты для выбора MP4 файла (чем выше приоритет, тем лучше)
        mp4_priorities = {
            "shared_screen_with_speaker_view": 3,  # Лучший вариант - экран + спикер
            "shared_screen": 2,  # Хороший вариант - только экран
            "active_speaker": 1,  # Базовый вариант - только спикер
        }

        best_mp4_file = None
        best_priority = -1
        best_size = -1

        for file_data in recording_files:
            file_type = file_data.get("file_type", "")
            file_size = file_data.get("file_size", 0)
            download_url = file_data.get("download_url", "")
            recording_type = file_data.get("recording_type", "")
            download_access_token = file_data.get("download_access_token")

            if file_type == "MP4":
                priority = mp4_priorities.get(recording_type, 0)
                if priority > best_priority or (priority == best_priority and file_size > best_size):
                    best_priority = priority
                    best_size = file_size or 0
                    best_mp4_file = {
                        "file_size": file_size,
                        "download_url": download_url,
                        "recording_type": recording_type,
                        "download_access_token": download_access_token,
                    }

        if best_mp4_file:
            self.video_file_size = best_mp4_file["file_size"]
            self.video_file_download_url = best_mp4_file["download_url"]
            if best_mp4_file.get("download_access_token"):
                self.download_access_token = best_mp4_file["download_access_token"]

    def update_status(
        self,
        new_status: ProcessingStatus,
        failed: bool = False,
        failed_reason: str | None = None,
        failed_at_stage: str | None = None,
    ) -> None:
        """
        Обновление статуса записи с поддержкой FSM полей (ADR-015).

        Args:
            new_status: Новый статус
            failed: Флаг ошибки (если True, статус откатывается)
            failed_reason: Причина ошибки
            failed_at_stage: Этап, на котором произошла ошибка
        """
        self.status = new_status
        if failed:
            self.failed = True
            self.failed_at = datetime.utcnow()
            if failed_reason:
                self.failed_reason = failed_reason
            if failed_at_stage:
                self.failed_at_stage = failed_at_stage
        else:
            # Сбрасываем failed при успешном переходе
            self.failed = False

    def mark_failure(
        self,
        reason: str,
        rollback_to_status: ProcessingStatus | None = None,
        failed_at_stage: str | None = None,
    ) -> None:
        """
        Пометить запись как провалившуюся с откатом статуса (ADR-015).

        Args:
            reason: Причина ошибки
            rollback_to_status: Статус для отката (если None, определяется автоматически)
            failed_at_stage: Этап, на котором произошла ошибка
        """
        # Определяем статус для отката
        if rollback_to_status is None:
            # Автоматическое определение предыдущего статуса
            if self.status == ProcessingStatus.DOWNLOADING:
                rollback_to_status = ProcessingStatus.INITIALIZED
            elif self.status == ProcessingStatus.PROCESSING:
                rollback_to_status = ProcessingStatus.DOWNLOADED
            elif self.status == ProcessingStatus.UPLOADING:
                # Откат к TRANSCRIBED если есть, иначе PROCESSED
                transcription_stage = self.get_stage(ProcessingStageType.TRANSCRIBE)
                if transcription_stage and transcription_stage.status == ProcessingStageStatus.COMPLETED:
                    rollback_to_status = ProcessingStatus.TRANSCRIBED
                else:
                    rollback_to_status = ProcessingStatus.PROCESSED
            else:
                # Если статус не в процессе, оставляем как есть
                rollback_to_status = self.status

        # Откат статуса и установка FSM полей
        self.status = rollback_to_status
        self.failed = True
        self.failed_at = datetime.utcnow()
        self.failed_reason = reason
        if failed_at_stage:
            self.failed_at_stage = failed_at_stage

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
        """
        Проверка, завершилась ли обработка с ошибкой (FSM: проверка failed флага).

        Согласно ADR-015, ошибки обрабатываются через флаг failed=true,
        а не через статус FAILED. При ошибке статус откатывается к предыдущему этапу.
        """
        return self.failed

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
        """
        Проверка, готова ли запись для загрузки.

        Запись готова если:
        - Статус PROCESSED или TRANSCRIBED
        - Есть обработанное видео
        """
        return (
            self.status in [ProcessingStatus.PROCESSED, ProcessingStatus.TRANSCRIBED]
            and self.processed_video_path is not None
        )

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

    # --- Работа с этапами обработки (FSM) ---
    def get_stage(self, stage_type: ProcessingStageType) -> ProcessingStage | None:
        """Получить этап обработки по типу."""
        for stage in self.processing_stages:
            if stage.stage_type == stage_type:
                return stage
        return None

    def ensure_stage(self, stage_type: ProcessingStageType) -> ProcessingStage:
        """Создать или получить этап обработки."""
        existing = self.get_stage(stage_type)
        if existing:
            return existing
        new_stage = ProcessingStage(stage_type=stage_type)
        self.processing_stages.append(new_stage)
        return new_stage

    def mark_stage_completed(self, stage_type: ProcessingStageType, meta: dict[str, Any] | None = None) -> None:
        """Пометить этап как завершенный (FSM: успешный переход)."""
        stage = self.ensure_stage(stage_type)
        stage.mark_completed(meta=meta)
        # Обновляем агрегированный статус
        self._update_aggregate_status()

    def mark_stage_in_progress(self, stage_type: ProcessingStageType) -> None:
        """Пометить этап как выполняющийся (FSM: переход в IN_PROGRESS)."""
        stage = self.ensure_stage(stage_type)
        stage.mark_in_progress()
        self._update_aggregate_status()

    def mark_stage_failed(
        self,
        stage_type: ProcessingStageType,
        reason: str,
        rollback_to_status: ProcessingStatus | None = None,
    ) -> None:
        """
        Пометить этап как провалившийся (FSM: переход в FAILED с откатом).

        Args:
            stage_type: Тип этапа
            reason: Причина ошибки
            rollback_to_status: Статус для отката (если None, определяется автоматически)
        """
        stage = self.ensure_stage(stage_type)
        stage.mark_failed(reason)

        # Откат агрегированного статуса (ADR-015)
        if rollback_to_status is None:
            rollback_to_status = self._get_previous_status_for_stage(stage_type)
        if rollback_to_status:
            self.status = rollback_to_status

        # Устанавливаем FSM поля
        self.failed = True
        self.failed_at = datetime.utcnow()
        self.failed_reason = reason
        self.failed_at_stage = stage_type.value

    def mark_stage_skipped(self, stage_type: ProcessingStageType) -> None:
        """Пометить этап как пропущенный (FSM: переход в SKIPPED)."""
        stage = self.ensure_stage(stage_type)
        stage.mark_skipped()
        self._update_aggregate_status()

    def can_retry_stage(self, stage_type: ProcessingStageType, max_retries: int = 2) -> bool:
        """Проверить возможность retry этапа."""
        stage = self.get_stage(stage_type)
        if not stage:
            return False
        return stage.can_retry(max_retries=max_retries)

    def prepare_stage_retry(self, stage_type: ProcessingStageType) -> None:
        """Подготовить этап к retry (FSM: переход из FAILED в IN_PROGRESS)."""
        stage = self.get_stage(stage_type)
        if not stage:
            raise ValueError(f"Stage {stage_type.value} not found")
        stage.prepare_retry()
        # Сбрасываем общий флаг failed при retry
        if self.failed_at_stage == stage_type.value:
            self.failed = False
        self._update_aggregate_status()

    def _get_previous_status_for_stage(self, stage_type: ProcessingStageType) -> ProcessingStatus | None:
        """
        Получить предыдущий статус для отката при ошибке этапа (FSM логика).

        Args:
            stage_type: Тип этапа, на котором произошла ошибка

        Returns:
            Предыдущий статус для отката
        """
        # Маппинг этапов на предыдущие статусы
        stage_to_previous_status = {
            ProcessingStageType.TRANSCRIBE: ProcessingStatus.PROCESSED,
            ProcessingStageType.EXTRACT_TOPICS: ProcessingStatus.PROCESSED,  # Может быть TRANSCRIBED если транскрибация есть
            ProcessingStageType.GENERATE_SUBTITLES: ProcessingStatus.PROCESSED,  # Аналогично
        }

        previous = stage_to_previous_status.get(stage_type)
        if previous:
            return previous

        # Если транскрибация завершена, то топики/субтитры откатываются к TRANSCRIBED
        transcription_stage = self.get_stage(ProcessingStageType.TRANSCRIBE)
        if (
            transcription_stage
            and transcription_stage.status == ProcessingStageStatus.COMPLETED
            and stage_type in [ProcessingStageType.EXTRACT_TOPICS, ProcessingStageType.GENERATE_SUBTITLES]
        ):
            return ProcessingStatus.TRANSCRIBED

        return ProcessingStatus.PROCESSED

    def _update_aggregate_status(self) -> None:
        """
        Обновить агрегированный ProcessingStatus на основе этапов (FSM вычисление).

        Логика:
        - Если есть этапы в процессе -> соответствующий статус
        - Если все этапы завершены -> TRANSCRIBED
        - Учитывает зависимости между этапами
        """
        # Основные этапы (не зависят от этапов обработки)
        if self.status in [
            ProcessingStatus.INITIALIZED,
            ProcessingStatus.DOWNLOADING,
            ProcessingStatus.DOWNLOADED,
            ProcessingStatus.PROCESSING,
        ]:
            # Эти статусы не зависят от этапов, оставляем как есть
            return

        # Проверяем этапы после PROCESSED
        transcription_stage = self.get_stage(ProcessingStageType.TRANSCRIBE)
        topic_stage = self.get_stage(ProcessingStageType.EXTRACT_TOPICS)
        subtitle_stage = self.get_stage(ProcessingStageType.GENERATE_SUBTITLES)

        # Если статус PROCESSED, но есть завершенная транскрибация - обновляем статус
        if self.status == ProcessingStatus.PROCESSED:
            if transcription_stage and transcription_stage.status == ProcessingStageStatus.COMPLETED:
                # Транскрибация завершена, обновляем статус
                self.status = ProcessingStatus.TRANSCRIBED
                return
            # Если транскрибация в процессе, обновляем статус
            if transcription_stage and transcription_stage.status == ProcessingStageStatus.IN_PROGRESS:
                self.status = ProcessingStatus.TRANSCRIBING
                return
            # Если нет этапов транскрибации, оставляем PROCESSED
            return

        # Если есть хотя бы один этап
        if transcription_stage or topic_stage or subtitle_stage:
            # Если транскрибация в процессе
            if transcription_stage and transcription_stage.status == ProcessingStageStatus.IN_PROGRESS:
                self.status = ProcessingStatus.TRANSCRIBING
                return

            # Если транскрибация завершена
            if transcription_stage and transcription_stage.status == ProcessingStageStatus.COMPLETED:
                # Проверяем другие этапы
                topic_in_progress = topic_stage and topic_stage.status == ProcessingStageStatus.IN_PROGRESS
                subtitle_in_progress = subtitle_stage and subtitle_stage.status == ProcessingStageStatus.IN_PROGRESS

                if topic_in_progress or subtitle_in_progress:
                    # Есть этапы в процессе, но транскрибация завершена
                    self.status = ProcessingStatus.TRANSCRIBED
                    return

                # Все этапы завершены
                topic_done = not topic_stage or topic_stage.status == ProcessingStageStatus.COMPLETED
                subtitle_done = not subtitle_stage or subtitle_stage.status == ProcessingStageStatus.COMPLETED

                if topic_done and subtitle_done:
                    self.status = ProcessingStatus.TRANSCRIBED
                    return

        # Загрузка (не зависит от этапов)
        if self.status in [ProcessingStatus.UPLOADING, ProcessingStatus.UPLOADED]:
            return

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
            "status": self.status.value,
            "downloaded": self.is_downloaded(),
            "processed": self.is_processed(),
        }

        # Добавляем пути к файлам, если они есть
        if self.local_video_path:
            progress["local_file"] = self.local_video_path
        if self.processed_video_path:
            progress["processed_file"] = self.processed_video_path
        if self.processed_audio_dir:
            progress["processed_audio_dir"] = self.processed_audio_dir
        if self.transcription_dir:
            progress["transcription_dir"] = self.transcription_dir

        # Добавляем информацию о транскрипции
        if self.topic_timestamps:
            progress["topics_count"] = len(self.topic_timestamps)
        if self.main_topics:
            progress["main_topics"] = self.main_topics

        # Добавляем информацию о таргетах
        if self.output_targets:
            progress["outputs"] = self.targets_summary()

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
