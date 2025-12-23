#!/usr/bin/env python3
"""Показ сырых данных от Zoom API на примере любой записи"""
import asyncio
import json
import sys

from api.zoom_api import ZoomAPI
from config import load_config_from_file
from config.settings import settings


async def main():
    # Загружаем конфигурацию Zoom
    config_file = settings.zoom.config_file
    configs = load_config_from_file(config_file)

    if not configs:
        print(f"Не найдено конфигураций в файле {config_file}")
        sys.exit(1)

    # Берем первый доступный аккаунт
    account = list(configs.keys())[0]
    config = configs[account]
    print(f"Используем аккаунт: {account}\n")

    # Создаем API клиент
    api = ZoomAPI(config)

    # Получаем записи за последний год
    from datetime import datetime, timedelta
    from_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

    print(f"Получаем записи с {from_date}...\n")

    try:
        # Получаем все записи
        response = await api.get_recordings(
            page_size=300,
            from_date=from_date
        )

        meetings = response.get('meetings', [])

        if not meetings:
            print("Записи не найдены")
            return

        # Берем первую запись с достаточной длительностью для примера
        example_meeting = None
        for meeting in meetings:
            if meeting.get('duration', 0) > 10:  # Берем запись длиннее 10 минут
                example_meeting = meeting
                break

        if not example_meeting:
            example_meeting = meetings[0]  # Иначе берем первую

        print("=" * 80)
        print("ПРИМЕР СЫРЫХ ДАННЫХ ОТ ZOOM API (get_recordings)")
        print("=" * 80)
        print(f"\nНазвание записи: {example_meeting.get('topic', 'Без названия')}\n")
        print(json.dumps(example_meeting, indent=2, ensure_ascii=False))

        # Также получаем детальную информацию
        meeting_id = example_meeting.get('uuid') or example_meeting.get('id')
        if meeting_id:
            print("\n\n" + "=" * 80)
            print("ПРИМЕР СЫРЫХ ДАННЫХ ОТ ZOOM API (get_recording_details)")
            print("=" * 80)
            print(f"\nMeeting ID: {meeting_id}\n")
            try:
                details = await api.get_recording_details(meeting_id, include_download_token=True)
                print(json.dumps(details, indent=2, ensure_ascii=False))
            except Exception as e:
                print(f"Ошибка при получении деталей: {e}")

        # Показываем структуру всего ответа
        print("\n\n" + "=" * 80)
        print("СТРУКТУРА ПОЛНОГО ОТВЕТА ОТ get_recordings")
        print("=" * 80)
        print("\nКлючи верхнего уровня:")
        for key in response.keys():
            print(f"  - {key}: {type(response[key]).__name__}")

        print("\n\nПример структуры meeting:")
        if meetings:
            print("\nКлючи в объекте meeting:")
            for key in meetings[0].keys():
                value = meetings[0][key]
                if isinstance(value, list) and value:
                    print(f"  - {key}: list[{len(value)}] (первый элемент: {type(value[0]).__name__})")
                elif isinstance(value, dict):
                    print(f"  - {key}: dict (ключи: {list(value.keys())[:5]}...)")
                else:
                    print(f"  - {key}: {type(value).__name__}")

    except Exception as e:
        print(f"Ошибка: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(main())

