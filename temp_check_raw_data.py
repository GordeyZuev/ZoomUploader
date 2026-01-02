#!/usr/bin/env python3
"""Временный скрипт для просмотра сырых данных от Zoom API"""

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

    # Получаем записи от 3 декабря 2025
    from_date = "2025-12-03"
    to_date = "2025-12-03"

    print(f"Получаем записи от {from_date}...\n")

    try:
        # Получаем все записи
        response = await api.get_recordings(
            page_size=300,  # Большой размер страницы
            from_date=from_date,
            to_date=to_date,
        )

        meetings = response.get("meetings", [])

        print(f"Всего найдено записей от 3 декабря: {len(meetings)}\n")
        print("=" * 80)

        if not meetings:
            print("Записи от 3 декабря не найдены.")
        else:
            print("\nСЫРЫЕ ДАННЫЕ ОТ ZOOM API (все записи от 3 декабря):\n")
            print("=" * 80)

            for i, meeting in enumerate(meetings, 1):
                print(f"\n--- ЗАПИСЬ #{i} ---")
                print(f"Название: {meeting.get('topic', 'Без названия')}")
                print(f"UUID: {meeting.get('uuid')}")
                print(f"ID: {meeting.get('id')}")
                print(f"Start time: {meeting.get('start_time')}")
                print(f"Duration: {meeting.get('duration')} минут")
                print(f"Total size: {meeting.get('total_size')} байт")
                print("\nПолные сырые данные:")
                print(json.dumps(meeting, indent=2, ensure_ascii=False))
                print("\n" + "=" * 80)

                # Также получаем детальную информацию
                meeting_id = meeting.get("uuid") or meeting.get("id")
                if meeting_id:
                    print(f"\nДетальная информация для meeting_id={meeting_id}:\n")
                    try:
                        details = await api.get_recording_details(meeting_id, include_download_token=True)
                        print(json.dumps(details, indent=2, ensure_ascii=False))
                    except Exception as e:
                        print(f"Ошибка при получении деталей: {e}")
                    print("\n" + "=" * 80)

    except Exception as e:
        print(f"Ошибка: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
