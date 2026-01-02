"""Тестовый скрипт для проверки извлечения тем через DeepSeek v3.2 на Fireworks."""

import asyncio
import re
import sys
from pathlib import Path

from deepseek_module import DeepSeekConfig, TopicExtractor
from logger import get_logger, setup_logger


def parse_transcription_file(file_path: str) -> tuple[str, list[dict]]:
    """
    Парсинг файла транскрипции в формате [HH:MM:SS - HH:MM:SS] текст.

    Args:
        file_path: Путь к файлу транскрипции

    Returns:
        Кортеж (полный текст, список сегментов)
    """
    with open(file_path, encoding="utf-8") as f:
        lines = f.readlines()

    segments: list[dict] = []
    full_text_parts: list[str] = []

    # Паттерн для [HH:MM:SS - HH:MM:SS] текст
    pattern = r"\[(\d{2}):(\d{2}):(\d{2})\s*-\s*(\d{2}):(\d{2}):(\d{2})\]\s*(.+)"

    for line in lines:
        line = line.strip()
        if not line:
            continue

        match = re.match(pattern, line)
        if match:
            start_h, start_m, start_s, end_h, end_m, end_s, text = match.groups()

            # Преобразуем время в секунды
            start_seconds = int(start_h) * 3600 + int(start_m) * 60 + int(start_s)
            end_seconds = int(end_h) * 3600 + int(end_m) * 60 + int(end_s)

            segments.append(
                {
                    "start": float(start_seconds),
                    "end": float(end_seconds),
                    "text": text.strip(),
                }
            )

            full_text_parts.append(text.strip())

    full_text = " ".join(full_text_parts)

    return full_text, segments


async def test_deepseek_fireworks_extraction(
    transcription_file: str,
    recording_topic: str | None = None,
    granularity: str = "long",
):
    """
    Тестирование извлечения тем через DeepSeek v3.2 на Fireworks.

    Args:
        transcription_file: Путь к файлу транскрипции
        recording_topic: Название курса/предмета (опционально)
        granularity: Режим извлечения тем ("short" или "long")
    """
    setup_logger()
    logger = get_logger()

    # Проверяем существование файла
    if not Path(transcription_file).exists():
        logger.error(f"❌ Файл транскрипции не найден: {transcription_file}")
        sys.exit(1)

    logger.info(f"📖 Загрузка транскрипции из: {transcription_file}")

    # Парсим транскрипцию
    try:
        transcription_text, segments = parse_transcription_file(transcription_file)
        logger.info(f"✅ Загружено: {len(segments)} сегментов, {len(transcription_text)} символов")
    except Exception as e:
        logger.error(f"❌ Ошибка при парсинге транскрипции: {e}")
        sys.exit(1)

    if not segments:
        logger.error("❌ Не найдено сегментов в транскрипции")
        sys.exit(1)

    # Загружаем конфигурацию DeepSeek через Fireworks
    try:
        deepseek_config = DeepSeekConfig.from_file("config/deepseek_fireworks_creds.json")
        logger.info(
            f"✅ Конфигурация Fireworks DeepSeek загружена: {deepseek_config.base_url}, model={deepseek_config.model}"
        )
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки конфигурации Fireworks DeepSeek: {e}")
        sys.exit(1)

    # Создаем TopicExtractor
    try:
        topic_extractor = TopicExtractor(deepseek_config)
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации TopicExtractor: {e}")
        sys.exit(1)

    # Запускаем извлечение тем
    logger.info(f"🚀 Начало извлечения тем через Fireworks DeepSeek (режим: {granularity})...")

    try:
        result = await topic_extractor.extract_topics(
            transcription_text=transcription_text,
            segments=segments,
            recording_topic=recording_topic,
            granularity=granularity,
        )

        # Выводим результаты
        print("\n" + "=" * 80)
        print("📊 РЕЗУЛЬТАТЫ ИЗВЛЕЧЕНИЯ ТЕМ (Fireworks DeepSeek)")
        print("=" * 80)

        main_topics = result.get("main_topics", [])
        topic_timestamps = result.get("topic_timestamps", [])

        if main_topics:
            print(f"\n🎯 ОСНОВНЫЕ ТЕМЫ ({len(main_topics)}):")
            for i, topic in enumerate(main_topics, 1):
                print(f"   {i}. {topic}")
        else:
            print("\n⚠️ Основные темы не найдены")

        if topic_timestamps:
            print(f"\n📝 ДЕТАЛИЗИРОВАННЫЕ ТОПИКИ ({len(topic_timestamps)}):")
            for ts in topic_timestamps:
                start = ts.get("start", 0)
                end = ts.get("end", 0)
                topic = ts.get("topic", "")

                # Форматируем время
                start_h = int(start // 3600)
                start_m = int((start % 3600) // 60)
                start_s = int(start % 60)
                end_h = int(end // 3600)
                end_m = int((end % 3600) // 60)
                end_s = int(end % 60)

                start_str = f"{start_h:02d}:{start_m:02d}:{start_s:02d}"
                end_str = f"{end_h:02d}:{end_m:02d}:{end_s:02d}"
                duration = end - start

                print(f"   [{start_str} - {end_str}] ({duration / 60:.1f} мин) {topic}")
        else:
            print("\n⚠️ Детализированные топики не найдены")

        print("\n" + "=" * 80)
        print("✅ Тестирование Fireworks DeepSeek завершено!")
        print("=" * 80 + "\n")

    except Exception as e:
        logger.error(f"❌ Ошибка при извлечении тем: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    import click

    @click.command()
    @click.argument("transcription_file", type=click.Path(exists=True))
    @click.option("--topic", "-t", help="Название курса/предмета (опционально)")
    @click.option(
        "--granularity",
        "-g",
        type=click.Choice(["short", "long"]),
        default="long",
        show_default=True,
        help="Режим извлечения тем: short (меньше тем, крупнее) или long (больше тем, детальнее)",
    )
    def main(transcription_file, topic, granularity):
        """Тестирование извлечения тем через DeepSeek v3.2 на Fireworks."""
        asyncio.run(test_deepseek_fireworks_extraction(transcription_file, topic, granularity))

    main()
