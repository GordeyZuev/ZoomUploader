"""
Менеджер пайплайна обработки видео
"""

import asyncio
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from config.unified_config import AppConfig, load_app_config
from database import DatabaseManager
from fireworks_module import FireworksConfig
from logger import get_logger
from models import MeetingRecording, PlatformStatus, ProcessingStatus
from utils import (
    filter_available_recordings,
    filter_recordings_by_date_range,
)
from utils.formatting import normalize_datetime_string
from utils.interactive_mapper import get_interactive_mapper
from utils.title_mapper import TitleMapper
from video_download_module import ZoomDownloader
from video_upload_module.core.base import UploadResult

logger = get_logger()


class PipelineManager:
    """Менеджер пайплайна обработки видео"""

    def __init__(
        self,
        db_manager: DatabaseManager,
        app_config: AppConfig | None = None,
    ):
        self.db_manager = db_manager
        self.logger = get_logger()
        self.app_config = app_config or load_app_config()
        self.title_mapper = TitleMapper(self.app_config)
        self.interactive_mapper = get_interactive_mapper()
        self.console = Console(force_terminal=True, color_system="auto")

    async def list_recordings(
        self, from_date: str, to_date: str | None = None, status: ProcessingStatus | None = None
    ) -> list[MeetingRecording]:
        """Получение списка записей"""
        if status:
            recordings = await self.db_manager.get_recordings(status=status)
        else:
            recordings = await self.db_manager.get_recordings()

        if from_date or to_date:
            recordings = filter_recordings_by_date_range(recordings, from_date, to_date)

        return recordings

    async def get_recordings_from_db(
        self, from_date: str, to_date: str | None = None
    ) -> list[MeetingRecording]:
        """Получение записей только из базы данных (без обращения к Zoom API)"""
        all_recordings = await self.db_manager.get_recordings()

        if not all_recordings:
            self.logger.info("📋 Записи в БД не найдены")
            return []

        filtered_recordings = filter_recordings_by_date_range(all_recordings, from_date, to_date)
        self.logger.info(
            f"📋 Записей за период {from_date} - {to_date or 'текущая дата'}: {len(filtered_recordings)}"
        )

        available_recordings = filter_available_recordings(filtered_recordings, min_size_mb=40)
        print(f"📋 Доступных записей (>30 мин, >40 МБ): {len(available_recordings)}")

        return available_recordings

    async def sync_recordings_to_db(self, recordings: list[MeetingRecording]) -> int:
        """Синхронизация записей с базой данных"""
        if not recordings:
            return 0

        filtered_recordings = []
        filtered_count = 0

        for recording in recordings:
            if recording.duration < 30:
                filtered_count += 1
                topic = recording.topic.strip() if recording.topic else "Без названия"
                self.logger.info(
                    f"⏭️ Запись '{topic}' пропущена (длительность {recording.duration} мин < 30 мин)"
                )
                continue

            size_mb = recording.video_file_size / (1024 * 1024) if recording.video_file_size else 0
            if size_mb < 40:
                filtered_count += 1
                topic = recording.topic.strip() if recording.topic else "Без названия"
                self.logger.info(
                    f"⏭️ Запись '{topic}' пропущена (размер {size_mb:.1f} МБ < 40 МБ)"
                )
                continue

            filtered_recordings.append(recording)

        if filtered_count > 0:
            self.logger.info(f"📊 Отфильтровано записей: {filtered_count}")

        # Проверяем маппинг для каждой записи
        for recording in filtered_recordings:
            self._check_and_set_mapping(recording)

        synced_count = await self.db_manager.save_recordings(filtered_recordings)
        self.logger.info(f"✅ Синхронизировано записей: {synced_count}")
        return synced_count

    async def reset_specific_recordings(self, recording_ids: list[int]) -> dict:
        """Сброс конкретных записей к статусу INITIALIZED"""
        reset_count = 0
        total_deleted_files = 0

        # Получаем все записи одним запросом
        recordings = await self.db_manager.get_recordings_by_ids(recording_ids)
        recordings_by_id = {recording.db_id: recording for recording in recordings}

        for recording_id in recording_ids:
            try:
                # Получаем запись из кэша
                recording = recordings_by_id.get(recording_id)
                if not recording:
                    self.logger.warning(f"⚠️ Запись {recording_id} не найдена")
                    continue

                # Удаляем физические файлы перед сбросом
                deleted_files = []
                if recording.local_video_path and os.path.exists(recording.local_video_path):
                    try:
                        os.remove(recording.local_video_path)
                        deleted_files.append(recording.local_video_path)
                        self.logger.info(f"🗑️ Удален файл: {recording.local_video_path}")
                    except Exception as e:
                        self.logger.warning(
                            f"⚠️ Не удалось удалить файл {recording.local_video_path}: {e}"
                        )

                if recording.processed_video_path and os.path.exists(
                    recording.processed_video_path
                ):
                    try:
                        os.remove(recording.processed_video_path)
                        deleted_files.append(recording.processed_video_path)
                        self.logger.info(f"🗑️ Удален файл: {recording.processed_video_path}")
                    except Exception as e:
                        self.logger.warning(
                            f"⚠️ Не удалось удалить файл {recording.processed_video_path}: {e}"
                        )

                if recording.processed_audio_path and os.path.exists(recording.processed_audio_path):
                    try:
                        os.remove(recording.processed_audio_path)
                        deleted_files.append(recording.processed_audio_path)
                        self.logger.info(f"🗑️ Удален файл: {recording.processed_audio_path}")
                    except Exception as e:
                        self.logger.warning(
                            f"⚠️ Не удалось удалить файл {recording.processed_audio_path}: {e}"
                        )

                # Удаляем файл транскрипции, если он существует
                if recording.transcription_file_path and os.path.exists(recording.transcription_file_path):
                    try:
                        os.remove(recording.transcription_file_path)
                        deleted_files.append(recording.transcription_file_path)
                        self.logger.info(f"🗑️ Удален файл транскрипции: {recording.transcription_file_path}")
                    except Exception as e:
                        self.logger.warning(
                            f"⚠️ Не удалось удалить файл транскрипции {recording.transcription_file_path}: {e}"
                        )

                # Полный сброс к изначальному состоянию
                # Если есть маппинг, ставим INITIALIZED, иначе SKIPPED
                if recording.is_mapped:
                    recording.status = ProcessingStatus.INITIALIZED
                else:
                    recording.status = ProcessingStatus.SKIPPED

                # Сбрасываем локальные файлы
                recording.local_video_path = None
                recording.processed_video_path = None
                recording.processed_audio_path = None
                recording.downloaded_at = None

                # Сбрасываем транскрипцию и темы
                recording.transcription_file_path = None
                recording.topic_timestamps = None
                recording.main_topics = None

                # Сбрасываем статусы загрузки на платформы
                recording.youtube_status = PlatformStatus.NOT_UPLOADED
                recording.vk_status = PlatformStatus.NOT_UPLOADED

                # Сбрасываем URL на платформах
                recording.youtube_url = None
                recording.vk_url = None

                # Сбрасываем метаданные обработки
                recording.processing_notes = ""
                recording.processing_time = None

                # Обновляем время изменения
                recording.updated_at = datetime.now()

                # Сохраняем изменения
                await self.db_manager.update_recording(recording)
                reset_count += 1
                total_deleted_files += len(deleted_files)

            except Exception as e:
                self.logger.error(f"❌ Ошибка при сбросе записи {recording_id}: {e}")

        return {
            'total_reset': reset_count,
            'by_status': {'INITIALIZED': reset_count},
            'deleted_files': total_deleted_files,
        }

    async def download_recordings(
        self,
        recordings: list[MeetingRecording],
        max_concurrent: int = 3,
        force_download: bool = False,
    ) -> int:
        """Загрузка записей"""
        if not recordings:
            return 0

        downloader = ZoomDownloader()

        # Загружаем записи без общего прогресс-бара (используем только индивидуальные)
        results = await downloader.download_multiple(recordings, max_concurrent, force_download)

        success_count = sum(results)
        self.logger.info(f"✅ Загружено записей: {success_count}/{len(recordings)}")

        for recording, success in zip(recordings, results, strict=False):
            if success:
                await self.db_manager.update_recording(recording)

        return success_count

    async def process_recordings(self, recordings: list[MeetingRecording]) -> int:
        """Обработка записей"""
        if not recordings:
            return 0

        # Обрабатываем записи без общего прогресс-бара (используем только индивидуальные)
        success_count = 0
        for recording in recordings:
            if await self._process_single_recording(recording):
                success_count += 1

        self.logger.info(f"✅ Обработано записей: {success_count}/{len(recordings)}")
        return success_count

    async def transcribe_recordings(
        self,
        recordings: list[MeetingRecording],
        transcription_model: str = "fireworks",
        topic_mode: str = "long",
    ) -> int:
        """Транскрибация записей (параллельно)"""
        if not recordings:
            return 0

        self.logger.info(
            f"🎤 Параллельная транскрибация {len(recordings)} записей "
            f"(модель: {transcription_model}, режим тем: {topic_mode})..."
        )

        # Запускаем все транскрибации параллельно
        tasks = [
            self._transcribe_single_recording(
                recording, transcription_model=transcription_model, topic_mode=topic_mode
            )
            for recording in recordings
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        success_count = 0
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.logger.error(f"❌ Ошибка транскрибации записи {recordings[i].topic}: {result}")
            elif result:
                success_count += 1

        self.logger.info(f"✅ Транскрибировано записей: {success_count}/{len(recordings)}")
        return success_count

    async def upload_recordings(
        self, recordings: list[MeetingRecording], platforms: list[str]
    ) -> tuple[int, list[MeetingRecording]]:
        """Загрузка записей на платформы"""
        if not recordings:
            return 0, []

        success_count = 0
        uploaded_recordings = []

        for recording in recordings:
            if await self._upload_single_recording(recording, platforms):
                success_count += 1
                uploaded_recordings.append(recording)

        return success_count, uploaded_recordings

    def display_uploaded_videos(self, uploaded_recordings: list[MeetingRecording]) -> None:
        """Отображение списка загруженных видео с ссылками"""
        if not uploaded_recordings:
            return

        self.console.print("\n[bold white]📹 ЗАГРУЖЕННЫЕ ВИДЕО:[/bold white]")
        self.console.print("[dim]" + "=" * 60 + "[/dim]")

        for i, recording in enumerate(uploaded_recordings, 1):
            if recording.youtube_url or recording.vk_url:
                self.console.print(
                    f"\n[bold cyan]{i}.[/bold cyan] [bold white]{recording.topic}[/bold white]"
                )

                if recording.youtube_url:
                    self.console.print(
                        f"    [bold red]📺 YouTube:[/bold red] [link={recording.youtube_url}]{recording.youtube_url}[/link]"
                    )

                if recording.vk_url:
                    self.console.print(
                        f"    [bold blue]📘 VK:[/bold blue] [link={recording.vk_url}]{recording.vk_url}[/link]"
                    )

    def _create_upload_config_from_app_config(self):
        """Создание конфигурации загрузки из конфигурации приложения"""
        from video_upload_module.config_factory import UploadConfigFactory

        # Используем фабрику для создания конфигурации
        upload_config = UploadConfigFactory.from_app_config(self.app_config)

        return upload_config

    async def get_recordings_by_selection(
        self, select_all: bool, recordings: list[str], from_date: str, to_date: str | None = None
    ) -> list[MeetingRecording]:
        """Получение записей по выбору"""
        all_recordings = await self.get_recordings_from_db(from_date, to_date)

        if select_all:
            return all_recordings

        if recordings:
            return [r for r in all_recordings if r.topic in recordings]

        return []

    async def get_recordings_by_numbers(
        self, recording_ids: list[int], from_date: str, to_date: str | None = None
    ) -> list[MeetingRecording]:
        """Получение записей по номерам"""
        all_recordings = await self.get_recordings_from_db(from_date, to_date)

        target_recordings = []
        for recording in all_recordings:
            if recording.db_id in recording_ids:
                if (
                    recording.duration >= 30
                    and recording.video_file_size >= 30 * 1024 * 1024
                    and recording.status == ProcessingStatus.INITIALIZED
                ):
                    target_recordings.append(recording)

        return target_recordings

    async def get_all_zoom_recordings(
        self, configs: dict, from_date: str, to_date: str | None = None
    ) -> list[MeetingRecording]:
        """Получение всех записей из Zoom"""
        from api.zoom_api import ZoomAPI
        from utils import get_recordings_by_date_range

        all_recordings = []

        for account, config in configs.items():
            try:
                api = ZoomAPI(config)
                recordings = await get_recordings_by_date_range(
                    api, start_date=from_date, end_date=to_date, filter_video_only=False
                )
                # Добавляем информацию об аккаунте к каждой записи
                for recording in recordings:
                    recording.account = account
                all_recordings.extend(recordings)
                self.logger.info(f"📥 Получено записей от аккаунта {account}: {len(recordings)}")
            except Exception as e:
                self.logger.error(f"❌ Ошибка получения записей от аккаунта {account}: {e}")

        return all_recordings

    def _check_and_set_mapping(self, recording: MeetingRecording) -> None:
        """Проверка маппинга записи и установка соответствующего статуса"""
        try:
            topic = recording.topic.strip() if recording.topic else ""
            # Проверяем, есть ли маппинг для этой записи
            mapping_result = self.title_mapper.map_title(
                topic, recording.start_time, recording.duration
            )

            if mapping_result.title:
                # Есть маппинг - устанавливаем статус INITIALIZED
                recording.is_mapped = True
                recording.status = ProcessingStatus.INITIALIZED
                self.logger.debug(
                    f"✅ Маппинг найден для '{topic}' -> '{mapping_result.title}'"
                )
            else:
                # Нет маппинга - устанавливаем статус SKIPPED
                recording.is_mapped = False
                recording.status = ProcessingStatus.SKIPPED
                self.logger.debug(f"⏭️ Маппинг не найден для '{topic}'")

        except Exception as e:
            # В случае ошибки - считаем, что маппинга нет
            recording.is_mapped = False
            recording.status = ProcessingStatus.SKIPPED
            self.logger.warning(f"   ❌ Ошибка проверки маппинга для '{recording.topic}': {e}")

    async def _check_and_update_skipped_recordings(
        self, from_date: str, to_date: str | None = None
    ) -> int:
        """Проверка существующих записей со статусом SKIPPED и обновление их статуса если появился маппинг"""
        from utils.data_processing import filter_recordings_by_date_range

        skipped_recordings = await self.db_manager.get_recordings(ProcessingStatus.SKIPPED)

        if not skipped_recordings:
            return 0

        filtered_skipped = filter_recordings_by_date_range(skipped_recordings, from_date, to_date)

        if not filtered_skipped:
            return 0

        self.logger.info(
            f"🔍 Проверка {len(filtered_skipped)} пропущенных записей на наличие нового маппинга..."
        )

        updated_count = 0
        recordings_to_update = []

        for recording in filtered_skipped:
            old_status = recording.status
            old_is_mapped = recording.is_mapped
            topic = recording.topic.strip() if recording.topic else "Без названия"

            self.logger.debug(
                f"🔍 Проверка записи: «{topic}» (статус: {old_status.value}, is_mapped: {old_is_mapped})"
            )

            self._check_and_set_mapping(recording)

            if old_status == ProcessingStatus.SKIPPED and recording.status == ProcessingStatus.INITIALIZED:
                self.logger.info(
                    f"✅ Найден маппинг для пропущенной записи: «{topic}» - статус обновлён на INITIALIZED (is_mapped: {recording.is_mapped})"
                )
                recordings_to_update.append(recording)
                updated_count += 1
            elif old_is_mapped != recording.is_mapped:
                self.logger.info(
                    f"🔄 Изменён is_mapped для записи: «{topic}»: {old_is_mapped} -> {recording.is_mapped}"
                )
                recordings_to_update.append(recording)
                updated_count += 1

        if recordings_to_update:
            await self.db_manager.save_recordings(recordings_to_update)
            self.logger.info(f"✅ Обновлено пропущенных записей: {updated_count}")

        return updated_count

    def _format_duration(self, minutes: int) -> str:
        """Форматирование длительности в читаемый вид"""
        if minutes < 60:
            return f"{minutes}м"
        else:
            hours = minutes // 60
            remaining_minutes = minutes % 60
            if remaining_minutes == 0:
                return f"{hours}ч"
            else:
                return f"{hours}ч {remaining_minutes}м"

    def _format_elapsed_time(self, seconds: float) -> str:
        """Форматирование времени выполнения в читаемый вид"""
        if seconds < 60:
            return f"{seconds:.1f}с"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{minutes}м {secs}с"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            return f"{hours}ч {minutes}м {secs}с"

    async def run_full_pipeline(
        self,
        configs: dict,
        from_date: str,
        to_date: str | None,
        select_all: bool,
        recordings: list[str],
        platforms: list[str],
        allow_skipped: bool = False,
        no_transcription: bool = False,
        transcription_model: str = "fireworks",
        topic_mode: str = "long",
    ) -> dict:
        """Запуск полного пайплайна обработки"""
        # Разрешаем работу с записями в любом статусе (кроме UPLOADED и FAILED)
        # Это позволяет продолжить обработку уже частично обработанных записей
        allowed_statuses = [
            ProcessingStatus.INITIALIZED,
            ProcessingStatus.DOWNLOADED,
            ProcessingStatus.PROCESSED,
            ProcessingStatus.TRANSCRIBED,
        ]
        if allow_skipped:
            allowed_statuses.append(ProcessingStatus.SKIPPED)

        if select_all:
            all_recordings = await self.get_recordings_from_db(from_date, to_date)
            target_recordings = [r for r in all_recordings if r.status in allowed_statuses]
        elif recordings:
            all_recordings = await self.get_recordings_from_db(from_date, to_date)
            target_recordings = []

            # Пытаемся интерпретировать как ID записей
            try:
                recording_ids = [int(r) for r in recordings]
                # Ищем записи по ID
                for recording in all_recordings:
                    if recording.db_id in recording_ids and recording.status in allowed_statuses:
                        target_recordings.append(recording)
            except ValueError:
                # Если не числа, используем старую логику с названиями
                target_recordings = [
                    r
                    for r in all_recordings
                    if r.topic in recordings and r.status in allowed_statuses
                ]
        else:
            # Если не указаны ни --all, ни записи - обрабатываем все за указанный период
            all_recordings = await self.get_recordings_from_db(from_date, to_date)
            target_recordings = [r for r in all_recordings if r.status in allowed_statuses]

        if not target_recordings:
            self.logger.warning("❌ Нет записей для обработки")
            return {"success": False, "message": "Нет записей для обработки"}

        self.logger.info(f"🚀 Запуск полного пайплайна для {len(target_recordings)} записей")

        # Начало отсчета общего времени выполнения пайплайна
        pipeline_start_time = time.time()

        # ЭТАП 1: СКАЧИВАНИЕ
        # Скачиваем только записи со статусом INITIALIZED или SKIPPED
        recordings_to_download = [
            r for r in target_recordings
            if r.status in [ProcessingStatus.INITIALIZED, ProcessingStatus.SKIPPED]
        ]
        download_count = 0
        if recordings_to_download:
            self.console.print()
            self.console.print("[bold blue]" + "=" * 70 + "[/bold blue]")
            self.console.print("[bold blue]📥 ЭТАП 1: СКАЧИВАНИЕ ЗАПИСЕЙ[/bold blue]")
            self.console.print("[bold blue]" + "=" * 70 + "[/bold blue]")
            self.console.print()
            stage_start_time = time.time()
            download_count = await self.download_recordings(recordings_to_download)
            stage_elapsed = time.time() - stage_start_time
            self.console.print()
            self.console.print(
                f"[bold green]✅ Этап 1 завершен: скачано {download_count}/{len(recordings_to_download)} записей "
                f"[dim](время выполнения: {self._format_elapsed_time(stage_elapsed)})[/dim][/bold green]"
            )
        else:
            self.logger.info("⏭️  Пропуск этапа скачивания: нет записей для скачивания")

        # Обновляем список записей после скачивания (обновляем статусы)
        # Получаем актуальные статусы записей из БД
        if recordings_to_download:
            updated_recordings = await self.db_manager.get_recordings_by_ids(
                [r.db_id for r in recordings_to_download]
            )
            # Обновляем статусы в target_recordings
            updated_dict = {r.db_id: r for r in updated_recordings}
            for recording in target_recordings:
                if recording.db_id in updated_dict:
                    recording.status = updated_dict[recording.db_id].status
                    recording.local_video_path = updated_dict[recording.db_id].local_video_path

        # Проверяем, есть ли записи для обработки (скачанные или уже имеющиеся)
        recordings_to_process = [
            r for r in target_recordings
            if r.status == ProcessingStatus.DOWNLOADED and r.local_video_path
        ]

        # ЭТАП 2: ОБРАБОТКА
        process_count = 0
        if recordings_to_process:
            self.console.print()
            self.console.print("[bold yellow]" + "=" * 70 + "[/bold yellow]")
            self.console.print("[bold yellow]🎬 ЭТАП 2: ОБРАБОТКА ВИДЕО[/bold yellow]")
            self.console.print("[bold yellow]" + "=" * 70 + "[/bold yellow]")
            self.console.print()
            stage_start_time = time.time()
            process_count = await self.process_recordings(recordings_to_process)
            stage_elapsed = time.time() - stage_start_time
            self.console.print()
            self.console.print(
                f"[bold green]✅ Этап 2 завершен: обработано {process_count}/{len(recordings_to_process)} записей "
                f"[dim](время выполнения: {self._format_elapsed_time(stage_elapsed)})[/dim][/bold green]"
            )

            # Обновляем статусы после обработки
            updated_recordings = await self.db_manager.get_recordings_by_ids(
                [r.db_id for r in recordings_to_process]
            )
            updated_dict = {r.db_id: r for r in updated_recordings}
            for recording in target_recordings:
                if recording.db_id in updated_dict:
                    recording.status = updated_dict[recording.db_id].status
                    recording.processed_video_path = updated_dict[recording.db_id].processed_video_path
                    recording.processed_audio_path = updated_dict[recording.db_id].processed_audio_path
        else:
            self.logger.info("⏭️  Пропуск этапа обработки: нет записей для обработки")

        # ЭТАП 3: ТРАНСКРИБАЦИЯ
        transcribe_count = 0
        if not no_transcription:
            # Транскрибируем только записи со статусом PROCESSED, которые еще не транскрибированы
            recordings_to_transcribe = [
                r for r in target_recordings
                if r.status == ProcessingStatus.PROCESSED
                and (r.processed_audio_path or r.processed_video_path)
            ]
            if recordings_to_transcribe:
                self.console.print()
                self.console.print("[bold cyan]" + "=" * 70 + "[/bold cyan]")
                self.console.print("[bold cyan]🎤 ЭТАП 3: ТРАНСКРИБАЦИЯ АУДИО[/bold cyan]")
                self.console.print("[bold cyan]" + "=" * 70 + "[/bold cyan]")
                self.console.print()
                stage_start_time = time.time()
                transcribe_count = await self.transcribe_recordings(
                    recordings_to_transcribe,
                    transcription_model=transcription_model,
                    topic_mode=topic_mode,
                )
                stage_elapsed = time.time() - stage_start_time
                self.console.print()
                self.console.print(
                    f"[bold green]✅ Этап 3 завершен: транскрибировано {transcribe_count}/{len(recordings_to_transcribe)} записей "
                    f"[dim](время выполнения: {self._format_elapsed_time(stage_elapsed)})[/dim][/bold green]"
                )

                # Обновляем статусы после транскрибации
                updated_recordings = await self.db_manager.get_recordings_by_ids(
                    [r.db_id for r in recordings_to_transcribe]
                )
                updated_dict = {r.db_id: r for r in updated_recordings}
                for recording in target_recordings:
                    if recording.db_id in updated_dict:
                        recording.status = updated_dict[recording.db_id].status
                        recording.transcription_file_path = updated_dict[recording.db_id].transcription_file_path
            else:
                self.logger.info("⏭️  Пропуск этапа транскрибации: нет записей для транскрибации")

        # ЭТАП 4: ЗАГРУЗКА НА ПЛАТФОРМЫ
        # Загружаем записи со статусом PROCESSED или TRANSCRIBED, которые еще не загружены
        recordings_to_upload = [
            r for r in target_recordings
            if r.status in [ProcessingStatus.PROCESSED, ProcessingStatus.TRANSCRIBED]
            and not (r.youtube_url or r.vk_url)  # Еще не загружены ни на одну платформу
        ]
        upload_count = 0
        uploaded_recordings = []
        if recordings_to_upload and platforms:
            self.console.print()
            self.console.print("[bold green]" + "=" * 70 + "[/bold green]")
            self.console.print("[bold green]📤 ЭТАП 4: ЗАГРУЗКА НА ПЛАТФОРМЫ[/bold green]")
            self.console.print("[bold green]" + "=" * 70 + "[/bold green]")
            self.console.print()
            stage_start_time = time.time()
            upload_count, uploaded_recordings = await self.upload_recordings(recordings_to_upload, platforms)
            stage_elapsed = time.time() - stage_start_time
            self.console.print()
            self.console.print(
                f"[bold green]✅ Этап 4 завершен: загружено {upload_count}/{len(recordings_to_upload)} записей "
                f"[dim](время выполнения: {self._format_elapsed_time(stage_elapsed)})[/dim][/bold green]"
            )

        # Вычисляем общее время выполнения пайплайна
        pipeline_total_time = time.time() - pipeline_start_time

        return {
            "success": True,
            "download_count": download_count,
            "process_count": process_count,
            "transcribe_count": transcribe_count,
            "upload_count": upload_count,
            "uploaded_recordings": uploaded_recordings,
            "total_time": pipeline_total_time,
        }

    async def _download_single_recording(self, recording: MeetingRecording) -> bool:
        """Загрузка одной записи"""
        downloader = ZoomDownloader()

        with Progress(
            SpinnerColumn(style="blue"),
            TextColumn("[bold blue]Скачивание записи[/bold blue]"),
            TimeElapsedColumn(),
            transient=False,
            console=self.console,
        ) as progress:
            task_id = progress.add_task("Скачивание", total=None)

            success = await downloader.download_recording(recording, progress, task_id)

            if success:
                await self.db_manager.update_recording(recording)

            return success



    async def clean_old_recordings(self, days_ago: int = 7) -> dict[str, Any]:
        """Очистка старых записей: удаление файлов и установка статуса EXPIRED"""
        cutoff_date = datetime.now() - timedelta(days=days_ago)
        all_recordings = await self.db_manager.get_records_older_than(cutoff_date)

        if not all_recordings:
            self.logger.info("📋 Старые записи для очистки не найдены")
            return {'cleaned_count': 0, 'freed_space_mb': 0, 'cleaned_recordings': []}

        cleaned_count = 0
        freed_space_mb = 0
        cleaned_recordings = []

        for recording in all_recordings:
            file_deleted = False

            if recording.local_video_path and os.path.exists(recording.local_video_path):
                try:
                    file_size = os.path.getsize(recording.local_video_path) / (1024 * 1024)
                    os.remove(recording.local_video_path)
                    freed_space_mb += file_size
                    file_deleted = True
                    self.logger.info(
                        f"🗑️ Удален файл: {recording.local_video_path} ({file_size:.1f} МБ)"
                    )
                except Exception as e:
                    self.logger.error(f"❌ Ошибка удаления файла {recording.local_video_path}: {e}")

            if recording.processed_video_path and os.path.exists(recording.processed_video_path):
                try:
                    file_size = os.path.getsize(recording.processed_video_path) / (1024 * 1024)
                    os.remove(recording.processed_video_path)
                    freed_space_mb += file_size
                    file_deleted = True
                    self.logger.info(
                        f"🗑️ Удален файл: {recording.processed_video_path} ({file_size:.1f} МБ)"
                    )
                except Exception as e:
                    self.logger.error(
                        f"❌ Ошибка удаления файла {recording.processed_video_path}: {e}"
                    )

            if recording.processed_audio_path and os.path.exists(recording.processed_audio_path):
                try:
                    file_size = os.path.getsize(recording.processed_audio_path) / (1024 * 1024)
                    os.remove(recording.processed_audio_path)
                    freed_space_mb += file_size
                    file_deleted = True
                    self.logger.info(
                        f"🗑️ Удален файл: {recording.processed_audio_path} ({file_size:.1f} МБ)"
                    )
                except Exception as e:
                    self.logger.error(
                        f"❌ Ошибка удаления файла {recording.processed_audio_path}: {e}"
                    )

            if file_deleted:
                recording.status = ProcessingStatus.EXPIRED
                recording.processing_notes = (
                    f"Очищено {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
                await self.db_manager.update_recording(recording)
                cleaned_count += 1
                cleaned_recordings.append(
                    {'id': recording.db_id, 'topic': recording.topic, 'deleted_files': []}
                )

        self.logger.info(
            f"✅ Очищено записей: {cleaned_count}, освобождено места: {freed_space_mb:.1f} МБ"
        )
        return {
            'cleaned_count': cleaned_count,
            'freed_space_mb': freed_space_mb,
            'cleaned_recordings': cleaned_recordings,
        }


    async def sync_zoom_recordings(
        self, configs: dict, from_date: str, to_date: str | None = None
    ) -> int:
        """Синхронизация записей из Zoom API с базой данных за указанный период"""
        from api import ZoomAPI
        from utils import get_recordings_by_date_range

        self.logger.info(
            f"📥 Синхронизация записей из Zoom API за период {from_date} - {to_date or 'текущая дата'}..."
        )
        all_recordings = []

        for account, config in configs.items():
            self.logger.info(f"📥 Получение записей из аккаунта: {account}")

            try:
                api = ZoomAPI(config)
                # Загружаем записи только за указанный период
                recordings = await get_recordings_by_date_range(
                    api, start_date=from_date, end_date=to_date, filter_video_only=False
                )

                if recordings:
                    self.logger.info(f"   Найдено записей: {len(recordings)}")
                    # Добавляем информацию об аккаунте к каждой записи
                    for recording in recordings:
                        recording.account = account
                    all_recordings.extend(recordings)
                else:
                    self.logger.info("   Записи не найдены")

            except Exception as e:
                self.logger.error(f"   ❌ Ошибка получения записей из {account}: {e}")
                continue

        # Синхронизируем все записи с БД (включая дедупликацию)
        synced_count = 0
        if all_recordings:
            synced_count = await self.sync_recordings_to_db(all_recordings)

        updated_skipped_count = await self._check_and_update_skipped_recordings(from_date, to_date)

        total_count = synced_count + updated_skipped_count
        if total_count > 0:
            return total_count
        else:
            self.logger.info("📋 Записи не найдены")
            return 0

    def display_recordings(self, recordings: list[MeetingRecording]):
        """Отображение списка записей"""
        if not recordings:
            self.console.print("\n[bold dark_red]📋 Доступных записей не найдено[/bold dark_red]")
            self.console.print(
                "[dim]💡 Критерии: длительность >30 мин, размер >40 МБ, наличие видео[/dim]"
            )
            return

        # Заголовок с общей статистикой
        self.console.print(f"\n[bold blue]📋 Доступных записей: {len(recordings)}[/bold blue]")
        self.console.print("[dim]" + "=" * 80 + "[/dim]")

        # Группируем записи по датам
        from collections import defaultdict
        from datetime import datetime

        dates = defaultdict(list)
        for recording in recordings:
            if recording.start_time:
                try:
                    # Парсим строку даты в datetime объект
                    normalized_time = normalize_datetime_string(recording.start_time)
                    meeting_dt = datetime.fromisoformat(normalized_time)

                    # Используем только дату (без времени) для группировки
                    date_key = meeting_dt.date()
                    dates[date_key].append(recording)
                except ValueError:
                    # Если не удалось распарсить дату, пропускаем запись
                    continue

        # Сортируем даты по возрастанию (старые сначала)
        sorted_dates = sorted(dates.keys(), reverse=False)

        # Показываем записи по датам
        for date_idx, date_key in enumerate(sorted_dates):
            date_recordings = dates[date_key]

            # Сортируем записи по времени (по возрастанию)
            def get_start_time_for_sort(recording):
                try:
                    normalized_time = normalize_datetime_string(recording.start_time)
                    return datetime.fromisoformat(normalized_time)
                except ValueError:
                    return datetime.min  # Если не удалось распарсить, ставим в начало

            date_recordings.sort(key=get_start_time_for_sort)

            # Разделитель между датами (кроме первого)
            if date_idx > 0:
                self.console.print("")

            # Заголовок даты
            date_str = date_key.strftime("%d.%m.%Y")
            self.console.print(
                f"\n[bold blue]📅 ДАТА:[/bold blue] [bold white]{date_str}[/bold white]"
            )
            self.console.print(
                f"[bold blue]📊 Записей:[/bold blue] [bold white]{len(date_recordings)}[/bold white]"
            )
            self.console.print("[dim]" + "-" * 60 + "[/dim]")

            for recording in date_recordings:
                # Показываем ID записи из базы данных
                display_id = recording.db_id

                from utils import format_date, format_duration

                date_human = format_date(recording.start_time)
                dur_human = format_duration(recording.duration)

                # Получаем статус и форматируем его
                status_text = self._format_status(recording.status)

                # Показываем информацию о видео
                if recording.has_video():
                    size_str = f"{recording.video_file_size / (1024 * 1024):.1f} МБ"

                    # Формируем строку с названием (с кавычками и strip)
                    topic = recording.topic.strip() if recording.topic else "Без названия"
                    title_with_link = f"[bold blue]«{topic}»[/bold blue]"

                    # Основная строка с ID и названием
                    self.console.print(f"[bold blue][{display_id}][/bold blue] {title_with_link}")

                    # Детали записи с отступами и цветами
                    self.console.print(
                        f"     📅 [white]{date_human}[/white] [dim]({dur_human})[/dim]"
                    )
                    self.console.print(f"     💾 [white]{size_str}[/white]")
                    self.console.print(f"     🔐 {recording.account or 'Unknown'}")
                    self.console.print(f"     {status_text}")
                else:
                    # Формируем строку с названием (с кавычками и strip)
                    topic = recording.topic.strip() if recording.topic else "Без названия"
                    title_with_link = f"[bold blue]«{topic}»[/bold blue]"

                    # Основная строка с ID и названием
                    self.console.print(f"[bold blue][{display_id}][/bold blue] {title_with_link}")

                    # Детали записи с отступами и цветами
                    self.console.print(
                        f"     📅 [white]{date_human}[/white] [dim]({dur_human})[/dim]"
                    )
                    self.console.print("     [red]❌ Нет видео[/red]")
                    self.console.print(f"     🔐 {recording.account or 'Unknown'}")
                    self.console.print(f"     {status_text}")

                # Разделитель между записями
                self.console.print("")

    def _format_status(self, status: ProcessingStatus) -> str:
        """Форматирование статуса с цветовым кодированием"""
        status_map = {
            ProcessingStatus.INITIALIZED: "[dim]⏳ Инициализировано[/dim]",
            ProcessingStatus.DOWNLOADING: "[bold yellow]⬇️ Загружается...[/bold yellow]",
            ProcessingStatus.DOWNLOADED: "[bold green]✅ Загружено[/bold green]",
            ProcessingStatus.PROCESSING: "[bold yellow]⚙️ Обрабатывается...[/bold yellow]",
            ProcessingStatus.PROCESSED: "[bold green]🎬 Обработано[/bold green]",
            ProcessingStatus.TRANSCRIBING: "[bold yellow]🎤 Транскрибируется...[/bold yellow]",
            ProcessingStatus.TRANSCRIBED: "[bold cyan]🎤 Транскрибировано[/bold cyan]",
            ProcessingStatus.UPLOADING: "[bold yellow]⬆️ Загружается на платформы...[/bold yellow]",
            ProcessingStatus.UPLOADED: "[bold blue]🚀 Загружено на платформы[/bold blue]",
            ProcessingStatus.FAILED: "[bold red]❌ Ошибка[/bold red]",
            ProcessingStatus.SKIPPED: "[white][dim]⏭️  Пропущено[/dim][/white]",
            ProcessingStatus.EXPIRED: "[dim]🗑️  Устарело[/dim]",
        }
        return status_map.get(status, f"[dim]{status.value}[/dim]")

    async def _download_single_recording(self, recording: MeetingRecording) -> bool:
        """Скачивание одной записи с прогресс-баром"""
        try:
            from rich.progress import (
                BarColumn,
                DownloadColumn,
                Progress,
                SpinnerColumn,
                TextColumn,
                TimeElapsedColumn,
                TransferSpeedColumn,
            )

            from video_download_module.downloader import ZoomDownloader

            downloader = ZoomDownloader()

            # Показываем прогресс-бар во время скачивания
            with Progress(
                SpinnerColumn(style="blue"),
                TextColumn("[bold blue]Скачивание"),
                "•",
                BarColumn(),
                DownloadColumn(),
                TransferSpeedColumn(),
                TimeElapsedColumn(),
                transient=False,
                console=self.console,
            ) as progress:
                # Создаем задачу для прогресс-бара
                try:
                    from datetime import datetime

                    from utils.formatting import normalize_datetime_string

                    normalized_time = normalize_datetime_string(recording.start_time)
                    meeting_dt = datetime.fromisoformat(normalized_time)
                    date_str = meeting_dt.strftime("%d.%m.%y")
                except Exception:
                    date_str = "??/??/??"

                title = f"{recording.topic[:45]}{'...' if len(recording.topic) > 45 else ''}"
                estimated_size = recording.video_file_size or (
                    200 * 1024 * 1024
                )  # 200 МБ по умолчанию
                task_id = progress.add_task(title, total=estimated_size, date=date_str)

                # Используем download_recording с прогресс-баром
                success = await downloader.download_recording(
                    recording, progress, task_id, force_download=True
                )

            if success:
                # Обновляем статус на DOWNLOADED после успешного скачивания
                recording.status = ProcessingStatus.DOWNLOADED
                # Записываем обновленную запись с путем к файлу в БД
                await self.db_manager.update_recording(recording)
                self.logger.debug(f"Статус записи {recording.topic} обновлен на DOWNLOADED")
            else:
                recording.status = ProcessingStatus.FAILED
                await self.db_manager.update_recording(recording)
                self.logger.debug(f"Статус записи {recording.topic} обновлен на FAILED")

            return success
        except Exception as e:
            self.logger.error(f"Ошибка скачивания записи {recording.topic}: {e}")
            await self.db_manager.update_recording_status(
                recording.meeting_id, ProcessingStatus.FAILED
            )
            return False

    async def _process_single_recording(self, recording: MeetingRecording) -> bool:
        """Обработка одной записи с прогресс-баром"""
        try:
            from rich.progress import (
                Progress,
                SpinnerColumn,
                TextColumn,
                TimeElapsedColumn,
            )

            from video_processing_module.video_processor import ProcessingConfig, VideoProcessor

            config = ProcessingConfig()
            processor = VideoProcessor(config)

            # Проверяем существование файла
            file_path = recording.local_video_path
            if not file_path:
                self.logger.error("Путь к файлу не указан")
                recording.status = ProcessingStatus.FAILED
                await self.db_manager.update_recording(recording)
                return False

            # Если путь начинается с '/', это абсолютный путь, иначе - относительный
            if not os.path.isabs(file_path):
                file_path = os.path.join(os.getcwd(), file_path)

            if not os.path.exists(file_path):
                self.logger.error(f"Файл не найден: {file_path}")
                recording.status = ProcessingStatus.FAILED
                await self.db_manager.update_recording(recording)
                return False

            # Получаем информацию о видео для оценки времени
            video_info = await processor.get_video_info(file_path)
            duration_minutes = video_info['duration'] / 60

            self.console.print(
                f"[dim]📊 Видео: {duration_minutes:.1f} мин, обработка с детекцией звука[/dim]"
            )

            # Обрабатываем видео с крутящимся индикатором
            with Progress(
                SpinnerColumn(style="yellow"),
                TextColumn("[bold yellow]Обработка видео[/bold yellow]"),
                TimeElapsedColumn(),
                transient=False,
                console=self.console,
            ) as progress:
                progress.add_task("Обработка", total=None)

                try:
                    # Создаем задачу обработки видео (используем быстрый метод с детекцией звука)
                    process_task = asyncio.create_task(
                        processor.process_video_with_audio_detection(file_path, recording.topic)
                    )

                    # Ждем завершения с возможностью прерывания
                    # process_video_with_audio_detection возвращает только (success, processed_path)
                    success, processed_path = await process_task
                    processed_audio_path = None  # Этот метод не создает отдельный аудио файл

                except asyncio.CancelledError:
                    self.console.print("\n[bold red]❌ Обработка прервана пользователем[/bold red]")
                    recording.status = ProcessingStatus.FAILED
                    await self.db_manager.update_recording(recording)
                    return False
                except Exception as e:
                    self.logger.error(f"Ошибка обработки видео: {e}")
                    recording.status = ProcessingStatus.FAILED
                    await self.db_manager.update_recording(recording)
                    return False

            if success and processed_path:
                # Обновляем статус на PROCESSED после успешной обработки
                recording.status = ProcessingStatus.PROCESSED
                recording.processed_video_path = processed_path

                # Извлекаем аудио из обработанного видео, если его еще нет
                if not processed_audio_path:
                    try:
                        # Создаем путь для аудио файла
                        safe_title = processor._sanitize_filename(recording.topic)
                        audio_dir = "video/processed_audio"
                        os.makedirs(audio_dir, exist_ok=True)
                        audio_filename = f"{safe_title}_processed.mp3"
                        audio_path = os.path.join(audio_dir, audio_filename)

                        # Извлекаем аудио из обработанного видео с оптимальными параметрами для Whisper API
                        # Используем те же параметры, что и AudioCompressor (64k, 16kHz, моно)
                        # чтобы сразу получить файл подходящего размера
                        self.logger.info(f"🎵 Извлечение аудио из обработанного видео: {recording.topic}")
                        extract_cmd = [
                            'ffmpeg',
                            '-i', processed_path,
                            '-vn',  # Без видео
                            '-acodec', 'libmp3lame',  # MP3 кодек
                            '-ab', '64k',  # Битрейт (оптимально для Whisper)
                            '-ar', '16000',  # Частота дискретизации 16kHz (оптимально для речи)
                            '-ac', '1',  # Моно (для речи достаточно)
                            '-y',  # Перезаписать, если существует
                            audio_path,
                        ]

                        extract_process = await asyncio.create_subprocess_exec(
                            *extract_cmd,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE
                        )
                        await extract_process.wait()

                        if extract_process.returncode == 0 and os.path.exists(audio_path):
                            processed_audio_path = audio_path
                            self.logger.info(f"✅ Аудио извлечено: {audio_path}")
                        else:
                            self.logger.warning(f"⚠️ Не удалось извлечь аудио из видео: {recording.topic}")
                    except Exception as e:
                        self.logger.warning(f"⚠️ Ошибка при извлечении аудио: {e}")

                # Сохраняем путь к обработанному аудио, если оно было создано
                if processed_audio_path:
                    # Используем относительный путь, если возможно
                    try:
                        audio_path_obj = Path(processed_audio_path)
                        if audio_path_obj.is_absolute():
                            recording.processed_audio_path = str(audio_path_obj.relative_to(Path.cwd()))
                        else:
                            recording.processed_audio_path = processed_audio_path
                    except Exception:
                        recording.processed_audio_path = processed_audio_path
                # Записываем обновленную запись в БД
                await self.db_manager.update_recording(recording)
                self.logger.debug(f"Статус записи {recording.topic} обновлен на PROCESSED")
                self.console.print(
                    f"[bold green]✅ Обработано успешно: {processed_path}[/bold green]"
                )
                if processed_audio_path:
                    self.console.print(
                        f"[bold green]🎵 Аудио сохранено: {recording.processed_audio_path}[/bold green]"
                    )
            else:
                recording.status = ProcessingStatus.FAILED
                await self.db_manager.update_recording(recording)
                self.logger.debug(f"Статус записи {recording.topic} обновлен на FAILED")

            return success

        except Exception as e:
            self.logger.error(f"Ошибка обработки записи {recording.topic}: {e}")
            await self.db_manager.update_recording_status(
                recording.meeting_id, ProcessingStatus.FAILED
            )
            return False

    async def _transcribe_single_recording(
        self,
        recording: MeetingRecording,
        transcription_model: str = "fireworks",
        topic_mode: str = "long",
    ) -> bool:
        """Транскрибация одной записи с прогресс-баром"""
        try:
            # Проверяем наличие аудио или видео файла
            # TranscriptionService может работать с видео файлами, извлекая аудио автоматически
            import os

            from rich.progress import (
                Progress,
                SpinnerColumn,
                TextColumn,
                TimeElapsedColumn,
            )
            audio_path = recording.processed_audio_path
            if not audio_path:
                # Если нет отдельного аудио файла, используем видео файл
                audio_path = recording.processed_video_path
                if audio_path:
                    self.logger.info(f"Используем видео файл для транскрибации: {recording.topic}")
                else:
                    self.logger.error(f"Аудио или видео файл не найден для записи: {recording.topic}")
                    recording.status = ProcessingStatus.FAILED
                    await self.db_manager.update_recording(recording)
                    return False

            # Если путь начинается с '/', это абсолютный путь, иначе - относительный
            if not os.path.isabs(audio_path):
                audio_path = os.path.join(os.getcwd(), audio_path)

            if not os.path.exists(audio_path):
                self.logger.error(f"Файл не найден: {audio_path}")
                recording.status = ProcessingStatus.FAILED
                await self.db_manager.update_recording(recording)
                return False

            # Проверяем, не транскрибирована ли уже запись
            if recording.status == ProcessingStatus.TRANSCRIBED and recording.transcription_file_path:
                self.logger.info(f"✅ Запись уже транскрибирована: {recording.topic}")
                return True

            self.console.print(
                f"[dim]🎤 Транскрибация аудио: {recording.topic}[/dim]"
            )

            # Создаем сервис транскрибации
            try:
                from deepseek_module import DeepSeekConfig
                from openai_module import TranscriptionService
                from openai_module.config import OpenAIConfig

                openai_config = None
                try:
                    openai_config = OpenAIConfig.from_file()
                except Exception as exc:
                    self.logger.warning(f"⚠️ OpenAI конфигурация не загружена: {exc}")

                deepseek_config = DeepSeekConfig.from_file()
                fireworks_config = FireworksConfig.from_file()
                transcription_service = TranscriptionService(
                    openai_config=openai_config,
                    deepseek_config=deepseek_config,
                    fireworks_config=fireworks_config,
                )
            except Exception as e:
                self.logger.error(f"❌ Ошибка загрузки конфигурации: {e}")
                recording.status = ProcessingStatus.FAILED
                await self.db_manager.update_recording(recording)
                return False

            # Обрабатываем аудио с крутящимся индикатором
            with Progress(
                SpinnerColumn(style="cyan"),
                TextColumn("[bold cyan]Транскрибация аудио[/bold cyan]"),
                TimeElapsedColumn(),
                transient=False,
                console=self.console,
            ) as progress:
                progress.add_task("Транскрибация", total=None)

                try:
                    # Обновляем статус на TRANSCRIBING
                    recording.status = ProcessingStatus.TRANSCRIBING
                    await self.db_manager.update_recording(recording)

                    # Выполняем транскрибацию
                    result = await transcription_service.process_audio(
                        audio_path=audio_path,
                        recording_id=recording.db_id,
                        recording_topic=recording.topic,
                        provider=transcription_model,
                        granularity="short" if topic_mode == "short" else "long",
                    )

                    # Сохраняем результаты
                    recording.transcription_file_path = result['transcription_file_path']
                    recording.topic_timestamps = result.get('topic_timestamps', [])
                    recording.main_topics = result.get('main_topics', [])
                    recording.status = ProcessingStatus.TRANSCRIBED

                    # Обновляем запись в БД
                    await self.db_manager.update_recording(recording)

                    self.logger.debug(f"Статус записи {recording.topic} обновлен на TRANSCRIBED")
                    self.console.print(
                        f"[bold green]✅ Транскрибировано успешно: {recording.topic}[/bold green]"
                    )
                    if recording.main_topics:
                        self.console.print(
                            f"[bold green]📝 Основные темы: {', '.join(recording.main_topics)}[/bold green]"
                        )

                    return True

                except asyncio.CancelledError:
                    self.console.print("\n[bold red]❌ Транскрибация прервана пользователем[/bold red]")
                    recording.status = ProcessingStatus.FAILED
                    await self.db_manager.update_recording(recording)
                    return False
                except Exception as e:
                    self.logger.error(f"Ошибка транскрибации: {e}")
                    recording.status = ProcessingStatus.FAILED
                    await self.db_manager.update_recording(recording)
                    return False

        except Exception as e:
            self.logger.error(f"Ошибка транскрибации записи {recording.topic}: {e}")
            await self.db_manager.update_recording_status(
                recording.meeting_id, ProcessingStatus.FAILED
            )
            return False

    async def _upload_single_recording(
        self, recording: MeetingRecording, platforms: list[str]
    ) -> bool:
        """Загрузка одной записи на платформы с крутящимся индикатором"""
        try:
            from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

            from video_upload_module.config_factory import UploadConfigFactory
            from video_upload_module.core.manager import UploadManager

            # Создаем конфигурацию загрузки
            upload_config = UploadConfigFactory.from_app_config(self.app_config)
            upload_manager = UploadManager(upload_config)

            # Аутентификация на платформах
            auth_results = await upload_manager.authenticate_platforms(platforms)
            for platform, success in auth_results.items():
                if not success:
                    self.logger.error(f"Ошибка аутентификации на {platform}")
                    return False

            # Проверяем маппинг ОДИН РАЗ (до цикла по платформам)
            mapping_result = None
            if recording.is_mapped:
                # Получаем основную тему из транскрибации (первая из main_topics, если есть)
                main_topic = None
                if recording.main_topics and len(recording.main_topics) > 0:
                    main_topic = recording.main_topics[0]

                # Если есть маппинг, получаем его
                mapping_result = self.title_mapper.map_title(
                    original_title=recording.topic,
                    start_time=recording.start_time,
                    duration=recording.duration,
                    main_topic=main_topic,
                )

            # Если правило не найдено, запрашиваем общие метаданные один раз
            common_metadata = {}
            if not recording.is_mapped or not mapping_result or not mapping_result.matched_rule:
                self.console.print(
                    f"\n[yellow]⚠️ Правило маппинга не найдено для '{recording.topic}'[/yellow]"
                )
                self.console.print("[cyan]📤 Требуется ввод метаданных для загрузки[/cyan]")
                common_metadata = self._get_common_metadata(recording)

            # Подготавливаем метаданные для всех платформ заранее (до параллельной загрузки)
            platform_configs = {}
            upload_time_str = datetime.now().strftime('%d.%m.%Y %H:%M')
            
            for platform in platforms:
                try:
                    # Формируем топики для добавления в описание
                    topics_description = self._format_topics_description(recording.topic_timestamps, platform)

                    # Подготавливаем метаданные для конкретной платформы
                    if (
                        not recording.is_mapped
                        or not mapping_result
                        or not mapping_result.matched_rule
                    ):
                        # Используем общие метаданные + спрашиваем специфичные для платформы
                        title = common_metadata['title']
                        description = common_metadata.get('description', '')

                        thumbnail_path = common_metadata.get('thumbnail_path')
                        privacy_status = common_metadata.get('privacy_status', 'unlisted')

                        # Спрашиваем специфичные для платформы параметры
                        platform_specific = self._get_platform_specific_metadata(
                            recording, platform
                        )

                        upload_kwargs = {'privacy_status': privacy_status}

                        if thumbnail_path:
                            upload_kwargs['thumbnail_path'] = thumbnail_path

                        if platform == 'youtube' and platform_specific.get('playlist_id'):
                            upload_kwargs['playlist_id'] = platform_specific['playlist_id']
                        elif platform == 'vk' and platform_specific.get('album_id'):
                            upload_kwargs['album_id'] = platform_specific['album_id']
                    else:
                        # Используем данные из маппинга
                        title = mapping_result.title
                        description = mapping_result.description

                        thumbnail_path = mapping_result.thumbnail_path
                        playlist_id = (
                            mapping_result.youtube_playlist_id if platform == 'youtube' else None
                        )
                        album_id = mapping_result.vk_album_id if platform == 'vk' else None
                        privacy_status = 'unlisted'  # По умолчанию unlisted

                        upload_kwargs = {
                            'thumbnail_path': thumbnail_path,
                            'privacy_status': privacy_status,
                        }

                        if playlist_id:
                            upload_kwargs['playlist_id'] = playlist_id
                        if album_id:
                            upload_kwargs['album_id'] = album_id

                    # Формируем финальное описание
                    parts = []
                    if description:
                        parts.append(description)
                    if topics_description:
                        parts.append(topics_description)
                    parts.append(f"Видео выложено: {upload_time_str}")
                    parts.append("P.S. Сформировано автоматически, возможны неточности.")
                    final_description = "\n\n".join([p for p in parts if p])

                    platform_configs[platform] = {
                        'title': title,
                        'description': final_description,
                        'upload_kwargs': upload_kwargs,
                    }
                except Exception as e:
                    self.logger.error(f"Ошибка подготовки метаданных для {platform}: {e}")
                    continue

            # Теперь запускаем параллельную загрузку на все платформы
            async def upload_single_platform(platform: str, config: dict) -> tuple[str, UploadResult | None]:
                """Вспомогательная функция для загрузки на одну платформу"""
                try:
                    result = await upload_manager.upload_to_platform(
                        platform=platform,
                        video_path=recording.processed_video_path,
                        title=config['title'],
                        description=config['description'],
                        **config['upload_kwargs'],
                    )
                    return platform, result
                except Exception as e:
                    self.logger.error(f"Ошибка загрузки на {platform}: {e}")
                    return platform, None

            # Создаем задачи для параллельной загрузки
            upload_tasks = [
                upload_single_platform(platform, config)
                for platform, config in platform_configs.items()
            ]

            # Запускаем все загрузки параллельно
            results = await asyncio.gather(*upload_tasks, return_exceptions=True)

            # Обрабатываем результаты
            success_count = 0
            for result in results:
                if isinstance(result, Exception):
                    self.logger.error(f"Ошибка при параллельной загрузке: {result}")
                    continue
                
                platform, upload_result = result
                if upload_result and upload_result.status == 'uploaded':
                    success_count += 1
                    # Обновляем статус и URL записи
                    if platform == 'youtube':
                        recording.update_platform_status('youtube', PlatformStatus.UPLOADED_YOUTUBE, upload_result.video_url)
                    elif platform == 'vk':
                        recording.update_platform_status('vk', PlatformStatus.UPLOADED_VK, upload_result.video_url)

            # Обновляем основной статус записи на UPLOADED, если загружена хотя бы на одну платформу
            if success_count > 0:
                # Проверяем, загружена ли запись хотя бы на одну платформу
                is_uploaded = (
                    recording.youtube_status == PlatformStatus.UPLOADED_YOUTUBE
                    or recording.vk_status == PlatformStatus.UPLOADED_VK
                )
                if is_uploaded and recording.status != ProcessingStatus.UPLOADED:
                    recording.status = ProcessingStatus.UPLOADED
                    self.logger.debug(f"Статус записи {recording.topic} обновлен на UPLOADED")

            # Сохраняем изменения в базе данных после всех загрузок
            if success_count > 0:
                await self.db_manager.update_recording(recording)

            return success_count > 0

        except Exception as e:
            self.logger.error(f"Ошибка загрузки записи {recording.topic}: {e}")
            return False

    def _get_common_metadata(self, recording: MeetingRecording) -> dict[str, Any]:
        """Интерактивный ввод общих метаданных для всех платформ"""
        metadata = {}

        self.console.print()
        self.console.print("[bold yellow]" + "=" * 70 + "[/bold yellow]")
        self.console.print("[bold yellow]🎬 НАСТРОЙКА МЕТАДАННЫХ[/bold yellow]")
        self.console.print("[bold yellow]" + "=" * 70 + "[/bold yellow]")
        self.console.print(f"[bold white]Видео:[/bold white] {recording.topic}")
        self.console.print()

        # Название (обязательное)
        while True:
            title = input("📝 Название видео (обязательно): ").strip()
            if title:
                metadata['title'] = title
                break
            self.console.print("[red]❌ Название не может быть пустым![/red]")

        # Описание (необязательное)
        description = input("📄 Описание (необязательно, Enter для пропуска): ").strip()
        if description:
            metadata['description'] = description

        # Миниатюра (необязательное)
        thumbnail_path = input("🖼️ Путь к миниатюре (необязательно, Enter для пропуска): ").strip()
        if thumbnail_path and os.path.exists(thumbnail_path):
            metadata['thumbnail_path'] = thumbnail_path
        elif thumbnail_path:
            self.console.print(f"[yellow]⚠️ Файл миниатюры не найден: {thumbnail_path}[/yellow]")

        # Приватность (по умолчанию unlisted)
        privacy_options = ['public', 'unlisted', 'private']
        self.console.print()
        self.console.print("[dim]" + "-" * 70 + "[/dim]")
        self.console.print(f"🔒 [bold]Настройки приватности:[/bold] {', '.join(privacy_options)}")
        privacy = input("🔒 Приватность (по умолчанию: unlisted): ").strip().lower()
        if privacy in privacy_options:
            metadata['privacy_status'] = privacy
        else:
            metadata['privacy_status'] = 'unlisted'

        self.console.print()
        self.console.print("[bold green]✅ Общие метаданные настроены[/bold green]")
        return metadata

    def _get_platform_specific_metadata(
        self, recording: MeetingRecording, platform: str
    ) -> dict[str, Any]:
        """Интерактивный ввод метаданных, специфичных для платформы"""
        metadata = {}

        self.console.print()
        self.console.print("[bold cyan]" + "=" * 70 + "[/bold cyan]")
        self.console.print(f"[bold cyan]📺 НАСТРОЙКА ДЛЯ {platform.upper()}[/bold cyan]")
        self.console.print("[bold cyan]" + "=" * 70 + "[/bold cyan]")
        self.console.print()

        # Плейлист/Альбом (необязательное)
        if platform == 'youtube':
            playlist_id = input(
                "🎵 ID плейлиста YouTube (необязательно, Enter для пропуска): "
            ).strip()
            if playlist_id:
                metadata['playlist_id'] = playlist_id
        elif platform == 'vk':
            album_id = input("📁 ID альбома VK (необязательно, Enter для пропуска): ").strip()
            if album_id:
                metadata['album_id'] = album_id

        self.console.print()
        self.console.print(f"[bold green]✅ Метаданные для {platform.upper()} настроены[/bold green]")
        return metadata

    def _format_topics_description(
        self, topic_timestamps: list[dict[str, Any]] | None, platform: str
    ) -> str:
        """
        Форматирование топиков в описание для видео.

        Формат B: с разделителем
        📚 Оглавление лекции:

        00:00:00 - Введение в курс...
        00:04:21 - Концепция итераторов...

        Args:
            topic_timestamps: Список топиков с временными метками
            platform: Платформа ('youtube' или 'vk')

        Returns:
            Отформатированная строка с топиками или пустая строка
        """
        if not topic_timestamps or len(topic_timestamps) == 0:
            return ""

        # Лимиты длины описания: ~5000 символов (VK & YouTube)
        max_length = 5000

        # Формируем заголовок
        lines = ["🔹 Темы лекции:", ""]
        current_length = len('\n'.join(lines))

        # Фильтруем только элементы с непустым названием или паузы
        valid_items = [
            t for t in topic_timestamps
            if (t.get('type') == 'pause') or (t.get('topic', '').strip())
        ]
        total_valid_count = len(valid_items)

        # Добавляем все элементы (темы и паузы) в хронологическом порядке
        added_count = 0
        for item_data in valid_items:
            # Определяем, это пауза или тема
            is_pause = item_data.get('type') == 'pause'

            if is_pause:
                topic = 'Перерыв'
            else:
                topic = item_data.get('topic', '').strip()

            start = item_data.get('start', 0)

            # Форматируем время в HH:MM:SS
            hours = int(start // 3600)
            minutes = int((start % 3600) // 60)
            seconds = int(start % 60)
            time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

            # Формируем строку с длинным тире
            item_line = f"{time_str} — {topic}"

            # Проверяем, не превысим ли лимит
            new_length = current_length + len(item_line) + 1  # +1 для \n
            if new_length > max_length:
                # Если превышаем лимит, добавляем сообщение и прекращаем
                remaining_count = total_valid_count - added_count
                if remaining_count > 0:
                    lines.append(f"... и еще {remaining_count} тем")
                break

            lines.append(item_line)
            current_length = new_length
            added_count += 1

        result = '\n'.join(lines)

        # Финальная проверка длины (на всякий случай)
        if len(result) > max_length:
            # Обрезаем до лимита, стараясь не обрезать посередине строки
            result = result[:max_length]
            last_newline = result.rfind('\n')
            if last_newline > max_length * 0.9:  # Если последний перенос строки близко к концу
                result = result[:last_newline]
            result += "\n... (описание обрезано)"

        return result
