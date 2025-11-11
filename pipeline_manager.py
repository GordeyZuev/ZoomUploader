"""
Менеджер пайплайна обработки видео
"""

import asyncio
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from config.unified_config import AppConfig, load_app_config
from database import DatabaseManager
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

    async def transcribe_recordings(self, recordings: list[MeetingRecording]) -> int:
        """Транскрибация записей (параллельно)"""
        if not recordings:
            return 0

        self.logger.info(f"🎤 Параллельная транскрибация {len(recordings)} записей...")

        # Запускаем все транскрибации параллельно
        tasks = [self._transcribe_single_recording(recording) for recording in recordings]
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

            if mapping_result.youtube_title:
                # Есть маппинг - устанавливаем статус INITIALIZED
                recording.is_mapped = True
                recording.status = ProcessingStatus.INITIALIZED
                self.logger.debug(
                    f"✅ Маппинг найден для '{topic}' -> '{mapping_result.youtube_title}'"
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
    ) -> dict:
        """Запуск полного пайплайна обработки"""
        allowed_statuses = [ProcessingStatus.INITIALIZED]
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

        download_count = await self.download_recordings(target_recordings)

        # Проверяем, есть ли записи для обработки (скачанные или уже имеющиеся)
        recordings_to_process = [r for r in target_recordings if r.status == ProcessingStatus.DOWNLOADED]
        if not recordings_to_process:
            return {
                "success": False,
                "message": "Нет записей для обработки (ничего не скачано)",
                "download_count": download_count,
                "process_count": 0,
                "upload_count": 0
            }

        process_count = await self.process_recordings(recordings_to_process)

        # Проверяем, есть ли записи для транскрибации (обработанные с аудио)
        transcribe_count = 0
        if not no_transcription:
            recordings_to_transcribe = [
            r for r in target_recordings
            if r.status == ProcessingStatus.PROCESSED and r.processed_audio_path
        ]
        if recordings_to_transcribe:
            transcribe_count = await self.transcribe_recordings(recordings_to_transcribe)

        # Проверяем, есть ли записи для загрузки (обработанные, можно транскрибированные)
        recordings_to_upload = [
            r for r in target_recordings
            if r.status in [ProcessingStatus.PROCESSED, ProcessingStatus.TRANSCRIBED]
        ]
        upload_count = 0
        uploaded_recordings = []
        if recordings_to_upload and platforms:
            upload_count, uploaded_recordings = await self.upload_recordings(recordings_to_upload, platforms)

        return {
            "success": True,
            "download_count": download_count,
            "process_count": process_count,
            "transcribe_count": transcribe_count,
            "upload_count": upload_count,
            "uploaded_recordings": uploaded_recordings,
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
                    success, processed_path, processed_audio_path = await process_task

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

    async def _transcribe_single_recording(self, recording: MeetingRecording) -> bool:
        """Транскрибация одной записи с прогресс-баром"""
        try:
            from rich.progress import (
                Progress,
                SpinnerColumn,
                TextColumn,
                TimeElapsedColumn,
            )

            # Проверяем наличие аудио файла
            audio_path = recording.processed_audio_path
            if not audio_path:
                self.logger.error(f"Аудио файл не найден для записи: {recording.topic}")
                recording.status = ProcessingStatus.FAILED
                await self.db_manager.update_recording(recording)
                return False

            # Если путь начинается с '/', это абсолютный путь, иначе - относительный
            import os
            if not os.path.isabs(audio_path):
                audio_path = os.path.join(os.getcwd(), audio_path)

            if not os.path.exists(audio_path):
                self.logger.error(f"Аудио файл не найден: {audio_path}")
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

                openai_config = OpenAIConfig.from_file()
                deepseek_config = DeepSeekConfig.from_file()
                transcription_service = TranscriptionService(
                    openai_config=openai_config,
                    deepseek_config=deepseek_config
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

            # Загружаем на каждую платформу с крутящимся индикатором
            success_count = 0
            for platform in platforms:
                try:
                    # Подготавливаем метаданные для конкретной платформы
                    if (
                        not recording.is_mapped
                        or not mapping_result
                        or not mapping_result.matched_rule
                    ):
                        # Используем общие метаданные + спрашиваем специфичные для платформы
                        title = common_metadata['title']
                        description = common_metadata.get('description', '')

                        # Добавляем топики в описание, если они есть
                        topics_description = self._format_topics_description(recording.topic_timestamps, platform)
                        if topics_description:
                            if description:
                                description = f"{description}\n\n{topics_description}"
                            else:
                                description = topics_description

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
                        title = mapping_result.youtube_title
                        description = mapping_result.description

                        # Добавляем топики в описание, если они есть
                        topics_description = self._format_topics_description(recording.topic_timestamps, platform)
                        if topics_description:
                            if description:
                                description = f"{description}\n\n{topics_description}"
                            else:
                                description = topics_description

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

                    # Теперь запускаем загрузку со спиннером
                    with Progress(
                        SpinnerColumn(style="green"),
                        TextColumn(f"[bold green]Загрузка на {platform.upper()}[/bold green]"),
                        TimeElapsedColumn(),
                        transient=False,
                        console=self.console,
                    ) as progress:
                        progress.add_task("Загрузка", total=None)

                        result = await upload_manager.upload_to_platform(
                            platform=platform,
                            video_path=recording.processed_video_path,
                            title=title,
                            description=description,
                            **upload_kwargs,
                        )
                        if result and result.status == 'uploaded':
                            success_count += 1
                            # Обновляем статус и URL записи
                            if platform == 'youtube':
                                recording.update_platform_status('youtube', PlatformStatus.UPLOADED_YOUTUBE, result.video_url)
                            elif platform == 'vk':
                                recording.update_platform_status('vk', PlatformStatus.UPLOADED_VK, result.video_url)

                            # Сохраняем изменения в базе данных
                            await self.db_manager.update_recording(recording)

                except asyncio.CancelledError:
                    self.console.print(
                        f"\n[bold red]❌ Загрузка на {platform} прервана пользователем[/bold red]"
                    )
                    break
                except Exception as e:
                    self.logger.error(f"Ошибка загрузки на {platform}: {e}")

            return success_count > 0

        except Exception as e:
            self.logger.error(f"Ошибка загрузки записи {recording.topic}: {e}")
            return False

    def _get_common_metadata(self, recording: MeetingRecording) -> dict[str, Any]:
        """Интерактивный ввод общих метаданных для всех платформ"""
        metadata = {}

        print(f"\n🎬 Настройка метаданных для видео: {recording.topic}")
        print("=" * 60)

        # Название (обязательное)
        while True:
            title = input("📝 Название видео (обязательно): ").strip()
            if title:
                metadata['title'] = title
                break
            print("❌ Название не может быть пустым!")

        # Описание (необязательное)
        description = input("📄 Описание (необязательно, Enter для пропуска): ").strip()
        if description:
            metadata['description'] = description

        # Миниатюра (необязательное)
        thumbnail_path = input("🖼️ Путь к миниатюре (необязательно, Enter для пропуска): ").strip()
        if thumbnail_path and os.path.exists(thumbnail_path):
            metadata['thumbnail_path'] = thumbnail_path
        elif thumbnail_path:
            print(f"⚠️ Файл миниатюры не найден: {thumbnail_path}")

        # Приватность (по умолчанию unlisted)
        privacy_options = ['public', 'unlisted', 'private']
        print(f"\n🔒 Настройки приватности: {', '.join(privacy_options)}")
        privacy = input("🔒 Приватность (по умолчанию: unlisted): ").strip().lower()
        if privacy in privacy_options:
            metadata['privacy_status'] = privacy
        else:
            metadata['privacy_status'] = 'unlisted'

        print("✅ Общие метаданные настроены")
        return metadata

    def _get_platform_specific_metadata(
        self, recording: MeetingRecording, platform: str
    ) -> dict[str, Any]:
        """Интерактивный ввод метаданных, специфичных для платформы"""
        metadata = {}

        print(f"\n📺 Настройка для платформы: {platform.upper()}")
        print("=" * 60)

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

        print(f"✅ Метаданные для {platform.upper()} настроены")
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

        # Лимиты длины описания
        # YouTube: ~5000 символов
        # VK: ~2000 символов (примерно)
        max_length = 5000 if platform == 'youtube' else 2000

        # Формируем заголовок
        lines = ["📚 Оглавление лекции:", ""]
        current_length = len('\n'.join(lines))

        # Фильтруем только топики с непустым названием
        valid_topics = [t for t in topic_timestamps if t.get('topic', '').strip()]
        total_valid_count = len(valid_topics)

        # Добавляем топики
        added_count = 0
        for topic_data in valid_topics:
            topic = topic_data.get('topic', '').strip()
            start = topic_data.get('start', 0)

            # Форматируем время в HH:MM:SS
            hours = int(start // 3600)
            minutes = int((start % 3600) // 60)
            seconds = int(start % 60)
            time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

            # Формируем строку топика
            topic_line = f"{time_str} - {topic}"

            # Проверяем, не превысим ли лимит
            new_length = current_length + len(topic_line) + 1  # +1 для \n
            if new_length > max_length:
                # Если превышаем лимит, добавляем сообщение и прекращаем
                remaining_count = total_valid_count - added_count
                if remaining_count > 0:
                    lines.append(f"... и еще {remaining_count} тем")
                break

            lines.append(topic_line)
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
