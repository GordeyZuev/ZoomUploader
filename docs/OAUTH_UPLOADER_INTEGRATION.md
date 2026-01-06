# OAuth Credentials Integration with Uploaders

## Обзор

Теперь `YouTubeUploader` и `VKUploader` могут работать с credentials из **базы данных** (через OAuth) или из **файлов** (legacy режим).

---

## 🎯 Как это работает

### **1. Credential Provider Pattern**

Создан абстрактный `CredentialProvider` с двумя реализациями:
- **`FileCredentialProvider`** - работает с файлами (backward compatibility)
- **`DatabaseCredentialProvider`** - работает с БД (для OAuth)

### **2. Автоматический refresh токенов**

При использовании DB credentials, токены **автоматически обновляются** в БД после refresh:
```python
# Token expired? → автоматически refresh → сохранение в БД
await uploader.authenticate()  # Все происходит автоматически!
```

---

## 📖 Примеры использования

### **Вариант 1: Использование DB credentials (рекомендуемый)**

```python
from sqlalchemy.ext.asyncio import AsyncSession
from video_upload_module.uploader_factory import create_youtube_uploader_from_db

async def upload_with_oauth_credentials(
    credential_id: int,
    session: AsyncSession,
    video_path: str,
    title: str,
):
    # Создать uploader с credentials из БД
    uploader = await create_youtube_uploader_from_db(
        credential_id=credential_id,
        session=session,
    )
    
    # Authenticate (автоматически refresh если нужно)
    if not await uploader.authenticate():
        print("Authentication failed!")
        return None
    
    # Upload video
    result = await uploader.upload_video(
        video_path=video_path,
        title=title,
        description="Uploaded via OAuth",
    )
    
    return result
```

### **Вариант 2: Использование файлов (legacy)**

```python
from video_upload_module.platforms.youtube.uploader import YouTubeUploader
from video_upload_module.config_factory import YouTubeUploadConfig

# Старый способ - работает как раньше
config = YouTubeUploadConfig(
    enabled=True,
    client_secrets_file="config/youtube_creds.json",
    credentials_file="config/youtube_token.json",
)

uploader = YouTubeUploader(config=config)
await uploader.authenticate()  # Файловый режим
```

### **Вариант 3: Универсальная фабрика**

```python
from video_upload_module.uploader_factory import create_uploader_from_db

# Работает для YouTube и VK
uploader = await create_uploader_from_db(
    platform="youtube",  # or "vk_video"
    credential_id=5,
    session=session,
)

await uploader.authenticate()
```

---

## 🔄 Интеграция с Celery задачами

### **Пример: Обновить существующую задачу загрузки**

```python
from celery import shared_task
from api.dependencies import get_db_session
from video_upload_module.uploader_factory import create_uploader_from_db

@shared_task
async def upload_video_task(
    user_id: int,
    credential_id: int,
    platform: str,
    video_path: str,
    title: str,
):
    async with get_db_session() as session:
        # Create uploader from DB credentials
        uploader = await create_uploader_from_db(
            platform=platform,
            credential_id=credential_id,
            session=session,
        )
        
        # Authenticate (auto-refresh if needed)
        if not await uploader.authenticate():
            return {"status": "error", "message": "Authentication failed"}
        
        # Upload
        result = await uploader.upload_video(
            video_path=video_path,
            title=title,
        )
        
        return {"status": "success", "result": result}
```

---

## 🔧 Архитектура

### **Credential Provider**

```
CredentialProvider (ABC)
├── load_credentials() → dict
├── save_credentials(data: dict) → bool
├── get_google_credentials(scopes) → Credentials
└── update_google_credentials(creds) → bool

FileCredentialProvider
├── Читает/пишет в файлы
└── Backward compatibility

DatabaseCredentialProvider
├── Читает/пишет в БД
├── Использует encryption
└── Автоматический refresh
```

### **Uploader Factory**

```python
uploader_factory.py
├── create_youtube_uploader_from_db()
├── create_vk_uploader_from_db()
└── create_uploader_from_db()  # Универсальная
```

---

## ✅ Преимущества

1. **Обратная совместимость** - старый код работает без изменений
2. **Автоматический refresh** - токены обновляются и сохраняются в БД
3. **Multi-tenancy** - каждый пользователь имеет свои credentials
4. **Безопасность** - credentials зашифрованы в БД
5. **Гибкость** - легко добавить новые платформы

---

## 🚀 Миграция существующего кода

### **Было:**
```python
uploader = YouTubeUploader(config)
await uploader.authenticate()
```

### **Стало (для OAuth):**
```python
uploader = await create_youtube_uploader_from_db(credential_id, session)
await uploader.authenticate()
```

**Старый код продолжит работать!** 🎉

---

## 📝 TODO для полной интеграции

- [ ] Обновить `pipeline_manager.py` для использования DB credentials
- [ ] Добавить выбор credential в API endpoints для загрузки
- [ ] Обновить Celery задачи для поддержки `credential_id`
- [ ] Добавить UI для выбора credential при создании preset
- [ ] Добавить мониторинг истечения токенов

---

## 🔍 Troubleshooting

### **Ошибка: "Authentication failed"**
- Проверь что credential существует в БД
- Проверь что credential активен (`is_active=true`)
- Проверь что refresh_token есть в credential

### **Ошибка: "Token validation failed"**
- Пользователь отозвал доступ → нужна повторная авторизация через OAuth
- Credential устарел → удалить и создать новый

### **Файловый режим не работает**
- Убедись что файлы существуют
- Проверь структуру JSON (должна быть "web" или "installed")

---

## 📚 См. также

- `docs/OAUTH_IMPLEMENTATION_SUMMARY.md` - общая архитектура OAuth
- `docs/OAUTH_TESTING_GUIDE.md` - как тестировать OAuth flow
- `video_upload_module/credentials_provider.py` - реализация провайдеров
- `video_upload_module/uploader_factory.py` - фабрика uploaders

