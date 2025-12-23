from typing import Any

import httpx

from config.settings import ZoomConfig
from logger import get_logger

from .token_manager import TokenManager

logger = get_logger()


class ZoomAPIError(Exception):
    """Базовая ошибка Zoom API."""

    pass


class ZoomAuthenticationError(ZoomAPIError):
    """Ошибка аутентификации."""

    pass


class ZoomRequestError(ZoomAPIError):
    """Ошибка выполнения запроса."""

    pass


class ZoomResponseError(ZoomAPIError):
    """Ошибка ответа API."""

    pass


class ZoomAPI:
    """
    Класс для работы с Zoom API.

    Использует TokenManager для централизованного управления токенами доступа
    с синхронизацией и механизмом повторных попыток.
    """

    def __init__(self, config: ZoomConfig):
        """Инициализация API клиента."""
        self.config = config
        # TokenManager будет использоваться через get_instance для каждого запроса

    async def get_access_token(self) -> str | None:
        """
        Получение токена доступа с кэшированием и синхронизацией.

        Использует TokenManager для централизованного управления токенами,
        предотвращая race conditions при параллельных запросах.

        Returns:
            Access token или None в случае неудачи
        """
        token_manager = await TokenManager.get_instance(self.config.account)
        return await token_manager.get_token(self.config)

    async def get_recordings(
        self,
        page_size: int = 30,
        from_date: str = "2024-01-01",
        to_date: str | None = None,
        meeting_id: str | None = None,
    ) -> dict[str, Any]:
        """Получение списка записей."""
        access_token = await self.get_access_token()
        if not access_token:
            raise ZoomAuthenticationError("Не удалось получить access token")

        params = {"page_size": str(page_size), "from": from_date, "trash": "false"}

        if to_date:
            params["to"] = to_date

        if meeting_id:
            params["meeting_id"] = meeting_id

        try:
            logger.info(f"Запрос записей: from={from_date}, to={to_date}, meeting_id={meeting_id}")
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    "https://api.zoom.us/v2/users/me/recordings",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params=params,
                )

                if response.status_code == 200:
                    data = response.json()
                    logger.info(f"Получено записей: {len(data.get('meetings', []))}")
                    # Логируем сырые данные от Zoom API
                    import json
                    logger.debug(f"Сырые данные от Zoom API (get_recordings):\n{json.dumps(data, indent=2, ensure_ascii=False)}")
                    return data
                else:
                    logger.error(
                        f"Ошибка API для аккаунта {self.config.account}: "
                        f"{response.status_code} - {response.text}"
                    )
                    raise ZoomResponseError(
                        f"Ошибка API: {response.status_code} - {response.text}"
                    )

        except httpx.RequestError as e:
            error_type = type(e).__name__
            logger.error(
                f"Ошибка сетевого запроса для аккаунта {self.config.account} "
                f"({error_type}): {e}",
                exc_info=True,
            )
            raise ZoomRequestError(f"Ошибка сетевого запроса: {e}") from e
        except ZoomAPIError:
            raise
        except Exception as e:
            error_type = type(e).__name__
            logger.error(
                f"Неожиданная ошибка для аккаунта {self.config.account} "
                f"({error_type}): {e}",
                exc_info=True,
            )
            raise ZoomAPIError(f"Неожиданная ошибка: {e}") from e

    async def get_recording_details(
        self, meeting_id: str, include_download_token: bool = True
    ) -> dict[str, Any]:
        """Получение детальной информации о конкретной записи."""
        access_token = await self.get_access_token()
        if not access_token:
            raise ZoomAuthenticationError("Не удалось получить access token")

        try:
            params = {}
            if include_download_token:
                params = {"include_fields": "download_access_token", "ttl": "1"}

            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"https://api.zoom.us/v2/meetings/{meeting_id}/recordings",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params=params,
                )

                if response.status_code == 200:
                    data = response.json()
                    # Логируем сырые данные от Zoom API
                    import json
                    logger.debug(f"Сырые данные от Zoom API (get_recording_details для meeting_id={meeting_id}):\n{json.dumps(data, indent=2, ensure_ascii=False)}")
                    return data
                else:
                    logger.error(
                        f"Ошибка API для аккаунта {self.config.account} "
                        f"при получении деталей записи {meeting_id}: "
                        f"{response.status_code} - {response.text}"
                    )
                    raise ZoomResponseError(
                        f"Ошибка API: {response.status_code} - {response.text}"
                    )

        except httpx.RequestError as e:
            error_type = type(e).__name__
            logger.error(
                f"Ошибка сетевого запроса для аккаунта {self.config.account} "
                f"при получении деталей записи {meeting_id} ({error_type}): {e}",
                exc_info=True,
            )
            raise ZoomRequestError(f"Ошибка сетевого запроса: {e}") from e
        except ZoomAPIError:
            raise
        except Exception as e:
            error_type = type(e).__name__
            logger.error(
                f"Неожиданная ошибка для аккаунта {self.config.account} "
                f"при получении деталей записи {meeting_id} ({error_type}): {e}",
                exc_info=True,
            )
            raise ZoomAPIError(f"Неожиданная ошибка: {e}") from e
