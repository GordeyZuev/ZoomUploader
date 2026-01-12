# ⚠️ VK Policy Update - Январь 2026

## Критическое изменение

**VK прекратил выдачу расширенных API-доступов для новых приложений.**

### Официальное сообщение от VK Support

> Здравствуйте!
> 
> Спасибо за обращение. В связи с изменениями доступности расширенных API-методов новые расширенные API-доступы в сервисе больше не выдаются, согласно п.7.2 условий Оферты.
> 
> Команда Поддержки VK ID

**Дата:** 8 января 2026  
**Источник:** [VK ID Оферта п.7.2](https://id.vk.com/terms)

---

## Что это означает

### До изменений ✅

- **VK ID OAuth 2.1** - основной метод для multi-user приложений
- Refresh tokens позволяли автоматически обновлять доступ
- Расширенные права (video, groups, wall) одобрялись для новых приложений

### После изменений ⚠️

- **VK ID OAuth 2.1** - доступен ТОЛЬКО для существующих приложений
- Новые приложения получают отказ в расширенных правах
- Необходимо использовать альтернативные методы

---

## Доступные методы для новых проектов

### 1. ⭐ Implicit Flow (рекомендуется для multi-user)

**Плюсы:**
- ✅ Доступен для всех приложений
- ✅ Поддерживает multi-user
- ✅ Расширенные права (video, groups, wall)

**Минусы:**
- ❌ Нет refresh token
- ❌ Токен истекает ~24 часа
- ❌ Требует переавторизации

**Endpoint:**
```bash
GET /api/v1/oauth/vk/authorize/implicit
```

**Использование:**
```bash
curl 'http://localhost:8000/api/v1/oauth/vk/authorize/implicit' \
  -H 'Authorization: Bearer YOUR_JWT'
```

### 2. Service Token (для single-user ботов)

**Плюсы:**
- ✅ Не истекает
- ✅ Простая настройка
- ✅ Полные права приложения

**Минусы:**
- ❌ Только для владельца приложения
- ❌ Не подходит для multi-user

**Получение:**
VK Developer Console → Приложение → Настройки → Сервисный ключ доступа

### 3. Legacy VK ID OAuth 2.1 (только для существующих app)

**Статус:** Работает только для приложений, которые **УЖЕ ИМЕЮТ** одобренные расширенные права.

Если ваше приложение было одобрено до изменения политики - продолжайте использовать.

---

## Стратегия миграции

### Для новых проектов

```
1. Используйте Implicit Flow как основной метод
2. Настройте систему обновления токенов:
   - Webhook уведомления при истечении
   - UI для переавторизации
   - Celery task для мониторинга expiry
3. Или используйте Service Token для single-user
```

### Для существующих проектов

```
Если у вас УЖЕ ЕСТЬ VK ID OAuth 2.1:
  → Продолжайте использовать (работает)
  → Не пересоздавайте приложение

Если НЕТ VK ID OAuth:
  → Перейдите на Implicit Flow
  → Или используйте Service Token
```

---

## Реализация в ZoomUploader

### ✅ Все методы поддерживаются

#### 1. Implicit Flow

**Endpoint:** `/api/v1/oauth/vk/authorize/implicit`

Генерирует URL для авторизации и инструкции по получению токена.

**Пример credentials:**
```json
{
  "platform": "vk_video",
  "account_name": "my_vk",
  "credentials": {
    "access_token": "vk1.a.EXAMPLE_TOKEN_xxx...",
    "user_id": 123456
  }
}
```

#### 2. Service Token

**Добавление через API:**
```bash
POST /api/v1/credentials/
{
  "platform": "vk_video",
  "account_name": "service_bot",
  "credentials": {
    "access_token": "SERVICE_TOKEN_EXAMPLE_xxx...",
    "user_id": 123456
  }
}
```

#### 3. VK ID OAuth 2.1 (legacy)

**Endpoint:** `/api/v1/oauth/vk/authorize`

Работает только если приложение уже имеет одобренные права.

---

## Автоматизация обновления токенов (Implicit Flow)

### Вариант 1: Celery Task

```python
@celery_app.task
def check_vk_token_expiry():
    """Проверка истечения VK токенов."""
    expiring = find_expiring_credentials(
        platform="vk_video",
        hours=1  # Уведомлять за 1 час
    )
    
    for cred in expiring:
        send_notification(
            user_id=cred.user_id,
            message="VK токен истекает. Требуется переавторизация.",
            action_url="/oauth/vk/authorize/implicit"
        )
```

### Вариант 2: Frontend Notification

```javascript
// При ошибке "token expired"
if (error.code === 'vk_token_expired') {
  showModal({
    title: 'Требуется обновить VK токен',
    message: 'Токен истек. Переавторизуйтесь для продолжения.',
    action: {
      label: 'Обновить токен',
      url: '/api/v1/oauth/vk/authorize/implicit'
    }
  });
}
```

### Вариант 3: Scheduled Reminder

```python
# Cron: Каждые 12 часов
@celery_app.task
def remind_token_refresh():
    """Напоминание об обновлении токенов."""
    credentials = get_credentials_older_than(hours=12)
    
    for cred in credentials:
        if not cred.has_refresh_token:
            send_email_reminder(cred.user)
```

---

## Сравнение методов

| Метод | Доступность | Multi-user | Refresh | Длительность | Рекомендация |
|-------|-------------|------------|---------|--------------|--------------|
| **Implicit Flow** | ✅ Все | ✅ Да | ❌ Нет | 24 часа | ⭐ **Production** |
| Service Token | ✅ Все | ❌ Нет | ❌ Нет | Не истекает | Single-user |
| VK ID OAuth | ⚠️ Legacy | ✅ Да | ✅ Да | До обновления | Существующие app |
| setup_vk.py | ✅ Все | ❌ Нет | ❌ Нет | 24 часа | Dev/CLI |

---

## Рекомендации

### Для multi-user приложений

```
✅ Используйте: Implicit Flow
✅ Настройте: Систему уведомлений об истечении токена
✅ Реализуйте: UI для быстрой переавторизации
✅ Мониторьте: Expiry времени токенов
```

### Для single-user ботов

```
✅ Используйте: Service Token
✅ Преимущество: Не истекает
✅ Ограничение: Только владелец приложения
```

### Для development

```
✅ Используйте: setup_vk.py
✅ Преимущество: Быстрый старт
✅ Ограничение: Токен 24 часа
```

---

## FAQ

### Q: Можно ли получить VK ID OAuth для нового приложения?

**A:** Нет. VK прекратил выдачу расширенных API-доступов с января 2026.

### Q: Работает ли VK ID OAuth для существующих приложений?

**A:** Да! Если ваше приложение уже имеет одобренные права - продолжайте использовать.

### Q: Как часто нужно обновлять Implicit Flow токен?

**A:** Примерно каждые 24 часа. Рекомендуем мониторить `expiry` и уведомлять за 1-2 часа.

### Q: Можно ли автоматизировать Implicit Flow?

**A:** Нет полной автоматизации (нет refresh token). Но можно автоматизировать уведомления и упростить процесс переавторизации через UI.

### Q: Service Token может истечь?

**A:** Нет, Service Token не истекает. Но он может быть отозван в настройках приложения.

### Q: Что делать если токен истек во время загрузки?

**A:** Система вернет ошибку. Пользователь должен переавторизоваться. Рекомендуем показывать friendly UI для быстрой переавторизации.

---

## Полезные ссылки

- [CREDENTIALS_GUIDE.md](CREDENTIALS_GUIDE.md) - Полное руководство по credentials
- [VK ID Оферта](https://id.vk.com/terms) - Официальные условия
- [VK ID Documentation](https://id.vk.com/about/business/go/docs/ru/vkid/latest/vk-id/connection/tokens/access-token) - Документация по токенам
- [Implicit Flow Endpoint](/api/v1/oauth/vk/authorize/implicit) - Генерация токена

---

## Статус в ZoomUploader

✅ **Полностью адаптировано к новой политике**

- ✅ Implicit Flow endpoint реализован
- ✅ Service Token поддерживается
- ✅ VK ID OAuth работает для legacy
- ✅ setup_vk.py сохраняет полный формат
- ✅ Документация обновлена
- ✅ Примеры credentials готовы

**Дата обновления:** 8 января 2026  
**Версия:** v2.10

