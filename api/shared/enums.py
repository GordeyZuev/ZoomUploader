from enum import Enum


class InputPlatform(str, Enum):
    ZOOM = "zoom"
    YANDEX_DISK = "yandex_disk"
    GOOGLE_DRIVE = "google_drive"
    DROPBOX = "dropbox"
    LOCAL = "local"


class OutputPlatform(str, Enum):
    YOUTUBE = "youtube"
    VK_VIDEO = "vk_video"
    YANDEX_DISK = "yandex_disk"
    GOOGLE_DRIVE = "google_drive"
    TELEGRAM = "telegram"
    RUTUBE = "rutube"
    LOCAL = "local"


class CredentialPlatform(str, Enum):
    ZOOM = "zoom"
    YOUTUBE = "youtube"
    VK_VIDEO = "vk_video"
    YANDEX_DISK = "yandex_disk"
    GOOGLE_DRIVE = "google_drive"
    DROPBOX = "dropbox"
    FIREWORKS = "fireworks"
    DEEPSEEK = "deepseek"
    OPENAI = "openai"
    TELEGRAM = "telegram"
    RUTUBE = "rutube"
