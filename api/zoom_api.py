import base64
from typing import Any

import httpx

from config.settings import ZoomConfig
from logger import get_logger

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
    """Класс для работы с Zoom API."""

    def __init__(self, config: ZoomConfig):
        """Инициализация API клиента."""
        self.config = config
        self._cached_token = None
        self._token_expires_at = None

    async def get_access_token(self) -> str | None:
        """Получение токена доступа с кэшированием."""
        import time

        # Проверяем, есть ли действующий кэшированный токен
        if (
            self._cached_token
            and self._token_expires_at
            and time.time() < self._token_expires_at - 60
        ):  # Обновляем за минуту до истечения
            logger.debug(f"Используем кэшированный токен для аккаунта: {self.config.account}")
            return self._cached_token

        credentials = f"{self.config.client_id}:{self.config.client_secret}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()

        try:
            logger.info(f"Получение токена для аккаунта: {self.config.account}")
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://zoom.us/oauth/token",
                    headers={"Authorization": f"Basic {encoded_credentials}"},
                    params={
                        "grant_type": "account_credentials",
                        "account_id": self.config.account_id,
                    },
                )

                if response.status_code == 200:
                    token_data = response.json()
                    access_token = token_data.get("access_token")
                    expires_in = token_data.get("expires_in", 3600)  # По умолчанию 1 час

                    # Кэшируем токен
                    self._cached_token = access_token
                    self._token_expires_at = time.time() + expires_in

                    logger.info("Токен получен успешно")
                    return access_token
                else:
                    logger.error(
                        f"Ошибка получения токена: {response.status_code} - {response.text}"
                    )
                    return None

        except Exception as e:
            logger.error(f"Исключение при получении токена: {e}")
            return None

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
                    return data
                else:
                    logger.error(f"Ошибка API: {response.status_code} - {response.text}")
                    raise ZoomResponseError(f"Ошибка API: {response.status_code} - {response.text}")

        except httpx.RequestError as e:
            logger.error(f"Ошибка сетевого запроса: {e}")
            raise ZoomRequestError(f"Ошибка сетевого запроса: {e}") from e
        except ZoomAPIError:
            raise
        except Exception as e:
            logger.error(f"Неожиданная ошибка: {e}")
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
                    return response.json()
                else:
                    raise ZoomResponseError(f"Ошибка API: {response.status_code} - {response.text}")

        except httpx.RequestError as e:
            raise ZoomRequestError(f"Ошибка сетевого запроса: {e}") from e
        except ZoomAPIError:
            raise
        except Exception as e:
            raise ZoomAPIError(f"Неожиданная ошибка: {e}") from e
