"""Скрипт миграции для перемещения thumbnails в правильную структуру."""

import shutil
from pathlib import Path


def migrate_thumbnails():
    """
    Переместить глобальные thumbnails в media/templates/thumbnails/.

    Новая структура:
    - media/templates/thumbnails/ - глобальные templates (read-only для всех)
    - media/user_{id}/thumbnails/ - личные thumbnails пользователя
    """

    # Старая структура
    old_thumbnails_dir = Path("thumbnails")

    # Новая структура
    templates_dir = Path("media/templates/thumbnails")

    if not old_thumbnails_dir.exists():
        print("❌ Директория thumbnails/ не найдена")
        return

    # Создать директорию для templates
    templates_dir.mkdir(parents=True, exist_ok=True)

    # Переместить все файлы в templates
    moved_count = 0
    for thumbnail_file in old_thumbnails_dir.glob("*.png"):
        target_file = templates_dir / thumbnail_file.name

        if target_file.exists():
            print(f"⚠️  Файл уже существует: {target_file}")
            continue

        shutil.copy2(thumbnail_file, target_file)
        print(f"✅ Скопировано в templates: {thumbnail_file} → {target_file}")
        moved_count += 1

    print(f"\n✅ Миграция завершена! Перемещено файлов: {moved_count}")
    print("\n📁 Новая структура:")
    print(f"   - {templates_dir}/ - глобальные templates (для всех пользователей)")
    print("   - media/user_{id}/thumbnails/ - личные thumbnails каждого пользователя")
    print("\n⚠️  ВАЖНО: Старая директория thumbnails/ НЕ удалена автоматически.")
    print("   Проверьте работу приложения и удалите вручную:")
    print(f"   rm -rf {old_thumbnails_dir}")
    print("\n💡 При создании нового пользователя:")
    print("   - Автоматически создается media/user_{{id}}/thumbnails/")
    print("   - Можно скопировать templates через ThumbnailManager.initialize_user_thumbnails()")


if __name__ == "__main__":
    migrate_thumbnails()

