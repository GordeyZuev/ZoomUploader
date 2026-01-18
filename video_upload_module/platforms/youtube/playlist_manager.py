"""YouTube playlist manager."""

from typing import Any

from googleapiclient.errors import HttpError

from logger import get_logger

from ...config_factory import YouTubeConfig
from ...credentials_provider import CredentialProvider
from .token_handler import TokenRefreshError, requires_valid_token

logger = get_logger()


class YouTubePlaylistManager:
    """YouTube playlist manager."""

    def __init__(
        self,
        service,
        config: YouTubeConfig,
        credentials=None,
        credential_provider: CredentialProvider | None = None,
    ):
        self.service = service
        self.config = config
        self.credentials = credentials
        self.credential_provider = credential_provider

    @requires_valid_token(max_retries=1)
    async def create_playlist(self, title: str, description: str = "", privacy_status: str = "unlisted") -> str | None:
        """Create playlist."""
        try:
            body = {
                "snippet": {"title": title, "description": description},
                "status": {"privacyStatus": privacy_status},
            }

            request = self.service.playlists().insert(part="snippet,status", body=body)
            response = request.execute()

            playlist_id = response["id"]
            playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"

            logger.info(f"Playlist created: {playlist_url}")
            return playlist_id

        except TokenRefreshError as e:
            logger.error(f"Token error during create_playlist: {e}")
            return None
        except HttpError as e:
            logger.error(f"Playlist creation error: {e}")
            return None

    @requires_valid_token(max_retries=1)
    async def add_video_to_playlist(self, playlist_id: str, video_id: str) -> bool:
        """Add video to playlist."""
        try:
            body = {
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {"kind": "youtube#video", "videoId": video_id},
                }
            }

            request = self.service.playlistItems().insert(part="snippet", body=body)
            request.execute()

            logger.info(f"Video added to playlist {playlist_id}")
            return True
        except TokenRefreshError as e:
            logger.error(f"Token error during add_video_to_playlist: {e}")
            return False
        except HttpError as e:
            logger.error(f"Error adding to playlist: {e}")
            return False

    @requires_valid_token(max_retries=1)
    async def remove_video_from_playlist(self, playlist_item_id: str) -> bool:
        """Remove video from playlist."""
        try:
            request = self.service.playlistItems().delete(id=playlist_item_id)
            request.execute()

            logger.info("Video removed from playlist")
            return True
        except TokenRefreshError as e:
            logger.error(f"Token error during remove_video_from_playlist: {e}")
            return False
        except HttpError as e:
            logger.error(f"Error removing from playlist: {e}")
            return False

    @requires_valid_token(max_retries=1)
    async def get_playlist_info(self, playlist_id: str) -> dict[str, Any] | None:
        """Get playlist information."""
        try:
            request = self.service.playlists().list(part="snippet,contentDetails,status", id=playlist_id)
            response = request.execute()

            if response["items"]:
                playlist = response["items"][0]
                return {
                    "title": playlist["snippet"]["title"],
                    "description": playlist["snippet"]["description"],
                    "item_count": playlist["contentDetails"]["itemCount"],
                    "privacy_status": playlist["status"]["privacyStatus"],
                    "published_at": playlist["snippet"]["publishedAt"],
                }
            return None

        except TokenRefreshError as e:
            logger.error(f"Token error during get_playlist_info: {e}")
            return None
        except HttpError as e:
            logger.error(f"Error getting playlist info: {e}")
            return None

    async def get_playlist_videos(self, playlist_id: str, max_results: int = 50) -> list[dict[str, Any]]:
        """Get list of videos in playlist."""
        try:
            videos = []
            next_page_token = None

            while True:
                request = self.service.playlistItems().list(
                    part="snippet,contentDetails",
                    playlistId=playlist_id,
                    maxResults=min(max_results, 50),
                    pageToken=next_page_token,
                )
                response = request.execute()

                for item in response["items"]:
                    videos.append(
                        {
                            "video_id": item["contentDetails"]["videoId"],
                            "title": item["snippet"]["title"],
                            "description": item["snippet"]["description"],
                            "position": item["snippet"]["position"],
                        }
                    )

                if len(videos) >= max_results or "nextPageToken" not in response:
                    break

                next_page_token = response["nextPageToken"]

            return videos[:max_results]

        except HttpError as e:
            logger.error(f"Error getting playlist videos: {e}")
            return []

    async def update_playlist(self, playlist_id: str, title: str | None = None, description: str | None = None) -> bool:
        """Update playlist."""
        try:
            body = {"id": playlist_id, "snippet": {}}

            if title:
                body["snippet"]["title"] = title
            if description:
                body["snippet"]["description"] = description

            request = self.service.playlists().update(part="snippet", body=body)
            request.execute()

            logger.info(f"Playlist updated: {playlist_id}")
            return True

        except HttpError as e:
            logger.error(f"Playlist update error: {e}")
            return False

    async def delete_playlist(self, playlist_id: str) -> bool:
        """Delete playlist."""
        try:
            request = self.service.playlists().delete(id=playlist_id)
            request.execute()

            logger.info(f"Playlist deleted: {playlist_id}")
            return True

        except HttpError as e:
            logger.error(f"Playlist deletion error: {e}")
            return False

    async def get_user_playlists(self, max_results: int = 50) -> list[dict[str, Any]]:
        """Get user playlists."""
        try:
            playlists = []
            next_page_token = None

            while True:
                request = self.service.playlists().list(
                    part="snippet,contentDetails",
                    mine=True,
                    maxResults=min(max_results, 50),
                    pageToken=next_page_token,
                )
                response = request.execute()

                for playlist in response["items"]:
                    playlists.append(
                        {
                            "playlist_id": playlist["id"],
                            "title": playlist["snippet"]["title"],
                            "description": playlist["snippet"]["description"],
                            "item_count": playlist["contentDetails"]["itemCount"],
                            "published_at": playlist["snippet"]["publishedAt"],
                        }
                    )

                if len(playlists) >= max_results or "nextPageToken" not in response:
                    break

                next_page_token = response["nextPageToken"]

            return playlists[:max_results]

        except HttpError as e:
            logger.error(f"Error getting user playlists: {e}")
            return []
