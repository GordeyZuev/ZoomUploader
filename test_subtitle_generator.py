"""Тестовый скрипт для проверки генератора субтитров"""

import os

from subtitle_module import SubtitleGenerator


def test_subtitle_generation():
    """Тест генерации субтитров из примера транскрипции"""

    # Путь к тестовому файлу транскрипции
    test_transcription = "media/transcriptions/old/transcription_Тестовая запись.txt"

    if not os.path.exists(test_transcription):
        print(f"❌ Файл транскрипции не найден: {test_transcription}")
        return

    print(f"📝 Тестирование генерации субтитров из: {test_transcription}")

    generator = SubtitleGenerator()

    try:
        # Парсим транскрипцию
        entries = generator.parse_transcription_file(test_transcription)
        print(f"✅ Извлечено {len(entries)} записей из транскрипции")

        if entries:
            print(f"   Первая запись: {entries[0]}")
            print(f"   Последняя запись: {entries[-1]}")

        # Генерируем субтитры
        result = generator.generate_from_transcription(transcription_path=test_transcription, formats=["srt", "vtt"])

        print("\n✅ Субтитры успешно сгенерированы:")
        for fmt, path in result.items():
            if os.path.exists(path):
                size = os.path.getsize(path)
                print(f"   {fmt.upper()}: {path} ({size} байт)")
            else:
                print(f"   {fmt.upper()}: {path} (файл не найден)")

    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    test_subtitle_generation()
