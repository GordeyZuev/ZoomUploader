# CHANGELOG - LEAP Platform

**Production-Ready Multi-tenant SaaS**

Полная история разработки платформы с фокусом на ключевые вехи и достижения.

---

## 📊 Текущее состояние (v0.9.3)

**Дата:** Январь 2026  
**Статус:** Dev Status

### Метрики

```
API Endpoints:       84 (100% типизация)
Database Tables:     12 (19 миграций)
Pydantic Models:     118+
Platform Integrations: 3 (Zoom, YouTube, VK)
AI Models:           2 (Whisper, DeepSeek)
Subscription Plans:  4 (Free/Plus/Pro/Enterprise)
```

### Tech Stack

- FastAPI (async)
- PostgreSQL + Redis
- Celery + Celery Beat
- Pydantic V2
- SQLAlchemy (async)
- OAuth 2.0 (3 providers)

---

## 🎯 Ключевые вехи

### 2026-01-14: Pydantic V2 Рефакторинг

**Цель:** Clean Architecture + Best Practices

**Что сделано:**
- ✅ Миграция на Pydantic V2 `model_config`
- ✅ Field constraints вместо custom валидаторов
- ✅ Централизованные валидаторы (`api/schemas/common/validators.py`)
- ✅ Порядок полей в Swagger UI (не алфавитный)
- ✅ 100% типизация (118+ моделей)
- ✅ 0 lint errors

**Принципы:**
- DRY - нет дублирования
- YAGNI - удалены неиспользуемые поля
- KISS - встроенные Field constraints

**Документация:**
- [API_GUIDE.md](API_GUIDE.md) - Pydantic schemas & best practices

---

### 2026-01-14: Bulk Operations & Template Lifecycle

**Bulk Operations:**
- ✅ Endpoints: `/bulk/download`, `/bulk/trim`, `/bulk/transcribe`, `/bulk/upload`
- ✅ Unified `BulkOperationRequest` (recording_ids OR filters)
- ✅ Dry-run support для preview
- ✅ RecordingFilters расширены (template_id, source_id, is_mapped, failed)

**Template Lifecycle:**
- ✅ Auto-unmap при удалении template
- ✅ Симметричное поведение (create → rematch, delete → unmap)
- ✅ Status сохраняется при unmap

**Bug Fixes:**
- 🐛 metadata_config терялся при создании template → fixed
- 🐛 `/bulk/sync` возвращал 422 → fixed route ordering
- 🐛 Filter `status: ["FAILED"]` вызывал DB error → добавлена обработка

**Документация:**
- [BULK_OPERATIONS_GUIDE.md](BULK_OPERATIONS_GUIDE.md)
- [TEMPLATE_MAPPING_ARCHITECTURE.md](TEMPLATE_MAPPING_ARCHITECTURE.md)

---

### 2026-01-12: CLI Legacy Removal

**Removed:** CLI полностью удален из кодовой базы

**Rationale:** Полный переход на REST API архитектуру

**Deleted:**
- `main.py` (1,360 lines) - CLI entry point
- `cli_helpers.py` (107 lines)
- `setup_vk.py`, `setup_youtube.py` (интерактивные setup scripts)
- 7 display methods из `pipeline_manager.py`

**Migration:**
- `python main.py sync` → `POST /recordings/sync`
- `python main.py process` → `POST /recordings/{id}/process`
- `setup_youtube.py` → `GET /oauth/youtube/authorize`

**Benefits:**
- Cleaner codebase (-2,000+ lines)
- Single interface (REST API)
- Modern architecture

---

### 2026-01-12: Template Config Live Update

**Проблема:** Template changes не применялись к существующим recordings

**Решение:**
- Template config теперь читается live (не кэшируется)
- `processing_preferences` хранит только overrides
- Добавлен `DELETE /recordings/{id}/config` для reset

**Архитектура:**
```
User Config → Template Config (live) → User Overrides
```

**Результат:** Template updates автоматически применяются ко всем recordings ✅

---

### 2026-01-12: Audio Path Fix

**Проблема:** Recording показывал wrong audio file (shared directory)

**Решение:**
- Migration 019: `processed_audio_dir` → `processed_audio_path`
- Каждая запись хранит specific file path
- Исключена cross-contamination

**Результат:** Каждая запись показывает правильный audio file ✅

---

### 2026-01-11: Topics Timestamps + Playlist Fix

**Topics Timestamps:**
- ✅ Формат: `HH:MM:SS — Название темы`
- ✅ `show_timestamps: true` в topics_display
- ✅ Автоформатирование секунд в HH:MM:SS

**Bug Fixes:**
- 🐛 Playlist не добавлялся → исправлен поиск playlist_id
- 🐛 Thumbnail не загружался → добавлена поддержка thumbnail_path
- 🐛 Response показывал upload: false → резолвит реальную конфигурацию

**Example:** `00:02:36 — Введение лектора и контекст индустрии`

**Протестировано:**
- ✅ YouTube: video_id f36_YylcsLQ (успешно)
- ⚠️ VK: ошибка форматирования (requires debugging)

---

### 2026-01-11: Blank Records Filtering + Auto-Upload Fix

**Blank Records:**
- ✅ Флаг `blank_record` для коротких/маленьких записей
- ✅ Критерии: duration < 20 мин ИЛИ size < 25 МБ
- ✅ Автоопределение при sync из Zoom
- ✅ Автоматический skip в pipeline
- ✅ Фильтры по датам: `from_date` / `to_date`

**Bug Fixes:**
- 🐛 auto_upload читался неправильно → исправлен на output_config
- 🐛 Убран `.get()` в task (Celery anti-pattern)

**Migration 018:** Backfill существующих записей

---

### 2026-01-11: Template Variables Refactoring

**Changes:**
- ✅ Убрали `{summary}` (не существует в БД)
- ✅ Переименовали: `{main_topics}` → `{themes}`
- ✅ Переименовали: `{topics_list}` → `{topics}`
- ✅ Добавили `{record_time}` и `{publish_time}` с форматированием
- ✅ Inline форматирование: `{publish_time:DD-MM-YY hh:mm}`
- ✅ Поддержка форматов: DD, MM, YY, YYYY, hh, mm, ss, date, time

**Production Updates:**
- YouTube Unlisted Default preset
- VK Public Default preset
- Template "Анализ временных рядов"

---

### 2026-01-11: Output Preset Refactoring

**Separation of Concerns:**
- **Output Preset** = Platform defaults (privacy, topics_display format)
- **Template** = Content-specific metadata (title_template, playlist_id, thumbnail)
- **Manual Override** = Per-recording overrides (highest priority)

**Metadata Resolution:**
```
Preset → Template → Manual Override
```

**ConfigResolver:**
- `resolve_upload_metadata()` method
- Deep merge hierarchy
- DRY: один preset переиспользуется между templates

**Benefits:**
- Clean architecture
- No legacy багаж
- Практическое применение: разделили content-specific поля

---

### 2026-01-10: OAuth Complete + Fireworks Batch

**OAuth 2.0:**
- ✅ Zoom OAuth 2.0 (user-level scopes)
- ✅ VK Token API (Implicit Flow)
- ✅ Async sync через Celery

**Fireworks Batch API:**
- ✅ Экономия ~50% на транскрибации
- ✅ Polling механизм для batch jobs

**Документация:**
- [ZOOM_OAUTH_IMPLEMENTATION.md](ZOOM_OAUTH_IMPLEMENTATION.md)
- [VK_TOKEN_API.md](VK_TOKEN_API.md)
- [FIREWORKS_BATCH_API.md](FIREWORKS_BATCH_API.md)

---

### 2026-01-09: Subscription System Refactoring

**Subscription Plans:**
- ✅ 4 тарифных плана (Free/Plus/Pro/Enterprise)
- ✅ Quota system по периодам
- ✅ Custom quotas для VIP
- ✅ История использования

**Admin API:**
- `GET /admin/stats/overview` - Platform stats
- `GET /admin/stats/users` - User stats
- `GET /admin/stats/quotas` - Quota usage

**API Consistency:**
- ✅ 100% RESTful conventions
- ✅ PATCH вместо PUT
- ✅ Единый формат ошибок

**Документация:**
- [API_GUIDE.md](API_GUIDE.md) - Admin & Quota API
- [API_CONSISTENCY_AUDIT.md](API_CONSISTENCY_AUDIT.md)

---

### 2026-01-08: Preset Metadata + VK OAuth 2.1

**Template Rendering:**
- ✅ 10+ variables (`{display_name}`, `{duration}`, `{themes}`, `{topics}`)
- ✅ Inline time formatting (`{record_time:DD.MM.YYYY}`)
- ✅ Topics display (5 форматов)

**YouTube Metadata:**
- publishAt (scheduled publishing)
- tags, category_id, playlist_id
- made_for_kids, embeddable, license

**VK Metadata:**
- group_id, album_id
- privacy_view, privacy_comment
- wallpost, no_comments, repeat

**VK OAuth 2.1:**
- VK ID OAuth 2.1 с PKCE (legacy apps)
- Implicit Flow API (новые проекты)
- Service Token support

**Credentials Validation:**
- Platform-specific validation
- Encrypted storage (Fernet)

**Документация:**
- [TEMPLATES.md](TEMPLATES.md) - Metadata configuration
- [PLATFORM_SPECIFIC_METADATA.md](PLATFORM_SPECIFIC_METADATA.md)
- [VK_POLICY_UPDATE_2026.md](VK_POLICY_UPDATE_2026.md)

---

### 2026-01-07: Security Hardening

**Token Management:**
- ✅ Token validation через БД (refresh_tokens table)
- ✅ Logout all devices
- ✅ Automatic expired tokens cleanup

**User Features:**
- ✅ Timezone support (per-user)
- ✅ Password change endpoint
- ✅ Account deletion

**Документация:**
- [SECURITY_AUDIT.md](SECURITY_AUDIT.md)
- [SECURITY_QUICKSTART.md](SECURITY_QUICKSTART.md)

---

### 2026-01-06: OAuth + Automation

**OAuth 2.0:**
- ✅ YouTube OAuth 2.0 (web-based flow)
- ✅ VK OAuth 2.1 (web-based flow)
- ✅ Automatic token refresh
- ✅ Multi-user support

**Automation System:**
- ✅ Celery Beat scheduler
- ✅ Declarative schedules (daily, hours, weekdays, cron)
- ✅ Template-driven automation
- ✅ Dry-run mode

**Документация:**
- [OAUTH.md](OAUTH.md) - OAuth integration (comprehensive guide)

---

### 2026-01-05: Core Infrastructure

**Celery Integration:**
- ✅ Async processing (download, process, transcribe, upload)
- ✅ 3 queues (processing, upload, automation)
- ✅ Progress tracking (0-100%)
- ✅ Flower UI monitoring

**Unified Config:**
- ✅ user_configs table (1:1 с users)
- ✅ Config hierarchy (user → template → recording)

**User Management:**
- ✅ User API (register, login, profile)
- ✅ JWT authentication (access + refresh tokens)
- ✅ RBAC (admin/user roles)

**Thumbnails Multi-tenancy:**
- ✅ `media/user_{id}/thumbnails/` structure
- ✅ Template thumbnails fallback
- ✅ Auto-init при регистрации

**Transcription Pipeline:**
- ✅ Refactored modules
- ✅ Fireworks API integration
- ✅ DeepSeek topics extraction

---

### 2026-01-02 to 2026-01-04: Foundation

**Multi-tenant Architecture:**
- ✅ Shared Database + user_id isolation
- ✅ Row-level filtering во всех таблицах
- ✅ ServiceContext pattern

**JWT Authentication:**
- ✅ Access tokens (1 hour)
- ✅ Refresh tokens (7 days)
- ✅ Token rotation

**Repository Pattern:**
- ✅ Clean separation (Repository → Service → Router)
- ✅ Dependency Injection
- ✅ Unit of Work pattern

**Recordings API:**
- ✅ CRUD operations
- ✅ Processing pipeline
- ✅ Status tracking (FSM)

**Template System:**
- ✅ Auto-matching (keywords, patterns, exact matches)
- ✅ Template-driven configs
- ✅ Re-match functionality

---

## 📝 Архитектурные решения

### KISS (Keep It Simple)
- First-match template strategy
- ServiceContext для передачи контекста
- Shared Database multi-tenancy

### DRY (Don't Repeat Yourself)
- ConfigResolver - единая точка resolution
- Template reuse across recordings
- Unified OAuth pattern

### YAGNI (You Aren't Gonna Need It)
- Нет audit/versioning templates (пока не нужно)
- Нет сложной системы priority
- Нет WebSocket (polling работает)

### Separation of Concerns
- **Output Preset** = Platform defaults
- **Template** = Content-specific + Preset overrides
- **Manual Override** = Per-recording (highest priority)
- **Metadata Resolution** = Deep merge: preset → template → manual

---

## 🚀 Production Readiness

| Компонент | Статус | Комментарий |
|-----------|--------|-------------|
| Multi-tenancy | ✅ | Полная изоляция |
| Authentication | ✅ | JWT + Refresh + OAuth 2.0 |
| API | ✅ | 84 endpoints |
| Database | ✅ | Auto-init, 19 миграций |
| Async Processing | ✅ | Celery + Redis |
| Subscriptions | ✅ | 4 plans + custom quotas |
| Templates | ✅ | Auto-matching + live updates |
| OAuth | ✅ | YouTube, VK, Zoom |
| Admin API | ✅ | Stats & monitoring |
| Encryption | ✅ | Fernet для credentials |
| Security | ✅ | CSRF, token refresh |
| Documentation | ✅ | 20+ docs |
| Linter | ✅ | 0 errors |

**Готово к production:** ✅

---

## 📈 Эволюция проекта

### Фаза 1: CLI Application (v0.1 - v0.4)
- Zoom API integration
- FFmpeg processing
- Basic transcription
- YouTube/VK upload

### Фаза 2: Modular Architecture (v0.5 - v0.6)
- Separation of concerns
- Module разделение
- PostgreSQL integration

### Фаза 3: Multi-tenancy (v0.7 - v0.8)
- User management
- JWT authentication
- Shared database isolation
- REST API foundations

### Фаза 4: Production SaaS (v0.9 - v0.9.3)
- OAuth 2.0 integrations
- Celery async processing
- Template-driven automation
- Subscription system
- Full API coverage (84 endpoints)

---

## 🎯 Следующие шаги

**Near-term (Q1 2026):**
- Load testing
- Monitoring (Prometheus/Grafana)
- Audit logging (full)
- Email notifications

**Mid-term (Q2 2026):**
- WebSocket для real-time
- Multiple template matching
- Advanced analytics dashboard
- Payment integration

**Long-term (H2 2026):**
- Self-hosted deployment
- Multi-language support
- Advanced AI features (summary, quiz generation)
- Speaker diarization

---

## 📚 Документация

### Core
- [ADR_OVERVIEW.md](ADR_OVERVIEW.md) - Архитектурные решения
- [ADR_FEATURES.md](ADR_FEATURES.md) - Детали фич
- [DATABASE_DESIGN.md](DATABASE_DESIGN.md) - Схемы БД
- [TECHNICAL.md](TECHNICAL.md) - Техническая документация

### API
- [API_GUIDE.md](API_GUIDE.md) - Pydantic schemas & best practices
- [BULK_OPERATIONS_GUIDE.md](BULK_OPERATIONS_GUIDE.md) - Bulk операции
- [API_GUIDE.md](API_GUIDE.md) - Admin & Quota API - Quota & Admin API

### Features
- [TEMPLATES.md](TEMPLATES.md) - Templates, matching & automation

### Integration
- [OAUTH.md](OAUTH.md) - OAuth integration - OAuth setup
- [OAUTH.md](OAUTH.md) - OAuth & credentials (complete guide)

### Deployment
- [DEPLOYMENT.md](DEPLOYMENT.md) - Production deployment
- [DEPLOYMENT.md](DEPLOYMENT.md) - Deployment & infrastructure
- [SECURITY_AUDIT.md](SECURITY_AUDIT.md) - Security

---

**Документ обновлен:** Январь 2026  
**Версия:** v0.9.3  
**Статус:** Production-Ready ✅
