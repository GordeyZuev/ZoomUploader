# Quota & Admin API Documentation

**Дата:** 9 января 2026  
**Версия:** v2.11

---

## Обзор изменений

### Что было сделано

1. **Отдельный роутер для квот** (`/api/v1/quota`)
2. **Упрощен `/api/v1/users/me`** - убрана информация о квотах
3. **Admin роутер** (`/api/v1/admin/stats`) для просмотра статистики
4. **Admin dependency** - проверка роли `admin`

---

## User Quota Endpoints

### GET /api/v1/users/me/quota

Получить полный статус квот текущего пользователя.

**Требует:** JWT токен

**Response:**
```json
{
  "subscription": {
    "id": 1,
    "user_id": 1,
    "plan": {
      "id": 1,
      "name": "free",
      "display_name": "Free Plan",
      "included_recordings_per_month": 10,
      "included_storage_gb": 5,
      "max_concurrent_tasks": 1,
      "max_automation_jobs": 0,
      "min_automation_interval_hours": null,
      "price_monthly": 0.00,
      "is_active": true
    },
    "custom_max_recordings_per_month": null,
    "custom_max_storage_gb": null,
    "effective_max_recordings_per_month": 10,
    "effective_max_storage_gb": 5,
    "effective_max_concurrent_tasks": 1,
    "pay_as_you_go_enabled": false,
    "starts_at": "2026-01-09T00:00:00Z",
    "expires_at": null
  },
  "current_usage": {
    "period": 202601,
    "recordings_count": 3,
    "storage_gb": 1.25,
    "concurrent_tasks_count": 0,
    "overage_recordings_count": 0,
    "overage_cost": 0.00
  },
  "recordings": {
    "used": 3,
    "limit": 10,
    "available": 7
  },
  "storage": {
    "used_gb": 1.25,
    "limit_gb": 5,
    "available_gb": 3.75
  },
  "concurrent_tasks": {
    "used": 0,
    "limit": 1,
    "available": 1
  },
  "automation_jobs": {
    "used": 0,
    "limit": 0,
    "available": 0
  },
  "is_overage_enabled": false,
  "overage_cost_this_month": 0.00,
  "overage_limit": null
}
```

**Ключевые поля:**
- `subscription.plan` - базовый план (Free/Plus/Pro/Enterprise)
- `subscription.custom_*` - индивидуальные переопределения (если есть)
- `subscription.effective_*` - эффективные квоты (custom override plan)
- `current_usage` - использование за текущий период (YYYYMM)
- `recordings/storage/concurrent_tasks/automation_jobs` - детальный статус по каждой квоте

---

### GET /api/v1/users/me/quota/history

Получить историю использования квот.

**Требует:** JWT токен

**Query Parameters:**
- `limit` (int, default=12, max=24) - количество периодов
- `period` (int, optional) - конкретный период (YYYYMM)

**Examples:**
```bash
# Последние 12 месяцев
GET /api/v1/users/me/quota/history

# Последние 6 месяцев
GET /api/v1/users/me/quota/history?limit=6

# Только январь 2026
GET /api/v1/users/me/quota/history?period=202601
```

**Response:**
```json
[
  {
    "period": 202601,
    "recordings_count": 3,
    "storage_gb": 1.25,
    "concurrent_tasks_count": 0,
    "overage_recordings_count": 0,
    "overage_cost": 0.00
  },
  {
    "period": 202512,
    "recordings_count": 8,
    "storage_gb": 2.50,
    "concurrent_tasks_count": 0,
    "overage_recordings_count": 0,
    "overage_cost": 0.00
  }
]
```

---

## Updated User Endpoint

### GET /api/v1/users/me

Получить базовую информацию о текущем пользователе (без квот).

**Требует:** JWT токен

**Response:**
```json
{
  "id": 1,
  "email": "user@example.com",
  "full_name": "John Doe",
  "timezone": "Europe/Moscow",
  "role": "user",
  "is_active": true,
  "is_verified": false,
  "created_at": "2026-01-09T10:00:00Z",
  "last_login_at": "2026-01-09T12:00:00Z"
}
```

**Изменения:**
- ❌ Убрано поле `quota_status`
- ✅ Для квот используйте `GET /api/v1/users/me/quota`

---

## Admin Endpoints

### GET /api/v1/admin/stats/overview

Получить общую статистику платформы.

**Требует:** JWT токен + роль `admin`

**Response:**
```json
{
  "total_users": 150,
  "active_users": 142,
  "total_recordings": 1250,
  "total_storage_gb": 320.50,
  "total_plans": 4,
  "users_by_plan": {
    "free": 120,
    "plus": 20,
    "pro": 8,
    "enterprise": 2
  }
}
```

---

### GET /api/v1/admin/stats/users

Получить детальную статистику по пользователям.

**Требует:** JWT токен + роль `admin`

**Query Parameters:**
- `page` (int, default=1) - номер страницы
- `page_size` (int, default=50, max=100) - размер страницы
- `exceeded_only` (bool, default=false) - только пользователи с превышением квот
- `plan_name` (str, optional) - фильтр по плану (free, plus, pro, enterprise)

**Examples:**
```bash
# Все пользователи (первая страница)
GET /api/v1/admin/stats/users

# Только пользователи с превышением квот
GET /api/v1/admin/stats/users?exceeded_only=true

# Только пользователи на Free плане
GET /api/v1/admin/stats/users?plan_name=free

# Вторая страница, 20 пользователей
GET /api/v1/admin/stats/users?page=2&page_size=20
```

**Response:**
```json
{
  "total_count": 150,
  "users": [
    {
      "user_id": 1,
      "email": "user1@example.com",
      "plan_name": "free",
      "recordings_used": 8,
      "recordings_limit": 10,
      "storage_used_gb": 3.25,
      "storage_limit_gb": 5,
      "is_exceeding": false,
      "overage_enabled": false,
      "overage_cost": 0.00
    },
    {
      "user_id": 5,
      "email": "user5@example.com",
      "plan_name": "plus",
      "recordings_used": 55,
      "recordings_limit": 50,
      "storage_used_gb": 28.50,
      "storage_limit_gb": 25,
      "is_exceeding": true,
      "overage_enabled": true,
      "overage_cost": 2.50
    }
  ],
  "page": 1,
  "page_size": 50
}
```

**Ключевые поля:**
- `is_exceeding` - превышены ли квоты (recordings или storage)
- `overage_enabled` - включен ли Pay-as-you-go
- `overage_cost` - стоимость превышения за текущий месяц

---

### GET /api/v1/admin/stats/quotas

Получить статистику использования квот по планам.

**Требует:** JWT токен + роль `admin`

**Query Parameters:**
- `period` (int, optional) - период (YYYYMM), по умолчанию текущий

**Examples:**
```bash
# Текущий месяц
GET /api/v1/admin/stats/quotas

# Январь 2026
GET /api/v1/admin/stats/quotas?period=202601
```

**Response:**
```json
{
  "period": 202601,
  "total_recordings": 1250,
  "total_storage_gb": 320.50,
  "total_overage_cost": 125.50,
  "plans": [
    {
      "plan_name": "free",
      "total_users": 120,
      "total_recordings": 850,
      "total_storage_gb": 180.25,
      "avg_recordings_per_user": 7.08,
      "avg_storage_per_user_gb": 1.50
    },
    {
      "plan_name": "plus",
      "total_users": 20,
      "total_recordings": 280,
      "total_storage_gb": 95.50,
      "avg_recordings_per_user": 14.00,
      "avg_storage_per_user_gb": 4.78
    },
    {
      "plan_name": "pro",
      "total_users": 8,
      "total_recordings": 100,
      "total_storage_gb": 38.75,
      "avg_recordings_per_user": 12.50,
      "avg_storage_per_user_gb": 4.84
    },
    {
      "plan_name": "enterprise",
      "total_users": 2,
      "total_recordings": 20,
      "total_storage_gb": 6.00,
      "avg_recordings_per_user": 10.00,
      "avg_storage_per_user_gb": 3.00
    }
  ]
}
```

---

## Архитектура

### Компоненты

```
api/
├── routers/
│   ├── quota.py           # User quota endpoints
│   ├── admin.py           # Admin stats endpoints
│   └── users.py           # Updated /me endpoint
├── auth/
│   └── admin.py           # Admin dependency (role check)
├── schemas/
│   ├── admin/
│   │   ├── __init__.py
│   │   └── stats.py       # Admin stats schemas
│   └── auth/
│       └── response.py    # Updated UserMeResponse
└── services/
    └── quota_service.py   # QuotaService (unchanged)
```

### Dependency: get_current_admin

```python
from api.auth.admin import get_current_admin

@router.get("/admin/stats/overview")
async def get_overview_stats(
    _admin: UserInDB = Depends(get_current_admin),
):
    # Only users with role="admin" can access
    ...
```

**Логика:**
1. Проверяет JWT токен (через `get_current_user`)
2. Проверяет `current_user.role == "admin"`
3. Возвращает `403 Forbidden` если не админ

---

## Примеры использования

### User: Проверка квот

```bash
# 1. Получить JWT токен
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"password123"}'

# Response: {"access_token": "...", "refresh_token": "..."}

# 2. Проверить квоты
curl http://localhost:8000/api/v1/users/me/quota \
  -H "Authorization: Bearer ACCESS_TOKEN"

# 3. Посмотреть историю
curl http://localhost:8000/api/v1/users/me/quota/history?limit=6 \
  -H "Authorization: Bearer ACCESS_TOKEN"
```

### Admin: Статистика платформы

```bash
# 1. Войти как админ
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"admin123"}'

# 2. Общая статистика
curl http://localhost:8000/api/v1/admin/stats/overview \
  -H "Authorization: Bearer ADMIN_TOKEN"

# 3. Пользователи с превышением квот
curl "http://localhost:8000/api/v1/admin/stats/users?exceeded_only=true" \
  -H "Authorization: Bearer ADMIN_TOKEN"

# 4. Статистика по квотам за декабрь 2025
curl "http://localhost:8000/api/v1/admin/stats/quotas?period=202512" \
  -H "Authorization: Bearer ADMIN_TOKEN"
```

---

## Безопасность

### Роли

- **user** - обычный пользователь (доступ к `/api/v1/quota`)
- **admin** - администратор (доступ к `/api/v1/admin/*`)

### Проверка прав

```python
# User endpoints - требуют только JWT токен
@router.get("/users/me/quota")
async def get_my_quota(current_user: UserInDB = Depends(get_current_user)):
    ...

# Admin endpoints - требуют JWT + role=admin
@router.get("/admin/stats/overview")
async def get_overview(_admin: UserInDB = Depends(get_current_admin)):
    ...
```

---

## Миграция с предыдущей версии

### Что изменилось

**Было:**
```bash
GET /api/v1/users/me
# → Возвращал user + quota_status
```

**Стало:**
```bash
GET /api/v1/users/me
# → Возвращает только user (без quota_status)

GET /api/v1/users/me/quota
# → Возвращает полный quota_status
```

### Обновление клиентского кода

**Старый код:**
```typescript
const response = await fetch('/api/v1/users/me');
const { user, quota_status } = await response.json();
```

**Новый код:**
```typescript
// Базовая информация о пользователе
const userResponse = await fetch('/api/v1/users/me');
const user = await userResponse.json();

// Квоты (отдельный запрос)
const quotaResponse = await fetch('/api/v1/users/me/quota');
const quota_status = await quotaResponse.json();
```

---

## Готовность к Production

| Компонент | Статус | Комментарий |
|-----------|--------|-------------|
| Quota endpoints | ✅ Готов | 2 endpoints |
| Admin endpoints | ✅ Готов | 3 endpoints |
| Admin dependency | ✅ Готов | Role check |
| Updated /users/me | ✅ Готов | Simplified response |
| Linter errors | ✅ 0 | Clean code |
| Import checks | ✅ Passed | All imports successful |

---

## Итоги

### Добавлено

- ✅ 2 user quota endpoints (`/api/v1/users/me/quota`, `/api/v1/users/me/quota/history`)
- ✅ 3 admin stats endpoints (`/overview`, `/users`, `/quotas`)
- ✅ Admin dependency с проверкой роли
- ✅ Упрощен `/api/v1/users/me` (убрана quota_status)

### Файлы созданы

- `api/routers/admin.py` - Admin stats router
- `api/auth/admin.py` - Admin dependency
- `api/schemas/admin/__init__.py` - Admin schemas export
- `api/schemas/admin/stats.py` - Admin stats schemas
- `docs/QUOTA_AND_ADMIN_API.md` - Документация

### Файлы изменены

- `api/routers/users.py` - Добавлены `/me/quota` endpoints + обновлен `/me`
- `api/routers/auth.py` - Обновлен register для новой системы подписок
- `api/auth/dependencies.py` - Обновлен `check_user_quotas`
- `api/schemas/auth/response.py` - Добавлен `UserMeResponse`
- `api/schemas/auth/__init__.py` - Обновлены экспорты
- `api/main.py` - Добавлен admin роутер
- `database/auth_models.py` - Исправлен relationship для subscription

**Всего endpoints:** 67 (было 65)  
**Linter errors:** 0 ✅

