"""Утилита для анализа использования токенов и моделей"""

import json
from pathlib import Path
from typing import Any


def analyze_transcription_usage(user_id: int, recording_id: int | None = None) -> dict[str, Any]:
    """
    Анализирует использование токенов и моделей для транскрипций.

    Args:
        user_id: ID пользователя
        recording_id: ID конкретной записи (опционально, если None - анализ всех записей)

    Returns:
        Словарь со статистикой использования
    """
    # Определяем путь относительно корня проекта
    script_dir = Path(__file__).parent.parent
    base_path = script_dir / f"media/user_{user_id}/transcriptions"

    if not base_path.exists():
        return {"error": f"Папка не найдена: {base_path}"}

    results = []

    # Если указан recording_id, анализируем только его
    if recording_id:
        recording_dirs = [base_path / str(recording_id)]
    else:
        # Анализируем все записи
        recording_dirs = [d for d in base_path.iterdir() if d.is_dir()]

    for rec_dir in recording_dirs:
        if not rec_dir.exists():
            continue

        master_json = rec_dir / "master.json"
        topics_json = rec_dir / "topics.json"

        rec_stats = {
            "recording_id": rec_dir.name,
            "transcription": None,
            "topics": [],
        }

        # Анализируем транскрипцию (master.json)
        if master_json.exists():
            try:
                with open(master_json, "r", encoding="utf-8") as f:
                    data = json.load(f)

                metadata = data.get("_metadata", {})
                rec_stats["transcription"] = {
                    "model": metadata.get("model", "unknown"),
                    "duration_seconds": metadata.get("audio_file", {}).get("duration_seconds", 0),
                    "duration_minutes": round(metadata.get("audio_file", {}).get("duration_seconds", 0) / 60, 2),
                    "language": data.get("language", "unknown"),
                    "words_count": data.get("stats", {}).get("words_count", 0),
                    "segments_count": data.get("stats", {}).get("segments_count", 0),
                    "config": metadata.get("config", {}),
                    "usage": metadata.get("usage"),  # Если API возвращает usage
                    "created_at": data.get("created_at"),
                }
            except Exception as e:
                rec_stats["transcription"] = {"error": str(e)}

        # Анализируем топики (topics.json)
        if topics_json.exists():
            try:
                with open(topics_json, "r", encoding="utf-8") as f:
                    topics_data = json.load(f)

                for version in topics_data.get("versions", []):
                    metadata = version.get("_metadata", {})
                    rec_stats["topics"].append({
                        "version_id": version.get("id"),
                        "model": metadata.get("model", "unknown"),
                        "granularity": version.get("granularity"),
                        "is_active": version.get("is_active"),
                        "topics_count": len(version.get("topic_timestamps", [])),
                        "main_topics": version.get("main_topics", []),
                        "config": metadata.get("config", {}),
                        "created_at": version.get("created_at"),
                    })
            except Exception as e:
                rec_stats["topics"] = [{"error": str(e)}]

        results.append(rec_stats)

    # Общая статистика
    summary = {
        "total_recordings": len(results),
        "transcription_models": {},
        "topic_models": {},
        "total_duration_minutes": 0,
        "total_words": 0,
        "total_segments": 0,
    }

    for rec in results:
        if rec["transcription"] and "error" not in rec["transcription"]:
            trans = rec["transcription"]
            model = trans["model"]
            summary["transcription_models"][model] = summary["transcription_models"].get(model, 0) + 1
            summary["total_duration_minutes"] += trans.get("duration_minutes", 0)
            summary["total_words"] += trans.get("words_count", 0)
            summary["total_segments"] += trans.get("segments_count", 0)

        for topic in rec.get("topics", []):
            if "error" not in topic:
                model = topic["model"]
                summary["topic_models"][model] = summary["topic_models"].get(model, 0) + 1

    return {
        "summary": summary,
        "recordings": results,
    }


def print_usage_report(user_id: int, recording_id: int | None = None):
    """Красиво печатает отчет об использовании."""
    stats = analyze_transcription_usage(user_id, recording_id)

    if "error" in stats:
        print(f"❌ Ошибка: {stats['error']}")
        return

    summary = stats["summary"]

    print("\n" + "=" * 80)
    print("📊 СТАТИСТИКА ИСПОЛЬЗОВАНИЯ ТОКЕНОВ И МОДЕЛЕЙ")
    print("=" * 80)

    print(f"\n📁 Всего записей: {summary['total_recordings']}")
    print(f"⏱️  Общая длительность: {summary['total_duration_minutes']:.1f} минут ({summary['total_duration_minutes'] / 60:.1f} часов)")
    print(f"📝 Всего слов: {summary['total_words']:,}")
    print(f"🎯 Всего сегментов: {summary['total_segments']:,}")

    print("\n🤖 МОДЕЛИ ТРАНСКРИПЦИИ:")
    for model, count in summary["transcription_models"].items():
        print(f"   • {model}: {count} записей")

    if summary["topic_models"]:
        print("\n🎓 МОДЕЛИ ИЗВЛЕЧЕНИЯ ТОПИКОВ:")
        for model, count in summary["topic_models"].items():
            print(f"   • {model}: {count} версий")

    print("\n" + "-" * 80)
    print("📋 ДЕТАЛИ ПО ЗАПИСЯМ:")
    print("-" * 80)

    for rec in stats["recordings"]:
        print(f"\n🎬 Recording ID: {rec['recording_id']}")

        if rec["transcription"]:
            trans = rec["transcription"]
            if "error" not in trans:
                print("   📹 Транскрипция:")
                print(f"      • Модель: {trans['model']}")
                print(f"      • Длительность: {trans['duration_minutes']} мин")
                print(f"      • Язык: {trans['language']}")
                print(f"      • Слов: {trans['words_count']:,}")
                print(f"      • Сегментов: {trans['segments_count']}")
                print(f"      • Создано: {trans['created_at']}")
                if trans.get("usage"):
                    print(f"      • Usage: {trans['usage']}")
            else:
                print(f"   ❌ Ошибка транскрипции: {trans['error']}")

        if rec["topics"]:
            for topic in rec["topics"]:
                if "error" not in topic:
                    print(f"   🎓 Топики (версия {topic['version_id']}):")
                    print(f"      • Модель: {topic['model']}")
                    print(f"      • Режим: {topic['granularity']}")
                    print(f"      • Активна: {'✅' if topic['is_active'] else '❌'}")
                    print(f"      • Топиков: {topic['topics_count']}")
                    print(f"      • Основные темы: {', '.join(topic['main_topics'])}")
                    print(f"      • Создано: {topic['created_at']}")
                else:
                    print(f"   ❌ Ошибка топиков: {topic['error']}")

    print("\n" + "=" * 80 + "\n")


def export_usage_to_json(user_id: int, output_file: str = "usage_report.json"):
    """Экспортирует статистику в JSON файл."""
    stats = analyze_transcription_usage(user_id)

    output_path = Path(output_file)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, ensure_ascii=False, indent=2)

    print(f"✅ Статистика экспортирована в: {output_path.absolute()}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python utils/usage_stats.py <user_id> [recording_id]")
        print("\nПримеры:")
        print("  python utils/usage_stats.py 4                  # Все записи пользователя 4")
        print("  python utils/usage_stats.py 4 21               # Только запись 21")
        print("  python utils/usage_stats.py 4 --export         # Экспорт в JSON")
        sys.exit(1)

    user_id = int(sys.argv[1])

    if len(sys.argv) > 2 and sys.argv[2] == "--export":
        export_usage_to_json(user_id)
    elif len(sys.argv) > 2:
        recording_id = int(sys.argv[2])
        print_usage_report(user_id, recording_id)
    else:
        print_usage_report(user_id)

