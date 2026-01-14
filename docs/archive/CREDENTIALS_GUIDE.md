# Руководство по Credentials

## Обзор

Система поддерживает 3 типа credentials:
- **YouTube** - OAuth 2.0 с refresh tokens (multi-user)
- **VK** - VK ID OAuth 2.1, Implicit Flow, Service Token
- **Zoom** - OAuth 2.0 с refresh tokens (multi-user), Server-to-Server OAuth (legacy)

---

## YouTube Credentials

### Формат OAuth (рекомендуется)

```json
{
  "token": "ya29.a0AfB_byD...",
  "refresh_token": "1//0gKxxx...",
  "token_uri": "https://oauth2.googleapis.com/token",
  "client_id": "475008846278-xxx.apps.googleusercontent.com",
  "client_secret": "GOCSPX-xxxxxxxx",
  "scopes": [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl"
  ],
  "expiry": "2026-01-08T18:00:00Z"
}
```

### Обязательные поля

| Поле | Описание |
|------|----------|
| `token` | Access token для YouTube API |
| `client_id` | Google OAuth client ID |
| `client_secret` | Google OAuth client secret |
| `scopes` | Массив OAuth scopes |

### Опциональные поля

| Поле | Описание |
|------|----------|
| `refresh_token` | Refresh token (обязателен для долгосрочного использования) |
| `expiry` | Время истечения токена (ISO 8601) |
| `token_uri` | Token endpoint (по умолчанию Google) |

### Получение credentials

1. **Через OAuth Flow (рекомендуется):**
   ```bash
   GET /api/v1/oauth/youtube/authorize
   ```

2. **Вручную через API:**
   ```bash
   POST /api/v1/credentials/
   {
     "platform": "youtube",
     "account_name": "my_channel",
     "credentials": { ... }
   }
   ```

---

## VK Credentials

⚠️ **ВАЖНО (январь 2026):** VK больше не выдает расширенные API-доступы для новых приложений ([п.7.2 Оферты](https://id.vk.com/terms)). Для новых проектов используйте **Implicit Flow** или **Service Token**.

### 1. VK ID OAuth 2.1 ⚠️ (только для существующих приложений)

**С refresh token - можно обновлять автоматически:**

```json
{
  "access_token": "vk1.a.xxx...",
  "refresh_token": "vk1.r.yyy...",
  "user_id": 123456,
  "expires_in": 86400,
  "expiry": "2026-01-09T16:00:00Z",
  "client_id": "54417027",
  "client_secret": "XuEmN5fCuE56lRsRCH2V"
}
```

**Получение:**
```bash
GET /api/v1/oauth/vk/authorize
```

**⚠️ Статус:** Работает только для приложений с уже одобренными расширенными правами. Новые приложения получат отказ от VK.

### 2. Implicit Flow (⭐ рекомендуется для multi-user)

**Без refresh token - токен живет ~24 часа:**

```json
{
  "access_token": "vk1.a.EXAMPLE_TOKEN_xxx...",
  "user_id": 123456,
  "app_id": "54249533"
}
```

**Получение:**
```bash
GET /api/v1/oauth/vk/authorize/implicit
```

Инструкции в response.

### 3. Service Token (для single-account)

**Long-lived token от владельца приложения:**

```json
{
  "access_token": "SERVICE_TOKEN_EXAMPLE_xxx...",
  "app_id": "54417027",
  "user_id": 123456
}
```

**Получение:** VK Developer Console → Приложение → Настройки → Сервисный ключ доступа

### 4. Через setup_vk.py (CLI)

```bash
python setup_vk.py
```

Сохраняет credentials в `config/vk_creds.json`:

```json
{
  "access_token": "xxx...",
  "user_id": 123456,
  "app_id": "54249533"
}
```

---

### Автоматическое обновление токенов Implicit Flow

Так как Implicit Flow токены живут ~24 часа, рекомендуется настроить автообновление:

#### Вариант 1: Webhook для пользователя

Пользователь переавторизуется через `/api/v1/oauth/vk/authorize/implicit` когда получает ошибку истечения токена.

#### Вариант 2: Scheduled task (cron)

```python
# Celery task для напоминания об обновлении
@celery_app.task
def check_vk_token_expiry():
    # Проверить credentials с expiry < 1 hour
    # Отправить уведомление пользователю
    pass
```

#### Вариант 3: Notification система

При ошибке `access_token has expired` показывать пользователю UI для переавторизации:

```javascript
// Frontend
if (error.code === 'vk_token_expired') {
  showModal('Требуется обновить VK токен', {
    action: 'reauthorize',
    url: '/api/v1/oauth/vk/authorize/implicit'
  });
}
```

### Обязательные поля VK

| Поле | Описание |
|------|----------|
| `access_token` | VK access token (min 10 символов) |

### Опциональные (но рекомендуемые) поля

| Поле | Описание | Важность |
|------|----------|----------|
| `user_id` | VK user ID | ⭐⭐⭐ Очень важно |
| `refresh_token` | Для автообновления | ⭐⭐⭐ VK ID only |
| `client_id` | VK application ID | ⭐⭐ Для OAuth |
| `client_secret` | VK client secret | ⭐⭐ Для OAuth |
| `expiry` | Время истечения токена | ⭐ Удобно |
| `group_id` | ID группы для постинга | ⭐ Опционально |
| `album_id` | ID альбома | ⭐ Опционально |

**⚠️ Важно:** `user_id` необходим для многих операций VK API. Система может работать без него, но с ограниченной функциональностью.

---

## Zoom Credentials

### 1. OAuth 2.0 (⭐ рекомендуется для multi-user)

**С refresh token - можно обновлять автоматически:**

```json
{
  "client_id": "Xyz789Abc",
  "client_secret": "verylongsecretstring123456",
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzUxMiIsInYiOiIyLjAiLCJraWQi...",
  "token_type": "bearer",
  "scope": "cloud_recording:read:list_user_recordings cloud_recording:read:recording recording:write:recording user:read:user",
  "expires_in": 3600,
  "expiry": "2026-01-10T12:00:00Z"
}
```

**Получение:**
```bash
GET /api/v1/oauth/zoom/authorize
```

**Преимущества:**
- ✅ Refresh token для автоматического обновления
- ✅ Multi-user support (каждый пользователь со своими credentials)
- ✅ Web-based authorization (не требует интерактивного CLI)

**Необходимые scopes (User-level):**
- `cloud_recording:read:list_user_recordings` - список своих записей
- `cloud_recording:read:recording` - детали записи
- `recording:write:recording` - удаление своих записей
- `user:read:user` - информация о себе

### 2. Server-to-Server OAuth (legacy, single-user)

**Для одного аккаунта без user-specific авторизации:**

```json
{
  "account_id": "abc123def456",
  "client_id": "Xyz789Abc",
  "client_secret": "verylongsecretstring123456",
  "account": "my_zoom_account"
}
```

**Получение:**
Zoom Developer Console → Build App → Server-to-Server OAuth

**Ограничения:**
- ❌ Один аккаунт для всех пользователей системы
- ❌ Нет user-specific permissions
- ⚠️ Подходит только для single-tenant использования

### Сравнение методов

| Метод | Refresh Token | Multi-user | Рекомендация |
|-------|---------------|------------|--------------|
| **OAuth 2.0** | ✅ Да | ✅ Да | ⭐ **Production multi-user** |
| Server-to-Server | N/A | ❌ Нет | Legacy / Single-tenant |

### Обязательные поля OAuth 2.0

| Поле | Описание |
|------|----------|
| `access_token` | JWT access token для Zoom API |
| `client_id` | Zoom OAuth client ID |
| `client_secret` | Zoom OAuth client secret |

### Опциональные поля OAuth 2.0

| Поле | Описание |
|------|----------|
| `refresh_token` | Refresh token (обязателен для долгосрочного использования) |
| `expiry` | Время истечения токена (ISO 8601) |
| `token_type` | Тип токена (обычно "bearer") |
| `scope` | Предоставленные OAuth scopes |

---

## API Endpoints

### Добавление credentials вручную

```bash
POST /api/v1/credentials/
Authorization: Bearer YOUR_JWT_TOKEN
Content-Type: application/json

{
  "platform": "vk_video",
  "account_name": "my_vk_account",
  "credentials": {
    "access_token": "xxx...",
    "user_id": 123456
  }
}
```

### Список credentials пользователя

```bash
GET /api/v1/credentials/
Authorization: Bearer YOUR_JWT_TOKEN
```

### Удаление credentials

```bash
DELETE /api/v1/credentials/{credential_id}
Authorization: Bearer YOUR_JWT_TOKEN
```

---

## Валидация Credentials

### Python API

```python
from api.helpers.credentials_validator import CredentialsValidator

# Validate VK credentials
is_valid, error = CredentialsValidator.validate_vk({
    "access_token": "xxx...",
    "user_id": 123456
})

if is_valid:
    print("Credentials valid!")
else:
    print(f"Error: {error}")

# Get required fields for platform
required = CredentialsValidator.get_required_fields("vk_video")
print(required)  # ['access_token']

# Get optional fields
optional = CredentialsValidator.get_optional_fields("vk_video")
print(optional)  # ['refresh_token', 'user_id', ...]
```

### Pydantic Validation

```python
from api.schemas.credentials.platform_credentials import VKCredentialsManual

# Auto-validates on instantiation
creds = VKCredentialsManual(
    access_token="xxx...",
    user_id=123456,
    refresh_token="yyy..."
)
```

---

## Сравнение методов получения VK credentials

| Метод | Refresh Token | Длительность | Multi-user | Доступность | Рекомендация |
|-------|---------------|--------------|------------|-------------|--------------|
| VK ID OAuth 2.1 | ✅ Да | До обновления | ✅ Да | ⚠️ Только старые app | Legacy |
| **Implicit Flow** | ❌ Нет | ~24 часа | ✅ Да | ✅ **Доступен всем** | ⭐ **Multi-user** |
| Service Token | ❌ Нет | Не истекает | ❌ Нет | ✅ Доступен | Single-user |
| setup_vk.py | ❌ Нет | ~24 часа | ❌ Нет | ✅ Доступен | CLI/Dev |

**Рекомендации (январь 2026):**
- **Production multi-user:** ⭐ **Implicit Flow** (обновление токена каждые 24 часа через cron/webhook)
- **Single-user бот:** Service Token (не истекает)
- **Dev/Testing:** setup_vk.py (быстрый старт)
- **Legacy приложения:** VK ID OAuth 2.1 (если уже одобрен)

⚠️ **Важно:** VK больше не одобряет расширенные права для новых приложений. Implicit Flow - единственный доступный метод для multi-user функциональности в новых проектах.

---

## Troubleshooting

### YouTube: "Invalid grant"

**Проблема:** refresh_token expired или revoked

**Решение:**
1. Получите новый OAuth token через `/api/v1/oauth/youtube/authorize`
2. Проверьте, что приложение не в тестовом режиме (ограничение 7 дней)

### VK: "User authorization failed: access_token has expired"

**Проблема:** Токен истек

**Решение:**
- **VK ID OAuth:** Используйте refresh_token (автоматически)
- **Implicit Flow:** Получите новый токен
- **Service Token:** Не истекает (проверьте, не был ли отозван)

### Zoom: "Invalid access token"

**Проблема:** Access token expired или revoked

**Решение:**
1. **OAuth 2.0:** Используйте refresh_token (автоматически в системе)
2. Получите новый OAuth token через `/api/v1/oauth/zoom/authorize`
3. Проверьте scopes приложения в Zoom Developer Console

### Zoom: "User does not have recording permission"

**Проблема:** Недостаточно прав в Zoom

**Решение:**
1. Убедитесь, что OAuth app имеет необходимые scopes:
   - `cloud_recording:read:list_user_recordings`
   - `cloud_recording:read:recording`
   - `recording:write:recording`
   - `user:read:user`
2. Переавторизуйтесь через OAuth flow для обновления scopes

### VK: "user_id is missing"

**Проблема:** Credentials не содержат user_id

**Решение:**
1. Добавьте user_id вручную через API:
   ```bash
   PATCH /api/v1/credentials/{id}
   {
     "credentials": { "user_id": 123456 }
   }
   ```
2. Или пересоздайте credentials через OAuth

### Zoom: "Invalid client credentials"

**Проблема:** Неверные account_id, client_id или client_secret

**Решение:**
1. Проверьте Zoom Developer Console
2. Убедитесь, что приложение активировано
3. Проверьте, что скопировали правильные credentials

---

## Best Practices

### 1. Используйте refresh tokens

**YouTube:** Обязательно сохраняйте refresh_token  
**VK:** Используйте VK ID OAuth 2.1 для автообновления

### 2. Храните user_id для VK

Многие операции VK API требуют user_id. Всегда сохраняйте его в credentials.

### 3. Используйте account_name

Давайте понятные имена credentials для идентификации:
- ❌ "credentials_1", "vk_2"
- ✅ "my_main_channel", "lecture_vk_group"

### 4. Мониторьте expiry

Проверяйте `expiry` поле и обновляйте токены заранее (за 5-10 минут до истечения).

### 5. Тестируйте credentials после добавления

```bash
# Upload test video
POST /api/v1/recordings/{id}/upload/{platform}
```

---

## Security

### ⚠️ Важно

- Credentials шифруются в БД (Fernet)
- Никогда не коммитьте credentials в Git
- Добавьте `config/*_creds.json` в `.gitignore`
- Используйте environment variables для production

### Защита credentials

```bash
# .gitignore
config/*_creds.json
config/oauth_*.json
*.token
*.credentials
```

---

## Changelog

### v2.10 (2026-01-08)

- ✅ Добавлена валидация credentials через Pydantic
- ✅ Создан CredentialsValidator helper
- ✅ Исправлен setup_vk.py для сохранения user_id
- ✅ Добавлены примеры всех форматов credentials
- ✅ Полная документация для YouTube, VK, Zoom

