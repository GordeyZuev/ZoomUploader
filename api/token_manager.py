"""
Менеджер токенов для Zoom API с синхронизацией и механизмом повторных попыток.

Реализует паттерн Singleton для централизованного управления токенами доступа
на уровне аккаунта, предотвращая race conditions при параллельных запросах.
"""

import asyncio
import base64
import time

import httpx

from config.settings import ZoomConfig
from logger import get_logger

logger = get_logger()


class TokenManager:
    """
    Централизованный менеджер токенов с синхронизацией на уровне аккаунта.

    Использует паттерн Singleton для обеспечения единой точки доступа к токенам
    для каждого аккаунта, предотвращая дублирование запросов при параллельной обработке.
    """

    # Классовые переменные для хранения экземпляров и блокировок
    _instances: dict[str, "TokenManager"] = {}
    _locks: dict[str, asyncio.Lock] = {}
    _class_lock = asyncio.Lock()

    def __init__(self, account: str):
        """
        Инициализация менеджера токенов для конкретного аккаунта.

        Args:
            account: Email аккаунта Zoom
        """
        self.account = account
        self._cached_token: str | None = None
        self._token_expires_at: float | None = None
        self._refresh_buffer = 60  # Обновляем токен за 60 секунд до истечения

    @classmethod
    async def get_instance(cls, account: str) -> "TokenManager":
        """
        Получение или создание экземпляра TokenManager для аккаунта (Singleton).

        Args:
            account: Email аккаунта Zoom

        Returns:
            Экземпляр TokenManager для указанного аккаунта
        """
        async with cls._class_lock:
            if account not in cls._instances:
                cls._instances[account] = cls(account)
                cls._locks[account] = asyncio.Lock()
            return cls._instances[account]

    @classmethod
    def get_lock(cls, account: str) -> asyncio.Lock:
        """
        Получение блокировки для конкретного аккаунта.

        Args:
            account: Email аккаунта Zoom

        Returns:
            Блокировка для синхронизации доступа к токену аккаунта
        """
        if account not in cls._locks:
            cls._locks[account] = asyncio.Lock()
        return cls._locks[account]

    def _is_token_valid(self) -> bool:
        """
        Проверка валидности кэшированного токена.

        Returns:
            True если токен валиден и не истечет в ближайшие refresh_buffer секунд
        """
        if not self._cached_token or not self._token_expires_at:
            return False
        return time.time() < (self._token_expires_at - self._refresh_buffer)

    async def _fetch_token(
        self,
        config: ZoomConfig,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
    ) -> tuple[str | None, int | None]:
        """
        Получение токена с механизмом повторных попыток и экспоненциальной задержкой.

        Args:
            config: Конфигурация Zoom аккаунта
            max_retries: Максимальное количество попыток
            base_delay: Базовая задержка в секундах (для первой попытки)
            max_delay: Максимальная задержка в секундах

        Returns:
            Кортеж (access_token, expires_in) или (None, None) в случае неудачи
        """
        credentials = f"{config.client_id}:{config.client_secret}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()

        for attempt in range(max_retries):
            try:
                logger.info(f"Получение токена для аккаунта: {config.account} (попытка {attempt + 1}/{max_retries})")

                async with httpx.AsyncClient(timeout=30.0) as client:
                    response = await client.post(
                        "https://zoom.us/oauth/token",
                        headers={"Authorization": f"Basic {encoded_credentials}"},
                        params={
                            "grant_type": "account_credentials",
                            "account_id": config.account_id,
                        },
                    )

                    if response.status_code == 200:
                        token_data = response.json()
                        access_token = token_data.get("access_token")
                        expires_in = token_data.get("expires_in", 3600)  # По умолчанию 1 час

                        if access_token:
                            logger.info(
                                f"Токен получен успешно для аккаунта {config.account} "
                                f"(истекает через {expires_in} секунд)"
                            )
                            return (access_token, expires_in)
                        logger.error(f"Токен не найден в ответе API для аккаунта {config.account}")
                        return (None, None)
                    error_msg = (
                        f"Ошибка получения токена для аккаунта {config.account}: "
                        f"{response.status_code} - {response.text}"
                    )
                    logger.error(error_msg)

                    # Для ошибок аутентификации (401, 403) не имеет смысла повторять
                    if response.status_code in (401, 403):
                        logger.error(
                            f"Ошибка аутентификации для аккаунта {config.account}. Повторные попытки не помогут."
                        )
                        return (None, None)

                    # Для других ошибок продолжаем попытки
                    if attempt < max_retries - 1:
                        delay = min(base_delay * (2**attempt), max_delay)
                        logger.warning(
                            f"Повторная попытка получения токена для {config.account} через {delay:.1f} секунд..."
                        )
                        await asyncio.sleep(delay)
                    else:
                        return (None, None)

            except (httpx.NetworkError, httpx.TimeoutException, httpx.ConnectError) as e:
                error_type = type(e).__name__
                logger.warning(f"Сетевая ошибка при получении токена для {config.account} ({error_type}): {e}")

                if attempt < max_retries - 1:
                    delay = min(base_delay * (2**attempt), max_delay)
                    logger.info(
                        f"Повторная попытка получения токена для {config.account} "
                        f"через {delay:.1f} секунд (попытка {attempt + 2}/{max_retries})..."
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        f"Исчерпаны все попытки получения токена для {config.account}. "
                        f"Последняя ошибка: {error_type}: {e}"
                    )
                    return (None, None)

            except Exception as e:
                error_type = type(e).__name__
                logger.error(
                    f"Неожиданная ошибка при получении токена для {config.account} ({error_type}): {e}",
                    exc_info=True,  # Включаем traceback для диагностики
                )
                # Для неожиданных ошибок не повторяем
                return (None, None)

        return (None, None)

    async def get_token(
        self,
        config: ZoomConfig,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
    ) -> str | None:
        """
        Получение токена доступа с синхронизацией и кэшированием.

        Метод потокобезопасен и предотвращает дублирование запросов при параллельном
        доступе из разных корутин.

        Args:
            config: Конфигурация Zoom аккаунта
            max_retries: Максимальное количество попыток при ошибках
            base_delay: Базовая задержка для экспоненциальной задержки
            max_delay: Максимальная задержка между попытками

        Returns:
            Access token или None в случае неудачи
        """
        # Проверяем валидность кэшированного токена без блокировки
        if self._is_token_valid():
            logger.debug(f"Используем кэшированный токен для аккаунта: {config.account}")
            return self._cached_token

        # Получаем блокировку для синхронизации доступа
        lock = self.get_lock(config.account)
        async with lock:
            # Двойная проверка: возможно, токен был получен другой корутиной
            # пока мы ждали блокировки
            if self._is_token_valid():
                logger.debug(f"Используем кэшированный токен для аккаунта: {config.account} (получен другой корутиной)")
                return self._cached_token

            # Получаем новый токен
            access_token, expires_in = await self._fetch_token(config, max_retries, base_delay, max_delay)

            if access_token:
                # Кэшируем токен
                self._cached_token = access_token
                # Используем время истечения из ответа API или значение по умолчанию
                expires_in = expires_in or 3600  # 1 час по умолчанию
                self._token_expires_at = time.time() + expires_in
                return access_token
            logger.error(f"Не удалось получить токен для аккаунта: {config.account}")
            return None

    def invalidate_token(self) -> None:
        """
        Инвалидация кэшированного токена.

        Полезно при ошибках аутентификации для принудительного обновления токена.
        """
        logger.debug(f"Инвалидация токена для аккаунта: {self.account}")
        self._cached_token = None
        self._token_expires_at = None
