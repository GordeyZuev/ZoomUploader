"""
Менеджер пайплайна обработки видео
"""

import asyncio
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from rich.console import Console, RenderableType
from rich.progress import BarColumn, ProgressColumn
from rich.text import Text

from config.unified_config import AppConfig, load_app_config
from database import DatabaseManager
from fireworks_module import FireworksConfig
from logger import get_logger
from models import MeetingRecording, ProcessingStatus, TargetStatus, TargetType
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


class ConditionalBarColumn(ProgressColumn):
    """Колонка прогресс-бара, которая показывается только при скачивании"""

    def __init__(self, bar_width: int = 25):
        super().__init__()
        self.bar_column = BarColumn(bar_width=bar_width)

    def render(self, task) -> RenderableType:
        if task.fields.get("show_bar", False):
            return self.bar_column.render(task)
        return Text("")


class StatusSpinnerColumn(ProgressColumn):
    """Колонка для отображения спиннера или галочки в зависимости от статуса"""

    def render(self, task) -> RenderableType:
        status = task.fields.get("status", "")
        is_completed = task.completed >= task.total if task.total else False

        if is_completed and "✅" in status:
            return Text("✓", style="green")
        elif not is_completed and ("⏳" in status or "⬇️" in status or "⚙️" in status or "🎤" in status or "📤" in status):
            spinner_chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
            elapsed = task.elapsed or 0
            spinner_index = int(elapsed * 2) % len(spinner_chars)
            return Text(spinner_chars[spinner_index], style="yellow")
        return Text("")


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

    @staticmethod
    def _get_target_link(recording: MeetingRecording, target_type: TargetType) -> str | None:
        target = recording.get_target(target_type)
        if not target:
            return None
        status_val = target.status if isinstance(target.status, TargetStatus) else TargetStatus(target.status)
        if status_val == TargetStatus.UPLOADED:
            return target.get_link()
        return None

    def _has_any_uploaded(self, recording: MeetingRecording) -> bool:
        return any(
            (t.status == TargetStatus.UPLOADED or (not isinstance(t.status, TargetStatus) and t.status == TargetStatus.UPLOADED.value))
            for t in getattr(recording, "output_targets", [])
        )

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
                topic = recording.display_name.strip() if recording.display_name else "Без названия"
                self.logger.info(
                    f"⏭️ Запись '{topic}' пропущена (длительность {recording.duration} мин < 30 мин)"
                )
                continue

            size_mb = recording.video_file_size / (1024 * 1024) if recording.video_file_size else 0
            if size_mb < 40:
                filtered_count += 1
                topic = recording.display_name.strip() if recording.display_name else "Без названия"
                self.logger.info(
                    f"⏭️ Запись '{topic}' пропущена (размер {size_mb:.1f} МБ < 40 МБ)"
                )
                continue

            filtered_recordings.append(recording)

        if filtered_count > 0:
            self.logger.info(f"📊 Отфильтровано записей: {filtered_count}")

        for recording in filtered_recordings:
            self._check_and_set_mapping(recording)

        synced_count = await self.db_manager.save_recordings(filtered_recordings)
        self.logger.info(f"✅ Синхронизировано записей: {synced_count}")
        return synced_count

    async def reset_specific_recordings(self, recording_ids: list[int]) -> dict:
        """Сброс конкретных записей к статусу INITIALIZED"""
        reset_count = 0
        total_deleted_files = 0

        recordings = await self.db_manager.get_recordings_by_ids(recording_ids)
        recordings_by_id = {recording.db_id: recording for recording in recordings}

        for recording_id in recording_ids:
            try:
                recording = recordings_by_id.get(recording_id)
                if not recording:
                    self.logger.warning(f"⚠️ Запись {recording_id} не найдена")
                    continue

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

                if recording.processed_audio_dir and os.path.exists(recording.processed_audio_dir):
                    try:
                        import shutil
                        shutil.rmtree(recording.processed_audio_dir)
                        deleted_files.append(recording.processed_audio_dir)
                        self.logger.info(f"🗑️ Удалена папка аудио: {recording.processed_audio_dir}")
                    except Exception as e:
                        self.logger.warning(
                            f"⚠️ Не удалось удалить папку аудио {recording.processed_audio_dir}: {e}"
                        )

                # Удаляем папку транскрипции, если она существует
                if recording.transcription_dir and os.path.exists(recording.transcription_dir):
                    try:
                        import shutil
                        shutil.rmtree(recording.transcription_dir)
                        deleted_files.append(recording.transcription_dir)
                        self.logger.info(f"🗑️ Удалена папка транскрипции: {recording.transcription_dir}")
                    except Exception as e:
                        self.logger.warning(
                            f"⚠️ Не удалось удалить папку транскрипции {recording.transcription_dir}: {e}"
                        )

                if recording.is_mapped:
                    recording.status = ProcessingStatus.INITIALIZED
                else:
                    recording.status = ProcessingStatus.SKIPPED

                recording.local_video_path = None
                recording.processed_video_path = None
                recording.processed_audio_dir = None
                recording.downloaded_at = None

                recording.transcription_dir = None
                recording.transcription_info = None
                recording.topic_timestamps = None
                recording.main_topics = None

                recording.updated_at = datetime.now()

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

        # Помечаем записи как DOWNLOADING перед стартом и сохраняем в БД
        for recording in recordings:
            recording.status = ProcessingStatus.DOWNLOADING
            await self.db_manager.update_recording(recording)

        downloader = ZoomDownloader()
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

        # Обработка только для записей со статусом DOWNLOADED
        eligible = [r for r in recordings if r.status == ProcessingStatus.DOWNLOADED]
        skipped = len(recordings) - len(eligible)
        if skipped:
            self.logger.info(f"⏭️ Пропущено записей (не DOWNLOADED): {skipped}")
        if not eligible:
            self.logger.warning("❌ Нет записей со статусом DOWNLOADED для обработки")
            return 0

        success_count = 0
        for recording in eligible:
            recording.status = ProcessingStatus.PROCESSING
            await self.db_manager.update_recording(recording)
            if await self._process_single_recording(recording):
                success_count += 1

        self.logger.info(f"✅ Обработано записей: {success_count}/{len(eligible)}")
        return success_count

    async def transcribe_recordings(
        self,
        recordings: list[MeetingRecording],
        transcription_model: str = "fireworks",
        topic_mode: str = "long",
        topic_model: str = "deepseek",
        max_concurrent: int = 5,
    ) -> int:
        """
        Транскрибация записей (параллельно с ограничением).

        Args:
            recordings: Список записей для транскрибации
            transcription_model: Модель для транскрибации
            topic_mode: Режим извлечения тем
            topic_model: Модель для извлечения тем
            max_concurrent: Максимальное количество параллельных транскрибаций
        """
        if not recordings:
            return 0

        eligible = [r for r in recordings if r.status == ProcessingStatus.PROCESSED]
        skipped = len(recordings) - len(eligible)
        if skipped:
            self.logger.info(f"⏭️ Пропущено записей (не PROCESSED): {skipped}")
        if not eligible:
            self.logger.warning("❌ Нет записей со статусом PROCESSED для транскрибации")
            return 0

        self.logger.info(
            f"🎤 Параллельная транскрибация {len(eligible)} записей "
            f"(модель аудио: {transcription_model}, модель тем: {topic_model}, режим тем: {topic_mode}, "
            f"макс. параллельно: {max_concurrent})..."
        )

        semaphore = asyncio.Semaphore(max_concurrent)

        async def transcribe_with_limit(recording: MeetingRecording) -> bool:
            """Транскрибация с ограничением параллелизма."""
            async with semaphore:
                try:
                    return await self._transcribe_single_recording(
                        recording,
                        transcription_model=transcription_model,
                        topic_mode=topic_mode,
                        topic_model=topic_model,
                    )
                except Exception as e:
                    self.logger.error(f"❌ Ошибка транскрибации записи {recording.display_name}: {e}")
                    return False

        tasks = [transcribe_with_limit(recording) for recording in eligible]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        success_count = 0
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self.logger.error(f"❌ Ошибка транскрибации записи {recordings[i].display_name}: {result}")
            elif result:
                success_count += 1

        self.logger.info(f"✅ Транскрибировано записей: {success_count}/{len(recordings)}")
        return success_count

    async def generate_subtitles(
        self,
        recordings: list[MeetingRecording],
        formats: list[str] = None,
    ) -> int:
        """
        Генерация субтитров из транскрипций записей.

        Args:
            recordings: Список записей для генерации субтитров
            formats: Список форматов для генерации ['srt', 'vtt'] (по умолчанию оба)

        Returns:
            Количество успешно обработанных записей
        """
        if formats is None:
            formats = ['srt', 'vtt']

        if not recordings:
            return 0

        self.logger.info(
            f"📝 Генерация субтитров для {len(recordings)} записей "
            f"(форматы: {', '.join(formats)})..."
        )

        from subtitle_module import SubtitleGenerator

        generator = SubtitleGenerator()
        success_count = 0

        for recording in recordings:
            try:
                if not recording.transcription_dir:
                    self.logger.warning(
                        f"⚠️ У записи {recording.display_name} нет папки транскрипции, пропускаем"
                    )
                    continue

                if not os.path.exists(recording.transcription_dir):
                    self.logger.warning(
                        f"⚠️ Папка транскрипции не найдена: {recording.transcription_dir}"
                    )
                    continue

                # Генерируем субтитры из words.txt в папке транскрипции
                words_path = os.path.join(recording.transcription_dir, "words.txt")
                if not os.path.exists(words_path):
                    # Fallback: используем segments.txt
                    words_path = os.path.join(recording.transcription_dir, "segments.txt")
                    if not os.path.exists(words_path):
                        self.logger.warning(
                            f"⚠️ Не найден файл words.txt или segments.txt в {recording.transcription_dir}"
                        )
                        continue

                result = generator.generate_from_transcription(
                    transcription_path=words_path,
                    output_dir=recording.transcription_dir,
                    formats=formats
                )

                # Выводим информацию о созданных файлах
                for fmt, path in result.items():
                    self.logger.info(
                        f"✅ Создан файл субтитров ({fmt.upper()}): {path}"
                    )
                    if not self.console.is_terminal:
                        self.console.print(
                            f"[bold green]✅ Создан файл субтитров ({fmt.upper()}): {path}[/bold green]"
                        )

                success_count += 1

            except Exception as e:
                self.logger.error(
                    f"❌ Ошибка генерации субтитров для записи {recording.display_name}: {e}"
                )

        self.logger.info(f"✅ Субтитры сгенерированы для {success_count}/{len(recordings)} записей")
        return success_count

    async def _process_single_video_complete(
        self,
        recording: MeetingRecording,
        platforms: list[str],
        force_download: bool = False,
        no_transcription: bool = False,
        transcription_model: str = "fireworks",
        topic_mode: str = "long",
        topic_model: str = "deepseek",
        progress=None,
        task_id=None,
        recording_index: str = "?",
    ) -> dict[str, Any]:
        """
        Полная обработка одного видео от начала до конца (download -> process -> transcribe -> upload).
        Это асинхронная задача, которая может выполняться параллельно с другими видео.
        """
        result = {
            'recording': recording,
            'download_success': False,
            'process_success': False,
            'transcribe_success': False,
            'upload_success': False,
            'error': None,
        }

        def update_progress(
            stage: str,
            completed: int,
            status_icon: str = "",
            show_bar: bool = False,
            status_color: str = "white",
        ):
            """Обновление прогресса задачи"""
            if progress and task_id is not None:
                try:
                    # Получаем дату
                    try:
                        normalized_time = normalize_datetime_string(recording.start_time)
                        meeting_dt = datetime.fromisoformat(normalized_time)
                        date_str = meeting_dt.strftime("%d.%m.%y")
                    except Exception:
                        date_str = "??.??.??"

                    name = recording.display_name or ""
                    topic_short = name[:43] + "..." if len(name) > 43 else name

                    # Формируем статус с цветом
                    if status_icon:
                        status_text = f"[{status_color}]{status_icon} {stage}[/{status_color}]"
                    else:
                        status_text = f"[{status_color}]{stage}[/{status_color}]"

                    progress.update(
                        task_id,
                        completed=completed,
                        date=date_str,
                        index=str(recording_index),
                        name=topic_short,
                        status=status_text,
                        show_bar=show_bar,
                    )
                except Exception:
                    pass

        try:
            # ЭТАП 1: СКАЧИВАНИЕ
            if recording.status in [ProcessingStatus.INITIALIZED, ProcessingStatus.SKIPPED]:
                update_progress("Скачивание", 0, "⬇️", show_bar=True, status_color="yellow")
                downloader = ZoomDownloader()

                # Создаем адаптер для обновления нашего progress на основе прогресса скачивания
                # download_recording использует свой progress, но мы можем обновлять наш вручную
                # Для этого используем download_recording напрямую
                estimated_size = recording.video_file_size or (200 * 1024 * 1024)

                # Обновляем total для прогресс-бара
                if progress and task_id is not None:
                    try:
                        progress.update(task_id, total=estimated_size, completed=0)
                    except Exception:
                        pass

                # Используем download_recording с нашим progress для обновления прогресс-бара
                success = await downloader.download_recording(
                    recording, progress, task_id, force_download
                )

                if success:
                    result['download_success'] = True
                    # Обновляем прогресс до 25% после скачивания
                    if progress and task_id is not None:
                        try:
                            # Сбрасываем total обратно на 100 для следующих этапов
                            progress.update(task_id, total=100, completed=25)
                            update_progress("Скачано", 25, "✅", show_bar=False, status_color="green")
                        except Exception:
                            pass
                    await self.db_manager.update_recording(recording)
                    updated = await self.db_manager.get_recordings_by_ids([recording.db_id])
                    if updated:
                        recording = updated[0]
                else:
                    result['error'] = "Ошибка скачивания"
                    update_progress("Ошибка скачивания", 0, "❌", show_bar=False, status_color="red")
                    return result
            elif recording.status == ProcessingStatus.DOWNLOADED:
                update_progress("Уже скачано", 25, "✅", show_bar=False, status_color="green")
                updated = await self.db_manager.get_recordings_by_ids([recording.db_id])
                if updated:
                    recording = updated[0]

            # ЭТАП 2: ОБРАБОТКА
            if recording.status == ProcessingStatus.DOWNLOADED and recording.local_video_path:
                update_progress("Обработка", 30, "⚙️", show_bar=False, status_color="yellow")
                if await self._process_single_recording(recording, progress, task_id, silent=True):
                    result['process_success'] = True
                    update_progress("Обработано", 50, "✅", show_bar=False, status_color="green")
                    updated = await self.db_manager.get_recordings_by_ids([recording.db_id])
                    if updated:
                        recording = updated[0]
                else:
                    result['error'] = "Ошибка обработки"
                    update_progress("Ошибка обработки", 0, "❌", show_bar=False, status_color="red")
                    return result
            elif recording.status == ProcessingStatus.PROCESSED:
                update_progress("Уже обработано", 50, "✅", show_bar=False, status_color="green")
                updated = await self.db_manager.get_recordings_by_ids([recording.db_id])
                if updated:
                    recording = updated[0]

            # ЭТАП 3: ТРАНСКРИБАЦИЯ
            if (
                not no_transcription
                and recording.status == ProcessingStatus.PROCESSED
                and (recording.get_primary_audio_path() or recording.processed_video_path)
            ):
                update_progress("Транскрибация", 60, "🎤", show_bar=False, status_color="yellow")
                if await self._transcribe_single_recording(
                    recording,
                    transcription_model=transcription_model,
                    topic_mode=topic_mode,
                    progress=progress,
                    task_id=task_id,
                    silent=True,
                ):
                    result['transcribe_success'] = True
                    update_progress("Транскрибировано", 75, "✅", show_bar=False, status_color="green")
                    updated = await self.db_manager.get_recordings_by_ids([recording.db_id])
                    if updated:
                        recording = updated[0]
                else:
                    result['error'] = "Ошибка транскрибации"
                    update_progress("Ошибка транскрибации", 0, "❌", show_bar=False, status_color="red")
                    return result
            elif recording.status == ProcessingStatus.TRANSCRIBED:
                update_progress("Уже транскрибировано", 75, "✅", show_bar=False, status_color="green")
                updated = await self.db_manager.get_recordings_by_ids([recording.db_id])
                if updated:
                    recording = updated[0]

            # ЭТАП 4: ЗАГРУЗКА
            if (
                platforms
                and recording.status in [ProcessingStatus.PROCESSED, ProcessingStatus.TRANSCRIBED]
                and not self._has_any_uploaded(recording)
            ):
                update_progress("Загрузка", 80, "📤", show_bar=False, status_color="yellow")
                if await self._upload_single_recording(recording, platforms, progress, task_id, silent=True):
                    result['upload_success'] = True
                    update_progress("Загружено", 100, "✅", show_bar=False, status_color="green")
                    updated = await self.db_manager.get_recordings_by_ids([recording.db_id])
                    if updated:
                        recording = updated[0]
                    result['recording'] = recording
                else:
                    result['error'] = "Ошибка загрузки"
                    update_progress("Ошибка загрузки", 0, "❌", show_bar=False, status_color="red")
                    return result
            elif self._has_any_uploaded(recording):
                update_progress("Уже загружено", 100, "✅", show_bar=False, status_color="green")

        except Exception as e:
            result['error'] = str(e)
            update_progress("Ошибка", 0, "❌", show_bar=False, status_color="red")
            self.logger.error(f"❌ Ошибка обработки видео {recording.display_name}: {e}")

        return result

    async def upload_recordings(
        self,
        recordings: list[MeetingRecording],
        platforms: list[str],
        upload_captions: bool | None = None,
    ) -> tuple[int, list[MeetingRecording]]:
        """Загрузка записей на платформы (параллельно)"""
        if not recordings:
            return 0, []

        eligible = [
            r
            for r in recordings
            if r.status in (ProcessingStatus.PROCESSED, ProcessingStatus.TRANSCRIBED)
        ]
        skipped = len(recordings) - len(eligible)
        if skipped:
            self.logger.info(f"⏭️ Пропущено записей (не PROCESSED/TRANSCRIBED): {skipped}")
        if not eligible:
            self.logger.warning("❌ Нет записей со статусами PROCESSED/TRANSCRIBED для загрузки")
            return 0, []

        tasks = [
            self._upload_single_recording(recording, platforms, upload_captions=upload_captions)
            for recording in eligible
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        success_count = 0
        uploaded_recordings = []
        for recording, result in zip(eligible, results, strict=False):
            if isinstance(result, Exception):
                self.logger.error(f"❌ Ошибка загрузки записи {recording.display_name}: {result}")
            elif result:
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
            youtube_link = self._get_target_link(recording, TargetType.YOUTUBE)
            vk_link = self._get_target_link(recording, TargetType.VK)
            if youtube_link or vk_link:
                self.console.print(
                    f"\n[bold cyan]{i}.[/bold cyan] [bold white]{recording.display_name}[/bold white]"
                )

                if youtube_link:
                    self.console.print(
                        f"    [bold red]📺 YouTube:[/bold red] [link={youtube_link}]{youtube_link}[/link]"
                    )

                if vk_link:
                    self.console.print(
                        f"    [bold blue]📘 VK:[/bold blue] [link={vk_link}]{vk_link}[/link]"
                    )

    def _create_upload_config_from_app_config(self):
        """Создание конфигурации загрузки из конфигурации приложения"""
        from video_upload_module.config_factory import UploadConfigFactory

        return UploadConfigFactory.from_app_config(self.app_config)

    async def get_recordings_by_selection(
        self, select_all: bool, recordings: list[str], from_date: str, to_date: str | None = None
    ) -> list[MeetingRecording]:
        """Получение записей по выбору"""
        all_recordings = await self.get_recordings_from_db(from_date, to_date)

        if select_all:
            return all_recordings

        if recordings:
            return [r for r in all_recordings if r.display_name in recordings]

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
            topic = recording.display_name.strip() if recording.display_name else ""
            mapping_result = self.title_mapper.map_title(
                topic, recording.start_time, recording.duration
            )

            if mapping_result.title:
                recording.is_mapped = True
                recording.status = ProcessingStatus.INITIALIZED
                self.logger.debug(
                    f"✅ Маппинг найден для '{topic}' -> '{mapping_result.title}'"
                )
            else:
                recording.is_mapped = False
                recording.status = ProcessingStatus.SKIPPED
                self.logger.debug(f"⏭️ Маппинг не найден для '{topic}'")

        except Exception as e:
            recording.is_mapped = False
            recording.status = ProcessingStatus.SKIPPED
            self.logger.warning(f"   ❌ Ошибка проверки маппинга для '{recording.display_name}': {e}")

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
            topic = recording.display_name.strip() if recording.display_name else "Без названия"

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
        topic_model: str = "deepseek",
    ) -> dict:
        """Запуск полного пайплайна обработки"""
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

            try:
                recording_ids = [int(r) for r in recordings]
                for recording in all_recordings:
                    if recording.db_id in recording_ids and recording.status in allowed_statuses:
                        target_recordings.append(recording)
            except ValueError:
                # Fallback to matching by human-friendly display_name when ids are not provided
                target_recordings = [
                    r
                    for r in all_recordings
                    if r.display_name in recordings and r.status in allowed_statuses
                ]
        else:
            all_recordings = await self.get_recordings_from_db(from_date, to_date)
            target_recordings = [r for r in all_recordings if r.status in allowed_statuses]

        if not target_recordings:
            self.logger.warning("❌ Нет записей для обработки")
            return {"success": False, "message": "Нет записей для обработки"}

        self.logger.info(f"🚀 Запуск полного пайплайна для {len(target_recordings)} записей")

        pipeline_start_time = time.time()

        self.console.print()
        self.console.print("[bold blue]" + "=" * 70 + "[/bold blue]")
        self.console.print("[bold blue]🚀 ПАРАЛЛЕЛЬНАЯ ОБРАБОТКА ВИДЕО[/bold blue]")
        self.console.print("[bold blue]" + "=" * 70 + "[/bold blue]")
        self.console.print()

        # Создаем единый Progress объект для всех видео
        from rich.progress import (
            Progress,
            TextColumn,
            TimeElapsedColumn,
        )

        with Progress(
            TextColumn("[cyan]{task.fields[date]}[/cyan]"),  # Дата слева
            TextColumn("•"),
            TextColumn("[dim][{task.fields[index]}][/dim]"),  # Номер видео [1], [2], [3]
            TextColumn("[bold white]{task.fields[name]:<45}[/bold white]"),  # Название
            TextColumn("{task.fields[status]}"),  # Статус с цветом
            ConditionalBarColumn(),  # Условный прогресс-бар (только при скачивании)
            StatusSpinnerColumn(),  # Спиннер или галочка
            TimeElapsedColumn(),  # Время выполнения
            console=self.console,
            transient=False,
        ) as progress:
            # Создаем задачи для каждого видео
            task_ids = {}
            for recording in target_recordings:
                # Получаем дату
                try:
                    normalized_time = normalize_datetime_string(recording.start_time)
                    meeting_dt = datetime.fromisoformat(normalized_time)
                    date_str = meeting_dt.strftime("%d.%m.%y")
                except Exception:
                    date_str = "??.??.??"

                topic_short = recording.display_name[:43] + "..." if len(recording.display_name) > 43 else recording.display_name

                task_id = progress.add_task(
                    "",  # Пустое описание, используем fields
                    total=100,
                    completed=0,
                    date=date_str,
                    index=str(recording.db_id),  # Используем db_id вместо порядкового номера
                    name=topic_short,
                    status="[dim]⏳ Ожидание[/dim]",
                    show_bar=False,  # Флаг для показа прогресс-бара
                )
                task_ids[recording.db_id] = task_id

            # Обертка для обновления прогресса
            async def process_with_progress(recording: MeetingRecording):
                task_id = task_ids.get(recording.db_id)
                return await self._process_single_video_complete(
                    recording=recording,
                    platforms=platforms,
                    force_download=False,
                    no_transcription=no_transcription,
                    transcription_model=transcription_model,
                    topic_mode=topic_mode,
                    topic_model=topic_model,
                    progress=progress,
                    task_id=task_id,
                    recording_index=str(recording.db_id),  # Используем db_id
                )

            tasks = [
                process_with_progress(recording)
                for recording in target_recordings
            ]

            results = await asyncio.gather(*tasks, return_exceptions=True)

        download_count = 0
        process_count = 0
        transcribe_count = 0
        upload_count = 0
        uploaded_recordings = []

        for result in results:
            if isinstance(result, Exception):
                self.logger.error(f"❌ Ошибка обработки видео: {result}")
                continue

            if result.get('download_success'):
                download_count += 1
            if result.get('process_success'):
                process_count += 1
            if result.get('transcribe_success'):
                transcribe_count += 1
            if result.get('upload_success'):
                upload_count += 1
                uploaded_recordings.append(result.get('recording'))

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

            if recording.processed_audio_dir and os.path.exists(recording.processed_audio_dir):
                try:
                    import shutil
                    total_before = freed_space_mb
                    # приблизительная оценка размера директории
                    for p in Path(recording.processed_audio_dir).rglob("*"):
                        if p.is_file():
                            freed_space_mb += p.stat().st_size / (1024 * 1024)
                    shutil.rmtree(recording.processed_audio_dir)
                    file_deleted = True
                    self.logger.info(
                        f"🗑️ Удалена папка аудио: {recording.processed_audio_dir} ({freed_space_mb - total_before:.1f} МБ)"
                    )
                except Exception as e:
                    self.logger.error(
                        f"❌ Ошибка удаления папки {recording.processed_audio_dir}: {e}"
                    )

            if file_deleted:
                recording.status = ProcessingStatus.EXPIRED
                await self.db_manager.update_recording(recording)
                cleaned_count += 1
                cleaned_recordings.append(
                    {'id': recording.db_id, 'display_name': recording.display_name, 'deleted_files': []}
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

    def display_recordings(self, recordings: list[MeetingRecording], show_meta: bool = False):
        """Отображение списка записей"""
        if not recordings:
            self.console.print("\n[bold dark_red]📋 Доступных записей не найдено[/bold dark_red]")
            self.console.print(
                "[dim]💡 Критерии: длительность >30 мин, размер >40 МБ, наличие видео[/dim]"
            )
            return

        self.console.print(f"\n[bold blue]📋 Доступных записей: {len(recordings)}[/bold blue]")
        self.console.print("[dim]" + "=" * 80 + "[/dim]")

        from collections import defaultdict
        from datetime import datetime

        dates = defaultdict(list)
        for recording in recordings:
            if recording.start_time:
                try:
                    normalized_time = normalize_datetime_string(recording.start_time)
                    meeting_dt = datetime.fromisoformat(normalized_time)
                    date_key = meeting_dt.date()
                    dates[date_key].append(recording)
                except ValueError:
                    continue

        sorted_dates = sorted(dates.keys(), reverse=False)

        for date_idx, date_key in enumerate(sorted_dates):
            date_recordings = dates[date_key]

            def get_start_time_for_sort(recording):
                try:
                    normalized_time = normalize_datetime_string(recording.start_time)
                    return datetime.fromisoformat(normalized_time)
                except ValueError:
                    return datetime.min

            date_recordings.sort(key=get_start_time_for_sort)

            if date_idx > 0:
                self.console.print("")

            date_str = date_key.strftime("%d.%m.%Y")
            self.console.print(
                f"\n[bold blue]📅 ДАТА:[/bold blue] [bold white]{date_str}[/bold white]"
            )
            self.console.print(
                f"[bold blue]📊 Записей:[/bold blue] [bold white]{len(date_recordings)}[/bold white]"
            )
            self.console.print("[dim]" + "-" * 60 + "[/dim]")

            for recording in date_recordings:
                display_id = recording.db_id

                from utils import format_date, format_duration

                date_human = format_date(recording.start_time)
                dur_human = format_duration(recording.duration)
                status_text = self._format_status(recording.status)

                topic = recording.display_name.strip() if recording.display_name else "Без названия"
                title_with_link = f"[bold blue]«{topic}»[/bold blue]"
                self.console.print(f"[bold blue][{display_id}][/bold blue] {title_with_link}")
                self.console.print(
                    f"     📅 [white]{date_human}[/white] [dim]({dur_human})[/dim]"
                )
                if recording.has_video():
                    size_str = f"{recording.video_file_size / (1024 * 1024):.1f} МБ"
                    self.console.print(f"     💾 [white]{size_str}[/white]")
                else:
                    self.console.print("     [red]❌ Нет видео[/red]")
                self.console.print(f"     🔐 {recording.account or 'Unknown'}")
                self.console.print(f"     {status_text}")

                # Отображаем метаданные если запрошено и статус >= TRANSCRIBED
                if show_meta and self._should_show_meta(recording.status):
                    self.console.print()  # Отступ после статуса
                    self._display_recording_meta(recording)

                self.console.print("")

    def _should_show_meta(self, status: ProcessingStatus) -> bool:
        """Проверяет, нужно ли отображать метаданные для данного статуса"""
        transcribed_and_above = [
            ProcessingStatus.TRANSCRIBED,
            ProcessingStatus.UPLOADING,
            ProcessingStatus.UPLOADED,
        ]
        return status in transcribed_and_above

    def _display_recording_meta(self, recording: MeetingRecording):
        """Отображает метаданные записи (темы и топики)"""
        from rich.table import Table

        # Если есть детализированные топики с временными метками
        if hasattr(recording, 'topic_timestamps') and recording.topic_timestamps:
            # Показываем основную тему если есть
            if hasattr(recording, 'main_topics') and recording.main_topics:
                main_topic = recording.main_topics[0]
                self.console.print(f"     📝 [bold yellow]Тема видео: «{main_topic}»:[/bold yellow]")
            else:
                self.console.print("     📝 [bold yellow]Темы:[/bold yellow]")

            self.console.print()

            # Создаем компактную таблицу
            table = Table(
                show_header=True,
                header_style="bold magenta",
                border_style="dim",
                expand=False,
                show_lines=False,
                padding=(0, 1),
                box=None,
            )

            table.add_column("№", style="dim", width=3, justify="right")
            table.add_column("Время", style="cyan", width=17, justify="center")
            table.add_column("Мин", style="yellow", width=5, justify="right")
            table.add_column("Топик", style="white")

            for idx, ts in enumerate(recording.topic_timestamps, 1):
                start = ts.get('start', 0)
                end = ts.get('end', 0)
                topic = ts.get('topic', '')

                # Форматируем время
                start_h = int(start // 3600)
                start_m = int((start % 3600) // 60)
                start_s = int(start % 60)
                end_h = int(end // 3600)
                end_m = int((end % 3600) // 60)
                end_s = int(end % 60)

                start_str = f"{start_h:02d}:{start_m:02d}:{start_s:02d}"
                end_str = f"{end_h:02d}:{end_m:02d}:{end_s:02d}"
                duration = end - start
                duration_mins = duration / 60

                time_str = f"{start_str}→{end_str}"

                table.add_row(
                    str(idx),
                    time_str,
                    f"{duration_mins:.1f}",
                    topic
                )

            # Добавляем отступ для таблицы
            from rich.padding import Padding

            padded_table = Padding(table, (0, 0, 0, 5))
            self.console.print(padded_table)
            self.console.print()

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

                title = f"{recording.display_name[:45]}{'...' if len(recording.display_name) > 45 else recording.display_name}"
                estimated_size = recording.video_file_size or (
                    200 * 1024 * 1024
                )  # 200 МБ по умолчанию
                task_id = progress.add_task(title, total=estimated_size, date=date_str)

                # Используем download_recording с прогресс-баром
                success = await downloader.download_recording(
                    recording, progress, task_id, force_download=True
                )

            if success:
                recording.status = ProcessingStatus.DOWNLOADED
                await self.db_manager.update_recording(recording)
                self.logger.debug(f"Статус записи {recording.display_name} обновлен на DOWNLOADED")
            else:
                recording.status = ProcessingStatus.FAILED
                await self.db_manager.update_recording(recording)
                self.logger.debug(f"Статус записи {recording.display_name} обновлен на FAILED")

            return success
        except Exception as e:
            self.logger.error(f"Ошибка скачивания записи {recording.display_name}: {e}")
            await self.db_manager.update_recording(recording)
            return False

    async def _process_single_recording(
        self, recording: MeetingRecording, progress=None, task_id=None, silent: bool = False
    ) -> bool:
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

            if not silent:
                self.console.print(
                    f"[dim]📊 Видео: {duration_minutes:.1f} мин, обработка с детекцией звука[/dim]"
                )

            # Если silent=True, не создаем отдельный Progress, используем переданный
            if silent and progress and task_id is not None:
                # Используем переданный progress, просто выполняем обработку
                try:
                    process_task = asyncio.create_task(
                        processor.process_video_with_audio_detection(
                            file_path, recording.display_name, recording.start_time
                        )
                    )

                    success, processed_path = await process_task

                except asyncio.CancelledError:
                    if not silent:
                        self.console.print("\n[bold red]❌ Обработка прервана пользователем[/bold red]")
                    recording.status = ProcessingStatus.FAILED
                    await self.db_manager.update_recording(recording)
                    return False
                except Exception as e:
                    self.logger.error(f"Ошибка обработки видео: {e}")
                    recording.status = ProcessingStatus.FAILED
                    await self.db_manager.update_recording(recording)
                    return False
            else:
                # Создаем отдельный Progress для не-silent режима
                with Progress(
                    SpinnerColumn(style="yellow"),
                    TextColumn("[bold yellow]Обработка видео[/bold yellow]"),
                    TimeElapsedColumn(),
                    transient=False,
                    console=self.console,
                ) as local_progress:
                    local_progress.add_task("Обработка", total=None)

                    try:
                        process_task = asyncio.create_task(
                            processor.process_video_with_audio_detection(
                                file_path, recording.display_name, recording.start_time
                            )
                        )

                        success, processed_path = await process_task

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
                recording.status = ProcessingStatus.PROCESSED
                recording.processed_video_path = processed_path

                try:
                    safe_title = processor._sanitize_filename(recording.display_name)
                    audio_dir = "media/processed_audio"
                    os.makedirs(audio_dir, exist_ok=True)

                    date_suffix = ""
                    if recording.start_time:
                        try:
                            normalized_time = normalize_datetime_string(recording.start_time)
                            date_obj = datetime.fromisoformat(normalized_time)
                            date_suffix = f"_{date_obj.strftime('%y-%m-%d_%H-%M')}"
                        except Exception as e:
                            self.logger.warning(f"⚠️ Ошибка парсинга даты '{recording.start_time}' для имени аудио файла: {e}")

                    audio_filename = f"{safe_title}{date_suffix}_processed.mp3"
                    audio_path = os.path.join(audio_dir, audio_filename)

                    self.logger.info(f"🎵 Извлечение аудио из обработанного видео: {recording.display_name}")
                    extract_cmd = [
                        'ffmpeg',
                        '-i', processed_path,
                        '-vn',
                        '-acodec', 'libmp3lame',
                        '-ab', '64k',
                        '-ar', '16000',
                        '-ac', '1',
                        '-y',
                        audio_path,
                    ]

                    extract_process = await asyncio.create_subprocess_exec(
                        *extract_cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE
                    )
                    await extract_process.wait()

                    if extract_process.returncode == 0 and os.path.exists(audio_path):
                        recording.set_primary_audio(audio_path)
                        self.logger.info(f"✅ Аудио извлечено: {audio_path}")
                    else:
                        self.logger.warning(f"⚠️ Не удалось извлечь аудио из видео: {recording.display_name}")
                except Exception as e:
                    self.logger.warning(f"⚠️ Ошибка при извлечении аудио: {e}")

                await self.db_manager.update_recording(recording)
                self.logger.debug(f"Статус записи {recording.display_name} обновлен на PROCESSED")
                if not silent:
                    self.console.print(
                        f"[bold green]✅ Обработано успешно: {processed_path}[/bold green]"
                    )
            else:
                recording.status = ProcessingStatus.FAILED
                await self.db_manager.update_recording(recording)
                self.logger.debug(f"Статус записи {recording.display_name} обновлен на FAILED")

            return success

        except Exception as e:
            self.logger.error(f"Ошибка обработки записи {recording.display_name}: {e}")
            await self.db_manager.update_recording(recording)
            return False

    async def _transcribe_single_recording(
        self,
        recording: MeetingRecording,
        transcription_model: str = "fireworks",
        topic_mode: str = "long",
        topic_model: str = "deepseek",
        progress=None,
        task_id=None,
        silent: bool = False,
    ) -> bool:
        """Транскрибация одной записи с прогресс-баром"""
        try:
            import os

            from rich.progress import (
                Progress,
                SpinnerColumn,
                TextColumn,
                TimeElapsedColumn,
            )
            audio_path = recording.get_primary_audio_path()
            if not audio_path:
                audio_path = recording.processed_video_path
                if audio_path:
                    self.logger.info(f"Используем видео файл для транскрибации: {recording.display_name}")
                else:
                    self.logger.error(f"Аудио или видео файл не найден для записи: {recording.display_name}")
                    recording.status = ProcessingStatus.FAILED
                    await self.db_manager.update_recording(recording)
                    return False

            if not os.path.isabs(audio_path):
                audio_path = os.path.join(os.getcwd(), audio_path)

            if not os.path.exists(audio_path):
                self.logger.error(f"Файл не найден: {audio_path}")
                recording.status = ProcessingStatus.FAILED
                await self.db_manager.update_recording(recording)
                return False

            if recording.status == ProcessingStatus.TRANSCRIBED and recording.transcription_dir:
                self.logger.info(f"✅ Запись уже транскрибирована: {recording.display_name}")
                return True

            if not silent:
                self.console.print(
                    f"[dim]🎤 Транскрибация аудио: {recording.display_name}[/dim]"
                )

            try:
                from deepseek_module import DeepSeekConfig
                from transcription_module import TranscriptionService

                # Выбор конфигурации для модели топиков:
                #  - "deepseek"           -> прямой DeepSeek API
                #  - "fireworks_deepseek" -> DeepSeek v3.2 через Fireworks
                if topic_model == "fireworks_deepseek":
                    deepseek_config = DeepSeekConfig.from_file("config/deepseek_fireworks_creds.json")
                else:
                    deepseek_config = DeepSeekConfig.from_file("config/deepseek_creds.json")

                fireworks_config = FireworksConfig.from_file()
                transcription_service = TranscriptionService(
                    deepseek_config=deepseek_config,
                    fireworks_config=fireworks_config,
                )
            except Exception as e:
                self.logger.error(f"❌ Ошибка загрузки конфигурации: {e}")
                recording.status = ProcessingStatus.FAILED
                await self.db_manager.update_recording(recording)
                return False

            # Если silent=True, не создаем отдельный Progress, используем переданный
            if silent and progress and task_id is not None:
                # Используем переданный progress, просто выполняем транскрибацию
                try:
                    recording.status = ProcessingStatus.TRANSCRIBING
                    await self.db_manager.update_recording(recording)

                    result = await transcription_service.process_audio(
                        audio_path=audio_path,
                        recording_id=recording.db_id,
                        recording_topic=recording.display_name,
                        recording_start_time=recording.start_time,
                        granularity="short" if topic_mode == "short" else "long",
                    )

                    recording.transcription_dir = result['transcription_dir']
                    recording.topic_timestamps = result.get('topic_timestamps', [])
                    recording.main_topics = result.get('main_topics', [])
                    recording.transcription_info = result.get('fireworks_raw', result)
                    recording.status = ProcessingStatus.TRANSCRIBED

                    await self.db_manager.update_recording(recording)

                    self.logger.debug(f"Статус записи {recording.display_name} обновлен на TRANSCRIBED")
                    if not silent:
                        self.console.print(
                        f"[bold green]✅ Транскрибировано успешно: {recording.display_name}[/bold green]"
                        )
                        if recording.main_topics:
                            self.console.print(
                                f"[bold green]📝 Основные темы: {', '.join(recording.main_topics)}[/bold green]"
                            )

                    return True

                except asyncio.CancelledError:
                    if not silent:
                        self.console.print("\n[bold red]❌ Транскрибация прервана пользователем[/bold red]")
                    recording.status = ProcessingStatus.FAILED
                    await self.db_manager.update_recording(recording)
                    return False
                except Exception as e:
                    self.logger.error(f"Ошибка транскрибации: {e}")
                    recording.status = ProcessingStatus.FAILED
                    await self.db_manager.update_recording(recording)
                    return False
            else:
                # Создаем отдельный Progress для не-silent режима
                with Progress(
                    SpinnerColumn(style="cyan"),
                    TextColumn("[bold cyan]Транскрибация аудио[/bold cyan]"),
                    TimeElapsedColumn(),
                    transient=False,
                    console=self.console,
                ) as local_progress:
                    local_progress.add_task("Транскрибация", total=None)

                    try:
                        recording.status = ProcessingStatus.TRANSCRIBING
                        await self.db_manager.update_recording(recording)

                        result = await transcription_service.process_audio(
                            audio_path=audio_path,
                            recording_id=recording.db_id,
                            recording_topic=recording.display_name,
                            recording_start_time=recording.start_time,
                            granularity="short" if topic_mode == "short" else "long",
                        )

                        recording.transcription_dir = result['transcription_dir']
                        recording.topic_timestamps = result.get('topic_timestamps', [])
                        recording.main_topics = result.get('main_topics', [])
                        recording.transcription_info = result.get('fireworks_raw', result)
                        recording.status = ProcessingStatus.TRANSCRIBED

                        await self.db_manager.update_recording(recording)

                        self.logger.debug(f"Статус записи {recording.display_name} обновлен на TRANSCRIBED")
                        if not silent:
                            self.console.print(
                                f"[bold green]✅ Транскрибировано успешно: {recording.display_name}[/bold green]"
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
            self.logger.error(f"Ошибка транскрибации записи {recording.display_name}: {e}")
            await self.db_manager.update_recording(recording)
            return False

    async def _upload_single_recording(
        self,
        recording: MeetingRecording,
        platforms: list[str],
        progress=None,
        task_id=None,
        silent: bool = False,
        upload_captions: bool | None = None,
    ) -> bool:
        """Загрузка одной записи на платформы с крутящимся индикатором"""
        try:
            from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

            from video_upload_module.config_factory import UploadConfigFactory
            from video_upload_module.core.manager import UploadManager

            # Помечаем статус UPLOADING перед стартом
            if recording.status != ProcessingStatus.UPLOADED:
                recording.status = ProcessingStatus.UPLOADING
                await self.db_manager.update_recording(recording)

            # Показываем информацию о загружаемой записи
            name = recording.display_name or ""
            topic_short = name[:50] + "..." if len(name) > 50 else name
            if not silent:
                self.console.print(
                    f"[dim]📤 Загрузка: {topic_short}[/dim]"
                )

            upload_config = UploadConfigFactory.from_app_config(self.app_config)
            upload_manager = UploadManager(upload_config)

            auth_results = await upload_manager.authenticate_platforms(platforms)
            for platform, success in auth_results.items():
                if not success:
                    self.logger.error(f"Ошибка аутентификации на {platform}")
                    return False

            mapping_result = None
            if recording.is_mapped:
                main_topic = None
                if recording.main_topics and len(recording.main_topics) > 0:
                    main_topic = recording.main_topics[0]

                mapping_result = self.title_mapper.map_title(
                    original_title=recording.display_name,
                    start_time=recording.start_time,
                    duration=recording.duration,
                    main_topic=main_topic,
                )

            common_metadata = {}
            if not recording.is_mapped or not mapping_result or not mapping_result.matched_rule:
                if not silent:
                    self.console.print(
                        f"\n[yellow]⚠️ Правило маппинга не найдено для '{recording.display_name}'[/yellow]"
                    )
                    self.console.print("[cyan]📤 Требуется ввод метаданных для загрузки[/cyan]")
                common_metadata = self._get_common_metadata(recording)

            platform_configs = {}
            upload_time_str = datetime.now().strftime('%d.%m.%Y %H:%M')

            for platform in platforms:
                try:
                    topics_description = self._format_topics_description(recording.topic_timestamps, platform)

                    if (
                        not recording.is_mapped
                        or not mapping_result
                        or not mapping_result.matched_rule
                    ):
                        title = common_metadata['title']
                        description = common_metadata.get('description', '')
                        thumbnail_path = common_metadata.get('thumbnail_path')
                        privacy_status = common_metadata.get('privacy_status', 'unlisted')

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
                        title = mapping_result.title
                        description = mapping_result.description
                        thumbnail_path = mapping_result.thumbnail_path
                        playlist_id = (
                            mapping_result.youtube_playlist_id if platform == 'youtube' else None
                        )
                        album_id = mapping_result.vk_album_id if platform == 'vk' else None
                        privacy_status = 'unlisted'

                        upload_kwargs = {
                            'thumbnail_path': thumbnail_path,
                            'privacy_status': privacy_status,
                        }

                        if playlist_id:
                            upload_kwargs['playlist_id'] = playlist_id
                        if album_id:
                            upload_kwargs['album_id'] = album_id

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

            # Если silent=True, не создаем отдельный Progress, используем переданный
            if silent and progress and task_id is not None:
                # Используем переданный progress, просто выполняем загрузку
                async def upload_single_platform(platform: str, config: dict) -> tuple[str, UploadResult | None]:
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

                upload_tasks = [
                    upload_single_platform(platform, config)
                    for platform, config in platform_configs.items()
                ]

                results = await asyncio.gather(*upload_tasks, return_exceptions=True)
            else:
                # Создаем отдельный Progress для не-silent режима
                with Progress(
                    SpinnerColumn(style="green"),
                    TextColumn("[bold green]Загрузка на платформы[/bold green]"),
                    TextColumn("[dim]{task.description}[/dim]"),
                    TimeElapsedColumn(),
                    transient=False,
                    console=self.console,
                ) as local_progress:
                    local_progress.add_task(
                        f"Загрузка: {', '.join(platforms)}",
                        total=None
                    )

                    async def upload_single_platform(platform: str, config: dict) -> tuple[str, UploadResult | None]:
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

                    upload_tasks = [
                        upload_single_platform(platform, config)
                        for platform, config in platform_configs.items()
                    ]

                    results = await asyncio.gather(*upload_tasks, return_exceptions=True)

            success_count = 0
            for result in results:
                if isinstance(result, Exception):
                    self.logger.error(f"Ошибка при параллельной загрузке: {result}")
                    continue

                platform, upload_result = result
                if upload_result and upload_result.status == 'uploaded':
                    success_count += 1
                    # Обновляем таргет в модели
                    if platform == 'youtube':
                        target = recording.ensure_target(TargetType.YOUTUBE)
                        target.status = TargetStatus.UPLOADED
                        target_meta = upload_result.metadata or {}
                        target_meta.update(
                            {
                                "video_id": upload_result.video_id,
                                "video_url": upload_result.video_url,
                                "platform": "youtube",
                            }
                        )
                        target.target_meta = target_meta
                        target.uploaded_at = upload_result.upload_time
                    if platform == 'youtube':
                        if not silent:
                            self.console.print(f"[bold green]✅ Загружено на YouTube: {upload_result.video_url}[/bold green]")
                        # Попытка загрузки субтитров (если есть транскрипт)
                        if self._captions_enabled(upload_captions):
                            caption_path = self._get_caption_path(recording.transcription_dir, platform="youtube")
                            if caption_path:
                                caption_lang = (
                                    self.app_config.platforms.get("youtube", {}).default_language
                                    if hasattr(self.app_config.platforms.get("youtube", {}), "default_language")
                                    else "ru"
                                )
                                caption_ok = await upload_manager.upload_caption(
                                    platform="youtube",
                                    video_id=upload_result.video_id,
                                    caption_path=caption_path,
                                    language=caption_lang,
                                    name="Transcript",
                                )
                                if caption_ok and not silent:
                                    self.console.print("[bold green]📝 Субтитры загружены на YouTube[/bold green]")
                                elif not caption_ok:
                                    self.logger.warning("⚠️ Не удалось загрузить субтитры на YouTube")
                    elif platform == 'vk':
                        target = recording.ensure_target(TargetType.VK)
                        target.status = TargetStatus.UPLOADED
                        target_meta = upload_result.metadata or {}
                        target_meta.update(
                            {
                                "video_id": upload_result.video_id,
                                "video_url": upload_result.video_url,
                                "platform": "vk",
                            }
                        )
                        target.target_meta = target_meta
                        target.uploaded_at = upload_result.upload_time
                        if not silent:
                            self.console.print(f"[bold green]✅ Загружено на VK: {upload_result.video_url}[/bold green]")

            if success_count > 0 and recording.status != ProcessingStatus.UPLOADED:
                recording.status = ProcessingStatus.UPLOADED
                self.logger.debug(f"Статус записи {recording.display_name} обновлен на UPLOADED")
                await self.db_manager.update_recording(recording)

            return success_count > 0

        except Exception as e:
            self.logger.error(f"Ошибка загрузки записи {recording.display_name}: {e}")
            return False

    def _get_common_metadata(self, recording: MeetingRecording) -> dict[str, Any]:
        """Интерактивный ввод общих метаданных для всех платформ"""
        metadata = {}

        self.console.print()
        self.console.print("[bold yellow]" + "=" * 70 + "[/bold yellow]")
        self.console.print("[bold yellow]🎬 НАСТРОЙКА МЕТАДАННЫХ[/bold yellow]")
        self.console.print("[bold yellow]" + "=" * 70 + "[/bold yellow]")
        self.console.print(f"[bold white]Видео:[/bold white] {recording.display_name}")
        self.console.print()

        while True:
            title = input("📝 Название видео (обязательно): ").strip()
            if title:
                metadata['title'] = title
                break
            self.console.print("[red]❌ Название не может быть пустым![/red]")

        description = input("📄 Описание (необязательно, Enter для пропуска): ").strip()
        if description:
            metadata['description'] = description

        thumbnail_path = input("🖼️ Путь к миниатюре (необязательно, Enter для пропуска): ").strip()
        if thumbnail_path and os.path.exists(thumbnail_path):
            metadata['thumbnail_path'] = thumbnail_path
        elif thumbnail_path:
            self.console.print(f"[yellow]⚠️ Файл миниатюры не найден: {thumbnail_path}[/yellow]")

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

        max_length = 5000
        lines = ["🔹 Темы лекции:", ""]
        current_length = len('\n'.join(lines))

        valid_items = [
            t for t in topic_timestamps
            if (t.get('type') == 'pause') or (t.get('topic', '').strip())
        ]
        total_valid_count = len(valid_items)

        added_count = 0
        for item_data in valid_items:
            is_pause = item_data.get('type') == 'pause'

            if is_pause:
                topic = 'Перерыв'
            else:
                topic = item_data.get('topic', '').strip()

            start = item_data.get('start', 0)
            hours = int(start // 3600)
            minutes = int((start % 3600) // 60)
            seconds = int(start % 60)
            time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

            item_line = f"{time_str} — {topic}"

            new_length = current_length + len(item_line) + 1
            if new_length > max_length:
                remaining_count = total_valid_count - added_count
                if remaining_count > 0:
                    lines.append(f"... и еще {remaining_count} тем")
                break

            lines.append(item_line)
            current_length = new_length
            added_count += 1

        result = '\n'.join(lines)

        if len(result) > max_length:
            result = result[:max_length]
            last_newline = result.rfind('\n')
            if last_newline > max_length * 0.9:
                result = result[:last_newline]
            result += "\n... (описание обрезано)"

        return result

    def _get_caption_path(self, transcription_dir: str | None, platform: str = "youtube") -> str | None:
        """Возвращает путь к файлу субтитров в папке транскрипции.

        YouTube: vtt > srt
        VK: только srt
        """
        if not transcription_dir:
            return None
        vtt_path = Path(transcription_dir) / "subtitles.vtt"
        srt_path = Path(transcription_dir) / "subtitles.srt"

        if platform.lower() == "vk":
            return str(srt_path) if srt_path.exists() else None

        # default youtube logic
        if vtt_path.exists():
            return str(vtt_path)
        if srt_path.exists():
            return str(srt_path)
        return None

    def _captions_enabled(self, override: bool | None = None) -> bool:
        """Флаг загрузки субтитров из app_config (upload_captions=True по умолчанию)."""
        if override is not None:
            return override
        return getattr(self.app_config, "upload_captions", True)
