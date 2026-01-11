# VK Token API - Implicit Flow Integration

Простое API для работы с VK токенами (Implicit Flow).

## 🎯 Зачем это нужно?

VK Implicit Flow не поддерживает refresh token, поэтому токен нужно обновлять вручную каждые ~24 часа.

Эти endpoints упрощают процесс:
- ✅ Валидация токена через VK API
- ✅ Автоматическое извлечение `user_id`
- ✅ Сохранение с отслеживанием expiry
- ✅ Проверка статуса токена

---

## 📡 Endpoints

### 1. POST `/api/v1/oauth/vk/token/submit`

**Описание:** Принимает и сохраняет VK access token.

**Требует авторизации:** Да (Bearer token)

#### Request Body

Принимает **полный URL** из браузера или **только токен**:

```json
{
  "token_data": "https://oauth.vk.com/blank.html#access_token=vk1.a.ABC123...&expires_in=86400&user_id=123456",
  "account_name": "my_vk"  // опционально
}
```

Или просто токен:

```json
{
  "token_data": "vk1.a.ABC123...",
  "account_name": "my_vk"  // опционально
}
```

#### Response (200 OK)

```json
{
  "success": true,
  "credential_id": 42,
  "user_id": 123456,
  "expiry": "2026-01-11T15:30:00Z",
  "message": "VK token saved successfully (expires in 24h)"
}
```

#### Response (400 Bad Request) - IP Mismatch

```json
{
  "detail": {
    "error": "IP address mismatch",
    "message": "Token is bound to a different IP address",
    "solution": "Please obtain a new token from your current IP address",
    "error_type": "ip_mismatch"
  }
}
```

#### Response (400 Bad Request) - Invalid Token

```json
{
  "detail": {
    "error": "VK API error",
    "message": "Token validation failed due to VK API error",
    "solution": "Check token permissions and try again",
    "error_type": "api_error"
  }
}
```

---

### 2. GET `/api/v1/oauth/vk/token/status`

**Описание:** Проверить статус VK токена.

**Требует авторизации:** Да (Bearer token)

#### Response (200 OK) - Token Valid

```json
{
  "has_token": true,
  "is_valid": true,
  "expiry": "2026-01-11T15:30:00Z",
  "time_until_expiry": "18h 45m",
  "needs_refresh": false,
  "credential_id": 42
}
```

#### Response (200 OK) - Token Expiring Soon

```json
{
  "has_token": true,
  "is_valid": true,
  "expiry": "2026-01-10T17:00:00Z",
  "time_until_expiry": "1h 30m",
  "needs_refresh": true,  // < 2 hours left
  "credential_id": 42
}
```

#### Response (200 OK) - Token Expired

```json
{
  "has_token": true,
  "is_valid": false,
  "expiry": "2026-01-09T15:30:00Z",
  "time_until_expiry": "expired",
  "needs_refresh": true,
  "credential_id": 42
}
```

#### Response (200 OK) - No Token

```json
{
  "has_token": false,
  "is_valid": null,
  "expiry": null,
  "time_until_expiry": null,
  "needs_refresh": true,
  "credential_id": null
}
```

---

## 🚀 Workflow: Получение и сохранение токена

### Шаг 1: Получить authorization URL

```bash
curl -X GET 'http://localhost:8000/api/v1/oauth/vk/authorize/implicit' \
  -H 'Authorization: Bearer YOUR_JWT_TOKEN'
```

**Response:**
```json
{
  "method": "implicit_flow",
  "app_id": "54249533",
  "authorization_url": "https://oauth.vk.com/authorize?client_id=54249533&...",
  "instructions": [
    "1. Open authorization_url in browser",
    "2. Allow app permissions (video, groups, wall)",
    "3. Copy access_token from redirected URL",
    "4. POST to /api/v1/vk/token/submit"
  ]
}
```

### Шаг 2: Открыть URL в браузере

1. Перейдите по `authorization_url`
2. Разрешите доступ приложению
3. Скопируйте `access_token` из URL:
   ```
   https://oauth.vk.com/blank.html#access_token=vk1.a.ABC123...&expires_in=86400&user_id=123456
   ```

### Шаг 3: Отправить токен в API

Копируем **весь URL** из браузера:

```bash
curl -X POST 'http://localhost:8000/api/v1/oauth/vk/token/submit' \
  -H 'Authorization: Bearer YOUR_JWT_TOKEN' \
  -H 'Content-Type: application/json' \
  -d '{
    "token_data": "https://oauth.vk.com/blank.html#access_token=vk1.a.ABC123...&expires_in=86400&user_id=123456",
    "account_name": "my_vk"
  }'
```

### Шаг 4: Проверить статус (опционально)

```bash
curl -X GET 'http://localhost:8000/api/v1/oauth/vk/token/status' \
  -H 'Authorization: Bearer YOUR_JWT_TOKEN'
```

---

## 🔄 Обновление истекшего токена

Когда токен истекает, просто повторите процесс:

1. **Проверьте статус:**
   ```bash
   GET /api/v1/oauth/vk/token/status
   # needs_refresh: true
   ```

2. **Получите новый токен:**
   ```bash
   GET /api/v1/oauth/vk/authorize/implicit
   # → Откройте URL, получите новый access_token
   ```

3. **Обновите credentials:**
   ```bash
   POST /api/v1/oauth/vk/token/submit
   {
     "token_data": "FULL_URL_OR_TOKEN",
     "account_name": "my_vk"  // тот же account_name → обновит существующий
   }
   ```

---

## ⚠️ Частые ошибки

### Ошибка: IP Mismatch

**Причина:** Токен привязан к другому IP-адресу.

**Решение:** Получите новый токен с **текущего** IP-адреса.

```bash
# НЕ используйте старый токен повторно!
# Получите НОВЫЙ токен через /oauth/vk/authorize/implicit
```

### Ошибка: Token Expired

**Причина:** Токен истек (прошло >24 часа).

**Решение:** Получите новый токен (см. "Обновление истекшего токена").

### Ошибка: Invalid Token

**Причина:** Неверный формат токена или отозванные права.

**Решение:** 
1. Проверьте, что скопировали весь `access_token` (без `access_token=`)
2. Убедитесь, что разрешили все права (video, groups, wall)
3. Получите новый токен

---

## 🤖 Автоматизация (будущее)

### Мониторинг expiry (TODO)

```python
# Celery task (будет добавлено позже)
@celery_app.task
def check_vk_token_expiry():
    """Проверяет токены каждый час и отправляет уведомления."""
    expiring_soon = find_expiring_tokens(hours=2)
    for credential in expiring_soon:
        send_notification(
            user_id=credential.user_id,
            message="VK token expires in < 2h. Please refresh.",
            action_url="/api/v1/vk/token/status"
        )
```

### UI Integration (TODO)

```javascript
// Frontend: Показать warning при needs_refresh: true
const status = await fetch('/api/v1/vk/token/status');
if (status.needs_refresh) {
  showModal({
    title: 'VK Token Expiring',
    message: `Token expires ${status.time_until_expiry}`,
    action: {
      label: 'Refresh Token',
      url: '/settings/vk/refresh'
    }
  });
}
```

---

## 🔗 Связанные документы

- [VK_POLICY_UPDATE_2026.md](VK_POLICY_UPDATE_2026.md) - Изменения политики VK
- [CREDENTIALS_GUIDE.md](CREDENTIALS_GUIDE.md) - Общее руководство по credentials
- [OAUTH_UPLOADER_INTEGRATION.md](OAUTH_UPLOADER_INTEGRATION.md) - OAuth интеграция

---

## 📊 Сравнение методов

| Метод | Refresh Token | Expiry | Сложность | Использование |
|-------|--------------|--------|-----------|---------------|
| **VK ID OAuth 2.1** | ✅ Да | До refresh | Средняя | Legacy apps only |
| **Implicit Flow (NEW)** | ❌ Нет | 24 часа | Низкая | ⭐ Рекомендуется |
| Service Token | ❌ Нет | Не истекает | Низкая | Single-user only |

---

## 🎉 Готово!

Теперь у вас есть простой способ управлять VK токенами через API.

**Полный workflow в 3 шага:**
1. `GET /oauth/vk/authorize/implicit` → Получить URL
2. Открыть URL → Скопировать токен
3. `POST /vk/token/submit` → Сохранить токен

**Дата создания:** 10 января 2026  
**Версия:** v1.0

