# История изменений

Краткая хронология основных изменений в проекте.

---

## 2026-01-17 - Автоматическое обновление токенов YouTube/VK

**Проблема:** При истечении токенов YouTube/VK во время загрузки видео операции завершались с ошибкой.

**Решение:** Декораторы `@requires_valid_token` и `@requires_valid_vk_token` для автоматического refresh токенов.

**Файлы:**
- `video_upload_module/platforms/youtube/token_handler.py` - универсальный обработчик
- `video_upload_module/platforms/youtube/uploader.py` - применен декоратор
- `video_upload_module/platforms/youtube/playlist_manager.py` - применен декоратор
- `video_upload_module/platforms/youtube/thumbnail_manager.py` - применен декоратор
- `video_upload_module/platforms/vk/uploader.py` - применен декоратор для VK
- `api/tasks/upload.py` - обработка TokenRefreshError

---
