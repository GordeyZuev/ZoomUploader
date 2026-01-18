import asyncio
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import httpx

from logger import get_logger
from models import MeetingRecording, ProcessingStatus
from utils.formatting import normalize_datetime_string

logger = get_logger()


class ZoomDownloader:
    """Zoom file downloader"""

    def __init__(self, download_dir: str = "media/video/unprocessed"):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Downloader initialized: {self.download_dir}")

    def _encode_download_url(self, url: str) -> str:
        """Correct URL encoding for downloading according to Zoom documentation."""
        if "==" in url or "//" in url:
            encoded = quote(url, safe="/:")
            double_encoded = quote(encoded, safe="/:")
            logger.debug(f"Double URL encoding completed: {url} -> {double_encoded}")
            return double_encoded
        return url

    def _get_filename(self, recording: MeetingRecording) -> str:
        display_name = recording.display_name.strip() if recording.display_name else ""
        safe_name = "".join(c for c in display_name if c.isalnum() or c in (" ", "-", "_", "(", ")")).strip()
        if len(safe_name) > 60:
            safe_name = safe_name[:60].rstrip()
        if recording.start_time and recording.start_time.strip():
            try:
                normalized_time = normalize_datetime_string(recording.start_time)
                date_obj = datetime.fromisoformat(normalized_time)
                formatted_date = date_obj.strftime("%d.%m.%Y")
            except Exception as e:
                logger.debug(f"Error parsing date in _get_filename '{recording.start_time}': {e}")
                formatted_date = "unknown_date"
        else:
            formatted_date = "unknown_date"

        return f"{safe_name} ({formatted_date}).mp4"

    async def download_file(
        self,
        url: str,
        filepath: Path,
        description: str = "file",
        expected_size: int | None = None,
        password: str | None = None,
        passcode: str | None = None,
        download_access_token: str | None = None,
        oauth_token: str | None = None,
        max_retries: int = 10,
    ) -> bool:
        """Download file by URL with resume and retry mechanism."""

        for attempt in range(max_retries):
            try:
                if attempt > 0:
                    logger.info(f"🔄 Download attempt {attempt + 1}/{max_retries}: {description}")
                else:
                    logger.debug(f"Starting download {description}: {url}")

                # Check if there is a partially downloaded file
                downloaded = 0
                if filepath.exists():
                    downloaded = filepath.stat().st_size
                    logger.info(
                        f"📦 Partially downloaded file found: {downloaded} bytes ({downloaded / (1024 * 1024):.1f} MB)"
                    )

                encoded_url = self._encode_download_url(url)

                headers = {}
                params = {}

                logger.info(
                    f"🔐 Authentication check: oauth_token={bool(oauth_token)}, download_access_token={bool(download_access_token)}, passcode={bool(passcode)}, password={bool(password)}"
                )

                if oauth_token:
                    headers["Authorization"] = f"Bearer {oauth_token}"
                    logger.info(f"✅ Using OAuth access token for authentication (length: {len(oauth_token)})")
                elif download_access_token:
                    headers["Authorization"] = f"Bearer {download_access_token}"
                    logger.info(
                        f"✅ Using download_access_token for authentication (length: {len(download_access_token)})"
                    )
                elif passcode:
                    headers["X-Zoom-Passcode"] = passcode
                    headers["Authorization"] = f"Bearer {passcode}"
                    logger.info(f"✅ Using passcode for authentication (length: {len(passcode)})")
                elif password:
                    params["password"] = password
                    params["access_token"] = password
                    logger.info(f"✅ Using password for authentication: {password}")
                else:
                    logger.warning("⚠️ No authentication data!")

                # Add Range header for continued download
                if downloaded > 0:
                    headers["Range"] = f"bytes={downloaded}-"
                    logger.info(f"🔄 Continuing download from byte {downloaded}")

                logger.debug(f"Headers: {headers}")
                logger.debug(f"Parameters: {params}")

                # Optimized timeouts for fast detection of break
                async with httpx.AsyncClient(
                    timeout=httpx.Timeout(
                        timeout=180.0,  # total timeout 3 minutes
                        connect=30.0,  # connection 30 seconds
                        read=60.0,  # read data 60 seconds (faster detection of break)
                        write=30.0,  # write 30 seconds
                    ),
                    follow_redirects=True,
                    limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
                ) as client:
                    async with client.stream("GET", encoded_url, headers=headers, params=params) as response:
                        # Check support for Range (206 Partial Content)
                        if downloaded > 0 and response.status_code == 206:
                            logger.info("✅ Server supports resume (206 Partial Content)")
                            mode = "ab"  # append binary
                        elif downloaded > 0 and response.status_code == 200:
                            logger.warning("⚠️ Server does not support resume, starting over")
                            downloaded = 0
                            mode = "wb"
                            # Remove old file to start from zero
                            if filepath.exists():
                                filepath.unlink()
                        else:
                            response.raise_for_status()
                            mode = "wb"

                        filepath.parent.mkdir(parents=True, exist_ok=True)

                        # Get full size from Content-Range or Content-Length
                        content_range = response.headers.get("content-range")
                        if content_range:
                            # Format: "bytes 1000-2000/3000" (Content-Range header)
                            total_size = int(content_range.split("/")[-1])
                            logger.debug(f"Content-Range received: {content_range}, total_size: {total_size}")
                        else:
                            total_size = int(response.headers.get("content-length", 0))
                            if downloaded > 0 and mode == "ab":
                                total_size += downloaded

                        if total_size == 0 and expected_size:
                            total_size = expected_size

                        logger.debug(
                            f"File size: {total_size} bytes ({total_size / (1024 * 1024):.1f} MB), already downloaded: {downloaded} bytes ({downloaded / (1024 * 1024):.1f} MB)"
                        )

                        # Open file in the needed mode (wb or ab)
                        with open(filepath, mode) as f:
                            chunk_count = 0
                            bytes_in_session = 0

                            async for chunk in response.aiter_bytes(chunk_size=8192):
                                f.write(chunk)
                                chunk_size = len(chunk)
                                bytes_in_session += chunk_size
                                downloaded += chunk_size
                                chunk_count += 1

                        logger.info(
                            f"✅ File written: {downloaded}/{total_size} bytes ({downloaded / (1024 * 1024):.1f}/{total_size / (1024 * 1024):.1f} MB)"
                        )

                # Check if the file is correct only on the last iteration or when successful download
                if not self._validate_downloaded_file(filepath, expected_size, total_size):
                    logger.warning(f"⚠️ Downloaded {description} is incorrect or incomplete")
                    if attempt < max_retries - 1:
                        wait_time = 3 if attempt < 2 else 5  # Fast retry for validation
                        logger.info(
                            f"🔄 Retry attempt {attempt + 2}/{max_retries} through {wait_time} seconds (file incomplete)..."
                        )
                        await asyncio.sleep(wait_time)
                        continue
                    logger.error(f"❌ All download attempts exhausted for {description}")
                    if filepath.exists():
                        filepath.unlink()
                    return False

                logger.debug(f"File successfully downloaded: description={description} | path={filepath}")
                return True

            except (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError, httpx.ReadTimeout) as e:
                logger.warning(f"⚠️ Network error during download {description}: {type(e).__name__}: {e}")
                if attempt < max_retries - 1:
                    # More aggressive backoff: 3s → 5s → 10s → 15s → 20s → 30s (max)
                    if attempt < 2:
                        wait_time = 3 + attempt * 2  # 3s, 5s
                    else:
                        wait_time = min(10 + (attempt - 2) * 5, 30)  # 10s, 15s, 20s, 25s, 30s...
                    logger.info(f"🔄 Retry attempt {attempt + 2}/{max_retries} through {wait_time} seconds...")
                    await asyncio.sleep(wait_time)
                    continue
                logger.error(f"❌ All download attempts exhausted for {description} after network errors")
                # Do not delete partially downloaded file - can continue later!
                return False

            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                # Special handling for 416 Range Not Satisfiable - file may have been already downloaded or size changed
                if status == 416 and filepath.exists():
                    logger.warning("⚠️ Received 416 Range Not Satisfiable - restarting download from zero")
                    try:
                        filepath.unlink()
                        downloaded = 0  # reset size for the next attempt
                    except Exception as e:
                        logger.warning(f"Ignored exception: {e}")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(1)
                        continue

                logger.error(f"❌ HTTP error during download {description}: {status}")
                if filepath.exists() and status >= 400:
                    filepath.unlink()
                return False

            except Exception as e:
                logger.error(f"❌ Unexpected error during download {description}: {type(e).__name__}: {e}")
                if attempt < max_retries - 1:
                    wait_time = 5
                    logger.info(
                        f"🔄 Retry attempt {attempt + 2}/{max_retries} through {wait_time} seconds (unexpected error)..."
                    )
                    await asyncio.sleep(wait_time)
                    continue
                if filepath.exists():
                    filepath.unlink()
                return False

        return False

    def _validate_downloaded_file(
        self, filepath: Path, expected_size: int | None = None, total_size: int | None = None
    ) -> bool:
        """Check if the downloaded file is correct."""
        try:
            if not filepath.exists():
                return False

            file_size = filepath.stat().st_size

            if file_size < 1024:
                logger.warning(f"File too small: {file_size} bytes")
                return False

            # Use total_size from Content-Range if available, otherwise expected_size
            reference_size = total_size or expected_size

            # Check if the file is fully downloaded (if we know the expected size)
            if reference_size:
                if file_size < reference_size:
                    # File is not fully downloaded
                    logger.warning(
                        f"File not fully downloaded: {file_size}/{reference_size} bytes "
                        f"({file_size / (1024 * 1024):.1f}/{reference_size / (1024 * 1024):.1f} MB, "
                        f"{(file_size / reference_size * 100):.1f}%)"
                    )
                    return False
                if file_size > reference_size * 1.1:
                    # File is larger than expected by 10%+ - something is wrong
                    logger.warning(
                        f"File is larger than expected: {file_size} > {reference_size} "
                        f"({file_size / (1024 * 1024):.1f} > {reference_size / (1024 * 1024):.1f} MB)"
                    )

            with open(filepath, "rb") as f:
                first_chunk = f.read(1024)
                if b"<html" in first_chunk.lower() or b"<!doctype html" in first_chunk.lower():
                    logger.error("Downloaded file is an HTML page (possibly requires a password)")
                    return False

                if filepath.suffix.lower() == ".mp4":
                    if not (
                        first_chunk.startswith(b"\x00\x00\x00") or b"ftyp" in first_chunk or b"moov" in first_chunk
                    ):
                        logger.error("File is not a valid MP4 video")
                        return False

            logger.debug(
                f"File passed validation: path={filepath} | size={file_size}bytes ({file_size / (1024 * 1024):.1f}MB)"
            )
            return True

        except Exception as e:
            logger.error(f"Error during file validation {filepath}: {e}")
            return False

    async def download_recording(
        self,
        recording: MeetingRecording,
        force_download: bool = False,
    ) -> bool:
        """Download one recording (one MP4)."""
        logger.debug(f"Starting download of recording: {recording.display_name}")

        if not recording.video_file_download_url:
            logger.error(f"No video link for {recording.display_name}")
            recording.mark_failure(
                reason="No video link",
                rollback_to_status=ProcessingStatus.INITIALIZED,
                failed_at_stage="downloading",
            )
            return False

        # Skip if already downloaded and file exists (if force=False)
        if (
            not force_download
            and recording.status == ProcessingStatus.DOWNLOADED
            and recording.local_video_path
            and Path(recording.local_video_path).exists()
        ):
            logger.info(f"⏭️ Recording already downloaded, skipping: {recording.display_name}")
            return False

        recording.update_status(ProcessingStatus.DOWNLOADING)

        base_filename = self._get_filename(recording)
        final_path = self.download_dir / base_filename

        fresh_download_token = None
        if recording.download_access_token:
            try:
                from api.zoom_api import ZoomAPI
                from config.accounts import ZOOM_ACCOUNTS

                account_config = ZOOM_ACCOUNTS.get(recording.account)
                if account_config:
                    api = ZoomAPI(account_config)
                    detailed_data = await api.get_recording_details(recording.meeting_id, include_download_token=True)
                    fresh_download_token = detailed_data.get("download_access_token")
                    logger.info(
                        f"🔄 Fresh download_access_token received (length: {len(fresh_download_token) if fresh_download_token else 0})"
                    )
                else:
                    logger.warning(f"⚠️ No config found for account: {recording.account}")
            except Exception as e:
                logger.error(f"❌ Error getting fresh token: {e}")
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
                    f"🔄 OAuth access token received for authentication (length: {len(oauth_token) if oauth_token else 0})"
                )
        except Exception as e:
            logger.error(f"❌ Error getting OAuth token: {e}")

        total_size = recording.video_file_size or 0

        success = await self.download_file(
            recording.video_file_download_url,
            final_path,
            "video file",
            total_size,
            recording.password,
            recording.recording_play_passcode,
            fresh_download_token or recording.download_access_token,
            oauth_token,
            max_retries=10,
        )

        if not success:
            recording.mark_failure(
                reason="Error downloading file",
                rollback_to_status=ProcessingStatus.INITIALIZED,
                failed_at_stage="downloading",
            )
            logger.error(f"❌ Error downloading recording {recording.display_name}")
            return False

        try:
            recording.local_video_path = str(final_path.relative_to(Path.cwd()))
        except ValueError:
            recording.local_video_path = str(final_path)
        recording.update_status(ProcessingStatus.DOWNLOADED)
        recording.downloaded_at = datetime.now()
        logger.debug(
            f"Recording successfully downloaded: recording={recording.display_name} | recording_id={recording.db_id} | path={recording.local_video_path}"
        )
        return True
