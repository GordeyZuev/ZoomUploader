"""Быстрый просмотр статистики последних обработок"""

import json
from datetime import datetime
from pathlib import Path


def quick_stats(user_id: int, limit: int = 10):
    """
    Быстрый просмотр последних обработанных записей.

    Args:
        user_id: ID пользователя
        limit: Количество последних записей для отображения
    """
    script_dir = Path(__file__).parent.parent
    base_path = script_dir / f"media/user_{user_id}/transcriptions"

    if not base_path.exists():
        print(f"❌ Папка не найдена: {base_path}")
        return

    # Собираем все записи с датами создания
    records = []

    for rec_dir in base_path.iterdir():
        if not rec_dir.is_dir():
            continue

        master_json = rec_dir / "master.json"
        if not master_json.exists():
            continue

        try:
            with open(master_json, "r", encoding="utf-8") as f:
                data = json.load(f)

            created_at = data.get("created_at", "")
            if created_at:
                created_dt = datetime.fromisoformat(created_at)
            else:
                # Используем время модификации файла
                created_dt = datetime.fromtimestamp(master_json.stat().st_mtime)

            metadata = data.get("_metadata", {})

            records.append({
                "recording_id": rec_dir.name,
                "created_at": created_dt,
                "model": metadata.get("model", "unknown"),
                "duration_min": round(metadata.get("audio_file", {}).get("duration_seconds", 0) / 60, 1),
                "words": data.get("stats", {}).get("words_count", 0),
                "segments": data.get("stats", {}).get("segments_count", 0),
                "language": data.get("language", "unknown"),
            })
        except Exception as e:
            print(f"⚠️ Ошибка чтения {rec_dir.name}: {e}")

    # Сортируем по дате (новые первые)
    records.sort(key=lambda x: x["created_at"], reverse=True)

    # Ограничиваем количество
    records = records[:limit]

    if not records:
        print(f"📭 Нет обработанных записей для пользователя {user_id}")
        return

    # Выводим таблицу
    print("\n" + "=" * 120)
    print(f"⚡ ПОСЛЕДНИЕ ОБРАБОТАННЫЕ ЗАПИСИ (Пользователь {user_id})")
    print("=" * 120)
    print(f"{'ID':<8} {'Дата':<20} {'Модель':<20} {'Мин':<8} {'Слова':<10} {'Сегм.':<8} {'Язык':<6}")
    print("-" * 120)

    for rec in records:
        print(
            f"{rec['recording_id']:<8} "
            f"{rec['created_at'].strftime('%Y-%m-%d %H:%M:%S'):<20} "
            f"{rec['model']:<20} "
            f"{rec['duration_min']:<8.1f} "
            f"{rec['words']:<10,} "
            f"{rec['segments']:<8} "
            f"{rec['language']:<6}"
        )

    # Итоги
    total_duration = sum(r["duration_min"] for r in records)
    total_words = sum(r["words"] for r in records)
    total_segments = sum(r["segments"] for r in records)

    print("-" * 120)
    print(f"{'ИТОГО:':<28} {len(records)} записей | "
          f"{total_duration:.1f} мин | "
          f"{total_words:,} слов | "
          f"{total_segments} сегм.")
    print("=" * 120 + "\n")


def latest_processing(user_id: int):
    """Показывает информацию о последней обработанной записи."""
    script_dir = Path(__file__).parent.parent
    base_path = script_dir / f"media/user_{user_id}/transcriptions"

    if not base_path.exists():
        print(f"❌ Папка не найдена: {base_path}")
        return

    # Находим последнюю запись
    latest = None
    latest_time = None

    for rec_dir in base_path.iterdir():
        if not rec_dir.is_dir():
            continue

        master_json = rec_dir / "master.json"
        if not master_json.exists():
            continue

        try:
            with open(master_json, "r", encoding="utf-8") as f:
                data = json.load(f)

            created_at = data.get("created_at", "")
            if created_at:
                created_dt = datetime.fromisoformat(created_at)
            else:
                created_dt = datetime.fromtimestamp(master_json.stat().st_mtime)

            if latest_time is None or created_dt > latest_time:
                latest_time = created_dt
                latest = {
                    "recording_id": rec_dir.name,
                    "created_at": created_dt,
                    "data": data,
                }
        except Exception:
            continue

    if not latest:
        print(f"📭 Нет обработанных записей для пользователя {user_id}")
        return

    data = latest["data"]
    metadata = data.get("_metadata", {})

    print("\n" + "=" * 80)
    print(f"🆕 ПОСЛЕДНЯЯ ОБРАБОТАННАЯ ЗАПИСЬ (Пользователь {user_id})")
    print("=" * 80)

    print(f"\n📌 ID записи: {latest['recording_id']}")
    print(f"🕐 Создано: {latest['created_at'].strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"⏱️  Длительность: {metadata.get('audio_file', {}).get('duration_seconds', 0) / 60:.1f} минут")

    print("\n🤖 ТРАНСКРИПЦИЯ:")
    print(f"   • Модель: {metadata.get('model', 'unknown')}")
    print(f"   • Язык: {data.get('language', 'unknown')}")
    print(f"   • Температура: {metadata.get('config', {}).get('temperature', 'N/A')}")
    print(f"   • Формат: {metadata.get('config', {}).get('response_format', 'N/A')}")

    print("\n📊 СТАТИСТИКА:")
    stats = data.get("stats", {})
    print(f"   • Слов: {stats.get('words_count', 0):,}")
    print(f"   • Сегментов: {stats.get('segments_count', 0)}")
    print(f"   • Средняя длина сегмента: {stats.get('total_duration', 0) / max(stats.get('segments_count', 1), 1):.1f} сек")

    # Проверяем топики
    topics_json = Path(base_path) / latest['recording_id'] / "topics.json"
    if topics_json.exists():
        try:
            with open(topics_json, "r", encoding="utf-8") as f:
                topics_data = json.load(f)

            active_version = topics_data.get("active_version")
            versions = topics_data.get("versions", [])

            print("\n🎓 ТОПИКИ:")
            print(f"   • Версий: {len(versions)}")
            print(f"   • Активная: {active_version}")

            for version in versions:
                if version.get("id") == active_version:
                    print(f"   • Модель: {version.get('_metadata', {}).get('model', 'unknown')}")
                    print(f"   • Режим: {version.get('granularity', 'unknown')}")
                    print(f"   • Топиков: {len(version.get('topic_timestamps', []))}")
                    main_topics = version.get('main_topics', [])
                    if main_topics:
                        print(f"   • Основные темы: {', '.join(main_topics)}")
        except Exception as e:
            print(f"\n⚠️ Ошибка чтения топиков: {e}")

    # Расчет стоимости
    try:
        from cost_calculator import estimate_transcription_cost

        cost_info = estimate_transcription_cost(
            model=metadata.get("model", "unknown"),
            duration_minutes=metadata.get('audio_file', {}).get('duration_seconds', 0) / 60
        )

        if cost_info.get("estimated_cost_usd"):
            print("\n💰 ПРИМЕРНАЯ СТОИМОСТЬ:")
            print(f"   • USD: ${cost_info['estimated_cost_usd']:.6f}")
            print(f"   • RUB: ₽{cost_info['estimated_cost_rub']:.4f}")
    except Exception:
        pass

    print("\n" + "=" * 80 + "\n")


def compare_models(user_id: int):
    """Сравнение использованных моделей."""
    script_dir = Path(__file__).parent.parent
    base_path = script_dir / f"media/user_{user_id}/transcriptions"

    if not base_path.exists():
        print(f"❌ Папка не найдена: {base_path}")
        return

    models_stats = {}

    for rec_dir in base_path.iterdir():
        if not rec_dir.is_dir():
            continue

        master_json = rec_dir / "master.json"
        if not master_json.exists():
            continue

        try:
            with open(master_json, "r", encoding="utf-8") as f:
                data = json.load(f)

            metadata = data.get("_metadata", {})
            model = metadata.get("model", "unknown")

            if model not in models_stats:
                models_stats[model] = {
                    "count": 0,
                    "total_duration": 0.0,
                    "total_words": 0,
                    "total_segments": 0,
                }

            models_stats[model]["count"] += 1
            models_stats[model]["total_duration"] += metadata.get("audio_file", {}).get("duration_seconds", 0) / 60
            models_stats[model]["total_words"] += data.get("stats", {}).get("words_count", 0)
            models_stats[model]["total_segments"] += data.get("stats", {}).get("segments_count", 0)
        except Exception:
            continue

    if not models_stats:
        print("📭 Нет данных для анализа")
        return

    print("\n" + "=" * 100)
    print(f"📊 СРАВНЕНИЕ МОДЕЛЕЙ (Пользователь {user_id})")
    print("=" * 100)
    print(f"{'Модель':<25} {'Записей':<10} {'Минут':<12} {'Слов':<15} {'Сегм.':<10}")
    print("-" * 100)

    for model, stats in sorted(models_stats.items()):
        print(
            f"{model:<25} "
            f"{stats['count']:<10} "
            f"{stats['total_duration']:<12.1f} "
            f"{stats['total_words']:<15,} "
            f"{stats['total_segments']:<10}"
        )

    print("=" * 100 + "\n")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python utils/quick_stats.py <user_id> [command]")
        print("\nКоманды:")
        print("  latest      - Показать последнюю обработанную запись (по умолчанию)")
        print("  list [N]    - Показать N последних записей (по умолчанию 10)")
        print("  compare     - Сравнить использованные модели")
        print("\nПримеры:")
        print("  python utils/quick_stats.py 4")
        print("  python utils/quick_stats.py 4 latest")
        print("  python utils/quick_stats.py 4 list 20")
        print("  python utils/quick_stats.py 4 compare")
        sys.exit(1)

    user_id = int(sys.argv[1])
    command = sys.argv[2] if len(sys.argv) > 2 else "latest"

    if command == "list":
        limit = int(sys.argv[3]) if len(sys.argv) > 3 else 10
        quick_stats(user_id, limit)
    elif command == "compare":
        compare_models(user_id)
    else:  # latest or default
        latest_processing(user_id)

