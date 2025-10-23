"""
Конфигурация для обработки видео (совместимость с Pydantic Settings)
"""

from config.settings import settings


class ProcessingConfig:
    """Конфигурация обработки видео (совместимость)"""

    def __init__(self, processing_settings=None):
        if processing_settings is None:
            processing_settings = settings.processing

        # Основные настройки
        self.output_format: str = "mp4"
        self.video_codec: str = processing_settings.video_codec
        self.audio_codec: str = processing_settings.audio_codec

        # Качество видео
        self.video_bitrate: str = processing_settings.video_bitrate
        self.audio_bitrate: str = processing_settings.audio_bitrate
        self.resolution: str = processing_settings.resolution
        self.fps: int = processing_settings.fps

        # Обрезка по звуку
        self.audio_detection: bool = True
        self.silence_threshold: float = processing_settings.silence_threshold
        self.min_silence_duration: float = processing_settings.min_silence_duration
        self.padding_before: float = processing_settings.padding_before
        self.padding_after: float = processing_settings.padding_after

        # Обрезка (для ручной настройки)
        self.trim_start: float | None = None
        self.trim_end: float | None = None
        self.max_duration: int | None = None

        # Сегментация
        self.segment_duration: int = 30
        self.overlap_duration: int = 1

        # Папки
        self.input_dir: str = processing_settings.input_dir
        self.output_dir: str = processing_settings.output_dir
        self.temp_dir: str = processing_settings.temp_dir

        # Дополнительные опции
        self.remove_intro: bool = processing_settings.remove_intro
        self.remove_outro: bool = processing_settings.remove_outro
        self.intro_duration: int = processing_settings.intro_duration
        self.outro_duration: int = processing_settings.outro_duration

        # Логирование
        self.verbose: bool = True
        self.keep_temp_files: bool = processing_settings.keep_temp_files

    def __post_init__(self):
        """Валидация конфигурации"""
        if self.max_duration and self.max_duration <= 0:
            raise ValueError("max_duration должен быть положительным числом")

        if self.segment_duration <= 0:
            raise ValueError("segment_duration должен быть положительным числом")

        if self.overlap_duration < 0:
            raise ValueError("overlap_duration не может быть отрицательным")

        if self.overlap_duration >= self.segment_duration:
            raise ValueError("overlap_duration должен быть меньше segment_duration")

        # Валидация настроек детекции звука
        if self.silence_threshold > 0:
            raise ValueError("silence_threshold должен быть отрицательным числом")

        if self.min_silence_duration <= 0:
            raise ValueError("min_silence_duration должен быть положительным числом")

        if self.padding_before < 0 or self.padding_after < 0:
            raise ValueError("padding значения не могут быть отрицательными")
