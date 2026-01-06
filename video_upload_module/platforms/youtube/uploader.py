import asyncio
import json
import os
from datetime import datetime
from typing import Any

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from logger import get_logger

from ...config_factory import YouTubeConfig
from ...core.base import BaseUploader, UploadResult
from ...credentials_provider import CredentialProvider, FileCredentialProvider

logger = get_logger()


class YouTubeUploader(BaseUploader):
    """Загрузчик видео на YouTube."""

    def __init__(self, config: YouTubeConfig, credential_provider: CredentialProvider | None = None):
        super().__init__(config)
        self.config = config
        self.service = None
        self.credentials = None
        self.credential_provider = credential_provider

        self.logger = logger

    async def authenticate(self) -> bool:
        """Аутентификация в YouTube API."""
        try:
            # If no credential provider, create file-based provider for backward compatibility
            if not self.credential_provider:
                self.credential_provider = FileCredentialProvider(self.config.credentials_file)

            # Try to load existing credentials
            self.credentials = await self.credential_provider.get_google_credentials(self.config.scopes)

            # Check if credentials are valid or need refresh
            if not self.credentials or not self.credentials.valid:
                refreshed_successfully = False

                # Try to refresh token if available
                if self.credentials and self.credentials.refresh_token:
                    try:
                        self.logger.info("Refreshing YouTube access token...")
                        self.credentials.refresh(Request())
                        refreshed_successfully = True

                        # Save refreshed credentials back to storage
                        await self.credential_provider.update_google_credentials(self.credentials)
                        self.logger.info("YouTube token refreshed and saved successfully")

                    except Exception as e:
                        self.logger.warning(f"Failed to refresh token: {e}")
                        self.credentials = None

                # If refresh failed and using file provider, try interactive flow
                if not refreshed_successfully and isinstance(self.credential_provider, FileCredentialProvider):
                    self.logger.warning("Refresh failed, attempting interactive authorization...")

                    flow = None
                    try:
                        with open(self.config.client_secrets_file, encoding="utf-8") as f:
                            secrets_data = json.load(f)
                        if isinstance(secrets_data, dict) and "client_secrets" in secrets_data:
                            flow = InstalledAppFlow.from_client_config(
                                secrets_data["client_secrets"], self.config.scopes
                            )
                        else:
                            flow = InstalledAppFlow.from_client_secrets_file(
                                self.config.client_secrets_file, self.config.scopes
                            )
                    except FileNotFoundError:
                        self.logger.error(f"Client secrets file not found: {self.config.client_secrets_file}")
                        return False

                    self.credentials = flow.run_local_server(port=0)

                    # Save new credentials
                    await self.credential_provider.update_google_credentials(self.credentials)

                elif not refreshed_successfully:
                    # Using DB provider but no valid token - user needs to re-authorize via OAuth
                    self.logger.error(
                        "YouTube credentials expired and cannot be refreshed. "
                        "User must re-authorize via OAuth flow."
                    )
                    return False

            # Build YouTube service
            self.service = build("youtube", "v3", credentials=self.credentials)
            self._authenticated = True

            self.logger.info("YouTube authentication successful")
            return True

        except Exception as e:
            self.logger.error(f"YouTube authentication error: {e}")
            return False

    async def upload_video(
        self,
        video_path: str,
        title: str,
        description: str = "",
        thumbnail_path: str | None = None,
        privacy_status: str | None = None,
        playlist_id: str | None = None,
        progress=None,
        task_id=None,
        **kwargs,
    ) -> UploadResult | None:
        """Загрузка видео на YouTube."""

        if not self._authenticated:
            if not await self.authenticate():
                return None

        try:
            final_description = description if description else f"Загружено {self._get_timestamp()}"
            self.logger.debug(f"Длина описания для YouTube: {len(final_description)} символов")

            body = {
                "snippet": {
                    "title": title,
                    "description": final_description,
                    "defaultLanguage": self.config.default_language,
                    "defaultAudioLanguage": self.config.default_language,
                },
                "status": {
                    "privacyStatus": privacy_status or self.config.default_privacy,
                    "selfDeclaredMadeForKids": False,
                },
            }

            media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/*")

            self.logger.info(f"Загрузка видео на YouTube: {title}")

            request = self.service.videos().insert(part=",".join(body.keys()), body=body, media_body=media)

            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    upload_progress = int(status.progress() * 100)
                    if progress and task_id is not None:
                        try:
                            if task_id in progress.task_ids:
                                progress.update(task_id, completed=upload_progress, total=100)
                        except Exception:
                            pass  # Игнорируем ошибки обновления прогресса

            if "id" in response:
                video_id = response["id"]
                video_url = f"https://www.youtube.com/watch?v={video_id}"

                self.logger.info(f"Видео загружено: {video_url}")

                result = self._create_result(video_id=video_id, video_url=video_url, title=title, platform="youtube")

                if playlist_id:
                    try:
                        await asyncio.sleep(10)

                        from .playlist_manager import YouTubePlaylistManager

                        playlist_manager = YouTubePlaylistManager(self.service, self.config)
                        success = await playlist_manager.add_video_to_playlist(playlist_id, video_id)
                        if success:
                            result.metadata["playlist_id"] = playlist_id
                            self.logger.info(f"Видео добавлено в плейлист: {playlist_id}")
                        else:
                            result.metadata["playlist_error"] = "Не удалось добавить в плейлист"
                    except Exception as e:
                        self.logger.error(f"Ошибка добавления в плейлист: {e}")
                        result.metadata["playlist_error"] = str(e)

                if thumbnail_path and os.path.exists(thumbnail_path):
                    try:
                        from .thumbnail_manager import YouTubeThumbnailManager

                        thumbnail_manager = YouTubeThumbnailManager(self.service, self.config)
                        await asyncio.sleep(5)
                        success = await thumbnail_manager.set_thumbnail(video_id, thumbnail_path)
                        if success:
                            result.metadata["thumbnail_set"] = True
                        else:
                            result.metadata["thumbnail_error"] = "Не удалось установить миниатюру"
                    except Exception as e:
                        self.logger.warning(f"Не удалось установить миниатюру: {e}")
                        result.metadata["thumbnail_error"] = str(e)

                return result
            else:
                self.logger.error(f"Ошибка загрузки: {response}")
                return None

        except HttpError as e:
            self.logger.error(f"Ошибка YouTube API: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Ошибка загрузки видео: {e}")
            return None

    async def upload_caption(
        self,
        video_id: str,
        caption_path: str,
        language: str = "ru",
        name: str | None = None,
    ) -> bool:
        """Загрузка субтитров (SRT/VTT) на YouTube."""

        if not self._authenticated:
            if not await self.authenticate():
                return False

        if not os.path.exists(caption_path):
            self.logger.error(f"Файл субтитров не найден: {caption_path}")
            return False

        mime_type = "application/octet-stream"
        if caption_path.lower().endswith(".vtt"):
            mime_type = "text/vtt"
        elif caption_path.lower().endswith(".srt"):
            mime_type = "application/x-subrip"

        try:
            body = {
                "snippet": {
                    "videoId": video_id,
                    "language": language,
                    "name": name or "Transcript",
                    "isDraft": False,
                }
            }

            media = MediaFileUpload(caption_path, mimetype=mime_type, resumable=True)

            self.logger.info(f"Загрузка субтитров на YouTube для видео {video_id} ({language})")

            request = self.service.captions().insert(part="snippet", body=body, media_body=media)
            response = request.execute()

            if response and response.get("id"):
                self.logger.info(f"Субтитры загружены: caption_id={response['id']}")
                return True

            self.logger.error(f"Не удалось загрузить субтитры: {response}")
            return False

        except HttpError as e:
            self.logger.error(f"Ошибка YouTube Captions API: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Ошибка загрузки субтитров: {e}")
            return False

    async def get_video_info(self, video_id: str) -> dict[str, Any] | None:
        """Получение информации о видео."""
        if not self._authenticated:
            return None

        try:
            request = self.service.videos().list(part="snippet,statistics,status", id=video_id)
            response = request.execute()

            if response["items"]:
                video = response["items"][0]
                return {
                    "title": video["snippet"]["title"],
                    "description": video["snippet"]["description"],
                    "status": video["status"]["privacyStatus"],
                    "view_count": video["statistics"].get("viewCount", "0"),
                    "like_count": video["statistics"].get("likeCount", "0"),
                    "published_at": video["snippet"]["publishedAt"],
                }
            return None

        except Exception as e:
            self.logger.error(f"Ошибка получения информации о видео: {e}")
            return None

    async def delete_video(self, video_id: str) -> bool:
        """Удаление видео."""
        if not self._authenticated:
            return False

        try:
            request = self.service.videos().delete(id=video_id)
            request.execute()

            self.logger.info(f"Видео удалено: {video_id}")
            return True

        except Exception as e:
            self.logger.error(f"Ошибка удаления видео: {e}")
            return False

    def _get_timestamp(self) -> str:
        """Получение текущего времени в строковом формате."""

        return datetime.now().strftime("%Y-%m-%d %H:%M")
