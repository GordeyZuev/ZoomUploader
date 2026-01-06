"""Калькулятор стоимости использования API для транскрипции и извлечения топиков"""

import json
from pathlib import Path
from typing import Any

# Примерные цены (обновите актуальными значениями)
PRICING = {
    # Fireworks AI (Whisper) - цена за минуту аудио
    "whisper-v3": {
        "price_per_minute": 0.0002,  # $0.0002 за минуту
        "unit": "минута аудио",
    },
    "whisper-v3-turbo": {
        "price_per_minute": 0.0001,  # $0.0001 за минуту (быстрее и дешевле)
        "unit": "минута аудио",
    },

    # DeepSeek - цена за токены
    "deepseek-chat": {
        "price_per_1k_input_tokens": 0.00014,  # $0.14 за 1M input токенов
        "price_per_1k_output_tokens": 0.00028,  # $0.28 за 1M output токенов
        "unit": "токены",
        # Примерный расчет: 1 слово ≈ 1.3 токена (для русского языка)
        "estimated_tokens_per_word": 1.3,
    },

    # Fireworks AI (DeepSeek через Fireworks)
    "accounts/fireworks/models/deepseek-v3": {
        "price_per_1k_input_tokens": 0.00009,  # $0.09 за 1M input токенов
        "price_per_1k_output_tokens": 0.00009,  # $0.09 за 1M output токенов (cached)
        "unit": "токены",
        "estimated_tokens_per_word": 1.3,
    },
}


def estimate_transcription_cost(model: str, duration_minutes: float) -> dict[str, Any]:
    """
    Оценка стоимости транскрипции.

    Args:
        model: Название модели транскрипции
        duration_minutes: Длительность аудио в минутах

    Returns:
        Словарь с оценкой стоимости
    """
    pricing = PRICING.get(model)

    if not pricing:
        return {
            "model": model,
            "duration_minutes": duration_minutes,
            "estimated_cost_usd": None,
            "note": f"Цены для модели '{model}' не настроены",
        }

    cost = duration_minutes * pricing["price_per_minute"]

    return {
        "model": model,
        "duration_minutes": round(duration_minutes, 2),
        "price_per_minute": pricing["price_per_minute"],
        "estimated_cost_usd": round(cost, 6),
        "estimated_cost_rub": round(cost * 100, 4),  # Примерный курс 1 USD = 100 RUB
        "unit": pricing["unit"],
    }


def estimate_topics_cost(
    model: str,
    input_words: int,
    output_topics: int,
    avg_topic_length: int = 5  # Средняя длина названия топика в словах
) -> dict[str, Any]:
    """
    Оценка стоимости извлечения топиков.

    Args:
        model: Название модели
        input_words: Количество слов в транскрипции (input)
        output_topics: Количество топиков (output)
        avg_topic_length: Средняя длина названия топика в словах

    Returns:
        Словарь с оценкой стоимости
    """
    pricing = PRICING.get(model)

    if not pricing or "estimated_tokens_per_word" not in pricing:
        return {
            "model": model,
            "input_words": input_words,
            "output_topics": output_topics,
            "estimated_cost_usd": None,
            "note": f"Цены для модели '{model}' не настроены",
        }

    # Оценка токенов
    input_tokens = input_words * pricing["estimated_tokens_per_word"]
    output_tokens = output_topics * avg_topic_length * pricing["estimated_tokens_per_word"]

    # Стоимость
    input_cost = (input_tokens / 1000) * pricing["price_per_1k_input_tokens"]
    output_cost = (output_tokens / 1000) * pricing["price_per_1k_output_tokens"]
    total_cost = input_cost + output_cost

    return {
        "model": model,
        "input_words": input_words,
        "estimated_input_tokens": round(input_tokens),
        "output_topics": output_topics,
        "estimated_output_tokens": round(output_tokens),
        "price_per_1k_input": pricing["price_per_1k_input_tokens"],
        "price_per_1k_output": pricing["price_per_1k_output_tokens"],
        "input_cost_usd": round(input_cost, 6),
        "output_cost_usd": round(output_cost, 6),
        "estimated_cost_usd": round(total_cost, 6),
        "estimated_cost_rub": round(total_cost * 100, 4),
        "unit": pricing["unit"],
    }


def calculate_user_costs(user_id: int) -> dict[str, Any]:
    """
    Подсчет полной стоимости для пользователя.

    Args:
        user_id: ID пользователя

    Returns:
        Словарь с детальной разбивкой стоимости
    """
    from usage_stats import analyze_transcription_usage

    stats = analyze_transcription_usage(user_id)

    if "error" in stats:
        return {"error": stats["error"]}

    total_transcription_cost = 0.0
    total_topics_cost = 0.0

    transcription_details = []
    topics_details = []

    for rec in stats["recordings"]:
        rec_id = rec["recording_id"]

        # Стоимость транскрипции
        if rec["transcription"] and "error" not in rec["transcription"]:
            trans = rec["transcription"]
            cost_info = estimate_transcription_cost(
                model=trans["model"],
                duration_minutes=trans["duration_minutes"]
            )
            cost_info["recording_id"] = rec_id
            transcription_details.append(cost_info)

            if cost_info.get("estimated_cost_usd"):
                total_transcription_cost += cost_info["estimated_cost_usd"]

        # Стоимость извлечения топиков
        if rec["topics"]:
            for topic in rec["topics"]:
                if "error" not in topic:
                    # Используем количество слов из транскрипции как input
                    input_words = rec["transcription"].get("words_count", 0) if rec["transcription"] else 0

                    cost_info = estimate_topics_cost(
                        model=topic["model"],
                        input_words=input_words,
                        output_topics=topic["topics_count"]
                    )
                    cost_info["recording_id"] = rec_id
                    cost_info["version_id"] = topic["version_id"]
                    topics_details.append(cost_info)

                    if cost_info.get("estimated_cost_usd"):
                        total_topics_cost += cost_info["estimated_cost_usd"]

    total_cost = total_transcription_cost + total_topics_cost

    return {
        "user_id": user_id,
        "total_recordings": stats["summary"]["total_recordings"],
        "costs": {
            "transcription": {
                "total_usd": round(total_transcription_cost, 6),
                "total_rub": round(total_transcription_cost * 100, 4),
                "details": transcription_details,
            },
            "topics": {
                "total_usd": round(total_topics_cost, 6),
                "total_rub": round(total_topics_cost * 100, 4),
                "details": topics_details,
            },
            "total": {
                "usd": round(total_cost, 6),
                "rub": round(total_cost * 100, 4),
            },
        },
    }


def print_cost_report(user_id: int):
    """Печатает красивый отчет о стоимости."""
    costs = calculate_user_costs(user_id)

    if "error" in costs:
        print(f"❌ Ошибка: {costs['error']}")
        return

    print("\n" + "=" * 80)
    print("💰 ОТЧЕТ О СТОИМОСТИ ИСПОЛЬЗОВАНИЯ API")
    print("=" * 80)

    print(f"\n👤 Пользователь ID: {costs['user_id']}")
    print(f"📁 Всего записей: {costs['total_recordings']}")

    trans_costs = costs["costs"]["transcription"]
    topics_costs = costs["costs"]["topics"]
    total_costs = costs["costs"]["total"]

    print("\n💵 ОБЩАЯ СТОИМОСТЬ:")
    print(f"   • USD: ${total_costs['usd']:.6f}")
    print(f"   • RUB: ₽{total_costs['rub']:.4f}")

    print("\n🎙️  ТРАНСКРИПЦИЯ:")
    print(f"   • Всего: ${trans_costs['total_usd']:.6f} (₽{trans_costs['total_rub']:.4f})")
    print(f"   • Записей: {len(trans_costs['details'])}")

    if trans_costs['details']:
        print("\n   📋 Детали по транскрипциям:")
        for detail in trans_costs['details']:
            if detail.get("estimated_cost_usd"):
                print(f"      • Recording {detail['recording_id']}: {detail['model']}")
                print(f"        - Длительность: {detail['duration_minutes']} мин")
                print(f"        - Стоимость: ${detail['estimated_cost_usd']:.6f} (₽{detail['estimated_cost_rub']:.4f})")
            else:
                print(f"      • Recording {detail['recording_id']}: {detail.get('note', 'Цена не определена')}")

    print("\n🎓 ИЗВЛЕЧЕНИЕ ТОПИКОВ:")
    print(f"   • Всего: ${topics_costs['total_usd']:.6f} (₽{topics_costs['total_rub']:.4f})")
    print(f"   • Версий: {len(topics_costs['details'])}")

    if topics_costs['details']:
        print("\n   📋 Детали по топикам:")
        for detail in topics_costs['details']:
            if detail.get("estimated_cost_usd"):
                print(f"      • Recording {detail['recording_id']} (версия {detail['version_id']}): {detail['model']}")
                print(f"        - Input: {detail['input_words']} слов (≈{detail['estimated_input_tokens']} токенов)")
                print(f"        - Output: {detail['output_topics']} топиков (≈{detail['estimated_output_tokens']} токенов)")
                print(f"        - Стоимость: ${detail['estimated_cost_usd']:.6f} (₽{detail['estimated_cost_rub']:.4f})")
            else:
                print(f"      • Recording {detail['recording_id']}: {detail.get('note', 'Цена не определена')}")

    print("\n" + "=" * 80)
    print("⚠️  ВНИМАНИЕ: Это приблизительная оценка на основе публичных цен.")
    print("    Реальная стоимость может отличаться в зависимости от:")
    print("    • Текущих тарифов провайдера")
    print("    • Специальных скидок или договоров")
    print("    • Точного подсчета токенов (если API не возвращает usage)")
    print("=" * 80 + "\n")


def export_costs_to_json(user_id: int, output_file: str = "cost_report.json"):
    """Экспортирует отчет о стоимости в JSON файл."""
    costs = calculate_user_costs(user_id)

    output_path = Path(output_file)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(costs, f, ensure_ascii=False, indent=2)

    print(f"✅ Отчет о стоимости экспортирован в: {output_path.absolute()}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python utils/cost_calculator.py <user_id> [--export]")
        print("\nПримеры:")
        print("  python utils/cost_calculator.py 4")
        print("  python utils/cost_calculator.py 4 --export")
        sys.exit(1)

    user_id = int(sys.argv[1])

    if len(sys.argv) > 2 and sys.argv[2] == "--export":
        export_costs_to_json(user_id)
    else:
        print_cost_report(user_id)

