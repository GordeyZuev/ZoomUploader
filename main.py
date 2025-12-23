import asyncio
import builtins
import math
import os
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import click

from config import get_config_by_account, load_config_from_file
from config.settings import settings
from config.unified_config import load_app_config
from database import DatabaseConfig, DatabaseManager
from logger import get_logger, setup_logger
from models import MeetingRecording, ProcessingStatus, SourceType
from pipeline_manager import PipelineManager
from utils import (
    export_recordings_summary,
    filter_recordings_by_duration,
    save_recordings_to_csv,
    save_recordings_to_json,
)
from video_processing_module.video_processor import ProcessingConfig, VideoProcessor


def parse_date(date_str: str) -> str:
    """
    Парсит дату в различных форматах и возвращает в формате YYYY-MM-DD

    Поддерживаемые форматы:
    - YYYY-MM-DD (стандартный)
    - DD-MM-YYYY (европейский)
    - DD/MM/YYYY (с слэшами)
    - DD-MM-YY (короткий год)
    - DD/MM/YY (короткий год)
    """
    if not date_str:
        return date_str

    date_str = date_str.strip()

    formats = [
        '%Y-%m-%d',  # YYYY-MM-DD
        '%d-%m-%Y',  # DD-MM-YYYY
        '%d/%m/%Y',  # DD/MM/YYYY
        '%d-%m-%y',  # DD-MM-YY
        '%d/%m/%y',  # DD/MM/YY
    ]

    for fmt in formats:
        try:
            parsed_date = datetime.strptime(date_str, fmt)
            return parsed_date.strftime('%Y-%m-%d')
        except ValueError:
            continue

    return date_str


def common_options(f):
    """Общие опции для всех команд"""
    f = click.option(
        '--from',
        'from_date',
        type=str,
        help='Дата начала (YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY, DD-MM-YY, DD/MM/YY)',
    )(f)
    f = click.option(
        '--to',
        'to_date',
        type=str,
        help='Дата окончания (YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY, DD-MM-YY, DD/MM/YY)',
    )(f)
    f = click.option('--account', type=str, help='Email аккаунта Zoom')(f)
    f = click.option(
        '--config-file', type=str, default='config/zoom_creds.json', help='Файл конфигурации'
    )(f)
    f = click.option('--use-db/--no-db', default=True, help='Использовать базу данных')(f)
    return f


def selection_options(f):
    """Опции для выбора записей"""
    f = click.option('-a', '--all', 'select_all', is_flag=True, help='Выбрать все записи')(f)
    f = click.option(
        '-recs',
        '--recordings',
        type=str,
        help='ID записей для обработки через запятую (например: 1,4,7)',
    )(f)
    return f


def platform_options(f):
    """Опции для выбора платформ"""
    f = click.option('--youtube', is_flag=True, help='Загрузить на YouTube')(f)
    f = click.option('--vk', is_flag=True, help='Загрузить на VK')(f)
    f = click.option('--all-platforms', is_flag=True, help='Загрузить на все платформы')(f)
    return f


def force_options(f):
    """Опции для принудительного выполнения"""
    f = click.option('-f', '--force', is_flag=True, help='Принудительно выполнить операцию')(f)
    return f


@click.group()
def cli():
    """Zoom Manager - управление записями Zoom встреч"""
    pass


async def _add_video_command(source_path: str, display_name: str | None, set_expire: int | None):
    """Создание записи из локального файла."""
    logger = get_logger()
    source_file = Path(source_path).expanduser().resolve()

    if not source_file.exists():
        logger.error(f"❌ Файл не найден: {source_file}")
        return

    # Настройки и инициализация БД
    db_config = DatabaseConfig()
    db_manager = DatabaseManager(db_config)
    await db_manager.create_tables()

    # Куда копируем
    dest_dir = Path(settings.processing.input_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / source_file.name

    try:
        shutil.copy2(source_file, dest_path)
        logger.info(f"📥 Файл скопирован в {dest_path}")
    except Exception as e:
        logger.error(f"❌ Не удалось скопировать файл: {e}")
        return

    # Получаем длительность через ffprobe (VideoProcessor)
    duration_minutes = 0
    try:
        processor = VideoProcessor(ProcessingConfig())
        info = await processor.get_video_info(str(dest_path))
        duration_sec = float(info.get("duration", 0))
        duration_minutes = int(math.ceil(duration_sec / 60)) if duration_sec > 0 else 0
        logger.info(f"⏱️  Длительность файла: {duration_minutes} мин")
    except Exception as e:
        logger.warning(f"⚠️ Не удалось определить длительность: {e}")

    # Данные записи
    now_utc = datetime.now(UTC).replace(microsecond=0)
    start_time_iso = now_utc.isoformat().replace("+00:00", "Z")
    display = display_name or source_file.stem

    expire_at = None
    if set_expire and set_expire > 0:
        expire_at = now_utc + timedelta(days=set_expire)

    meeting_data = {
        "display_name": display,
        "start_time": start_time_iso,
        "duration": duration_minutes,
        "status": ProcessingStatus.DOWNLOADED,
        "is_mapped": False,
        "expire_at": expire_at,
        "source_type": SourceType.LOCAL_FILE,
        "source_key": str(source_file),
        "source_metadata": {
            "file_path": str(source_file),
            "copied_path": str(dest_path),
            "added_at": start_time_iso,
        },
        "local_video_path": str(dest_path),
        "processed_video_path": None,
        "processed_audio_dir": None,
        "transcription_dir": None,
        "topic_timestamps": None,
        "main_topics": None,
        "transcription_info": None,
    }

    recording = MeetingRecording(meeting_data)
    try:
        await db_manager.save_recordings([recording])
        logger.info(f"✅ Запись добавлена: {display} (id={recording.db_id})")
    except Exception as e:
        logger.error(f"❌ Ошибка сохранения записи: {e}")
    finally:
        await db_manager.close()


@cli.command()
@common_options
@click.option(
    '--last',
    type=int,
    help='Последние N дней (0 = сегодня, 1 = вчера, 7 = неделя, 14 = две недели). Если не указан и нет --from/--to, показывает все записи',
)
@click.option(
    '-recs',
    '--recordings',
    type=str,
    help='ID записей для показа через запятую (например: 1,4,7) или одна запись (например: 42)',
)
@click.option('--export', type=click.Choice(['json', 'csv', 'summary']), help='Экспорт результатов')
@click.option('--output', type=str, help='Имя выходного файла')
@click.option('--show-meta', is_flag=True, help='Показать темы и топики для записей со статусом TRANSCRIBED и выше')
def list(from_date, to_date, last, recordings, account, config_file, use_db, export, output, show_meta):
    """Показать записи из базы данных"""
    asyncio.run(
        _list_command(
            from_date, to_date, last, recordings, account, config_file, use_db, export, output, show_meta
        )
    )


@cli.command()
@common_options
@click.option(
    '--last',
    type=int,
    default=14,
    help='Последние N дней (0 = сегодня, 1 = вчера, 7 = неделя, 14 = две недели)',
)
def sync(from_date, to_date, last, account, config_file, use_db):
    """Синхронизировать данные из Zoom в базу данных"""
    asyncio.run(_sync_command(from_date, to_date, last, account, config_file, use_db))


@cli.command()
@click.option(
    '--source',
    'source_path',
    required=True,
    type=str,
    help='Путь к локальному видеофайлу',
)
@click.option('--name', 'display_name', type=str, help='Отображаемое имя (по умолчанию имя файла)')
@click.option('--set-expire', type=int, help='Дней до истечения записи (status -> EXPIRED после очистки)')
def add_video(source_path: str, display_name: str | None, set_expire: int | None):
    """Добавить локальное видео как запись в БД."""
    asyncio.run(_add_video_command(source_path, display_name, set_expire))


@cli.command()
@common_options
@selection_options
@force_options
@click.option(
    '--last',
    type=int,
    default=14,
    help='Последние N дней (0 = сегодня, 1 = вчера, 7 = неделя, 14 = две недели)',
)
@click.option(
    '--allow-skipped', is_flag=True, help='Разрешить загрузку записей со статусом SKIPPED'
)
def download(
    from_date,
    to_date,
    last,
    account,
    config_file,
    use_db,
    select_all,
    recordings,
    force,
    allow_skipped,
):
    """Скачать записи"""
    asyncio.run(
        _download_command(
            from_date,
            to_date,
            last,
            account,
            config_file,
            use_db,
            select_all,
            recordings,
            force,
            allow_skipped,
        )
    )


@cli.command()
@common_options
@selection_options
@click.option(
    '--last',
    type=int,
    default=14,
    help='Последние N дней (0 = сегодня, 1 = вчера, 7 = неделя, 14 = две недели)',
)
def process(
    from_date, to_date, last, account, config_file, use_db, select_all, recordings):
    """Обработать записи"""
    asyncio.run(
        _process_command(
            from_date, to_date, last, account, config_file, use_db, select_all, recordings        )
    )


@cli.command()
@common_options
@selection_options
@click.option(
    '--last',
    type=int,
    default=14,
    help='Последние N дней (0 = сегодня, 1 = вчера, 7 = неделя, 14 = две недели)',
)
@click.option(
    '--topic-model',
    type=click.Choice(['deepseek', 'fireworks_deepseek']),
    default='deepseek',
    show_default=True,
    help='Модель для извлечения тем: deepseek (по умолчанию) или fireworks_deepseek',
)
@click.option(
    '--topic-mode',
    type=click.Choice(['short', 'long']),
    default='long',
    show_default=True,
    help='Режим извлечения тем: short (меньше тем, крупнее) или long (больше тем, детальнее)',
)
def transcribe(
    from_date,
    to_date,
    last,
    account,
    config_file,
    use_db,
    select_all,
    recordings,
    topic_model,
    topic_mode,
):
    """Транскрибировать записи"""
    asyncio.run(
        _transcribe_command(
            from_date,
            to_date,
            last,
            account,
            config_file,
            use_db,
            select_all,
            recordings,
            topic_model,
            topic_mode,
        )
    )


@cli.command()
@common_options
@selection_options
@click.option(
    '--last',
    type=int,
    default=14,
    help='Последние N дней (0 = сегодня, 1 = вчера, 7 = неделя, 14 = две недели)',
)
@click.option(
    '--format',
    'formats',
    type=str,
    default='srt,vtt',
    help='Форматы субтитров для генерации через запятую (srt, vtt). По умолчанию: srt,vtt',
)
def subtitles(
    from_date,
    to_date,
    last,
    account,
    config_file,
    use_db,
    select_all,
    recordings,
    formats,
):
    """Генерировать субтитры из транскрипций"""
    # Парсим форматы из строки
    valid_formats = {'srt', 'vtt'}
    if formats:
        formats_list = [f.strip().lower() for f in formats.split(',') if f.strip()]
        invalid_formats = [f for f in formats_list if f not in valid_formats]
        if invalid_formats:
            raise click.BadParameter(
                f"Недопустимые форматы: {', '.join(invalid_formats)}. Допустимые: {', '.join(valid_formats)}"
            )
        if not formats_list:
            formats_list = ['srt', 'vtt']
    else:
        formats_list = ['srt', 'vtt']

    asyncio.run(
        _subtitles_command(
            from_date,
            to_date,
            last,
            account,
            config_file,
            use_db,
            select_all,
            recordings,
            formats_list,
        )
    )


@cli.command()
@common_options
@selection_options
@platform_options
@click.option(
    '--last',
    type=int,
    default=14,
    help='Последние N дней (0 = сегодня, 1 = вчера, 7 = неделя, 14 = две недели)',
)
@click.option(
    '--upload-captions/--no-upload-captions',
    default=None,
    help='Загружать субтитры на поддерживаемые платформы (YouTube). По умолчанию берётся из app_config.upload_captions',
)
def upload(
    from_date,
    to_date,
    last,
    account,
    config_file,
    use_db,
    select_all,
    recordings,
    youtube,
    vk,
    all_platforms,
    upload_captions,
):
    """Загрузить записи на платформы"""
    asyncio.run(
        _upload_command(
            from_date,
            to_date,
            last,
            account,
            config_file,
            use_db,
            select_all,
            recordings,
            youtube,
            vk,
            all_platforms,
            upload_captions,
        )
    )


@cli.command()
@common_options
@selection_options
@platform_options
@click.option(
    '--last',
    type=int,
    default=14,
    help='Последние N дней (0 = сегодня, 1 = вчера, 7 = неделя, 14 = две недели)',
)
@click.option(
    '--allow-skipped',
    is_flag=True,
    help='Разрешить обработку записей со статусом SKIPPED (с интерактивным вводом метаданных)',
)
@click.option(
    '--no-transcription',
    is_flag=True,
    help='Пропустить шаг транскрибации (не вызывать транскрибацию и извлечение тем)',
)
@click.option(
    '--topic-model',
    type=click.Choice(['deepseek', 'fireworks_deepseek']),
    default='deepseek',
    show_default=True,
    help='Модель для извлечения тем: deepseek (по умолчанию) или fireworks_deepseek',
)
@click.option(
    '--topic-mode',
    type=click.Choice(['short', 'long']),
    default='long',
    show_default=True,
    help='Режим извлечения тем: short (меньше тем, крупнее) или long (больше тем, детальнее)',
)
def full_process(
    from_date,
    to_date,
    last,
    account,
    config_file,
    use_db,
    select_all,
    recordings,
    youtube,
    vk,
    all_platforms,
    allow_skipped,
    no_transcription,
    topic_model,
    topic_mode,
):
    """Полный пайплайн: скачать + обработать + загрузить записи"""
    asyncio.run(
        _full_process_command(
            from_date,
            to_date,
            last,
            account,
            config_file,
            use_db,
            select_all,
            recordings,
            youtube,
            vk,
            all_platforms,
            allow_skipped,
            no_transcription,
            topic_model,
            topic_mode,
        )
    )


@cli.command()
@common_options
@selection_options
@click.option(
    '--last',
    type=int,
    default=0,
    help='Последние N дней (0 = сегодня, 1 = вчера, 7 = неделя, 14 = две недели)',
)
@click.option('--full', is_flag=True, help='Полная очистка базы данных и удаление всех видео')
def reset(
    from_date, to_date, last, account, config_file, use_db, select_all, recordings, full):
    """Сбросить статусы записей (кроме загруженных)"""
    asyncio.run(
        _reset_command(
            from_date,
            to_date,
            last,
            account,
            config_file,
            use_db,
            select_all,
            recordings,
            full,
        )
    )


@cli.command()
@click.option('--use-db/--no-db', default=True, help='Использовать базу данных')
@click.option(
    '--days',
    type=int,
    default=7,
    help='Количество дней назад для очистки записей (по умолчанию: 7)',
)
def clean(use_db, days):
    """Очистить старые записи (удалить файлы и пометить как EXPIRED)"""
    asyncio.run(_clean_command(use_db, days))


@cli.command()
@click.option('--force', is_flag=True, help='Пропустить подтверждение (использовать с осторожностью)')
def recreate_db(force):
    """Полностью пересоздать базу данных (удалить и создать заново)"""
    asyncio.run(_recreate_db_command(force))


def main():
    """Точка входа в приложение"""
    cli()


def _parse_dates(from_date, to_date, last):
    """Парсинг дат для команд"""
    if from_date:
        # Если указана конкретная дата, парсим её
        from_date = parse_date(from_date)
        if to_date:
            to_date = parse_date(to_date)
    elif last is not None:
        # Используем --last, если указан
        if last == 0:
            # Сегодня
            from_date = datetime.now().strftime('%Y-%m-%d')
            to_date = datetime.now().strftime('%Y-%m-%d')
        else:
            # Последние N дней
            to_date = datetime.now().strftime('%Y-%m-%d')
            from_date = (datetime.now() - timedelta(days=last)).strftime('%Y-%m-%d')
    else:
        # Если ничего не указано, возвращаем None (будет означать все записи)
        from_date = None
        to_date = None

    return from_date, to_date


async def _setup_pipeline(use_db: bool) -> tuple[PipelineManager | None, DatabaseManager | None]:
    """
    Инициализация базы данных и pipeline.

    Args:
        use_db: Использовать ли базу данных

    Returns:
        tuple: (pipeline, db_manager)
    """
    db_manager = None
    if use_db:
        db_config = DatabaseConfig.from_env()
        db_manager = DatabaseManager(db_config)
        await db_manager.create_database_if_not_exists()
        await db_manager.create_tables()
        print("🗄️ \033[1;34mПодключение к базе данных...\033[0m")

    app_config = load_app_config()
    pipeline = PipelineManager(db_manager, app_config)

    return pipeline, db_manager


async def _get_target_recordings(
    pipeline: PipelineManager,
    from_date: str,
    to_date: str | None,
    select_all: bool,
    recordings: str | None,
    allowed_statuses: builtins.list[ProcessingStatus],
    min_duration: int = 0,
    min_size_mb: int = 0,
    require_file_path: str | None = None,
    filter_by_duration: bool = False,
) -> builtins.list:
    """
    Универсальная функция для получения целевых записей.

    Args:
        pipeline: Экземпляр PipelineManager
        from_date: Дата начала
        to_date: Дата окончания
        select_all: Выбрать все записи
        recordings: Строка с ID записей через запятую
        allowed_statuses: Список разрешенных статусов
        min_duration: Минимальная длительность в минутах
        min_size_mb: Минимальный размер в МБ
        require_file_path: Требуемый путь к файлу ('local_video_path', 'processed_audio_dir', 'processed_video_path')
        filter_by_duration: Фильтровать ли по длительности

    Returns:
        list: Список целевых записей
    """
    if recordings:
        # Если указаны конкретные записи, ищем их напрямую в БД
        recordings_list = recordings.split(',')
        try:
            # Пытаемся интерпретировать как ID записей
            recording_ids = [int(r.strip()) for r in recordings_list]
            found_recordings = await pipeline.db_manager.get_recordings_by_ids(recording_ids)
            target_recordings = []

            for recording in found_recordings:
                # Проверяем статус
                if recording.status not in allowed_statuses:
                    continue

                # Проверяем длительность и размер, если указано
                if filter_by_duration and recording.duration < min_duration:
                    continue
                if min_size_mb > 0 and recording.video_file_size < min_size_mb * 1024 * 1024:
                    continue

                # Проверяем наличие файла, если требуется
                if require_file_path:
                    file_path = getattr(recording, require_file_path, None)
                    if not file_path:
                        continue

                target_recordings.append(recording)

        except ValueError:
            # Если не числа, ищем по именам в базе данных
            all_recordings = await pipeline.get_recordings_from_db(from_date, to_date)
            if filter_by_duration:
                all_recordings = filter_recordings_by_duration(all_recordings, min_duration)

            target_recordings = [
                r
                for r in all_recordings
                if (r.display_name in recordings_list)
                and r.status in allowed_statuses
                and (not require_file_path or getattr(r, require_file_path, None))
            ]
    elif select_all:
        # Выбираем все записи за период
        all_recordings = await pipeline.get_recordings_from_db(from_date, to_date)
        if filter_by_duration:
            all_recordings = filter_recordings_by_duration(all_recordings, min_duration)

        target_recordings = [
            r
            for r in all_recordings
            if r.status in allowed_statuses
            and (not require_file_path or getattr(r, require_file_path, None))
            and (min_size_mb == 0 or r.video_file_size >= min_size_mb * 1024 * 1024)
        ]
    else:
        # По умолчанию берем все записи за период
        all_recordings = await pipeline.get_recordings_from_db(from_date, to_date)
        if filter_by_duration:
            all_recordings = filter_recordings_by_duration(all_recordings, min_duration)

        target_recordings = [
            r
            for r in all_recordings
            if r.status in allowed_statuses
            and (not require_file_path or getattr(r, require_file_path, None))
            and (min_size_mb == 0 or r.video_file_size >= min_size_mb * 1024 * 1024)
        ]

    return target_recordings


async def _list_command(
    from_date, to_date, last, recordings, account, config_file, use_db, export, output, show_meta):
    """Команда list - показать записи из БД"""

    setup_logger()
    logger = get_logger()

    try:
        # Инициализация БД и pipeline
        pipeline, db_manager = await _setup_pipeline(use_db)

        # Получаем записи из БД
        if recordings:
            # Фильтрация по конкретным ID
            try:
                recording_ids = [int(r.strip()) for r in recordings.split(',')]
                recordings_list = await pipeline.db_manager.get_recordings_by_ids(recording_ids)

                if not recordings_list:
                    print(f"📋 Записи с ID {recordings} не найдены в базе данных")
                    return

            except ValueError:
                logger.error("❌ Ошибка: ID записей должны быть числами")
                return
        else:
            # Парсим даты
            from_date, to_date = _parse_dates(from_date, to_date, last)

            if from_date is None:
                # Если даты не указаны, получаем все записи
                recordings_list = await db_manager.get_recordings()
            else:
                # Используем фильтрацию по датам
                recordings_list = await pipeline.get_recordings_from_db(from_date, to_date)

        if not recordings_list:
            print("📋 Записи не найдены в базе данных")
            return

        # Показываем записи
        pipeline.display_recordings(recordings_list, show_meta=show_meta)

        # Экспорт если запрошен
        if export and recordings_list:
            _export_recordings(recordings_list, export, output)

        # Закрываем соединение с БД
        if db_manager:
            await db_manager.close()

    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        sys.exit(1)


async def _sync_command(from_date, to_date, last, account, config_file, use_db):
    """Команда sync - синхронизировать данные из Zoom в БД"""
    from_date, to_date = _parse_dates(from_date, to_date, last)

    setup_logger()
    logger = get_logger()

    try:
        # Инициализация БД и pipeline
        pipeline, db_manager = await _setup_pipeline(use_db)

        # Загружаем конфигурации всех аккаунтов
        if os.path.exists(config_file):
            configs = load_config_from_file(config_file)
            if account:
                config = get_config_by_account(account, configs)
                configs = {account: config}
        else:
            logger.error(f"Файл конфигурации не найден: {config_file}")
            return

        # Используем спиннер для синхронизации
        from utils.spinner import spinner_manager

        async def sync_zoom_data():
            return await pipeline.sync_zoom_recordings(configs, from_date, to_date)

        synced_count = await spinner_manager.run_with_spinner(
            "Синхронизация данных из Zoom...", sync_zoom_data, style="blue"
        )

        spinner_manager.print_success(f"Синхронизация завершена: {synced_count} записей")

        # Закрываем соединение с БД
        if db_manager:
            await db_manager.close()

    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        sys.exit(1)


async def _download_command(
    from_date,
    to_date,
    last,
    account,
    config_file,
    use_db,
    select_all,
    recordings,
    force,
    allow_skipped,
):
    """Команда download - скачать записи"""
    from_date, to_date = _parse_dates(from_date, to_date, last)

    setup_logger()
    logger = get_logger()

    try:
        # Инициализация БД и pipeline
        pipeline, db_manager = await _setup_pipeline(use_db)

        # Загружаем конфигурации всех аккаунтов (нужны для синхронизации, но не для скачивания)
        if os.path.exists(config_file):
            configs = load_config_from_file(config_file)
            if account:
                config = get_config_by_account(account, configs)
                configs = {account: config}
        else:
            logger.error(f"Файл конфигурации не найден: {config_file}")
            return

        # Определяем разрешенные статусы
        allowed_statuses = [ProcessingStatus.INITIALIZED]
        if allow_skipped:
            allowed_statuses.append(ProcessingStatus.SKIPPED)

        # Получаем целевые записи с фильтрацией по длительности и размеру
        target_recordings = await _get_target_recordings(
            pipeline=pipeline,
            from_date=from_date,
            to_date=to_date,
            select_all=select_all,
            recordings=recordings,
            allowed_statuses=allowed_statuses,
            min_duration=30,
            min_size_mb=30,
            filter_by_duration=True,
        )

        # Логируем предупреждения для записей, которые не прошли фильтрацию
        if recordings:
            try:
                recording_ids = [int(r.strip()) for r in recordings.split(',')]
                found_recordings = await pipeline.db_manager.get_recordings_by_ids(recording_ids)
                target_ids = {recording.db_id for recording in target_recordings}
                found_ids = {recording.db_id for recording in found_recordings}
                for recording_id in recording_ids:
                    if recording_id not in found_ids:
                        logger.warning(f"⚠️ ID записи {recording_id} не найден в базе данных")
                    elif recording_id not in target_ids:
                        logger.warning(f"⚠️ ID записи {recording_id} не подходит для скачивания (статус, длительность или размер)")
            except ValueError:
                pass  # Уже обработано в _get_target_recordings

        if target_recordings:
            success_count = await pipeline.download_recordings(
                target_recordings, force_download=force
            )
            logger.info(f"✅ Скачивание завершено: {success_count}/{len(target_recordings)}")
        else:
            logger.warning("❌ Нет записей для скачивания")

        # Закрываем соединение с БД
        if db_manager:
            await db_manager.close()

    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        sys.exit(1)


async def _process_command(
    from_date, to_date, last, account, config_file, use_db, select_all, recordings):
    """Команда process - обработать записи"""
    from_date, to_date = _parse_dates(from_date, to_date, last)

    setup_logger()
    logger = get_logger()

    try:
        # Инициализация БД и pipeline
        pipeline, db_manager = await _setup_pipeline(use_db)

        # Получаем целевые записи со статусом DOWNLOADED и наличием файла
        target_recordings = await _get_target_recordings(
            pipeline=pipeline,
            from_date=from_date,
            to_date=to_date,
            select_all=select_all,
            recordings=recordings,
            allowed_statuses=[ProcessingStatus.DOWNLOADED],
            require_file_path='local_video_path',
        )

        if target_recordings:
            success_count = await pipeline.process_recordings(target_recordings)
            logger.info(f"✅ Обработка завершена: {success_count}/{len(target_recordings)}")
        else:
            logger.warning("❌ Нет записей для обработки")

        # Закрываем соединение с БД
        if db_manager:
            await db_manager.close()

    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        sys.exit(1)


async def _transcribe_command(
    from_date,
    to_date,
    last,
    account,
    config_file,
    use_db,
    select_all,
    recordings,
    topic_model,
    topic_mode,
):
    """Команда transcribe - транскрибировать записи"""
    from_date, to_date = _parse_dates(from_date, to_date, last)

    setup_logger()
    logger = get_logger()

    try:
        # Инициализация БД и pipeline
        pipeline, db_manager = await _setup_pipeline(use_db)

        # Получаем целевые записи со статусом PROCESSED и наличием аудио файла
        target_recordings = await _get_target_recordings(
            pipeline=pipeline,
            from_date=from_date,
            to_date=to_date,
            select_all=select_all,
            recordings=recordings,
            allowed_statuses=[ProcessingStatus.PROCESSED],
            require_file_path='processed_audio_dir',
        )

        if target_recordings:
            success_count = await pipeline.transcribe_recordings(
                target_recordings,
                transcription_model="fireworks",
                topic_mode=topic_mode,
                topic_model=topic_model,
            )
            logger.info(f"✅ Транскрибация завершена: {success_count}/{len(target_recordings)}")
        else:
            logger.warning("❌ Нет записей для транскрибации (нужны записи со статусом PROCESSED и аудио файлом)")

        # Закрываем соединение с БД
        if db_manager:
            await db_manager.close()

    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        sys.exit(1)


async def _subtitles_command(
    from_date,
    to_date,
    last,
    account,
    config_file,
    use_db,
    select_all,
    recordings,
    formats,
):
    """Команда subtitles - генерировать субтитры из транскрипций"""
    from_date, to_date = _parse_dates(from_date, to_date, last)

    setup_logger()
    logger = get_logger()

    try:
        # Инициализация БД и pipeline
        pipeline, db_manager = await _setup_pipeline(use_db)

        # Получаем целевые записи со статусом TRANSCRIBED и наличием файла транскрипции
        target_recordings = await _get_target_recordings(
            pipeline=pipeline,
            from_date=from_date,
            to_date=to_date,
            select_all=select_all,
            recordings=recordings,
            allowed_statuses=[ProcessingStatus.TRANSCRIBED],
            require_file_path='transcription_dir',
        )

        if target_recordings:
            success_count = await pipeline.generate_subtitles(
                target_recordings, formats=formats
            )
            logger.info(f"✅ Генерация субтитров завершена: {success_count}/{len(target_recordings)}")
        else:
            logger.warning(
                "❌ Нет записей для генерации субтитров "
                "(нужны записи со статусом TRANSCRIBED и файлом транскрипции)"
            )

        # Закрываем соединение с БД
        if db_manager:
            await db_manager.close()

    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        sys.exit(1)


async def _upload_command(
    from_date,
    to_date,
    last,
    account,
    config_file,
    use_db,
    select_all,
    recordings,
    youtube,
    vk,
    all_platforms,
    upload_captions,
):
    """Команда upload - загрузить записи на платформы"""
    from_date, to_date = _parse_dates(from_date, to_date, last)

    setup_logger()
    logger = get_logger()

    try:
        # Инициализация БД и pipeline
        pipeline, db_manager = await _setup_pipeline(use_db)

        # Определяем платформы для загрузки
        platforms = []
        if all_platforms:
            platforms = ['youtube', 'vk']
        else:
            if youtube:
                platforms.append('youtube')
            if vk:
                platforms.append('vk')

        if not platforms:
            logger.error("❌ Не указаны платформы для загрузки")
            return

        # Получаем целевые записи со статусом PROCESSED или TRANSCRIBED
        target_recordings = await _get_target_recordings(
            pipeline=pipeline,
            from_date=from_date,
            to_date=to_date,
            select_all=select_all,
            recordings=recordings,
            allowed_statuses=[ProcessingStatus.PROCESSED, ProcessingStatus.TRANSCRIBED],
        )

        if target_recordings:
            success_count, uploaded_recordings = await pipeline.upload_recordings(
                target_recordings, platforms, upload_captions=upload_captions
            )
            logger.info(f"✅ Загрузка завершена: {success_count}/{len(target_recordings)}")

            # Отображаем список загруженных видео с ссылками
            if uploaded_recordings:
                pipeline.display_uploaded_videos(uploaded_recordings)
        else:
            logger.warning("❌ Нет записей для загрузки")

        # Закрываем соединение с БД
        if db_manager:
            await db_manager.close()

    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        sys.exit(1)


async def _reset_command(
    from_date, to_date, last, account, config_file, use_db, select_all, recordings, full):
    """Команда reset - сбросить статусы записей"""
    from_date, to_date = _parse_dates(from_date, to_date, last)

    setup_logger()
    logger = get_logger()

    try:
        # Инициализация БД и pipeline
        pipeline, db_manager = await _setup_pipeline(use_db)

        # Полная очистка БД и удаление всех видео
        if full:
            print("🗑️  Полная очистка базы данных и удаление всех видео...")
            print("⚠️  ВНИМАНИЕ: это действие УДАЛИТ ВСЕ записи из базы данных!")
            print("⚠️  И УДАЛИТ все processed и unprocessed видео файлы!")
            print("⚠️  Это действие НЕОБРАТИМО!")

            # Двойное подтверждение
            confirm1 = (
                input("Вы уверены, что хотите удалить ВСЕ записи и видео? (yes/NO): ")
                .strip()
                .lower()
            )
            if confirm1 not in ['yes', 'да']:
                print("❌ Очистка отменена")
                return

            confirm2 = input("Последний шанс! Введите 'DELETE ALL' для подтверждения: ").strip()
            if confirm2 != 'DELETE ALL':
                print("❌ Очистка отменена")
                return

            # Выполняем полную очистку
            try:
                import os

                from sqlalchemy import text

                async with db_manager.async_session() as session:
                    # Удаляем все записи
                    result = await session.execute(text("DELETE FROM recordings"))
                    deleted_count = result.rowcount

                    # Сбрасываем последовательность ID
                    await session.execute(text("ALTER SEQUENCE recordings_id_seq RESTART WITH 1"))

                    await session.commit()

                # Удаляем все видео и аудио файлы
                media_dirs = [
                    'media/video/processed',
                    'media/video/unprocessed',
                    'media/processed_audio',
                    'media/video/temp_processing',
                ]
                deleted_files = 0

                for media_dir in media_dirs:
                    if os.path.exists(media_dir):
                        for filename in os.listdir(media_dir):
                            file_path = os.path.join(media_dir, filename)
                            if os.path.isfile(file_path):
                                os.remove(file_path)
                                deleted_files += 1

                print("\n" + "=" * 60)
                print("📊 РЕЗУЛЬТАТЫ ОЧИСТКИ")
                print("=" * 60)
                print(f"✅ Удалено записей: {deleted_count}")
                print(f"✅ Удалено медиа файлов: {deleted_files}")
                print("🔄 Сброшена последовательность ID")
                print("🗑️  База данных и видео полностью очищены")

            except Exception as e:
                print(f"❌ Ошибка при очистке: {e}")

        else:
            # Обычный сброс
            print("🔄 Сброс статусов записей...")

            if recordings:
                # Сброс конкретных записей
                recordings_list = recordings.split(',')
                try:
                    recording_ids = [int(r) for r in recordings_list]
                    print(
                        f"⚠️  Внимание: будет сброшено {len(recording_ids)} записей к статусу INITIALIZED"
                    )
                    print("⚠️  И удалены связи с видео файлами")

                    confirm = input("Продолжить? (y/N): ").strip().lower()
                    if confirm not in ['y', 'yes', 'да']:
                        print("❌ Сброс отменен")
                        return

                    reset_results = await pipeline.reset_specific_recordings(recording_ids)

                    print("\n" + "=" * 60)
                    print("📊 РЕЗУЛЬТАТЫ СБРОСА")
                    print("=" * 60)
                    print(f"✅ Сброшено записей: {reset_results['total_reset']}")
                    print("🔗 Убрана привязка к локальным файлам")
                    if reset_results.get('deleted_files', 0) > 0:
                        print(f"🗑️  Удалено файлов: {reset_results['deleted_files']}")

                except ValueError:
                    logger.error("❌ Ошибка: ID записей должны быть числами")
                    return
            else:
                # Обычный сброс всех записей
                print(
                    "⚠️  Внимание: это действие сбросит все записи к статусу INITIALIZED (кроме уже загруженных)"
                )
                print("⚠️  И уберет привязку к локальным файлам в базе данных")

                # Подтверждение от пользователя
                confirm = input("Продолжить? (y/N): ").strip().lower()
                if confirm not in ['y', 'yes', 'да']:
                    print("❌ Сброс отменен")
                    return

                # Выполняем сброс
                reset_results = await db_manager.reset_recordings(keep_uploaded=True)

                print("\n" + "=" * 60)
                print("📊 РЕЗУЛЬТАТЫ СБРОСА")
                print("=" * 60)
                print(f"✅ Всего сброшено записей: {reset_results['total_reset']}")
                print("🔗 Убрана привязка к локальным файлам в базе данных")

                if reset_results['by_status']:
                    print("\n📈 Сброшено по статусам:")
                    for status, count in reset_results['by_status'].items():
                        print(f"   • {status}: {count}")

        # Закрываем соединение с БД
        if db_manager:
            await db_manager.close()

    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        sys.exit(1)


async def _clean_command(use_db: bool, days: int):
    """Команда clean - очистить старые записи"""
    setup_logger()
    logger = get_logger()

    try:
        # Инициализация БД и pipeline
        pipeline, db_manager = await _setup_pipeline(use_db)

        # Используем спиннер для очистки
        from utils.spinner import spinner_manager

        async def clean_old_data():
            return await pipeline.clean_old_recordings(days)

        clean_results = await spinner_manager.run_with_spinner(
            f"Очистка записей старше {days} дней...", clean_old_data, style="yellow"
        )

        print("\n" + "=" * 60)
        print("📊 РЕЗУЛЬТАТЫ ОЧИСТКИ")
        print("=" * 60)
        print(f"🗑️ Очищено записей: {clean_results['cleaned_count']}")
        print(f"💾 Освобождено места: {clean_results['freed_space_mb']:.1f} МБ")

        if clean_results['cleaned_recordings']:
            print("\n📋 Очищенные записи:")
            for recording in clean_results['cleaned_recordings']:
                print(f"   • {recording['topic']} (ID: {recording['id']})")

        # Закрываем соединение с БД
        if db_manager:
            await db_manager.close()

    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        sys.exit(1)


async def _recreate_db_command(force):
    """Команда recreate-db - полное пересоздание базы данных"""
    setup_logger()
    logger = get_logger()

    try:
        if not force:
            print("⚠️  ВНИМАНИЕ: Это действие УДАЛИТ всю базу данных и создаст её заново!")
            print("⚠️  ВСЕ данные будут потеряны безвозвратно!")
            print("⚠️  Это действие НЕОБРАТИМО!")
            print()

            # Двойное подтверждение
            confirm1 = (
                input("Вы уверены, что хотите полностью пересоздать БД? (yes/NO): ")
                .strip()
                .lower()
            )
            if confirm1 not in ['yes', 'да']:
                print("❌ Пересоздание БД отменено")
                return

            confirm2 = input("Последний шанс! Введите 'RECREATE DB' для подтверждения: ").strip()
            if confirm2 != 'RECREATE DB':
                print("❌ Пересоздание БД отменено")
                return

        # Инициализация конфигурации БД
        db_config = DatabaseConfig.from_env()

        # Создаем временный менеджер для пересоздания
        # (не нужно создавать БД заранее, т.к. recreate_database сделает это)
        db_manager = DatabaseManager(db_config)

        print("🗄️  Пересоздание базы данных...")

        # Используем спиннер для пересоздания
        from utils.spinner import spinner_manager

        async def recreate_database():
            await db_manager.recreate_database()
            return {"success": True}

        await spinner_manager.run_with_spinner(
            "Пересоздание базы данных...", recreate_database, style="yellow"
        )

        print("\n" + "=" * 60)
        print("📊 РЕЗУЛЬТАТЫ ПЕРЕСОЗДАНИЯ БД")
        print("=" * 60)
        print("✅ База данных успешно пересоздана")
        print("✅ Все таблицы созданы заново")
        print("🔄 База данных готова к использованию")

        # Закрываем соединение с БД
        await db_manager.close()

    except Exception as e:
        logger.error(f"❌ Ошибка пересоздания БД: {e}")
        sys.exit(1)


async def _full_process_command(
    from_date,
    to_date,
    last,
    account,
    config_file,
    use_db,
    select_all,
    recordings,
    youtube,
    vk,
    all_platforms,
    allow_skipped,
    no_transcription,
    topic_model,
    topic_mode,
):
    """Команда full-process - полный пайплайн: скачать + обработать + загрузить"""
    from_date, to_date = _parse_dates(from_date, to_date, last)

    setup_logger()
    logger = get_logger()

    try:
        # Инициализация БД и pipeline
        pipeline, db_manager = await _setup_pipeline(use_db)

        # Загружаем конфигурации всех аккаунтов
        if os.path.exists(config_file):
            configs = load_config_from_file(config_file)
            if account:
                config = get_config_by_account(account, configs)
                configs = {account: config}
        else:
            logger.error(f"Файл конфигурации не найден: {config_file}")
            return

        # Определяем платформы для загрузки
        platforms = []
        if youtube:
            platforms.append('youtube')
        if vk:
            platforms.append('vk')
        if all_platforms:
            platforms = ['youtube', 'vk']

        # Подготавливаем список записей
        recordings_list = recordings.split(',') if recordings else []

        # Выводим информацию о запуске пайплайна
        pipeline.console.print()
        pipeline.console.print("[bold magenta]" + "=" * 70 + "[/bold magenta]")
        pipeline.console.print("[bold magenta]🚀 ЗАПУСК ПОЛНОГО ПАЙПЛАЙНА[/bold magenta]")
        pipeline.console.print("[bold magenta]" + "=" * 70 + "[/bold magenta]")
        pipeline.console.print(f"[bold]📅 Период:[/bold] {from_date} - {to_date or 'текущая дата'}")
        if platforms:
            pipeline.console.print(f"[bold]📤 Платформы:[/bold] {', '.join(platforms)}")
        else:
            pipeline.console.print("[bold]📤 Платформы:[/bold] не указаны (только скачивание и обработка)")
        pipeline.console.print()

        # Запускаем полный пайплайн
        results = await pipeline.run_full_pipeline(
            configs=configs,
            from_date=from_date,
            to_date=to_date,
            select_all=select_all,
            recordings=recordings_list,
            platforms=platforms,
            allow_skipped=allow_skipped,
            no_transcription=no_transcription,
            transcription_model="fireworks",
            topic_mode=topic_mode,
            topic_model=topic_model,
        )

        # Выводим итоговую статистику
        pipeline.console.print()
        pipeline.console.print("[bold magenta]" + "=" * 70 + "[/bold magenta]")
        pipeline.console.print("[bold magenta]📊 ИТОГИ ПОЛНОГО ПАЙПЛАЙНА[/bold magenta]")
        pipeline.console.print("[bold magenta]" + "=" * 70 + "[/bold magenta]")
        pipeline.console.print()

        if results.get('success', True):  # По умолчанию считаем успешным
            pipeline.console.print(f"✅ [bold]Скачано записей:[/bold] {results.get('download_count', 0)}")
            pipeline.console.print(f"🎬 [bold]Обработано записей:[/bold] {results.get('process_count', 0)}")
            pipeline.console.print(f"🎤 [bold]Транскрибировано записей:[/bold] {results.get('transcribe_count', 0)}")
            pipeline.console.print(f"📤 [bold]Загружено записей:[/bold] {results.get('upload_count', 0)}")

            # Выводим общее время выполнения, если оно есть
            if results.get('total_time'):
                total_time_formatted = pipeline._format_elapsed_time(results['total_time'])
                pipeline.console.print()
                pipeline.console.print(f"⏱️  [bold]Общее время выполнения:[/bold] [cyan]{total_time_formatted}[/cyan]")

            # Отображаем список загруженных видео с ссылками
            uploaded_recordings = results.get('uploaded_recordings', [])
            if uploaded_recordings:
                pipeline.display_uploaded_videos(uploaded_recordings)
        else:
            pipeline.console.print(f"❌ [bold red]Пайплайн завершился с ошибкой:[/bold red] {results.get('message', 'Неизвестная ошибка')}")

        if results.get('errors'):
            pipeline.console.print()
            pipeline.console.print("[bold red]" + "=" * 70 + "[/bold red]")
            pipeline.console.print(f"[bold red]❌ ОШИБКИ: {len(results['errors'])}[/bold red]")
            pipeline.console.print("[bold red]" + "=" * 70 + "[/bold red]")
            for error in results['errors']:
                pipeline.console.print(f"   • [red]{error}[/red]")

        pipeline.console.print()
        pipeline.console.print("[dim]" + "=" * 70 + "[/dim]")

        # Закрываем соединение с БД
        if db_manager:
            await db_manager.close()

    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        sys.exit(1)


def _export_recordings(recordings: builtins.list, export_format: str, output_file: str | None):
    """Экспорт записей в файл"""
    logger = get_logger()

    if not output_file:
        output_file = f"recordings.{export_format}"

    try:
        if export_format == 'json':
            save_recordings_to_json(recordings, output_file)
        elif export_format == 'csv':
            save_recordings_to_csv(recordings, output_file)
        elif export_format == 'summary':
            export_recordings_summary(recordings, output_file)

        logger.info(f"✅ Данные экспортированы в: {output_file}")
    except Exception as e:
        logger.error(f"❌ Ошибка экспорта: {e}")


if __name__ == "__main__":
    main()
