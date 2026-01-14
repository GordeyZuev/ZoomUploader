"""Transcription and topics file manager"""

import json
from datetime import datetime
from pathlib import Path

from logger import get_logger

logger = get_logger(__name__)


class TranscriptionManager:
    """Manage transcription files (master.json, topics.json, cache)"""

    def __init__(self, base_dir: str | Path | None = None):
        """
        Args:
            base_dir: Базовая директория для хранения транскрибаций (deprecated, используйте user_id)
        """
        self.base_dir = Path(base_dir) if base_dir else None

    def get_dir(self, recording_id: int, user_id: int | None = None) -> Path:
        """
        Получить путь к папке транскрибации для записи.

        Args:
            recording_id: ID записи
            user_id: ID пользователя (обязательно для multi-tenancy)

        Returns:
            Путь к директории транскрипции
        """
        if user_id is None:
            raise ValueError("user_id is required for transcription directory")

        # Используем UserPathManager для изоляции по пользователям
        from utils.user_paths import get_path_manager
        path_manager = get_path_manager()
        return path_manager.get_transcription_dir(user_id, recording_id)

    def has_master(self, recording_id: int, user_id: int | None = None) -> bool:
        """Проверить наличие master.json."""
        return (self.get_dir(recording_id, user_id) / "master.json").exists()

    def has_topics(self, recording_id: int, user_id: int | None = None) -> bool:
        """Проверить наличие topics.json."""
        return (self.get_dir(recording_id, user_id) / "topics.json").exists()

    def save_master(
        self,
        recording_id: int,
        words: list[dict],
        segments: list[dict],
        language: str = "ru",
        model: str = "fireworks",
        duration: float = 0.0,
        usage_metadata: dict | None = None,
        user_id: int | None = None,
        **meta,
    ) -> str:
        """
        Сохранить master.json с результатами транскрибации.

        Args:
            recording_id: ID записи
            words: Список слов с временными метками
            segments: Список сегментов с временными метками
            language: Язык транскрибации
            model: Модель транскрибации
            duration: Длительность видео в секундах
            usage_metadata: Метаданные использования (токены, промпт и т.д.) для админа
            user_id: ID пользователя (для multi-tenancy)
            **meta: Дополнительные метаданные

        Returns:
            Путь к созданному master.json
        """
        dir_path = self.get_dir(recording_id, user_id)
        dir_path.mkdir(parents=True, exist_ok=True)

        # Подсчитываем статистику
        stats = {
            "words_count": len(words),
            "segments_count": len(segments),
            "total_duration": duration,
        }

        master_data = {
            "recording_id": recording_id,
            "created_at": datetime.now().isoformat(),
            "model": model,
            "language": language,
            "duration": duration,
            "words": words,
            "segments": segments,
            "stats": stats,
            "_metadata": usage_metadata or {},  # Административные метаданные
            **meta,
        }

        master_path = dir_path / "master.json"
        with open(master_path, "w", encoding="utf-8") as f:
            json.dump(master_data, f, ensure_ascii=False, indent=2)

        logger.info(
            f"✅ Saved master.json: {master_path} | words={len(words)} | segments={len(segments)} | "
            f"language={language} | model={model}"
        )
        return str(master_path)

    def load_master(self, recording_id: int, user_id: int | None = None) -> dict:
        """
        Загрузить master.json.

        Args:
            recording_id: ID записи
            user_id: ID пользователя (для multi-tenancy)

        Returns:
            Данные из master.json

        Raises:
            FileNotFoundError: Если master.json не найден
        """
        master_path = self.get_dir(recording_id, user_id) / "master.json"
        if not master_path.exists():
            raise FileNotFoundError(f"master.json not found for recording {recording_id}: {master_path}")

        with open(master_path, encoding="utf-8") as f:
            return json.load(f)

    def add_topics_version(
        self,
        recording_id: int,
        version_id: str,
        model: str,
        granularity: str,
        main_topics: list[str],
        topic_timestamps: list[dict],
        pauses: list[dict] | None = None,
        is_active: bool = True,
        usage_metadata: dict | None = None,
        user_id: int | None = None,
        **meta,
    ) -> str:
        """
        Добавить версию топиков в topics.json.

        Args:
            recording_id: ID записи
            version_id: ID версии (например, "v1", "v2")
            model: Модель для извлечения тем
            granularity: Режим извлечения ("short" | "long")
            main_topics: Основные темы
            topic_timestamps: Список топиков с временными метками
            pauses: Список пауз (опционально)
            is_active: Активная версия (по умолчанию True)
            usage_metadata: Метаданные использования (токены, промпт и т.д.) для админа
            user_id: ID пользователя (для multi-tenancy)
            **meta: Дополнительные метаданные

        Returns:
            Путь к topics.json
        """
        topics_path = self.get_dir(recording_id, user_id) / "topics.json"

        # Загружаем существующий topics.json или создаём новый
        if topics_path.exists():
            with open(topics_path, encoding="utf-8") as f:
                topics_file = json.load(f)
        else:
            topics_file = {
                "recording_id": recording_id,
                "active_version": None,
                "versions": [],
            }

        # Если новая версия активна, деактивируем остальные
        if is_active:
            for v in topics_file["versions"]:
                v["is_active"] = False
            topics_file["active_version"] = version_id

        # Добавляем новую версию
        version_data = {
            "id": version_id,
            "model": model,
            "granularity": granularity,
            "created_at": datetime.now().isoformat(),
            "is_active": is_active,
            "main_topics": main_topics,
            "topic_timestamps": topic_timestamps,
            "pauses": pauses or [],
            "_metadata": usage_metadata or {},  # Административные метаданные (токены, промпт, модель)
            **meta,
        }

        topics_file["versions"].append(version_data)

        # Сохраняем
        topics_path.parent.mkdir(parents=True, exist_ok=True)
        with open(topics_path, "w", encoding="utf-8") as f:
            json.dump(topics_file, f, ensure_ascii=False, indent=2)

        logger.info(
            f"✅ Added topics version '{version_id}': {topics_path} | "
            f"topics={len(topic_timestamps)} | main_topics={len(main_topics)} | "
            f"model={model}"
        )
        return str(topics_path)

    def load_topics(self, recording_id: int, user_id: int | None = None) -> dict:
        """
        Загрузить topics.json.

        Args:
            recording_id: ID записи
            user_id: ID пользователя (для multi-tenancy)

        Returns:
            Данные из topics.json

        Raises:
            FileNotFoundError: Если topics.json не найден
        """
        topics_path = self.get_dir(recording_id, user_id) / "topics.json"
        if not topics_path.exists():
            raise FileNotFoundError(f"topics.json not found for recording {recording_id}: {topics_path}")

        with open(topics_path, encoding="utf-8") as f:
            return json.load(f)

    def get_active_topics(self, recording_id: int, user_id: int | None = None) -> dict | None:
        """
        Получить активную версию топиков.

        Args:
            recording_id: ID записи
            user_id: ID пользователя (для multi-tenancy)

        Returns:
            Данные активной версии топиков или None
        """
        try:
            topics_data = self.load_topics(recording_id, user_id)
            active_version_id = topics_data.get("active_version")

            if not active_version_id:
                return None

            for version in topics_data.get("versions", []):
                if version.get("id") == active_version_id:
                    return version

            return None
        except FileNotFoundError:
            return None

    def generate_cache_files(self, recording_id: int, user_id: int | None = None) -> dict[str, str]:
        """
        Генерировать кэш-файлы из master.json.

        Args:
            recording_id: ID записи
            user_id: ID пользователя (для multi-tenancy)

        Returns:
            Словарь с путями к созданным файлам
        """
        master = self.load_master(recording_id, user_id)
        cache_dir = self.get_dir(recording_id, user_id) / "cache"
        cache_dir.mkdir(exist_ok=True)

        files = {}

        # segments.txt
        segments_path = cache_dir / "segments.txt"
        self._generate_segments_txt(master["segments"], segments_path)
        files["segments_txt"] = str(segments_path)

        # words.txt
        words_path = cache_dir / "words.txt"
        self._generate_words_txt(master["words"], words_path)
        files["words_txt"] = str(words_path)

        # auto_segments.txt (пока копия segments)
        auto_segments_path = cache_dir / "auto_segments.txt"
        self._generate_segments_txt(master["segments"], auto_segments_path)
        files["auto_segments_txt"] = str(auto_segments_path)

        logger.info(f"✅ Generated cache files for recording {recording_id}: {list(files.keys())}")
        return files

    def ensure_segments_txt(self, recording_id: int, user_id: int | None = None) -> Path:
        """
        Гарантировать наличие segments.txt (генерируем если нет).

        Args:
            recording_id: ID записи
            user_id: ID пользователя (для multi-tenancy)

        Returns:
            Путь к segments.txt
        """
        segments_path = self.get_dir(recording_id, user_id) / "cache" / "segments.txt"

        if not segments_path.exists():
            master = self.load_master(recording_id, user_id)
            segments_path.parent.mkdir(parents=True, exist_ok=True)
            self._generate_segments_txt(master["segments"], segments_path)

        return segments_path

    def generate_subtitles(self, recording_id: int, formats: list[str], user_id: int | None = None) -> dict[str, str]:
        """
        Генерировать субтитры из master.json.

        Args:
            recording_id: ID записи
            formats: Список форматов ('srt', 'vtt')
            user_id: ID пользователя (для multi-tenancy)

        Returns:
            Словарь {формат: путь_к_файлу}
        """
        from subtitle_module import SubtitleGenerator

        # Гарантируем наличие segments.txt
        segments_path = self.ensure_segments_txt(recording_id, user_id)
        cache_dir = self.get_dir(recording_id, user_id) / "cache"

        generator = SubtitleGenerator()
        result = generator.generate_from_transcription(
            transcription_path=str(segments_path),
            output_dir=str(cache_dir),
            formats=formats,
        )

        logger.info(f"✅ Generated subtitles for recording {recording_id}: formats={formats}")
        return result

    def generate_version_id(self, recording_id: int, user_id: int | None = None) -> str:
        """
        Генерировать ID для новой версии топиков.

        Args:
            recording_id: ID записи
            user_id: ID пользователя (для multi-tenancy)

        Returns:
            ID версии (например, "v1", "v2")
        """
        try:
            topics_data = self.load_topics(recording_id, user_id)
            version_count = len(topics_data.get("versions", []))
            return f"v{version_count + 1}"
        except FileNotFoundError:
            return "v1"

    def _generate_segments_txt(self, segments: list[dict], output_path: Path):
        """Генерировать segments.txt из списка сегментов."""
        with open(output_path, "w", encoding="utf-8") as f:
            for seg in segments:
                start = self._format_time_ms(seg["start"])
                end = self._format_time_ms(seg["end"])
                text = seg["text"]
                f.write(f"[{start} - {end}] {text}\n")

        logger.debug(f"Generated segments.txt: {output_path} | count={len(segments)}")

    def _generate_words_txt(self, words: list[dict], output_path: Path):
        """Генерировать words.txt из списка слов."""
        with open(output_path, "w", encoding="utf-8") as f:
            for word in words:
                start = self._format_time_ms(word["start"])
                end = self._format_time_ms(word["end"])
                text = word["word"]
                f.write(f"[{start} - {end}] {text}\n")

        logger.debug(f"Generated words.txt: {output_path} | count={len(words)}")

    @staticmethod
    def _format_time_ms(seconds: float) -> str:
        """Форматировать время в HH:MM:SS.mmm."""
        total_seconds = int(seconds)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        secs = total_seconds % 60
        milliseconds = int((seconds - total_seconds) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}.{milliseconds:03d}"


# Синглтон
_transcription_manager = None


def get_transcription_manager() -> TranscriptionManager:
    """Получить глобальный экземпляр TranscriptionManager."""
    global _transcription_manager
    if _transcription_manager is None:
        _transcription_manager = TranscriptionManager()
    return _transcription_manager

