# Database Design - LEAP Platform

**Версия БД:** 19 миграций  
**Последнее обновление:** Январь 2026  
**Статус:** Production-Ready

---

## 📋 Содержание

1. [Обзор](#обзор)
2. [Архитектура](#архитектура)
3. [Таблицы](#таблицы)
4. [JSONB Structures](#jsonb-structures)
5. [Индексы и производительность](#индексы-и-производительность)
6. [Миграции](#миграции)

---

## Обзор

### Статистика

**12 таблиц:**
- Authentication & Users (4 таблицы)
- Subscription & Quotas (4 таблицы)
- Processing (4 таблицы)
- Automation (2 таблицы)

**19 миграций** (автоматическая инициализация)

**PostgreSQL версия:** 12+

### Multi-Tenancy

**Isolation Strategy:** Shared Database + Row-Level Filtering

Все таблицы с `user_id` имеют:
- Foreign Key: `REFERENCES users(id) ON DELETE CASCADE`
- Index: `idx_{table}_user_id ON {table}(user_id)`
- Автоматическая фильтрация в Repository Layer

---

## Архитектура

### Entity Relationship Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    AUTHENTICATION                        │
└─────────────────────────────────────────────────────────┘
                          users
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
  refresh_tokens    user_credentials    user_configs

┌─────────────────────────────────────────────────────────┐
│                    SUBSCRIPTIONS                         │
└─────────────────────────────────────────────────────────┘
       subscription_plans
                │
        user_subscriptions (user ← plan)
                │
        ┌───────┴────────┐
   quota_usage   quota_change_history

┌─────────────────────────────────────────────────────────┐
│                      PROCESSING                          │
└─────────────────────────────────────────────────────────┘
   recording_templates ─┐
                        │
   input_sources ───────┼─┐
                        │ │
   output_presets ──────┼─┼─┐
                        │ │ │
                recordings ←┘ │
                │   │         │
     source_metadata  │       │
                │     │       │
          output_targets ←────┘

┌─────────────────────────────────────────────────────────┐
│                     AUTOMATION                           │
└─────────────────────────────────────────────────────────┘
   automation_jobs (schedule + template)
        │
   processing_stages (tracking)
```

---

## Таблицы

### 🔐 Authentication & Users

#### 1. `users`

**Назначение:** Пользователи системы с ролями и permissions

```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    hashed_password VARCHAR(255) NOT NULL,
    full_name VARCHAR(255),
    
    -- Role & Permissions
    role VARCHAR(20) DEFAULT 'user',  -- admin, user
    is_active BOOLEAN DEFAULT TRUE,
    timezone VARCHAR(50) DEFAULT 'UTC',
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_login_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_active ON users(is_active, role);
```

**Связи:**
- 1:N → user_credentials, recordings, templates, etc.
- 1:1 → user_configs
- 1:1 → user_subscriptions

---

#### 2. `refresh_tokens`

**Назначение:** JWT refresh tokens для безопасной аутентификации

```sql
CREATE TABLE refresh_tokens (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token VARCHAR(500) NOT NULL UNIQUE,
    
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    revoked BOOLEAN DEFAULT FALSE,
    
    -- Security
    ip_address INET,
    user_agent TEXT
);

CREATE INDEX idx_refresh_tokens_user ON refresh_tokens(user_id);
CREATE INDEX idx_refresh_tokens_token ON refresh_tokens(token) WHERE NOT revoked;
CREATE INDEX idx_refresh_tokens_expiry ON refresh_tokens(expires_at) WHERE NOT revoked;
```

**Features:**
- Token rotation (auto-revoke old tokens)
- Logout all devices (revoke all tokens)
- Automatic cleanup (expired tokens)

---

#### 3. `user_credentials`

**Назначение:** Зашифрованные credentials для внешних сервисов

```sql
CREATE TABLE user_credentials (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Platform
    platform VARCHAR(50) NOT NULL,  -- zoom, youtube, vk, fireworks, deepseek
    account_name VARCHAR(255),      -- Для нескольких аккаунтов
    
    -- Encrypted Data (Fernet)
    encrypted_data TEXT NOT NULL,
    
    -- Metadata
    is_active BOOLEAN DEFAULT TRUE,
    last_used_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT unique_user_platform_account UNIQUE (user_id, platform, account_name)
);

CREATE INDEX idx_user_credentials_user ON user_credentials(user_id, platform);
CREATE INDEX idx_user_credentials_active ON user_credentials(is_active);
```

**Supported Platforms:**
- `zoom` - Zoom OAuth/Server-to-Server
- `youtube` - YouTube OAuth 2.0
- `vk` - VK OAuth 2.1 / Implicit Flow
- `fireworks` - Fireworks API key
- `deepseek` - DeepSeek API key
- `yandex_disk` - Yandex OAuth (future)

**Encryption:** Fernet (symmetric, AES-128)

---

#### 4. `user_configs`

**Назначение:** Unified configuration для пользователя (1:1)

```sql
CREATE TABLE user_configs (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    
    -- Processing defaults
    processing_config JSONB DEFAULT '{}',
    
    -- Transcription defaults
    transcription_config JSONB DEFAULT '{}',
    
    -- Metadata defaults
    metadata_config JSONB DEFAULT '{}',
    
    -- Upload defaults
    upload_config JSONB DEFAULT '{}',
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_user_configs_user ON user_configs(user_id);
```

**См:** [JSONB Structures](#jsonb-structures) для формата конфигураций

---

### 💰 Subscription & Quotas

#### 5. `subscription_plans`

**Назначение:** Тарифные планы (Free/Plus/Pro/Enterprise)

```sql
CREATE TABLE subscription_plans (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,  -- Free, Plus, Pro, Enterprise
    tier INT NOT NULL UNIQUE,           -- 0, 1, 2, 3
    
    -- Pricing
    price_monthly DECIMAL(10, 2) NOT NULL,
    price_yearly DECIMAL(10, 2),
    
    -- Quotas (JSONB)
    quotas JSONB NOT NULL,
    
    -- Features
    features JSONB DEFAULT '[]',
    
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_subscription_plans_active ON subscription_plans(is_active, tier);
```

**Quotas Format:**
```json
{
  "max_recordings_per_month": 50,
  "max_storage_gb": 25,
  "max_concurrent_tasks": 2,
  "max_automation_jobs": 3,
  "max_input_sources": 10,
  "max_output_presets": 10,
  "max_templates": 20
}
```

---

#### 6. `user_subscriptions`

**Назначение:** Подписки пользователей

```sql
CREATE TABLE user_subscriptions (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    plan_id INT NOT NULL REFERENCES subscription_plans(id),
    
    -- Custom quotas (override plan quotas)
    custom_quotas JSONB DEFAULT '{}',
    
    -- Subscription period
    start_date TIMESTAMP WITH TIME ZONE NOT NULL,
    end_date TIMESTAMP WITH TIME ZONE,
    
    -- Payment
    is_active BOOLEAN DEFAULT TRUE,
    auto_renew BOOLEAN DEFAULT TRUE,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_user_subscriptions_user ON user_subscriptions(user_id);
CREATE INDEX idx_user_subscriptions_plan ON user_subscriptions(plan_id);
CREATE INDEX idx_user_subscriptions_active ON user_subscriptions(is_active, end_date);
```

---

#### 7. `quota_usage`

**Назначение:** Отслеживание использования по периодам

```sql
CREATE TABLE quota_usage (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    period VARCHAR(6) NOT NULL,  -- YYYYMM format
    
    -- Usage counters
    recordings_count INT DEFAULT 0,
    storage_used_gb DECIMAL(10, 2) DEFAULT 0,
    tasks_run_count INT DEFAULT 0,
    automation_runs_count INT DEFAULT 0,
    
    -- Timestamps
    last_updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT unique_user_period UNIQUE (user_id, period)
);

CREATE INDEX idx_quota_usage_user_period ON quota_usage(user_id, period DESC);
```

---

#### 8. `quota_change_history`

**Назначение:** Audit trail для изменений квот

```sql
CREATE TABLE quota_change_history (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    admin_user_id INT REFERENCES users(id),  -- Who made the change
    
    change_type VARCHAR(50) NOT NULL,  -- plan_upgrade, custom_quota_override, etc.
    old_value JSONB,
    new_value JSONB,
    reason TEXT,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_quota_history_user ON quota_change_history(user_id, created_at DESC);
```

---

### 🎬 Processing

#### 9. `recordings`

**Назначение:** Основная таблица записей

```sql
CREATE TABLE recordings (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Template mapping
    template_id INT REFERENCES recording_templates(id) ON DELETE SET NULL,
    is_mapped BOOLEAN DEFAULT FALSE,
    
    -- Basic info
    display_name VARCHAR(500) NOT NULL,
    start_time TIMESTAMP WITH TIME ZONE,
    duration INT,  -- seconds
    
    -- Processing status (FSM)
    status VARCHAR(50) NOT NULL DEFAULT 'INITIALIZED',
    failed BOOLEAN DEFAULT FALSE,
    failed_at_stage VARCHAR(50),
    
    -- File paths
    local_video_path TEXT,
    processed_video_path TEXT,
    processed_audio_path TEXT,  -- Migration 019: specific file path
    transcription_dir TEXT,
    
    -- Transcription
    transcription_info JSONB DEFAULT '{}',
    topic_timestamps JSONB DEFAULT '[]',
    
    -- Template overrides
    processing_preferences JSONB DEFAULT '{}',
    
    -- Flags
    blank_record BOOLEAN DEFAULT FALSE,  -- Migration 018
    
    -- Timestamps
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    uploaded_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_recordings_user ON recordings(user_id, created_at DESC);
CREATE INDEX idx_recordings_status ON recordings(status, user_id);
CREATE INDEX idx_recordings_template ON recordings(template_id, status);
CREATE INDEX idx_recordings_mapped ON recordings(is_mapped, user_id);
CREATE INDEX idx_recordings_blank ON recordings(blank_record, user_id);
CREATE INDEX idx_recordings_failed ON recordings(failed, user_id) WHERE failed = TRUE;
```

**Processing Status (FSM):**
- `INITIALIZED` → `DOWNLOADING` → `DOWNLOADED`
- `PROCESSING` → `PROCESSED`
- `TRANSCRIBING` → `TRANSCRIBED`
- `UPLOADING` → `UPLOADED`
- `FAILED` (with failed_at_stage)
- `SKIPPED`

**Migrations:**
- 018: Added `blank_record` flag (duration < 20min OR size < 25MB)
- 019: `processed_audio_dir` → `processed_audio_path` (specific file)

---

#### 10. `source_metadata`

**Назначение:** Метаданные источника (1:1 с recordings)

```sql
CREATE TABLE source_metadata (
    id SERIAL PRIMARY KEY,
    recording_id INT NOT NULL UNIQUE REFERENCES recordings(id) ON DELETE CASCADE,
    
    source_type VARCHAR(50) NOT NULL,  -- zoom, local_file, yandex_disk_api
    source_key VARCHAR(500) NOT NULL,  -- Unique key в источнике
    metadata JSONB DEFAULT '{}',       -- Raw metadata from source
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT unique_source_key UNIQUE (source_type, source_key)
);

CREATE INDEX idx_source_metadata_recording ON source_metadata(recording_id);
CREATE INDEX idx_source_metadata_source ON source_metadata(source_type, source_key);
```

**Migration 009:** Added unique constraint на `(source_type, source_key)` для предотвращения дубликатов

---

#### 11. `output_targets`

**Назначение:** Отслеживание загрузок по платформам (1:N)

```sql
CREATE TABLE output_targets (
    id SERIAL PRIMARY KEY,
    recording_id INT NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    
    target_type VARCHAR(50) NOT NULL,  -- youtube, vk, yandex_disk
    status VARCHAR(50) NOT NULL DEFAULT 'NOT_UPLOADED',  -- FSM
    
    target_meta JSONB DEFAULT '{}',  -- Platform-specific: video_id, url, etc.
    
    uploaded_at TIMESTAMP WITH TIME ZONE,
    last_retry_at TIMESTAMP WITH TIME ZONE,
    retry_count INT DEFAULT 0,
    error_message TEXT,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT unique_recording_target UNIQUE (recording_id, target_type)
);

CREATE INDEX idx_output_targets_recording ON output_targets(recording_id);
CREATE INDEX idx_output_targets_status ON output_targets(target_type, status);
CREATE INDEX idx_output_targets_failed ON output_targets(status) WHERE status = 'FAILED';
```

**Target Status (FSM):**
- `NOT_UPLOADED` → `UPLOADING` → `UPLOADED`
- `NOT_UPLOADED` → `FAILED`
- `UPLOADING` → `FAILED`
- `FAILED` → `UPLOADING` (retry)

**Migration 010:** Added FSM fields for output targets

---

#### 12. `recording_templates`

**Назначение:** Шаблоны для автоматической обработки

```sql
CREATE TABLE recording_templates (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    name VARCHAR(255) NOT NULL,
    description TEXT,
    
    -- Matching rules (JSONB)
    matching_rules JSONB NOT NULL,
    
    -- Configs (JSONB)
    processing_config JSONB DEFAULT '{}',
    metadata_config JSONB DEFAULT '{}',
    output_config JSONB DEFAULT '{}',
    
    is_active BOOLEAN DEFAULT TRUE,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT unique_user_template_name UNIQUE (user_id, name)
);

CREATE INDEX idx_recording_templates_user ON recording_templates(user_id, is_active);
CREATE INDEX idx_recording_templates_active ON recording_templates(is_active, created_at);
```

**См:** [JSONB Structures](#jsonb-structures) для формата конфигураций

**Migration 007:** Created user_configs table (unified config)

---

### ⏰ Automation

#### 13. `automation_jobs`

**Назначение:** Scheduled jobs для автоматизации

```sql
CREATE TABLE automation_jobs (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    template_id INT REFERENCES recording_templates(id) ON DELETE CASCADE,
    
    name VARCHAR(255) NOT NULL,
    schedule_config JSONB NOT NULL,  -- Cron-like config
    
    enabled BOOLEAN DEFAULT TRUE,
    last_run_at TIMESTAMP WITH TIME ZONE,
    next_run_at TIMESTAMP WITH TIME ZONE,
    last_run_status VARCHAR(50),
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT unique_user_job_name UNIQUE (user_id, name)
);

CREATE INDEX idx_automation_jobs_user ON automation_jobs(user_id, enabled);
CREATE INDEX idx_automation_jobs_schedule ON automation_jobs(enabled, next_run_at);
```

**Migration 013:** Created automation_jobs table

---

#### 14. `processing_stages`

**Назначение:** Детальное отслеживание этапов обработки

```sql
CREATE TABLE processing_stages (
    id SERIAL PRIMARY KEY,
    recording_id INT NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    
    stage_name VARCHAR(50) NOT NULL,  -- download, process, transcribe, upload
    status VARCHAR(50) NOT NULL,      -- pending, running, completed, failed
    
    started_at TIMESTAMP WITH TIME ZONE,
    completed_at TIMESTAMP WITH TIME ZONE,
    duration_seconds INT,
    
    error_message TEXT,
    metadata JSONB DEFAULT '{}',
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_processing_stages_recording ON processing_stages(recording_id, created_at);
CREATE INDEX idx_processing_stages_status ON processing_stages(status, stage_name);
```

**Usage:**
- Progress tracking
- Debugging
- Analytics (avg time per stage)

---

### 📦 Other Tables

#### input_sources

**Назначение:** Источники данных (Zoom accounts, etc.)

```sql
CREATE TABLE input_sources (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    name VARCHAR(255) NOT NULL,
    source_type VARCHAR(50) NOT NULL,  -- zoom, yandex_disk
    config JSONB NOT NULL,  -- Credentials reference + settings
    
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT unique_user_source_name UNIQUE (user_id, name)
);

CREATE INDEX idx_input_sources_user ON input_sources(user_id, is_active);
```

**Migration 009:** Added unique constraint

---

#### output_presets

**Назначение:** Пресеты для загрузки (YouTube channels, VK groups)

```sql
CREATE TABLE output_presets (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    name VARCHAR(255) NOT NULL,
    platform VARCHAR(50) NOT NULL,  -- youtube, vk
    credential_id INT REFERENCES user_credentials(id) ON DELETE CASCADE,
    
    preset_metadata JSONB DEFAULT '{}',  -- Platform-specific settings
    
    is_default BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT unique_user_preset_name UNIQUE (user_id, name)
);

CREATE INDEX idx_output_presets_user ON output_presets(user_id, is_active);
CREATE INDEX idx_output_presets_platform ON output_presets(platform, is_active);
```

---

## JSONB Structures

### Template matching_rules

```json
{
  "exact_matches": ["Lecture: Machine Learning", "AI Course"],
  "keywords": ["ML", "AI", "neural networks"],
  "patterns": ["Лекция \\d+:.*ML", "\\[МО\\].*"],
  "source_ids": [1, 3],
  "match_mode": "any"  // "any" or "all"
}
```

### Template processing_config

```json
{
  "transcription": {
    "enable_transcription": true,
    "language": "ru",
    "prompt": "Technical lecture...",
    "enable_topics": true,
    "granularity": "long",
    "enable_subtitles": true
  },
  "video": {
    "enable_processing": true,
    "silence_threshold": -40.0,
    "min_silence_duration": 2.0
  }
}
```

### Template metadata_config

```json
{
  "title_template": "{themes} | {record_time:DD.MM.YYYY}",
  "description_template": "{topics}\\n\\nДлительность: {duration}",
  "topics_display": {
    "format": "numbered_list",  // numbered_list, bullet_list, dash_list, comma_separated, inline
    "max_count": 10,
    "min_length": 5,
    "show_timestamps": true
  },
  "youtube": {
    "playlist_id": "PLxxx...",
    "privacy": "unlisted",
    "category_id": "27",
    "tags": ["lecture", "ML"]
  },
  "vk": {
    "album_id": 63,
    "privacy_view": 0,
    "no_comments": false
  }
}
```

### Template output_config

```json
{
  "preset_ids": [1, 2],  // YouTube, VK presets
  "auto_upload": true
}
```

### Preset metadata (YouTube)

```json
{
  "privacy": "unlisted",
  "playlist_id": "PLmA-1xX7Iuz...",
  "category_id": "27",
  "default_language": "ru",
  "made_for_kids": false,
  "embeddable": true
}
```

### Preset metadata (VK)

```json
{
  "group_id": -227011779,
  "album_id": 63,
  "privacy_view": 0,
  "privacy_comment": 0,
  "no_comments": false,
  "repeat": false,
  "wallpost": false
}
```

---

## Индексы и производительность

### Стратегия индексирования

**1. Multi-tenancy:** Все таблицы с `user_id` имеют `(user_id, ...)` индексы

**2. Status filtering:** Composite индексы на `(status, user_id)` для быстрой фильтрации

**3. JSONB:** GIN индексы на JSONB полях для быстрого поиска

**4. Foreign Keys:** Все FK имеют индексы для быстрых JOIN'ов

**5. Partial indexes:** WHERE условия для часто используемых фильтров

### Примеры

```sql
-- Multi-tenancy
CREATE INDEX idx_recordings_user ON recordings(user_id, created_at DESC);

-- Status filtering
CREATE INDEX idx_recordings_status ON recordings(status, user_id);

-- Failed records
CREATE INDEX idx_recordings_failed ON recordings(failed, user_id) WHERE failed = TRUE;

-- JSONB
CREATE INDEX idx_recordings_prefs ON recordings USING GIN (processing_preferences);

-- Unique constraints
CREATE UNIQUE INDEX unique_source_key ON source_metadata(source_type, source_key);
```

---

## Миграции

### Список миграций (19)

| # | Название | Описание |
|---|----------|----------|
| 001 | create_base_tables | Базовые таблицы (recordings, etc.) |
| 002 | add_auth_tables | Users, authentication |
| 003 | add_multitenancy | Multi-tenant support |
| 004 | add_config_type_field | Config type field |
| 005 | add_account_name_to_credentials | Multiple accounts |
| 006 | add_foreign_keys_to_sources_and_presets | FK constraints |
| 007 | create_user_configs | Unified config table |
| 008 | update_platform_enum | Platform enum update |
| 009 | add_unique_constraint_to_input_sources | Unique constraint |
| 010 | add_fsm_fields_to_output_targets | FSM for output targets |
| 011 | update_processing_status_enum | Status enum update |
| 012 | add_automation_quotas | Automation quotas |
| 013 | create_automation_jobs | Automation jobs table |
| 014 | create_celery_beat_tables | Celery Beat tables |
| 015 | add_timezone_to_users | Timezone support |
| 016 | refactor_quota_system | Quota refactoring |
| 017 | add_template_id_to_recordings | Template mapping |
| 018 | add_blank_record_flag | Blank record filtering |
| 019 | replace_audio_dir_with_path | Specific audio file paths |

### Команды

```bash
# Auto-init (при первом запуске FastAPI)
# Автоматически создает БД и применяет миграции

# Вручную
make init-db         # Создать БД + миграции
make migrate         # Применить миграции
make migrate-down    # Откатить миграцию
make db-version      # Текущая версия
make db-history      # История миграций
make recreate-db     # Пересоздать БД (⚠️ УДАЛИТ ДАННЫЕ)
```

---

## См. также

- [ADR_OVERVIEW.md](ADR_OVERVIEW.md) - Архитектурные решения
- [TECHNICAL.md](TECHNICAL.md) - Полная техническая документация
- [OAUTH.md](OAUTH.md) - OAuth credentials & formats
- [TEMPLATES.md](TEMPLATES.md) - Metadata templates & configuration

---

**Документ обновлен:** Январь 2026  
**Версия БД:** 19 миграций
