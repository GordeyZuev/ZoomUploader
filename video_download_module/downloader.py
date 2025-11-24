import asyncio
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import httpx
from rich.console import Console
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    TaskID,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

from logger import get_logger
from models import MeetingRecording, ProcessingStatus
from utils.formatting import normalize_datetime_string

logger = get_logger()


class ZoomDownloader:
    """Класс для загрузки файлов Zoom."""

    def __init__(self, download_dir: str = "video/unprocessed_video"):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.console = Console()
        logger.debug(f"Загрузчик инициализирован: {self.download_dir}")

    def _encode_download_url(self, url: str) -> str:
        """Правильное кодирование URL для скачивания согласно документации Zoom."""
        if '==' in url or '//' in url:
            encoded = quote(url, safe='/:')
            double_encoded = quote(encoded, safe='/:')
            logger.debug(f"Выполнено двойное кодирование URL: {url} -> {double_encoded}")
            return double_encoded
        return url

    def _get_filename(self, recording: MeetingRecording) -> str:
        topic = recording.topic.strip() if recording.topic else ""
        safe_topic = "".join(
            c for c in topic if c.isalnum() or c in (' ', '-', '_', '(', ')')
        ).strip()
        if len(safe_topic) > 60:
            safe_topic = safe_topic[:60].rstrip()
        if recording.start_time and recording.start_time.strip():
            try:
                normalized_time = normalize_datetime_string(recording.start_time)
                date_obj = datetime.fromisoformat(normalized_time)
                formatted_date = date_obj.strftime('%d.%m.%Y')
            except Exception as e:
                logger.debug(f"Ошибка парсинга даты в _get_filename '{recording.start_time}': {e}")
                formatted_date = "unknown_date"
        else:
            formatted_date = "unknown_date"

        return f"{safe_topic} ({formatted_date}).mp4"

    async def download_file(
        self,
        url: str,
        filepath: Path,
        description: str = "файл",
        progress: Progress = None,
        task_id: TaskID = None,
        expected_size: int = None,
        password: str = None,
        passcode: str = None,
        download_access_token: str = None,
        oauth_token: str = None,
        max_retries: int = 10,
    ) -> bool:
        """Загрузка файла по URL с поддержкой возобновления и retry механизмом."""

        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    logger.info(f"🔄 Попытка загрузки {attempt + 1}/{max_retries}: {description}")
                else:
                    logger.debug(f"Начинаю загрузку {description}: {url}")

                # Проверяем, есть ли уже частично загруженный файл
                downloaded = 0
                if filepath.exists():
                    downloaded = filepath.stat().st_size
                    logger.info(f"📦 Найден частично загруженный файл: {downloaded} байт ({downloaded / (1024 * 1024):.1f} MB)")

                encoded_url = self._encode_download_url(url)

                headers = {}
                params = {}

                logger.info(
                    f"🔐 Проверка аутентификации: oauth_token={bool(oauth_token)}, download_access_token={bool(download_access_token)}, passcode={bool(passcode)}, password={bool(password)}"
                )

                if oauth_token:
                    headers['Authorization'] = f'Bearer {oauth_token}'
                    logger.info(
                        f"✅ Используем OAuth access token для аутентификации (длина: {len(oauth_token)})"
                    )
                elif download_access_token:
                    headers['Authorization'] = f'Bearer {download_access_token}'
                    logger.info(
                        f"✅ Используем download_access_token для аутентификации (длина: {len(download_access_token)})"
                    )
                elif passcode:
                    headers['X-Zoom-Passcode'] = passcode
                    headers['Authorization'] = f'Bearer {passcode}'
                    logger.info(f"✅ Используем passcode для аутентификации (длина: {len(passcode)})")
                elif password:
                    params['password'] = password
                    params['access_token'] = password
                    logger.info(f"✅ Используем пароль для аутентификации: {password}")
                else:
                    logger.warning("⚠️ Нет данных для аутентификации!")

                # Добавляем Range заголовок для продолжения загрузки
                if downloaded > 0:
                    headers['Range'] = f'bytes={downloaded}-'
                    logger.info(f"🔄 Продолжаем загрузку с байта {downloaded}")

                logger.debug(f"Заголовки: {headers}")
                logger.debug(f"Параметры: {params}")

                # Оптимизированные таймауты для быстрого обнаружения обрыва
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(
                        timeout=180.0,  # общий таймаут 3 минуты
                        connect=30.0,   # подключение 30 секунд
                        read=60.0,      # чтение данных 60 секунд (быстрее обнаруживаем обрыв)
                        write=30.0      # запись 30 секунд
                    ),
                    follow_redirects=True,
                    limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
                ) as client:
                    async with client.stream(
                        'GET', encoded_url, headers=headers, params=params
                    ) as response:
                        # Проверяем поддержку Range (206 Partial Content)
                        if downloaded > 0 and response.status_code == 206:
                            logger.info("✅ Сервер поддерживает возобновление загрузки (206 Partial Content)")
                            mode = 'ab'  # append binary
                        elif downloaded > 0 and response.status_code == 200:
                            logger.warning("⚠️ Сервер не поддерживает возобновление, начинаем заново")
                            downloaded = 0
                            mode = 'wb'
                            # Удаляем старый файл, чтобы начать с нуля
                            if filepath.exists():
                                filepath.unlink()
                        else:
                            response.raise_for_status()
                            mode = 'wb'

                        filepath.parent.mkdir(parents=True, exist_ok=True)

                        # Получаем полный размер из Content-Range или Content-Length
                        content_range = response.headers.get('content-range')
                        if content_range:
                            # Формат: "bytes 1000-2000/3000"
                            total_size = int(content_range.split('/')[-1])
                            logger.debug(f"Получен Content-Range: {content_range}, total_size: {total_size}")
                        else:
                            total_size = int(response.headers.get('content-length', 0))
                            if downloaded > 0 and mode == 'ab':
                                total_size += downloaded

                        if total_size == 0 and expected_size:
                            total_size = expected_size

                        logger.debug(
                            f"Размер файла: {total_size} байт ({total_size / (1024 * 1024):.1f} MB), уже загружено: {downloaded} байт ({downloaded / (1024 * 1024):.1f} MB)"
                        )

                        # Обновляем прогресс с учетом уже загруженного
                        if progress and task_id and total_size > 0:
                            progress.update(task_id, total=total_size, completed=downloaded)

                        # Открываем файл в нужном режиме (wb или ab)
                        with open(filepath, mode) as f:
                            chunk_count = 0
                            bytes_in_session = 0
                            last_update_downloaded = downloaded

                            async for chunk in response.aiter_bytes(chunk_size=8192):
                                f.write(chunk)
                                chunk_size = len(chunk)
                                bytes_in_session += chunk_size
                                downloaded += chunk_size
                                chunk_count += 1

                                # Обновляем прогресс каждые 10 чанков для плавности
                                if progress and task_id is not None and chunk_count % 10 == 0:
                                    try:
                                        # Проверяем, что задача существует в прогресс-баре
                                        if task_id in progress.task_ids:
                                            progress.update(task_id, completed=downloaded)
                                            last_update_downloaded = downloaded
                                    except Exception:
                                        pass  # Игнорируем ошибки обновления прогресса

                            # Финальное обновление прогресса
                            if progress and task_id is not None and downloaded > last_update_downloaded:
                                try:
                                    if task_id in progress.task_ids:
                                        progress.update(task_id, completed=downloaded)
                                except Exception:
                                    pass

                        logger.info(f"✅ Файл записан: {downloaded}/{total_size} байт ({downloaded / (1024 * 1024):.1f}/{total_size / (1024 * 1024):.1f} MB)")

                # Проверяем корректность файла только на последней итерации или при успешной загрузке
                if not self._validate_downloaded_file(filepath, expected_size, total_size):
                    logger.warning(f"⚠️ Скачанный {description} некорректен или неполный")
                    # НЕ удаляем файл - даем возможность повторить попытку!
                    if attempt < max_retries - 1:
                        wait_time = 3 if attempt < 2 else 5  # Быстрый retry для валидации
                        logger.info(f"🔄 Повторная попытка {attempt + 2}/{max_retries} через {wait_time} секунд (файл неполный)...")
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        logger.error(f"❌ Исчерпаны все попытки загрузки {description}")
                        # Только на последней попытке удаляем некорректный файл
                        if filepath.exists():
                            filepath.unlink()
                        return False

                logger.debug(f"✅ {description} успешно загружен: {filepath}")
                return True

            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError, httpx.ReadTimeout) as e:
                logger.warning(f"⚠️ Сетевая ошибка при загрузке {description}: {type(e).__name__}: {e}")
                if attempt < max_retries - 1:
                    # Более агрессивный backoff: 3s → 5s → 10s → 15s → 20s → 30s (макс)
                    if attempt < 2:
                        wait_time = 3 + attempt * 2  # 3s, 5s
                    else:
                        wait_time = min(10 + (attempt - 2) * 5, 30)  # 10s, 15s, 20s, 25s, 30s...
                    logger.info(f"🔄 Повторная попытка {attempt + 2}/{max_retries} через {wait_time} секунд...")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    logger.error(f"❌ Исчерпаны все попытки загрузки {description} после сетевых ошибок")
                    # НЕ удаляем частично загруженный файл - можно будет продолжить позже!
                    return False

            except httpx.HTTPStatusError as e:
                logger.error(f"❌ HTTP ошибка при загрузке {description}: {e.response.status_code}")
                # При HTTP ошибках (401, 403, 404 и т.д.) повторять бесполезно
                if filepath.exists() and e.response.status_code >= 400:
                    filepath.unlink()
                return False

            except Exception as e:
                logger.error(f"❌ Непредвиденная ошибка загрузки {description}: {type(e).__name__}: {e}")
                if attempt < max_retries - 1:
                    wait_time = 5
                    logger.info(f"🔄 Повторная попытка {attempt + 2}/{max_retries} через {wait_time} секунд (непредвиденная ошибка)...")
                    await asyncio.sleep(wait_time)
                    continue
                else:
                    # Только критические ошибки - удаляем файл
                    if filepath.exists():
                        filepath.unlink()
                    return False

        return False

    def _validate_downloaded_file(self, filepath: Path, expected_size: int = None, total_size: int = None) -> bool:
        """Проверка корректности скачанного файла."""
        try:
            if not filepath.exists():
                return False

            file_size = filepath.stat().st_size

            if file_size < 1024:
                logger.warning(f"Файл слишком мал: {file_size} байт")
                return False

            # Используем total_size из Content-Range если доступен, иначе expected_size
            reference_size = total_size or expected_size

            # Проверяем, что файл полностью загружен (если знаем ожидаемый размер)
            if reference_size:
                if file_size < reference_size:
                    # Файл еще не полностью загружен
                    logger.warning(
                        f"Файл загружен не полностью: {file_size}/{reference_size} байт "
                        f"({file_size / (1024 * 1024):.1f}/{reference_size / (1024 * 1024):.1f} MB, "
                        f"{(file_size / reference_size * 100):.1f}%)"
                    )
                    return False
                elif file_size > reference_size * 1.1:
                    # Файл больше ожидаемого на 10%+ - что-то не так
                    logger.warning(
                        f"Файл больше ожидаемого: {file_size} > {reference_size} "
                        f"({file_size / (1024 * 1024):.1f} > {reference_size / (1024 * 1024):.1f} MB)"
                    )
                    # Но не считаем это критичной ошибкой, продолжаем валидацию

            with open(filepath, 'rb') as f:
                first_chunk = f.read(1024)
                if b'<html' in first_chunk.lower() or b'<!doctype html' in first_chunk.lower():
                    logger.error(
                        "Скачанный файл является HTML страницей (возможно, требуется пароль)"
                    )
                    return False

                if filepath.suffix.lower() == '.mp4':
                    if not (
                        first_chunk.startswith(b'\x00\x00\x00')
                        or b'ftyp' in first_chunk
                        or b'moov' in first_chunk
                    ):
                        logger.error("Файл не является корректным MP4 видео")
                        return False

            logger.debug(f"✅ Файл прошел валидацию: {file_size} байт ({file_size / (1024 * 1024):.1f} MB)")
            return True

        except Exception as e:
            logger.error(f"Ошибка при валидации файла {filepath}: {e}")
            return False

    async def download_recording(
        self,
        recording: MeetingRecording,
        progress: Progress = None,
        task_id: TaskID = None,
        force_download: bool = False,
    ) -> bool:
        """Загрузка записи (только видео)."""
        logger.debug(f"Начинаю загрузку записи: {recording.topic}")

        if not recording.video_file_download_url:
            logger.error(f"Нет ссылки на видео для {recording.topic}")
            recording.update_status(ProcessingStatus.FAILED, "Нет ссылки на видео")
            return False

        if not force_download and recording.status not in [
            ProcessingStatus.INITIALIZED,
            ProcessingStatus.SKIPPED,
        ]:
            logger.info(
                f"⏭️ Запись уже обработана (статус: {recording.status.value}), пропускаем загрузку: {recording.topic}"
            )
            return False

        recording.update_status(ProcessingStatus.DOWNLOADING)

        video_filename = self._get_filename(recording)
        video_path = self.download_dir / video_filename

        fresh_download_token = None
        if recording.download_access_token:
            try:
                from api.zoom_api import ZoomAPI
                from config.accounts import ZOOM_ACCOUNTS

                account_config = ZOOM_ACCOUNTS.get(recording.account)
                if account_config:
                    api = ZoomAPI(account_config)
                    detailed_data = await api.get_recording_details(
                        recording.meeting_id, include_download_token=True
                    )
                    fresh_download_token = detailed_data.get('download_access_token')
                    logger.info(
                        f"🔄 Получен свежий download_access_token (длина: {len(fresh_download_token) if fresh_download_token else 0})"
                    )
                else:
                    logger.warning(f"⚠️ Не найден конфиг для аккаунта: {recording.account}")
            except Exception as e:
                logger.error(f"❌ Ошибка получения свежего токена: {e}")
                fresh_download_token = recording.download_access_token

        oauth_token = None
        try:
            from api.zoom_api import ZoomAPI
            from config.accounts import ZOOM_ACCOUNTS

            account_config = ZOOM_ACCOUNTS.get(recording.account)
            if account_config:
                api = ZoomAPI(account_config)
                oauth_token = await api.get_access_token()
                logger.info(
                    f"🔄 Получен OAuth access token для аутентификации (длина: {len(oauth_token) if oauth_token else 0})"
                )
        except Exception as e:
            logger.error(f"❌ Ошибка получения OAuth токена: {e}")

        if await self.download_file(
            recording.video_file_download_url,
            video_path,
            "видео",
            progress,
            task_id,
            recording.video_file_size,
            recording.password,
            recording.recording_play_passcode,
            fresh_download_token or recording.download_access_token,
            oauth_token,
        ):
            try:
                recording.local_video_path = str(video_path.relative_to(Path.cwd()))
            except ValueError:
                recording.local_video_path = str(video_path)
            recording.update_status(ProcessingStatus.DOWNLOADED)
            recording.downloaded_at = datetime.now()
            logger.debug(f"✅ Запись {recording.topic} успешно загружена: {video_path}")
            return True
        else:
            recording.update_status(ProcessingStatus.FAILED)
            logger.error(f"❌ Ошибка загрузки записи {recording.topic}")
            return False

    async def download_multiple(
        self,
        recordings: list[MeetingRecording],
        max_concurrent: int = 3,
        force_download: bool = False,
    ) -> list[bool]:
        """Загрузка нескольких записей параллельно с красивыми индивидуальными прогресс-барами."""
        logger.debug(
            f"Начинаю загрузку {len(recordings)} записей (макс. {max_concurrent} одновременно)"
        )

        with Progress(
            TextColumn("[cyan]{task.fields[date]}[/cyan]"),
            TextColumn("•"),
            TextColumn("[bold white]{task.description}[/bold white]"),
            BarColumn(bar_width=25),
            DownloadColumn(),
            TransferSpeedColumn(),
            TextColumn("[yellow]{task.percentage:>3.0f}%[/yellow]"),
            TimeRemainingColumn(),
            console=self.console,
            transient=False,
        ) as progress:
            semaphore = asyncio.Semaphore(max_concurrent)

            async def download_with_progress(recording: MeetingRecording) -> bool:
                async with semaphore:
                    try:
                        from utils.formatting import normalize_datetime_string

                        normalized_time = normalize_datetime_string(recording.start_time)
                        meeting_dt = datetime.fromisoformat(normalized_time)
                        date_str = meeting_dt.strftime("%d.%m.%y")
                    except Exception:
                        date_str = "??/??/??"

                    title = f"{recording.topic[:45]}{'...' if len(recording.topic) > 45 else ''}"
                    # Используем реальный размер файла или разумное значение по умолчанию
                    estimated_size = recording.video_file_size or (
                        200 * 1024 * 1024
                    )  # 200 МБ по умолчанию
                    task_id = progress.add_task(title, total=estimated_size, date=date_str)

                    success = await self.download_recording(
                        recording, progress, task_id, force_download
                    )

                    status_icon = "[green]✓[/green]" if success else "[red]✗[/red]"
                    progress.update(task_id, description=f"{status_icon} {title}")

                    return success

            results = await asyncio.gather(*[download_with_progress(rec) for rec in recordings])

        success_count = sum(results)
        logger.debug(f"Загрузка завершена: {success_count}/{len(recordings)} успешно")
        return results
