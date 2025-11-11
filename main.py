import asyncio
import os
import sys
from datetime import datetime, timedelta

import click

from api import ZoomAPI
from config import get_config_by_account, load_config_from_file
from database import DatabaseConfig, DatabaseManager
from logger import get_logger, setup_logger
from models import ProcessingStatus
from pipeline_manager import PipelineManager
from utils import (
    export_recordings_summary,
    filter_recordings_by_duration,
    save_recordings_to_csv,
    save_recordings_to_json,
)


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

    # Убираем лишние пробелы
    date_str = date_str.strip()

    # Список поддерживаемых форматов
    formats = [
        '%Y-%m-%d',  # YYYY-MM-DD
        '%d-%m-%Y',  # DD-MM-YYYY
        '%d/%m/%Y',  # DD/MM/YYYY
        '%d-%m-%y',  # DD-MM-YY
        '%d/%m/%y',  # DD/MM/YY
    ]

    # Пробуем распарсить дату в каждом формате
    for fmt in formats:
        try:
            parsed_date = datetime.strptime(date_str, fmt)
            return parsed_date.strftime('%Y-%m-%d')
        except ValueError:
            continue

    # Если формат не распознан, возвращаем как есть
    return date_str


# Общие опции для всех команд
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


# Опции для команд с выбором записей
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


# Опции для команд загрузки
def platform_options(f):
    """Опции для выбора платформ"""
    f = click.option('--youtube', is_flag=True, help='Загрузить на YouTube')(f)
    f = click.option('--vk', is_flag=True, help='Загрузить на VK')(f)
    f = click.option('--all-platforms', is_flag=True, help='Загрузить на все платформы')(f)
    return f


# Опции для команд с принудительным выполнением
def force_options(f):
    """Опции для принудительного выполнения"""
    f = click.option('-f', '--force', is_flag=True, help='Принудительно выполнить операцию')(f)
    return f


@click.group()
def cli():
    """Zoom Manager - управление записями Zoom встреч"""
    pass


@cli.command()
@common_options
@click.option(
    '--last',
    type=int,
    default=0,
    help='Последние N дней (0 = сегодня, 1 = вчера, 7 = неделя, 14 = две недели)',
)
@click.option('--export', type=click.Choice(['json', 'csv', 'summary']), help='Экспорт результатов')
@click.option('--output', type=str, help='Имя выходного файла')
def list(from_date, to_date, last, account, config_file, use_db, export, output):
    """Показать записи из базы данных"""
    asyncio.run(
        _list_command(
            from_date, to_date, last, account, config_file, use_db, export, output
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
def transcribe(
    from_date, to_date, last, account, config_file, use_db, select_all, recordings):
    """Транскрибировать записи"""
    asyncio.run(
        _transcribe_command(
            from_date, to_date, last, account, config_file, use_db, select_all, recordings
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
@common_options
@click.option(
    '--days',
    type=int,
    default=7,
    help='Количество дней назад для очистки записей (по умолчанию: 7)',
)
def clean(from_date, to_date, account, config_file, use_db,  days):
    """Очистить старые записи (удалить файлы и пометить как EXPIRED)"""
    asyncio.run(_clean_command(from_date, to_date, account, config_file, use_db,  days))


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
    else:
        # Используем --last (по умолчанию 0 = сегодня)
        if last == 0:
            # Сегодня
            from_date = datetime.now().strftime('%Y-%m-%d')
            to_date = datetime.now().strftime('%Y-%m-%d')
        else:
            # Последние N дней
            to_date = datetime.now().strftime('%Y-%m-%d')
            from_date = (datetime.now() - timedelta(days=last)).strftime('%Y-%m-%d')

    return from_date, to_date


async def _list_command(
    from_date, to_date, last, account, config_file, use_db, export, output):
    """Команда list - показать записи из БД"""
    from_date, to_date = _parse_dates(from_date, to_date, last)

    setup_logger()
    logger = get_logger()

    try:
        # Инициализация БД
        db_manager = None
        if use_db:
            db_config = DatabaseConfig.from_env()
            db_manager = DatabaseManager(db_config)
            await db_manager.create_database_if_not_exists()
            await db_manager.create_tables()
            print("🗄️ \033[1;34mПодключение к базе данных...\033[0m")

        # Загружаем унифицированную конфигурацию
        from config.unified_config import load_app_config

        app_config = load_app_config()
        pipeline = PipelineManager(db_manager, app_config, )

        # Получаем записи из БД
        recordings = await pipeline.get_recordings_from_db(from_date, to_date)

        if not recordings:
            print("📋 Записи не найдены в базе данных")
            return

        # Показываем записи
        pipeline.display_recordings(recordings)

        # Экспорт если запрошен
        if export and recordings:
            _export_recordings(recordings, export, output)

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
        # Инициализация БД
        db_manager = None
        if use_db:
            db_config = DatabaseConfig.from_env()
            db_manager = DatabaseManager(db_config)
            await db_manager.create_database_if_not_exists()
            await db_manager.create_tables()
            print("🗄️ \033[1;34mПодключение к базе данных...\033[0m")

            # Загружаем конфигурации всех аккаунтов
            if os.path.exists(config_file):
                configs = load_config_from_file(config_file)
                if account:
                    config = get_config_by_account(account, configs)
                    configs = {account: config}
            else:
                logger.error(f"Файл конфигурации не найден: {config_file}")
                return

        # Загружаем унифицированную конфигурацию
        from config.unified_config import load_app_config

        app_config = load_app_config()
        pipeline = PipelineManager(db_manager, app_config, )

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
        # Инициализация БД
        db_manager = None
        if use_db:
            db_config = DatabaseConfig.from_env()
            db_manager = DatabaseManager(db_config)
            await db_manager.create_database_if_not_exists()
            await db_manager.create_tables()
            print("🗄️ \033[1;34mПодключение к базе данных...\033[0m")

            # Загружаем конфигурации всех аккаунтов
            if os.path.exists(config_file):
                configs = load_config_from_file(config_file)
                if account:
                    config = get_config_by_account(account, configs)
                    configs = {account: config}
            else:
                logger.error(f"Файл конфигурации не найден: {config_file}")
                return

        # Загружаем унифицированную конфигурацию
        from config.unified_config import load_app_config

        app_config = load_app_config()
        pipeline = PipelineManager(db_manager, app_config, )

        if recordings:
            # Если указаны конкретные записи, ищем их напрямую в БД
            recordings_list = recordings.split(',')
            try:
                recording_ids = [int(r) for r in recordings_list]
                target_recordings = []

                # Ищем записи напрямую в базе данных по ID
                found_recordings = await pipeline.db_manager.get_recordings_by_ids(recording_ids)
                found_ids = {recording.db_id for recording in found_recordings}

                for recording in found_recordings:
                    # Проверяем, что запись подходит для скачивания и имеет правильный статус
                    allowed_statuses = [ProcessingStatus.INITIALIZED]
                    if allow_skipped:
                        allowed_statuses.append(ProcessingStatus.SKIPPED)

                    if (
                        recording.duration >= 30
                        and recording.video_file_size >= 30 * 1024 * 1024
                        and recording.status in allowed_statuses
                    ):
                        target_recordings.append(recording)
                    else:
                        if recording.status not in allowed_statuses:
                            logger.warning(
                                f"⚠️ Запись {recording.db_id} имеет статус {recording.status.value}, не подходит для загрузки"
                            )
                        else:
                            logger.warning(
                                f"⚠️ Запись {recording.db_id} не подходит для скачивания (длительность: {recording.duration} мин, размер: {recording.video_file_size / (1024 * 1024):.1f} МБ)"
                            )

                # Проверяем, какие ID не были найдены
                for recording_id in recording_ids:
                    if recording_id not in found_ids:
                        logger.warning(f"⚠️ ID записи {recording_id} не найден в базе данных")
            except ValueError:
                # Если не числа, ищем по именам в базе данных
                db_recordings = await pipeline.get_recordings_from_db(from_date, to_date)
                long_recordings = filter_recordings_by_duration(db_recordings, 30)
                # Фильтруем записи по статусу и именам
                allowed_statuses = [ProcessingStatus.INITIALIZED]
                if allow_skipped:
                    allowed_statuses.append(ProcessingStatus.SKIPPED)
                target_recordings = [
                    r
                    for r in long_recordings
                    if r.topic in recordings_list and r.status in allowed_statuses
                ]
        else:
            # Получаем записи из базы данных за период
            db_recordings = await pipeline.get_recordings_from_db(from_date, to_date)
            long_recordings = filter_recordings_by_duration(db_recordings, 30)

            # Фильтруем записи по статусу
            allowed_statuses = [ProcessingStatus.INITIALIZED]
            if allow_skipped:
                allowed_statuses.append(ProcessingStatus.SKIPPED)
            target_recordings = [r for r in long_recordings if r.status in allowed_statuses]

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
        # Инициализация БД
        db_manager = None
        if use_db:
            db_config = DatabaseConfig.from_env()
            db_manager = DatabaseManager(db_config)
            await db_manager.create_database_if_not_exists()
            await db_manager.create_tables()
            print("🗄️ \033[1;34mПодключение к базе данных...\033[0m")

        # Загружаем унифицированную конфигурацию
        from config.unified_config import load_app_config

        app_config = load_app_config()
        pipeline = PipelineManager(db_manager, app_config, )

        if recordings:
            # Если указаны конкретные записи, ищем их по ID
            try:
                recording_ids = [int(r.strip()) for r in recordings.split(',')]
                # Получаем записи по ID из БД напрямую
                found_recordings = await pipeline.db_manager.get_recordings_by_ids(recording_ids)
                # Фильтруем по статусу DOWNLOADED и наличию файла
                target_recordings = [
                    r for r in found_recordings
                    if r.status == ProcessingStatus.DOWNLOADED and r.local_video_path
                ]
            except ValueError:
                logger.error("❌ Ошибка: ID записей должны быть числами")
                return
        elif select_all:
            all_recordings = await pipeline.get_recordings_from_db(from_date, to_date)
            target_recordings = [
                r for r in all_recordings
                if r.status == ProcessingStatus.DOWNLOADED and r.local_video_path
            ]
        else:
            # По умолчанию берем все записи со статусом DOWNLOADED
            all_recordings = await pipeline.get_recordings_from_db(from_date, to_date)
            target_recordings = [
                r for r in all_recordings
                if r.status == ProcessingStatus.DOWNLOADED and r.local_video_path
            ]

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
    from_date, to_date, last, account, config_file, use_db, select_all, recordings
):
    """Команда transcribe - транскрибировать записи"""
    from_date, to_date = _parse_dates(from_date, to_date, last)

    setup_logger()
    logger = get_logger()

    try:
        # Инициализация БД
        db_manager = None
        if use_db:
            db_config = DatabaseConfig.from_env()
            db_manager = DatabaseManager(db_config)
            await db_manager.create_database_if_not_exists()
            await db_manager.create_tables()
            print("🗄️ \033[1;34mПодключение к базе данных...\033[0m")

        # Загружаем унифицированную конфигурацию
        from config.unified_config import load_app_config

        app_config = load_app_config()
        pipeline = PipelineManager(db_manager, app_config, )

        if recordings:
            # Если указаны конкретные записи, ищем их по ID
            try:
                recording_ids = [int(r.strip()) for r in recordings.split(',')]
                found_recordings = await pipeline.db_manager.get_recordings_by_ids(recording_ids)
                target_recordings = [
                    r for r in found_recordings
                    if r.status == ProcessingStatus.PROCESSED and r.processed_audio_path
                ]
            except ValueError:
                logger.error("❌ Ошибка: ID записей должны быть числами")
                return
        elif select_all:
            all_recordings = await pipeline.get_recordings_from_db(from_date, to_date)
            target_recordings = [
                r for r in all_recordings
                if r.status == ProcessingStatus.PROCESSED and r.processed_audio_path
            ]
        else:
            # По умолчанию берем все записи со статусом PROCESSED и с аудио файлом
            all_recordings = await pipeline.get_recordings_from_db(from_date, to_date)
            target_recordings = [
                r for r in all_recordings
                if r.status == ProcessingStatus.PROCESSED and r.processed_audio_path
            ]

        if target_recordings:
            success_count = await pipeline.transcribe_recordings(target_recordings)
            logger.info(f"✅ Транскрибация завершена: {success_count}/{len(target_recordings)}")
        else:
            logger.warning("❌ Нет записей для транскрибации (нужны записи со статусом PROCESSED и аудио файлом)")

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
):
    """Команда upload - загрузить записи на платформы"""
    from_date, to_date = _parse_dates(from_date, to_date, last)

    setup_logger()
    logger = get_logger()

    try:
        # Инициализация БД
        db_manager = None
        if use_db:
            db_config = DatabaseConfig.from_env()
            db_manager = DatabaseManager(db_config)
            await db_manager.create_database_if_not_exists()
            await db_manager.create_tables()
            print("🗄️ \033[1;34mПодключение к базе данных...\033[0m")

        # Загружаем унифицированную конфигурацию
        from config.unified_config import load_app_config

        app_config = load_app_config()
        pipeline = PipelineManager(db_manager, app_config, )

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

        # Выбираем записи для загрузки
        if select_all:
            all_recordings = await pipeline.get_recordings_from_db(from_date, to_date)
            target_recordings = [
                r for r in all_recordings
                if r.status in [ProcessingStatus.PROCESSED, ProcessingStatus.TRANSCRIBED]
            ]
        elif recordings:
            # Если указаны конкретные записи, ищем их по ID
            try:
                recording_ids = [int(r.strip()) for r in recordings.split(',')]
                found_recordings = await pipeline.db_manager.get_recordings_by_ids(recording_ids)
                target_recordings = [
                    r for r in found_recordings
                    if r.status in [ProcessingStatus.PROCESSED, ProcessingStatus.TRANSCRIBED]
                ]
            except ValueError:
                logger.error("❌ Ошибка: ID записей должны быть числами")
                return
        else:
            all_recordings = await pipeline.get_recordings_from_db(from_date, to_date)
            target_recordings = [
                r for r in all_recordings
                if r.status in [ProcessingStatus.PROCESSED, ProcessingStatus.TRANSCRIBED]
            ]

        if target_recordings:
            success_count, uploaded_recordings = await pipeline.upload_recordings(target_recordings, platforms)
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
        # Инициализация БД
        db_manager = None
        if use_db:
            db_config = DatabaseConfig.from_env()
            db_manager = DatabaseManager(db_config)
            await db_manager.create_database_if_not_exists()
            await db_manager.create_tables()
            print("🗄️ \033[1;34mПодключение к базе данных...\033[0m")

        # Загружаем унифицированную конфигурацию
        from config.unified_config import load_app_config

        app_config = load_app_config()
        pipeline = PipelineManager(db_manager, app_config, )

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
                    'video/processed_video',
                    'video/unprocessed_video',
                    'video/processed_audio',
                    'video/temp_processing',
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


async def _clean_command(from_date, to_date, account, config_file, use_db,  days):
    """Команда clean - очистить старые записи"""
    # Для команды clean мы не используем from_date и to_date, только days

    setup_logger()
    logger = get_logger()

    try:
        # Инициализация БД
        db_manager = None
        if use_db:
            db_config = DatabaseConfig.from_env()
            db_manager = DatabaseManager(db_config)
            await db_manager.create_database_if_not_exists()
            await db_manager.create_tables()
            print("🗄️ \033[1;34mПодключение к базе данных...\033[0m")

        # Загружаем унифицированную конфигурацию
        from config.unified_config import load_app_config

        app_config = load_app_config()
        pipeline = PipelineManager(db_manager, app_config, )

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
):
    """Команда full-process - полный пайплайн: скачать + обработать + загрузить"""
    from_date, to_date = _parse_dates(from_date, to_date, last)

    setup_logger()
    logger = get_logger()

    try:
        # Инициализация БД
        db_manager = None
        if use_db:
            db_config = DatabaseConfig.from_env()
            db_manager = DatabaseManager(db_config)
            await db_manager.create_database_if_not_exists()
            await db_manager.create_tables()
            print("🗄️ \033[1;34mПодключение к базе данных...\033[0m")

        # Загружаем унифицированную конфигурацию
        from config.unified_config import load_app_config

        app_config = load_app_config()
        pipeline = PipelineManager(db_manager, app_config, )

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

        print("🚀 \033[1;34mЗапуск полного пайплайна...\033[0m")
        print(f"📅 Период: {from_date} - {to_date or 'текущая дата'}")
        if platforms:
            print(f"📤 Платформы: {', '.join(platforms)}")
        else:
            print("📤 Платформы: не указаны (только скачивание и обработка)")

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
        )

        # Выводим итоговую статистику
        print("\n" + "=" * 60)
        print("📊 ИТОГИ ПОЛНОГО ПАЙПЛАЙНА")
        print("=" * 60)

        if results.get('success', True):  # По умолчанию считаем успешным
            print(f"✅ Скачано записей: {results.get('download_count', 0)}")
            print(f"🎬 Обработано записей: {results.get('process_count', 0)}")
            print(f"🎤 Транскрибировано записей: {results.get('transcribe_count', 0)}")
            print(f"📤 Загружено записей: {results.get('upload_count', 0)}")

            # Отображаем список загруженных видео с ссылками
            uploaded_recordings = results.get('uploaded_recordings', [])
            if uploaded_recordings:
                pipeline.display_uploaded_videos(uploaded_recordings)
        else:
            print(f"❌ Пайплайн завершился с ошибкой: {results.get('message', 'Неизвестная ошибка')}")

        if results.get('errors'):
            print(f"❌ Ошибок: {len(results['errors'])}")
            for error in results['errors']:
                print(f"   • {error}")

        # Закрываем соединение с БД
        if db_manager:
            await db_manager.close()

    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        sys.exit(1)


async def _get_zoom_api(account: str | None, config_file: str) -> ZoomAPI:
    """Получение API клиента Zoom"""
    if os.path.exists(config_file):
        configs = load_config_from_file(config_file)
        if account:
            config = get_config_by_account(account, configs)
        else:
            config = next(iter(configs.values()))
    else:
        raise FileNotFoundError(f"Файл конфигурации не найден: {config_file}")

    return ZoomAPI(config)


def _export_recordings(recordings: list, export_format: str, output_file: str | None):
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
