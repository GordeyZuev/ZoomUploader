#!/usr/bin/env python3
"""Тестовый скрипт для проверки транскрибации через Fireworks"""

import asyncio
import sys
from pathlib import Path

from logger import get_logger, setup_logger
from transcription_module import TranscriptionService

# Настройка логирования
setup_logger()
logger = get_logger()


async def test_fireworks_transcription(audio_path: str):
    """Тест транскрибации через Fireworks"""
    audio_file = Path(audio_path)

    if not audio_file.exists():
        logger.error(f"❌ Файл не найден: {audio_path}")
        return False

    file_size_mb = audio_file.stat().st_size / (1024 * 1024)
    logger.info(f"📁 Файл: {audio_path}")
    logger.info(f"📊 Размер: {file_size_mb:.2f} МБ")

    try:
        # Создаем сервис транскрибации
        logger.info("🔧 Инициализация сервиса транскрибации...")
        transcription_service = TranscriptionService()

        # Выполняем транскрибацию через Fireworks
        logger.info("🎆 Запуск транскрибации через Fireworks...")
        result = await transcription_service.process_audio(
            audio_path=audio_path,
            recording_id=None,
            recording_topic="Тестовая запись",
        )

        # Выводим результаты
        logger.info("✅ Транскрибация завершена успешно!")
        logger.info(f"📝 Длина текста: {len(result.get('transcription_text', ''))} символов")
        logger.info(f"📊 Количество сегментов: {len(result.get('topic_timestamps', []))}")
        logger.info(f"📁 Папка транскрипции: {result.get('transcription_dir', 'N/A')}")

        if result.get("main_topics"):
            logger.info(f"🔍 Основные темы: {', '.join(result['main_topics'])}")

        # Показываем первые 500 символов текста
        text = result.get("transcription_text", "")
        if text:
            preview = text[:500] + "..." if len(text) > 500 else text
            logger.info(f"\n📖 Превью транскрипции:\n{preview}\n")

        return True

    except Exception as e:
        logger.error(f"❌ Ошибка при транскрибации: {e}")
        import traceback

        logger.error(traceback.format_exc())
        return False


async def main():
    """Главная функция"""
    if len(sys.argv) < 2:
        # Используем файл по умолчанию
        audio_path = "media/processed_audio/ИИ_1_курс_НИС__Машинное_обучение_processed.mp3"
    else:
        audio_path = sys.argv[1]

    logger.info("=" * 70)
    logger.info("🧪 ТЕСТ ТРАНСКРИБАЦИИ ЧЕРЕЗ FIREWORKS")
    logger.info("=" * 70)
    logger.info("")

    success = await test_fireworks_transcription(audio_path)

    logger.info("")
    logger.info("=" * 70)
    if success:
        logger.info("✅ ТЕСТ ЗАВЕРШЕН УСПЕШНО")
    else:
        logger.info("❌ ТЕСТ ЗАВЕРШЕН С ОШИБКОЙ")
    logger.info("=" * 70)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
