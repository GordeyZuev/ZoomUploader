# Architecture Decision Records - Overview

**Проект:** LEAP Platform  
**Версия:** 2.0 (Актуализировано: январь 2026)  
**Статус:** Production-Ready Multi-tenant SaaS

---

## 📋 Содержание

1. [Обзор](#обзор)
2. [Контекст и эволюция](#контекст-и-эволюция)
3. [Ключевые архитектурные решения](#ключевые-архитектурные-решения)
4. [Текущее состояние системы](#текущее-состояние-системы)
5. [См. также](#см-также)

---

## Обзор

### Цель документа

Данный документ описывает ключевые архитектурные решения для LEAP Platform - production-ready multi-tenant SaaS платформы для автоматизации обработки образовательного видеоконтента.

### Ключевые достижения

**✅ Реализовано (Production-Ready):**
- Multi-tenancy с полной изоляцией данных
- REST API (84 endpoints) с полной типизацией
- JWT Authentication + OAuth 2.0 (YouTube, VK, Zoom)
- Асинхронная обработка (Celery + Redis)
- Template-driven automation
- Subscription plans с квотами
- FSM для надежной обработки
- Admin API для мониторинга

**🔧 Технологии:**
- FastAPI (async)
- PostgreSQL (12 таблиц)
- Redis + Celery
- Pydantic V2 (118+ моделей)
- SQLAlchemy (async)
- Alembic (19 миграций)

---

## Контекст и эволюция

### Исходное состояние (v0.1 - CLI)

**Что было:**
- CLI-приложение для обработки Zoom записей
- Единая БД без изоляции
- Конфигурации в JSON файлах
- Нет API и аутентификации
- Single-user система

**Проблемы:**
- Невозможность масштабирования
- Отсутствие изоляции данных
- Ручная работа для каждой записи
- Нет автоматизации

### Трансформация (v0.5 - v0.9)

**Этапы развития:**
1. **v0.5** - Добавление PostgreSQL, базовая БД
2. **v0.6** - Модульная архитектура (separation of concerns)
3. **v0.7** - Multi-tenancy (shared database + user_id)
4. **v0.8** - REST API + JWT authentication
5. **v0.9** - Celery, OAuth 2.0, Templates, Subscriptions

### Текущее состояние (v0.9.3)

**Production-Ready SaaS платформа:**
- 84 REST API endpoints
- 12 database tables
- 3 OAuth integrations (YouTube, VK, Zoom)
- 4 subscription plans
- Template-driven automation
- Full async processing

---

## Ключевые архитектурные решения

### ADR-001: Multi-Tenancy Model

**Решение:** Shared Database с изоляцией через `user_id`

**Архитектура:**
```
┌──────────────────────────────────────────┐
│        Multi-Tenant Isolation            │
└──────────────────────────────────────────┘

User A (user_id=1)          User B (user_id=2)
    │                              │
    ├─ recordings (user_id=1)     ├─ recordings (user_id=2)
    ├─ templates (user_id=1)      ├─ templates (user_id=2)
    ├─ credentials (user_id=1)    ├─ credentials (user_id=2)
    └─ media/user_1/              └─ media/user_2/

    ┌─────────────────────────────────────┐
    │   PostgreSQL (shared database)      │
    │   + Row-level filtering by user_id  │
    └─────────────────────────────────────┘
```

**Обоснование:**

**Альтернативы:**
1. **Shared Database + Tenant ID** ← **выбрано**
2. Separate Databases per tenant
3. Separate Schemas (PostgreSQL)

**Преимущества выбранного решения:**
- ✅ Простота управления (единые миграции)
- ✅ Эффективное использование ресурсов
- ✅ Легко масштабировать горизонтально
- ✅ Проще бэкапы и восстановление
- ✅ Подходит для 10-1000 пользователей

**Риски и митигация:**
- **Риск утечки данных:** Repository pattern с автоматической фильтрацией по user_id
- **Производительность:** Индексы на (user_id, ...) во всех таблицах
- **Сложность запросов:** ServiceContext + Dependency Injection

**Реализация:**
- `api/core/context.py` - ServiceContext с user_id
- `api/repositories/` - автоматическая фильтрация
- `api/middleware/` - извлечение user_id из JWT

**Статус:** ✅ Полностью реализовано

---

### ADR-002: Authentication & Authorization

**Решение:** JWT Tokens (access + refresh) + OAuth 2.0

**Архитектура:**
```
┌──────────────────────────────────────────┐
│        Authentication Flow               │
└──────────────────────────────────────────┘

1. Registration → User created
2. Login → JWT (access + refresh)
3. Request → Bearer token validation
4. Token expired → Refresh token
5. OAuth → YouTube/VK/Zoom authorization
```

**Обоснование:**

**Альтернативы:**
1. **JWT Tokens** ← **выбрано**
2. API Keys
3. Session-based auth

**Преимущества:**
- ✅ Stateless архитектура
- ✅ Масштабируемость
- ✅ Стандарт для REST API
- ✅ Поддержка refresh tokens
- ✅ Совместимость с OAuth 2.0

**Реализация:**

**JWT Tokens:**
- Access Token: 1 час (короткоживущий)
- Refresh Token: 7 дней (долгоживущий, хранится в БД)
- Алгоритм: HS256
- Payload: user_id, role, permissions

**Roles:**
- `admin` - полный доступ, управление пользователями
- `user` - доступ к своим ресурсам

**OAuth 2.0 интеграции:**
- **YouTube** - OAuth 2.0, auto-refresh tokens
- **VK** - VK ID OAuth 2.1 (PKCE) + Implicit Flow API
- **Zoom** - OAuth 2.0 + Server-to-Server dual mode

**Файлы:**
- `api/core/security.py` - JWT создание и валидация
- `api/routers/auth.py` - endpoints (register, login, refresh)
- `api/routers/oauth/` - OAuth flows для всех платформ
- `database/auth_models.py` - User, RefreshToken models

**Статус:** ✅ Полностью реализовано

---

### ADR-003: Configuration Hierarchy

**Решение:** Трехуровневая иерархия (User Config → Template → Recording Override)

**Архитектура:**
```
┌──────────────────────────────────────────────────────┐
│           Configuration Resolution                    │
└──────────────────────────────────────────────────────┘

Level 1: User Config (defaults)
    ↓
Level 2: Template Config (if template_id set)
    ↓
Level 3: Recording Override (processing_preferences)
    ↓
Final Config → Used for processing
```

**Обоснование:**

**Требования:**
- Глобальные defaults для пользователя
- Template-specific настройки
- Per-recording overrides (высший приоритет)
- Live updates при изменении template

**Преимущества:**
- ✅ DRY - настройки переиспользуются
- ✅ Гибкость - можно переопределить на любом уровне
- ✅ Live updates - изменения template применяются автоматически
- ✅ Explicit overrides - ясно видны ручные изменения

**Реализация:**

**Структура:**
```python
# User Config (stored in user_configs table)
{
  "transcription": {"language": "ru", "enable_topics": true},
  "upload": {"auto_upload": false}
}

# Template Config (stored in recording_templates table)
{
  "processing_config": {...},
  "metadata_config": {...},
  "output_config": {"preset_ids": [1, 2], "auto_upload": true}
}

# Recording Override (stored in recordings.processing_preferences)
{
  "transcription": {"language": "en"}  # Only overrides
}

# Final merged config
{
  "transcription": {"language": "en", "enable_topics": true},  # en from override
  "upload": {"auto_upload": true}  # true from template
}
```

**ConfigResolver:**
- `api/services/config_resolver.py` - единая точка resolution
- Deep merge с приоритетами
- Endpoints для управления:
  - `GET /recordings/{id}/config` - resolved config
  - `PUT /recordings/{id}/config` - set override
  - `DELETE /recordings/{id}/config` - reset to template

**Статус:** ✅ Полностью реализовано

---

### ADR-004: Data Storage & Encryption

**Решение:** PostgreSQL + JSONB + Fernet Encryption

**Архитектура:**
```
┌──────────────────────────────────────────┐
│           Data Storage                    │
└──────────────────────────────────────────┘

PostgreSQL:
├─ Structured data (users, recordings, templates)
├─ JSONB для гибких конфигураций
├─ GIN индексы на JSONB полях
└─ Full-text search (когда нужно)

Encryption:
├─ user_credentials.encrypted_data (Fernet)
├─ Encryption key в environment
└─ Automatic encryption/decryption в CredentialService
```

**Обоснование:**

**JSONB vs отдельные таблицы:**
- ✅ Гибкость - легко добавлять новые поля
- ✅ Производительность - GIN индексы быстрые
- ✅ Простота - меньше таблиц и JOIN'ов
- ✅ Подходит для metadata, конфигураций

**Fernet Encryption:**
- Symmetric encryption (AES-128)
- Простой API (encrypt/decrypt)
- Стандарт Python (cryptography library)
- Ключ в environment variable

**Реализация:**
- `api/core/encryption.py` - CredentialEncryption class
- `api/services/credential_service.py` - auto encrypt/decrypt
- Environment: `API_ENCRYPTION_KEY`

**Статус:** ✅ Полностью реализовано

---

### ADR-005: Template Matching System

**Решение:** First-match strategy с priority ordering

**Архитектура:**
```
┌──────────────────────────────────────────┐
│        Template Matching Flow            │
└──────────────────────────────────────────┘

1. Recording synced from source
    ↓
2. Match against all templates:
   - exact_matches (display_name)
   - keywords (case-insensitive)
   - regex patterns
   - source_ids filter
    ↓
3. Select first match (by template.created_at ASC)
    ↓
4. Set recording.template_id
    ↓
5. Auto-apply template config
```

**Matching Rules:**
```json
{
  "exact_matches": ["Lecture: Machine Learning", "AI Course"],
  "keywords": ["ML", "AI", "neural networks"],
  "patterns": ["Лекция \\d+:.*ML", "\\[МО\\].*"],
  "source_ids": [1, 3],
  "match_mode": "any"  // "any" or "all"
}
```

**Обоснование:**

**Альтернативы:**
1. **First-match** ← **выбрано** (simple, predictable)
2. Best-match (score-based)
3. Multiple templates (array)

**Преимущества:**
- ✅ KISS - простая и понятная логика
- ✅ Предсказуемость - всегда ясно какой template
- ✅ Производительность - O(n) по templates
- ✅ Достаточно для 95% use cases

**Lifecycle:**
- Auto-match при sync
- Re-match при создании нового template
- Preview re-match перед применением
- Unmap при удалении template

**Реализация:**
- `api/services/template_matcher.py` - matching logic
- `api/repositories/template_repository.py` - DB queries
- Endpoints:
  - `POST /templates/{id}/preview-match` - preview
  - `POST /templates/{id}/rematch` - apply
  - `GET /recordings?is_mapped=false` - unmapped list

**Статус:** ✅ Полностью реализовано

**См. также:** [TEMPLATES.md](TEMPLATES.md) - Template matching & re-match

---

### ADR-006: Async Processing Pipeline

**Решение:** Celery + Redis для асинхронной обработки

**Архитектура:**
```
┌──────────────────────────────────────────┐
│        Async Processing                  │
└──────────────────────────────────────────┘

API Request → Create Celery Task → Return task_id
                    ↓
              Celery Worker picks up task
                    ↓
              Execute: download → process → transcribe → upload
                    ↓
              Update status in DB (progress tracking)
                    ↓
              Client polls GET /tasks/{task_id}
```

**Queues:**
- `processing` - video processing (CPU-intensive, 2 workers)
- `upload` - API calls (I/O-intensive, 1 worker)
- `automation` - scheduled jobs (1 worker)

**Обоснование:**

**Альтернативы:**
1. **Celery + Redis** ← **выбрано**
2. Background threads
3. Cloud functions (AWS Lambda)

**Преимущества:**
- ✅ Масштабируемость - горизонтальное добавление workers
- ✅ Reliability - auto-retry, error handling
- ✅ Monitoring - Flower UI для мониторинга
- ✅ Scheduling - Celery Beat для cron jobs
- ✅ Priority queues - разные очереди для разных задач

**Task Types:**
```python
# Processing tasks
- download_task(recording_id, user_id)
- process_video_task(recording_id, user_id)
- transcribe_task(recording_id, user_id)
- extract_topics_task(recording_id, user_id)
- generate_subtitles_task(recording_id, user_id)

# Upload tasks
- upload_to_platform_task(recording_id, platform, user_id)
- retry_upload_task(recording_id, platform, user_id)

# Batch tasks
- bulk_process_task(recording_ids, user_id)
- bulk_sync_sources_task(source_id, user_id)

# Automation tasks
- scheduled_automation_job_task(job_id)
```

**Progress Tracking:**
```python
# Task result stored in Redis
{
  "task_id": "abc123",
  "status": "PROCESSING",  # PENDING, PROCESSING, SUCCESS, FAILURE
  "progress": 45,          # 0-100%
  "current_step": "Transcribing audio...",
  "result": null,          # Result when SUCCESS
  "error": null            # Error when FAILURE
}
```

**Реализация:**
- `api/celery_app.py` - Celery configuration
- `api/tasks/` - task definitions
- `api/services/task_service.py` - task management
- Endpoints:
  - `GET /tasks/{task_id}` - task status
  - `DELETE /tasks/{task_id}` - cancel task

**Статус:** ✅ Полностью реализовано

---

### ADR-007: Subscription & Quota System

**Решение:** План-based subscriptions с flexible quotas

**Архитектура:**
```
┌──────────────────────────────────────────┐
│        Subscription System               │
└──────────────────────────────────────────┘

subscription_plans (4 tiers)
    ↓
user_subscriptions (user ← plan)
    ↓
quota_usage (по периодам YYYYMM)
    ↓
Quota checks перед операциями
```

**Plans:**
```
Free:       10 recordings/mo, 5 GB, 1 task
Plus:       50 recordings/mo, 25 GB, 2 tasks, 3 automation jobs
Pro:        200 recordings/mo, 100 GB, 5 tasks, 10 automation jobs
Enterprise: ∞ recordings, ∞ storage, 10 tasks, ∞ automation jobs
```

**Обоснование:**

**Требования:**
- Ограничение ресурсов на user
- Гибкие планы (Free/Plus/Pro/Enterprise)
- Custom quotas для VIP
- Pay-as-you-go ready (overage pricing)

**Quota Types:**
- `max_recordings_per_month` - лимит recordings
- `max_storage_gb` - лимит storage
- `max_concurrent_tasks` - параллельные задачи
- `max_automation_jobs` - scheduled jobs

**Tracking:**
```python
# quota_usage table
{
  "user_id": 1,
  "period": "202601",  # YYYYMM
  "recordings_count": 15,
  "storage_used_gb": 3.2,
  "tasks_run": 45
}
```

**Реализация:**
- `database/subscription_models.py` - models
- `api/services/quota_service.py` - quota checks
- `api/routers/admin.py` - admin endpoints
- Middleware для quota validation

**Endpoints:**
- `GET /users/me/quota` - current usage
- `GET /users/me/quota/history` - history
- `POST /admin/users/{id}/quota` - admin override

**Статус:** ✅ Полностью реализовано

**См. также:** [API_GUIDE.md](API_GUIDE.md) - Admin & Quota API

---

### ADR-008: FSM для Processing Status

**Решение:** Finite State Machine для надежной обработки

**Архитектура:**
```
┌──────────────────────────────────────────┐
│        Processing FSM                     │
└──────────────────────────────────────────┘

INITIALIZED → DOWNLOADING → DOWNLOADED
    ↓              ↓
PROCESSING → PROCESSED → TRANSCRIBING
    ↓              ↓
TRANSCRIBED → UPLOADING → UPLOADED

Failed transitions:
- Any state → FAILED (with failed_at_stage)
- FAILED → retry → back to failed stage
```

**Статусы:**
- `INITIALIZED` - запись создана
- `DOWNLOADING` - скачивание из источника
- `DOWNLOADED` - скачано
- `PROCESSING` - обработка видео (FFmpeg)
- `PROCESSED` - обработано
- `TRANSCRIBING` - транскрибация
- `TRANSCRIBED` - транскрибировано
- `UPLOADING` - загрузка на платформы
- `UPLOADED` - загружено везде
- `FAILED` - ошибка (с указанием стадии)
- `SKIPPED` - пропущено (blank record)

**Output Target FSM:**
```
NOT_UPLOADED → UPLOADING → UPLOADED
       ↓           ↓
    FAILED ← FAILED
```

**Обоснование:**

**Проблемы без FSM:**
- Непонятные состояния
- Сложно откатывать
- Нет гарантий корректности
- Трудно дебажить

**Преимущества FSM:**
- ✅ Явные разрешенные переходы
- ✅ Невозможны invalid states
- ✅ Легко добавлять новые стадии
- ✅ Простой retry logic
- ✅ Audit trail

**Реализация:**
- `models/recording.py` - ProcessingStatus enum
- `database/models.py` - OutputTarget with TargetStatus
- FSM валидация в service layer

**Статус:** ✅ Полностью реализовано

---

### ADR-009: API Design Principles

**Решение:** RESTful API с консистентными конвенциями

**Принципы:**

**1. URL Structure:**
```
/api/v1/{resource}
/api/v1/{resource}/{id}
/api/v1/{resource}/{id}/{action}
/api/v1/{resource}/bulk/{action}
```

**2. HTTP Methods:**
- `GET` - чтение (idempotent)
- `POST` - создание + actions
- `PATCH` - частичное обновление
- `DELETE` - удаление
- **NO PUT** - используем PATCH для consistency

**3. Response Format:**
```json
// Success
{
  "id": 1,
  "field": "value"
}

// Error
{
  "detail": "Error message",
  "error_code": "RESOURCE_NOT_FOUND"
}

// Bulk operation
{
  "message": "Operation completed",
  "succeeded": 10,
  "failed": 2,
  "details": [...]
}
```

**4. Naming Conventions:**
- snake_case для полей JSON
- kebab-case для URL paths
- SCREAMING_SNAKE_CASE для enums

**5. Типизация:**
- Pydantic V2 для всех request/response
- 100% type coverage
- OpenAPI автогенерация

**Реализация:**
- 84 endpoints с полной типизацией
- 118+ Pydantic моделей
- Swagger UI: `/docs`
- OpenAPI: `/openapi.json`

**Статус:** ✅ Полностью реализовано

**См. также:** 
- [API_GUIDE.md](API_GUIDE.md)
- [API_CONSISTENCY_AUDIT.md](API_CONSISTENCY_AUDIT.md)

---

## Текущее состояние системы

### Метрики

**API:**
- 84 REST endpoints
- 118+ Pydantic models
- 100% типизация
- 0 lint errors

**Database:**
- 12 tables
- 19 migrations
- Multi-tenant isolation
- Encrypted credentials

**Integrations:**
- 3 OAuth providers (YouTube, VK, Zoom)
- 2 AI models (Whisper, DeepSeek)
- Async processing (Celery + Redis)

**Features:**
- Template-driven automation
- Subscription system (4 plans)
- Quota management
- Bulk operations
- Admin API

### Production Readiness

| Компонент | Статус | Комментарий |
|-----------|--------|-------------|
| Multi-tenancy | ✅ | Полная изоляция |
| Authentication | ✅ | JWT + OAuth 2.0 |
| API | ✅ | 84 endpoints |
| Database | ✅ | Auto-init, 19 миграций |
| Async Processing | ✅ | Celery + Redis |
| Subscriptions | ✅ | 4 plans + custom quotas |
| Templates | ✅ | Auto-matching + config hierarchy |
| OAuth | ✅ | YouTube, VK, Zoom |
| Admin API | ✅ | Stats & monitoring |
| Encryption | ✅ | Fernet для credentials |
| Security | ✅ | CSRF, token refresh |
| Documentation | ✅ | 20+ docs |

**Готово к production:** ✅

**Рекомендуется добавить:**
- Load testing
- Monitoring (Prometheus/Grafana)
- WebSocket для real-time (опционально)

---

## См. также

### Архитектура
- [ADR_FEATURES.md](ADR_FEATURES.md) - Автоматизация, FSM, квоты (детально)
- [DATABASE_DESIGN.md](DATABASE_DESIGN.md) - Схемы БД, JSONB структуры
- [TECHNICAL.md](TECHNICAL.md) - Полная техническая документация

### API & Integration
- [API_GUIDE.md](API_GUIDE.md) - Pydantic схемы
- [BULK_OPERATIONS_GUIDE.md](BULK_OPERATIONS_GUIDE.md) - Bulk операции
- [OAUTH.md](OAUTH.md) - OAuth setup & integration

### Features
- [TEMPLATES.md](TEMPLATES.md) - Templates, matching, metadata & configuration

### Deployment
- [DEPLOYMENT.md](DEPLOYMENT.md) - Production deployment & infrastructure

---

**Документ обновлен:** Январь 2026  
**Следующий review:** По мере добавления новых ADR
