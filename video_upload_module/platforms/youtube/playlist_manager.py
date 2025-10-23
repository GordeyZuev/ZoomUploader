"""
Менеджер плейлистов YouTube
"""

from typing import Any

from googleapiclient.errors import HttpError

from logger import get_logger

from ...config_factory import YouTubeConfig

logger = get_logger()


class YouTubePlaylistManager:
    """Менеджер для работы с плейлистами YouTube"""

    def __init__(self, service, config: YouTubeConfig):
        self.service = service
        self.config = config

        # Импортируем логгер только при необходимости
        try:
            from logger import get_logger

            self.logger = get_logger()
        except ImportError:
            import logging

            self.logger = logging.getLogger(__name__)

    async def create_playlist(
        self, title: str, description: str = "", privacy_status: str = "private"
    ) -> str | None:
        """Создание плейлиста"""
        try:
            body = {
                'snippet': {'title': title, 'description': description},
                'status': {'privacyStatus': privacy_status},
            }

            request = self.service.playlists().insert(part='snippet,status', body=body)
            response = request.execute()

            playlist_id = response['id']
            playlist_url = f"https://www.youtube.com/playlist?list={playlist_id}"

            logger.info(f"📋 Плейлист создан: {playlist_url}")
            return playlist_id

        except HttpError as e:
            logger.error(f"❌ Ошибка создания плейлиста: {e}")
            return None

    async def add_video_to_playlist(self, playlist_id: str, video_id: str) -> bool:
        """Добавление видео в плейлист"""
        try:
            body = {
                'snippet': {
                    'playlistId': playlist_id,
                    'resourceId': {'kind': 'youtube#video', 'videoId': video_id},
                }
            }

            request = self.service.playlistItems().insert(part='snippet', body=body)
            request.execute()

            logger.info(f"📋 Видео добавлено в плейлист {playlist_id}")
            return True
        except HttpError as e:
            logger.error(f"❌ Ошибка добавления в плейлист: {e}")
            return False

    async def remove_video_from_playlist(self, playlist_item_id: str) -> bool:
        """Удаление видео из плейлиста"""
        try:
            request = self.service.playlistItems().delete(id=playlist_item_id)
            request.execute()

            logger.info("📋 Видео удалено из плейлиста")
            return True
        except HttpError as e:
            logger.error(f"❌ Ошибка удаления из плейлиста: {e}")
            return False

    async def get_playlist_info(self, playlist_id: str) -> dict[str, Any] | None:
        """Получение информации о плейлисте"""
        try:
            request = self.service.playlists().list(
                part='snippet,contentDetails,status', id=playlist_id
            )
            response = request.execute()

            if response['items']:
                playlist = response['items'][0]
                return {
                    'title': playlist['snippet']['title'],
                    'description': playlist['snippet']['description'],
                    'item_count': playlist['contentDetails']['itemCount'],
                    'privacy_status': playlist['status']['privacyStatus'],
                    'published_at': playlist['snippet']['publishedAt'],
                }
            return None

        except HttpError as e:
            logger.error(f"❌ Ошибка получения информации о плейлисте: {e}")
            return None

    async def get_playlist_videos(
        self, playlist_id: str, max_results: int = 50
    ) -> list[dict[str, Any]]:
        """Получение списка видео в плейлисте"""
        try:
            videos = []
            next_page_token = None

            while True:
                request = self.service.playlistItems().list(
                    part='snippet,contentDetails',
                    playlistId=playlist_id,
                    maxResults=min(max_results, 50),
                    pageToken=next_page_token,
                )
                response = request.execute()

                for item in response['items']:
                    videos.append(
                        {
                            'video_id': item['contentDetails']['videoId'],
                            'title': item['snippet']['title'],
                            'description': item['snippet']['description'],
                            'position': item['snippet']['position'],
                        }
                    )

                if len(videos) >= max_results or 'nextPageToken' not in response:
                    break

                next_page_token = response['nextPageToken']

            return videos[:max_results]

        except HttpError as e:
            logger.error(f"❌ Ошибка получения видео плейлиста: {e}")
            return []

    async def update_playlist(
        self, playlist_id: str, title: str | None = None, description: str | None = None
    ) -> bool:
        """Обновление плейлиста"""
        try:
            body = {'id': playlist_id, 'snippet': {}}

            if title:
                body['snippet']['title'] = title
            if description:
                body['snippet']['description'] = description

            request = self.service.playlists().update(part='snippet', body=body)
            request.execute()

            logger.info(f"📋 Плейлист обновлен: {playlist_id}")
            return True

        except HttpError as e:
            logger.error(f"❌ Ошибка обновления плейлиста: {e}")
            return False

    async def delete_playlist(self, playlist_id: str) -> bool:
        """Удаление плейлиста"""
        try:
            request = self.service.playlists().delete(id=playlist_id)
            request.execute()

            logger.info(f"📋 Плейлист удален: {playlist_id}")
            return True

        except HttpError as e:
            logger.error(f"❌ Ошибка удаления плейлиста: {e}")
            return False

    async def get_user_playlists(self, max_results: int = 50) -> list[dict[str, Any]]:
        """Получение плейлистов пользователя"""
        try:
            playlists = []
            next_page_token = None

            while True:
                request = self.service.playlists().list(
                    part='snippet,contentDetails',
                    mine=True,
                    maxResults=min(max_results, 50),
                    pageToken=next_page_token,
                )
                response = request.execute()

                for playlist in response['items']:
                    playlists.append(
                        {
                            'playlist_id': playlist['id'],
                            'title': playlist['snippet']['title'],
                            'description': playlist['snippet']['description'],
                            'item_count': playlist['contentDetails']['itemCount'],
                            'published_at': playlist['snippet']['publishedAt'],
                        }
                    )

                if len(playlists) >= max_results or 'nextPageToken' not in response:
                    break

                next_page_token = response['nextPageToken']

            return playlists[:max_results]

        except HttpError as e:
            logger.error(f"❌ Ошибка получения плейлистов пользователя: {e}")
            return []
