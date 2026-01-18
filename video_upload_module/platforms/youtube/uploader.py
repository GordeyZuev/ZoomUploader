"""YouTube video uploader implementation."""

import asyncio
import json
from datetime import datetime
from pathlib import Path
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
from .token_handler import TokenRefreshError, requires_valid_token

logger = get_logger()


class YouTubeUploader(BaseUploader):
    """YouTube video uploader."""

    def __init__(self, config: YouTubeConfig, credential_provider: CredentialProvider | None = None):
        super().__init__(config)
        self.config = config
        self.service = None
        self.credentials = None
        self.credential_provider = credential_provider

    async def authenticate(self) -> bool:
        """Authenticate with YouTube API."""
        try:
            if not self.credential_provider:
                self.credential_provider = FileCredentialProvider(self.config.credentials_file)

            self.credentials = await self.credential_provider.get_google_credentials(self.config.scopes)

            if not self.credentials or not self.credentials.valid:
                refreshed_successfully = False

                if self.credentials and self.credentials.refresh_token:
                    try:
                        logger.info("Refreshing YouTube access token...")
                        self.credentials.refresh(Request())
                        refreshed_successfully = True

                        await self.credential_provider.update_google_credentials(self.credentials)
                        logger.info("YouTube token refreshed and saved successfully")

                    except Exception as e:
                        logger.warning(f"Failed to refresh token: {e}")
                        self.credentials = None

                if not refreshed_successfully and isinstance(self.credential_provider, FileCredentialProvider):
                    logger.warning("Refresh failed, attempting interactive authorization...")

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
                        logger.error(f"Client secrets file not found: {self.config.client_secrets_file}")
                        return False

                    self.credentials = flow.run_local_server(port=0)
                    await self.credential_provider.update_google_credentials(self.credentials)

                elif not refreshed_successfully:
                    logger.error(
                        "YouTube credentials expired and cannot be refreshed. User must re-authorize via OAuth flow."
                    )
                    return False

            self.service = build("youtube", "v3", credentials=self.credentials)
            self._authenticated = True

            logger.info("YouTube authentication successful")
            return True

        except Exception as e:
            logger.error(f"YouTube authentication error: {e}")
            return False

    @requires_valid_token(max_retries=1)
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
        """
        Upload video to YouTube.

        Supported kwargs:
            - tags: list[str] - Video tags
            - category_id: str|int - YouTube category ID
            - publish_at: str - ISO 8601 datetime for scheduled publishing
            - made_for_kids: bool - Whether video is made for kids
            - embeddable: bool - Whether video can be embedded
            - license: str - "youtube" or "creativeCommon"
            - public_stats_viewable: bool - Whether stats are publicly viewable
        """

        if not self._authenticated:
            if not await self.authenticate():
                return None

        try:
            final_description = description if description else f"Uploaded {self._get_timestamp()}"
            logger.debug(f"YouTube description length: {len(final_description)} characters")

            snippet = {
                "title": title,
                "description": final_description,
                "defaultLanguage": self.config.default_language,
                "defaultAudioLanguage": self.config.default_language,
            }

            if kwargs.get("tags"):
                snippet["tags"] = kwargs["tags"][:500]
                logger.debug(f"Added {len(snippet['tags'])} tags")

            if kwargs.get("category_id"):
                snippet["categoryId"] = str(kwargs["category_id"])
                logger.debug(f"Set category_id: {snippet['categoryId']}")

            status = {
                "privacyStatus": privacy_status or self.config.default_privacy,
                "selfDeclaredMadeForKids": kwargs.get("made_for_kids", False),
            }

            if kwargs.get("publish_at"):
                status["publishAt"] = kwargs["publish_at"]
                if status["privacyStatus"] != "private":
                    logger.warning("Setting privacy to 'private' for scheduled video")
                    status["privacyStatus"] = "private"
                logger.info(f"Video will be published at: {kwargs['publish_at']}")

            if "embeddable" in kwargs:
                status["embeddable"] = bool(kwargs["embeddable"])

            if "license" in kwargs and kwargs["license"] in ["youtube", "creativeCommon"]:
                status["license"] = kwargs["license"]

            if "public_stats_viewable" in kwargs:
                status["publicStatsViewable"] = bool(kwargs["public_stats_viewable"])

            body = {
                "snippet": snippet,
                "status": status,
            }

            media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/*")

            logger.info(f"Uploading video to YouTube: {title}")

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
                        except Exception as e:
                            logger.warning(f"Ignored exception: {e}")

            if "id" in response:
                video_id = response["id"]
                video_url = f"https://www.youtube.com/watch?v={video_id}"

                logger.info(f"Video uploaded: {video_url}")

                result = self._create_result(video_id=video_id, video_url=video_url, title=title, platform="youtube")

                if playlist_id:
                    try:
                        await asyncio.sleep(10)

                        from .playlist_manager import YouTubePlaylistManager

                        playlist_manager = YouTubePlaylistManager(
                            self.service, self.config, self.credentials, self.credential_provider
                        )
                        success = await playlist_manager.add_video_to_playlist(playlist_id, video_id)
                        if success:
                            result.metadata["playlist_id"] = playlist_id
                            logger.info(f"Video added to playlist: {playlist_id}")
                        else:
                            result.metadata["playlist_error"] = "Failed to add to playlist"
                    except Exception as e:
                        logger.error(f"Playlist addition error: {e}")
                        result.metadata["playlist_error"] = str(e)

                if thumbnail_path and Path(thumbnail_path).exists():
                    try:
                        from .thumbnail_manager import YouTubeThumbnailManager

                        thumbnail_manager = YouTubeThumbnailManager(
                            self.service, self.config, self.credentials, self.credential_provider
                        )
                        await asyncio.sleep(5)
                        success = await thumbnail_manager.set_thumbnail(video_id, thumbnail_path)
                        if success:
                            result.metadata["thumbnail_set"] = True
                        else:
                            result.metadata["thumbnail_error"] = "Failed to set thumbnail"
                    except Exception as e:
                        logger.warning(f"Failed to set thumbnail: {e}")
                        result.metadata["thumbnail_error"] = str(e)

                return result
            logger.error(f"Upload error: {response}")
            return None

        except TokenRefreshError as e:
            logger.error(f"Token error: {e}")
            return None
        except HttpError as e:
            logger.error(f"YouTube API error: {e}")
            return None
        except Exception as e:
            logger.error(f"Video upload error: {e}")
            return None

    @requires_valid_token(max_retries=1)
    async def upload_caption(
        self,
        video_id: str,
        caption_path: str,
        language: str = "ru",
        name: str | None = None,
    ) -> bool:
        """Upload captions (SRT/VTT) to YouTube."""

        if not self._authenticated:
            if not await self.authenticate():
                return False

        if not Path(caption_path).exists():
            logger.error(f"Caption file not found: {caption_path}")
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

            logger.info(f"Uploading captions to YouTube for video {video_id} ({language})")

            request = self.service.captions().insert(part="snippet", body=body, media_body=media)
            response = request.execute()

            if response and response.get("id"):
                logger.info(f"Captions uploaded: caption_id={response['id']}")
                return True

            logger.error(f"Failed to upload captions: {response}")
            return False

        except TokenRefreshError as e:
            logger.error(f"Token error during caption upload: {e}")
            return False
        except HttpError as e:
            logger.error(f"YouTube Captions API error: {e}")
            return False
        except Exception as e:
            logger.error(f"Caption upload error: {e}")
            return False

    @requires_valid_token(max_retries=1)
    async def get_video_info(self, video_id: str) -> dict[str, Any] | None:
        """Get video information."""
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

        except TokenRefreshError as e:
            logger.error(f"Token error during get_video_info: {e}")
            return None
        except Exception as e:
            logger.error(f"Error getting video info: {e}")
            return None

    @requires_valid_token(max_retries=1)
    async def delete_video(self, video_id: str) -> bool:
        """Delete video."""
        if not self._authenticated:
            return False

        try:
            request = self.service.videos().delete(id=video_id)
            request.execute()

            logger.info(f"Video deleted: {video_id}")
            return True

        except TokenRefreshError as e:
            logger.error(f"Token error during delete_video: {e}")
            return False
        except Exception as e:
            logger.error(f"Video deletion error: {e}")
            return False

    def _get_timestamp(self) -> str:
        """Get current timestamp as string."""
        return datetime.now().strftime("%Y-%m-%d %H:%M")
