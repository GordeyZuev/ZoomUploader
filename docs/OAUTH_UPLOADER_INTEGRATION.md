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

await uploader.authenticate()  # Auto-refresh для обеих платформ!
```

### **Вариант 4: Ручное добавление credentials через API**

```bash
# YouTube credentials (manual)
curl -X POST http://localhost:8000/api/v1/credentials \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "platform": "youtube",
    "account_name": "my_channel",
    "credentials": {
      "client_secrets": {
        "web": {
          "client_id": "...",
          "client_secret": "...",
          "redirect_uris": ["..."]
        }
      },
      "token": {
        "token": "ya29...",
        "refresh_token": "1//0c...",
        "client_id": "...",
        "client_secret": "...",
        "scopes": ["https://www.googleapis.com/auth/youtube.upload"],
        "expiry": "2026-01-08T12:00:00Z"
      }
    }
  }'

# VK credentials (manual, VK ID format)
curl -X POST http://localhost:8000/api/v1/credentials \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "platform": "vk_video",
    "account_name": "my_vk",
    "credentials": {
      "client_id": "...",
      "client_secret": "...",
      "access_token": "vk1...",
      "refresh_token": "vk_refresh...",
      "user_id": 123456,
      "expires_in": 86400,
      "expiry": "2026-01-08T12:00:00Z"
    }
  }'
```

**Validation:** Credentials автоматически валидируются через Pydantic схемы!

---

## 🔄 Интеграция с Celery задачами

### **Celery tasks уже обновлены!**

Все Celery задачи в `api/tasks/upload.py` уже используют новый `uploader_factory`:

```python
# api/tasks/upload.py
from video_upload_module.uploader_factory import create_uploader_from_db

async def _async_upload_recording(...):
    # Автоматически использует DB credentials
        uploader = await create_uploader_from_db(
            platform=platform,
            credential_id=credential_id,
        session=ctx.session,
        )
        
    # Auto-refresh для YouTube и VK!
    auth_success = await uploader.authenticate()
        
        # Upload
    result = await uploader.upload_video(...)
```

**Что работает:**
- ✅ Автоматический выбор credential из preset
- ✅ Fallback на первый доступный credential
- ✅ Автоматический refresh токенов (YouTube + VK ID)
- ✅ Multi-tenancy (каждый пользователь со своими credentials)

---

## 🔧 Архитектура

### **Credential Provider**

```
CredentialProvider (ABC)
├── load_credentials() → dict
├── save_credentials(data: dict) → bool
├── get_google_credentials(scopes) → Credentials
├── update_google_credentials(creds) → bool
├── get_vk_credentials() → dict                    # ✨ NEW
├── update_vk_credentials(token, expires) → bool   # ✨ NEW
└── refresh_vk_token() → dict                      # ✨ NEW

FileCredentialProvider
├── Читает/пишет в файлы
└── Backward compatibility

DatabaseCredentialProvider
├── Читает/пишет в БД
├── Использует encryption
├── Автоматический refresh (YouTube)
└── Автоматический refresh (VK ID) ✨ NEW
```

### **Uploader Factory**

```python
uploader_factory.py
├── create_youtube_uploader_from_db()  # ✅ Credential provider
├── create_vk_uploader_from_db()       # ✅ Credential provider (updated)
└── create_uploader_from_db()          # ✅ Универсальная
```

### **VK ID OAuth Flow**

```
User → GET /oauth/vk/authorize
     → VK ID Auth Page (https://id.vk.com/oauth2/auth)
     → User grants access
     → VK ID redirects → GET /oauth/vk/callback?code=...
     → Backend: POST https://id.vk.com/oauth2/token
     → Получаем: access_token + refresh_token ✨
     → Save to DB (encrypted)
     → VKUploader auto-refresh при expiry ✨
```

---

## ✅ Преимущества

1. **Обратная совместимость** - старый код работает без изменений
2. **Автоматический refresh** - токены обновляются и сохраняются в БД (YouTube + VK ID)
3. **Multi-tenancy** - каждый пользователь имеет свои credentials
4. **Безопасность** - credentials зашифрованы в БД
5. **Гибкость** - легко добавить новые платформы
6. **Validation** - Pydantic схемы для всех платформ (YouTube, VK, Zoom)
7. **VK ID support** - новый VK API с refresh token (вместо старого implicit flow)

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

## ✅ Статус интеграции

- [x] **VK ID OAuth** - обновлено на новый API с refresh token support
- [x] **VKUploader** - адаптирован под credential_provider паттерн
- [x] **Celery задачи** - мигрированы на новый `uploader_factory`
- [x] **Credential validation** - добавлены Pydantic схемы для YouTube/VK/Zoom
- [x] **Автоматический refresh** - работает для YouTube и VK ID
- [ ] Добавить UI для выбора credential при создании preset
- [ ] Добавить мониторинг истечения токенов (Celery periodic task)

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

