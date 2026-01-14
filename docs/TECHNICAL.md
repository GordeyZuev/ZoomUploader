# Technical Documentation

**Complete technical reference for LEAP Platform**

**Version:** v0.9.3 (January 2026)  
**Status:** 🚧 Development

---

## 📋 Table of Contents

1. [System Overview](#system-overview)
2. [Architecture](#architecture)
3. [Core Components](#core-components)
4. [System Modules](#system-modules)
5. [Database Design](#database-design)
6. [Processing Pipeline](#processing-pipeline)
7. [REST API](#rest-api)
8. [Security](#security)
9. [Development Guide](#development-guide)

---

## System Overview

### What is LEAP

**LEAP** (Learning Educational Automation Platform) - это multi-tenant платформа для автоматизации end-to-end обработки образовательного видеоконтента.

**Ключевые возможности:**
- ✅ Синхронизация видео из Zoom, локальных файлов
- ✅ FFmpeg обработка (удаление тишины, обрезка)
- ✅ AI транскрибация (Fireworks Whisper)
- ✅ AI извлечение тем (DeepSeek)
- ✅ Генерация субтитров (SRT, VTT)
- ✅ Multi-platform upload (YouTube, VK)
- ✅ Template-driven automation
- ✅ Scheduled jobs (Celery Beat)

### Technology Stack

**Backend:**
```
Python 3.11+ • FastAPI • SQLAlchemy 2.0 (async)
PostgreSQL 12+ • Redis • Celery + Beat
```

**AI & Media:**
```
Fireworks AI (Whisper-v3-turbo) • DeepSeek API
FFmpeg • Pydantic V2
```

**External APIs:**
```
Zoom API • YouTube Data API v3 • VK API
```

**Security:**
```
JWT • OAuth 2.0 • Fernet Encryption • PBKDF2
```

### Project Structure

```
ZoomUploader/
├── api/                      # FastAPI application
│   ├── routers/              # API endpoints (15 routers)
│   ├── services/             # Business logic layer
│   ├── repositories/         # Data access layer
│   ├── schemas/              # Pydantic models (118+)
│   ├── core/                 # Core utilities (context, security)
│   ├── helpers/              # Helper classes
│   └── tasks/                # Celery tasks
├── database/                 # Database models & config
│   ├── models.py             # Core models (Recording, etc.)
│   ├── auth_models.py        # User, Credentials, Subscriptions
│   ├── template_models.py    # Templates, Sources, Presets
│   ├── automation_models.py  # Automation jobs
│   └── config.py             # Database configuration
├── *_module/                 # Processing modules
│   ├── video_download_module/
│   ├── video_processing_module/
│   ├── transcription_module/
│   ├── deepseek_module/
│   ├── subtitle_module/
│   └── video_upload_module/
├── alembic/                  # Database migrations (19)
├── config/                   # Configuration files
├── utils/                    # Utilities
└── docs/                     # Documentation (14 guides)
```

---

## Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Client Layer                          │
│              REST API (84 endpoints) + JWT Auth              │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                      Service Layer                           │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│   │ Recording    │  │ Template     │  │ Automation   │    │
│   │ Service      │  │ Service      │  │ Service      │    │
│   └──────────────┘  └──────────────┘  └──────────────┘    │
│                                                              │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│   │ Credential   │  │ User         │  │ Upload       │    │
│   │ Service      │  │ Service      │  │ Service      │    │
│   └──────────────┘  └──────────────┘  └──────────────┘    │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                    Repository Layer                          │
│   (Database Access via SQLAlchemy async ORM)                │
│                                                              │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│   │ Recording    │  │ Template     │  │ User         │    │
│   │ Repository   │  │ Repository   │  │ Repository   │    │
│   └──────────────┘  └──────────────┘  └──────────────┘    │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                      Data Layer                              │
│              PostgreSQL (12 tables, 19 migrations)           │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                   Processing Modules                         │
│                                                              │
│   Video Download → Video Processing → Transcription →       │
│   Topic Extraction → Subtitle Generation → Upload           │
└─────────────────────────────────────────────────────────────┘
```

### Design Patterns

#### 1. Repository Pattern
**Purpose:** Изоляция доступа к данным от бизнес-логики

```python
class RecordingRepository:
    """Data access layer for recordings"""
    
    async def find_by_id(self, user_id: int, recording_id: int) -> Recording:
        """Get recording with multi-tenant isolation"""
        
    async def find_all(self, user_id: int, filters: dict) -> list[Recording]:
        """List recordings with filters"""
```

**Benefits:**
- ✅ Automatic multi-tenant filtering
- ✅ Reusable queries
- ✅ Easy to test and mock
- ✅ Separation of concerns

#### 2. Factory Pattern
**Purpose:** Создание сервисов с правильными credentials

```python
# TranscriptionServiceFactory
service = await TranscriptionServiceFactory.create_for_user(
    session, user_id
)

# UploaderFactory
uploader = await UploaderFactory.create_uploader(
    session, user_id, platform="youtube"
)
```

**Benefits:**
- ✅ Централизованная логика создания
- ✅ Автоматическая загрузка credentials
- ✅ Fallback на default config
- ✅ Type-safe

#### 3. Service Context Pattern
**Purpose:** Передача контекста выполнения (user_id, session)

```python
@dataclass
class ServiceContext:
    session: AsyncSession
    user_id: int
    
    @property
    def config_helper(self) -> ConfigHelper:
        """Lazy-loaded config helper"""
```

**Benefits:**
- ✅ Избегает передачи множества параметров
- ✅ Lazy-loading dependencies
- ✅ Единая точка входа

#### 4. Config-Driven Pattern
**Purpose:** Template-based automation

```python
# Config hierarchy (deep merge):
final_config = user_config ← template_config ← recording_override
```

**Benefits:**
- ✅ Консистентность обработки
- ✅ Гибкость через overrides
- ✅ Масштабируемость

### Architecture Principles

**KISS (Keep It Simple):**
- ServiceContext вместо передачи множества параметров
- ConfigHelper вместо прямого доступа к credentials
- Factories для упрощения создания объектов

**DRY (Don't Repeat Yourself):**
- Все credential-запросы через `CredentialService`
- Все config-запросы через `ConfigHelper`
- Repository pattern для избежания дублирования SQL

**Separation of Concerns:**
- Router → Service → Repository → Model
- Каждый слой имеет четкую ответственность
- Dependencies injection через FastAPI

---

## Core Components

### 1. ServiceContext

**File:** `api/core/context.py`

**Purpose:** Централизованное хранение контекста выполнения операции

```python
from api.dependencies import get_service_context

@router.post("/recordings/{id}/process")
async def process_recording(
    id: int,
    ctx: ServiceContext = Depends(get_service_context)
):
    # ctx содержит: session, user_id, config_helper
    config = await ctx.config_helper.get_fireworks_config()
    # ...
```

**Key Features:**
- Автоматическая инициализация в `get_service_context` dependency
- Lazy-loading `ConfigHelper` (создается только при обращении)
- Единая точка входа для всех сервисов

### 2. ConfigHelper

**File:** `api/helpers/config_helper.py`

**Purpose:** Получение конфигураций и credentials для пользователя

```python
config_helper = ConfigHelper(session, user_id)

# Platform credentials
zoom_config = await config_helper.get_zoom_config(account_name="myaccount")
youtube_creds = await config_helper.get_youtube_credentials()
vk_creds = await config_helper.get_vk_credentials()

# AI service credentials
fireworks_config = await config_helper.get_fireworks_config()
deepseek_config = await config_helper.get_deepseek_config()

# Generic access
creds = await config_helper.get_credentials_for_platform("zoom", "myaccount")
```

**Key Features:**
- Абстракция деталей хранения credentials
- Единый интерфейс для всех платформ
- Автоматическая валидация и дешифрование
- Fallback на default credentials

### 3. TranscriptionServiceFactory

**File:** `transcription_module/factory.py`

**Purpose:** Создание TranscriptionService с user credentials

```python
from transcription_module.factory import TranscriptionServiceFactory

# Создать для конкретного пользователя
service = await TranscriptionServiceFactory.create_for_user(session, user_id)

# С fallback на default credentials
service = await TranscriptionServiceFactory.create_with_fallback(
    session, user_id, use_default_on_missing=True
)
```

**Поддерживаемые провайдеры:**
- `fireworks` - Fireworks AI (Whisper-v3-turbo)

### 4. UploaderFactory

**File:** `video_upload_module/uploader_factory.py`

**Purpose:** Создание uploaders с user credentials

```python
from video_upload_module.factory import UploaderFactory

# По платформе (автоматический выбор credentials)
uploader = await UploaderFactory.create_uploader(session, user_id, "youtube")

# По credential_id (явный выбор)
uploader = await UploaderFactory.create_youtube_uploader(
    session, user_id, credential_id=5
)

# По output preset (из template)
uploader = await UploaderFactory.create_uploader_by_preset_id(
    session, user_id, preset_id=1
)
```

**Поддерживаемые платформы:**
- `youtube` - YouTube Data API v3
- `vk_video` - VK Video API

### 5. CredentialService

**File:** `api/services/credential_service.py`

**Purpose:** Низкоуровневая работа с credentials (encryption, validation)

```python
from api.services.credential_service import CredentialService

cred_service = CredentialService(session)

# Получение credentials
creds = await cred_service.get_decrypted_credentials(
    user_id=1,
    platform="zoom",
    account_name="myaccount"
)

# Platform-specific методы
zoom_creds = await cred_service.get_zoom_credentials(user_id, "myaccount")
youtube_creds = await cred_service.get_youtube_credentials(user_id)
api_key = await cred_service.get_api_key_credentials(user_id, "fireworks")

# Валидация
is_valid = await cred_service.validate_credentials(user_id, "zoom")
platforms = await cred_service.list_available_platforms(user_id)
```

**Key Features:**
- Автоматическое дешифрование (Fernet)
- Валидация структуры credentials
- Обновление `last_used_at`
- Multi-tenant изоляция

---

## System Modules

### 📡 API Module (`api/`)

**Purpose:** REST API endpoints, аутентификация, валидация

**Key Components:**
- `routers/` - 15 routers (84 endpoints)
- `services/` - Business logic
- `repositories/` - Data access
- `schemas/` - Pydantic models (118+)
- `core/` - Auth, security, context

**Features:**
- JWT authentication + refresh tokens
- OAuth 2.0 integration (YouTube, VK, Zoom)
- Role-based access control (RBAC)
- Quota management
- OpenAPI documentation (Swagger, ReDoc)

**Documentation:** [API_GUIDE.md](API_GUIDE.md)

---

### ⬇️ Video Download Module (`video_download_module/`)

**Purpose:** Загрузка видео из внешних источников

**Key Features:**
- Multi-threaded download
- Progress tracking
- Retry механизм
- Checksum validation

**Supported Sources:**
- Zoom API (OAuth 2.0 / Server-to-Server)
- Локальные файлы

**Output:** `media/video/unprocessed/recording_*.mp4`

---

### ✂️ Video Processing Module (`video_processing_module/`)

**Purpose:** FFmpeg обработка видео

**Key Features:**
- Детекция тишины (silence detection)
- Обрезка "тихих" частей
- Удаление пустого начала и конца
- Audio extraction для транскрибации
- Codec: copy (без перекодирования)

**Files:**
- `video_processor.py` - Main processor
- `audio_detector.py` - Silence detection
- `segments.py` - Segment management

**Output:**
- Processed video: `media/video/processed/recording_*_processed.mp4`
- Extracted audio: `media/processed_audio/recording_*_processed.mp3`

---

### 🎤 Transcription Module (`transcription_module/`)

**Purpose:** Координация транскрибации через AI сервисы

**Architecture:**
```
TranscriptionManager (manager.py)
    ↓
TranscriptionServiceFactory (factory.py)
    ↓
FireworksService (fireworks_module/service.py)
```

**Key Features:**
- Транскрибация через Fireworks AI (Whisper-v3-turbo)
- Параллельная обработка с ограничением (max 2 concurrent)
- Retry механизм (3 попытки с exponential backoff)
- Валидация конфигурации через Pydantic

**Output:** `media/user_{user_id}/transcriptions/{recording_id}/`
- `words.txt` - Слова с таймкодами
- `segments.txt` - Сегменты
- `master.json` - Метаданные транскрипции

**Documentation:** [Fireworks Audio API](https://fireworks.ai/docs/api-reference/audio-transcriptions)

---

### 🧠 DeepSeek Module (`deepseek_module/`)

**Purpose:** Извлечение тем и структурирование контента

**Key Features:**
- Определение основных тем (main topics)
- Генерация детализированных тем с таймкодами
- Автоматическое определение перерывов (паузы ≥8 минут)
- Динамический расчёт количества тем по длительности
- Поддержка двух провайдеров: DeepSeek, Fireworks DeepSeek

**Output:** `topics.json` с версионированием (v1, v2, ...)

**Example:**
```json
{
  "recording_id": 21,
  "active_version": "v1",
  "versions": [
    {
      "id": "v1",
      "model": "deepseek-chat",
      "main_topics": ["ML", "Neural Networks", "Backpropagation"],
      "detailed_topics": [
        {"time": "00:05:30", "title": "Introduction to ML"},
        {"time": "00:15:45", "title": "Neural Network Basics"}
      ],
      "breaks": [{"time": "01:30:00", "duration_minutes": 10}]
    }
  ]
}
```

---

### 📝 Subtitle Module (`subtitle_module/`)

**Purpose:** Генерация субтитров из транскрипций

**Key Features:**
- Форматы: SRT, VTT
- Автоматическое разбиение на строки
- Таймкоды из words.txt
- Поддержка multiple языков

**Output:** 
- `subtitles.srt`
- `subtitles.vtt`

**Usage:**
```bash
python main.py subtitles --format srt,vtt
```

**Upload:**
- YouTube: автоматическая загрузка субтитров
- VK: субтитры не поддерживаются

---

### 🚀 Upload Module (`video_upload_module/`)

**Purpose:** Загрузка видео на платформы

**Architecture:**
```
video_upload_module/
├── factory.py                # UploaderFactory
├── uploader_factory.py       # Legacy factory
├── credentials_provider.py   # Credential providers
├── config_factory.py         # Config factory
└── platforms/
    ├── youtube/
    │   ├── uploader.py       # YouTubeUploader
    │   └── config.py         # YouTubeUploadConfig
    └── vk/
        ├── uploader.py       # VKUploader
        └── config.py         # VKUploadConfig
```

**Supported Platforms:**

#### YouTube (YouTube Data API v3)
- Video upload с metadata
- Playlist management
- Subtitle upload (SRT, VTT)
- Thumbnail upload
- Privacy settings
- OAuth 2.0 authentication

#### VK (VK Video API)
- Video upload
- Album management
- Thumbnail upload
- Privacy settings
- Implicit Flow authentication (2026 policy)

**Key Features:**
- Automatic token refresh (YouTube)
- Retry механизм
- Progress tracking
- Multi-account support
- Credential provider pattern

**Documentation:**
- [OAUTH.md](OAUTH.md) - OAuth setup
- [VK_INTEGRATION.md](VK_INTEGRATION.md) - VK details

---

### 🗄️ Database Module (`database/`)

**Purpose:** Database models и migrations

**Key Files:**
- `models.py` - Core models (Recording, SourceMetadata, OutputTarget)
- `auth_models.py` - User, Credentials, Subscriptions
- `template_models.py` - Templates, Sources, Presets
- `automation_models.py` - Automation jobs
- `config.py` - Database configuration
- `manager.py` - Database manager

**ORM:** SQLAlchemy 2.0 (async)

**Migrations:** Alembic (19 migrations, auto-init)

**Documentation:** [DATABASE_DESIGN.md](DATABASE_DESIGN.md)

---

## Database Design

### Overview

**Database:** PostgreSQL 12+  
**ORM:** SQLAlchemy 2.0 (async)  
**Migrations:** Alembic (19 migrations)  
**Tables:** 12 (multi-tenant)

### Table Categories

**Authentication & Users (4 tables):**
- `users` - Пользователи с ролями и permissions
- `refresh_tokens` - JWT refresh tokens
- `user_credentials` - Encrypted credentials для внешних API
- `user_configs` - User-specific конфигурации

**Subscription & Quotas (4 tables):**
- `subscription_plans` - Планы подписок (Free/Plus/Pro/Enterprise)
- `user_subscriptions` - Привязка пользователей к планам
- `quota_usage` - Использование квот (recordings, storage, tasks)
- `quota_change_history` - История изменений квот

**Processing (4 tables):**
- `recordings` - Записи видео
- `source_metadata` - Метаданные источника (1:1 с recordings)
- `output_targets` - Целевые платформы (1:N с recordings)
- `recording_templates` - Шаблоны обработки

**Configuration (3 tables):**
- `base_configs` - Базовые конфигурации (deprecated)
- `input_sources` - Источники данных (Zoom accounts)
- `output_presets` - Пресеты загрузки (YouTube, VK)

**Automation (2 tables):**
- `automation_jobs` - Scheduled jobs (Celery Beat)
- `processing_stages` - Tracking stages (download, process, upload)

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

### Key Models

#### RecordingModel
```python
class RecordingModel:
    # Identification
    id: int
    user_id: int
    input_source_id: int | None
    template_id: int | None
    
    # Core metadata
    display_name: str
    start_time: datetime
    duration: int
    status: ProcessingStatus  # INITIALIZED → ... → UPLOADED
    
    # Flags
    is_mapped: bool           # Matched to template
    blank_record: bool        # Short/empty recording
    failed: bool
    
    # File paths
    local_video_path: str | None
    processed_video_path: str | None
    processed_audio_path: str | None
    transcription_dir: str | None
    
    # AI results
    transcription_info: dict | None
    topic_timestamps: dict | None
    main_topics: dict | None
    
    # Overrides
    processing_preferences: dict | None  # Config overrides
    
    # Relationships
    owner: UserModel
    input_source: InputSourceModel
    template: RecordingTemplateModel
    source: SourceMetadataModel (1:1)
    outputs: list[OutputTargetModel] (1:N)
```

#### RecordingTemplateModel
```python
class RecordingTemplateModel:
    # Identification
    id: int
    user_id: int
    name: str
    
    # Matching rules
    matching_rules: dict  # exact_matches, keywords, patterns
    
    # Configuration
    processing_config: dict  # transcription, video_processing
    metadata_config: dict    # title_template, youtube, vk
    output_config: dict      # preset_ids, auto_upload
    
    # State
    is_active: bool
```

#### UserCredentialModel
```python
class UserCredentialModel:
    # Identification
    id: int
    user_id: int
    platform: str  # zoom, youtube, vk_video, fireworks, deepseek
    account_name: str | None
    
    # Encrypted data (Fernet)
    encrypted_data: str
    encryption_key_version: int
    
    # State
    is_active: bool
    last_used_at: datetime | None
```

### Multi-Tenancy Strategy

**Shared Database + Row-Level Filtering**

**Implementation:**
1. Все таблицы имеют `user_id` колонку (кроме глобальных)
2. Foreign Key: `REFERENCES users(id) ON DELETE CASCADE`
3. Index на `user_id` для производительности
4. Repository Layer автоматически фильтрует по `user_id`

**Example:**
```python
class RecordingRepository:
    async def find_all(self, user_id: int, **filters) -> list[Recording]:
        query = select(RecordingModel).where(
            RecordingModel.user_id == user_id  # Automatic isolation
        )
        # ... apply filters
```

### Migrations

**19 migrations (автоматическая инициализация):**

```
001 → Create base tables (recordings, source_metadata, output_targets)
002 → Add auth tables (users, refresh_tokens)
003 → Add multitenancy (user_id to all tables)
004 → Add config_type field to base_configs
005 → Add account_name to user_credentials
006 → Add foreign keys to input_sources and output_presets
007 → Create user_configs table
008 → Update platform enum (add yandex_disk, rutube)
009 → Add unique constraint to input_sources
010 → Add FSM fields to output_targets
011 → Update ProcessingStatus enum
012 → Add automation quotas (max_automation_jobs to plans)
013 → Create automation_jobs table
014 → Create Celery Beat tables
015 → Add timezone to users
016 → Refactor quota system (quota_usage, quota_change_history)
017 → Add template_id to recordings
018 → Add blank_record flag
019 → Replace processed_audio_dir with processed_audio_path
```

**Auto-init on first run:**
```python
@app.on_event("startup")
async def startup_event():
    db_manager = DatabaseManager(DatabaseConfig.from_env())
    await db_manager.create_database_if_not_exists()
    subprocess.run(["alembic", "upgrade", "head"])
```

**Documentation:** [DATABASE_DESIGN.md](DATABASE_DESIGN.md)

---

## Processing Pipeline

### Full Pipeline Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           INPUT: Zoom Recording                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STAGE 1: SYNC                                                               │
│  • Zoom API request (OAuth 2.0)                                             │
│  • Fetch recordings metadata                                                 │
│  • Filter (duration > 30min, size > 40MB)                                   │
│  • Template matching (keywords, patterns)                                    │
│  • Save to PostgreSQL                                                        │
│  Status: INITIALIZED                                                         │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STAGE 2: DOWNLOAD                                                           │
│  • Multi-threaded download from Zoom                                         │
│  • Progress tracking                                                         │
│  • Checksum validation                                                       │
│  • Save to: media/video/unprocessed/                                        │
│  Status: DOWNLOADING → DOWNLOADED                                           │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STAGE 3: VIDEO PROCESSING                                                   │
│  • FFmpeg silence detection                                                  │
│  • Trim silent parts (begin, end, middle)                                   │
│  • Extract audio for transcription                                           │
│  • Output:                                                                   │
│    - media/video/processed/recording_*_processed.mp4                        │
│    - media/processed_audio/recording_*_processed.mp3                        │
│  Status: PROCESSING → PROCESSED                                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STAGE 4: TRANSCRIPTION                                                      │
│  • Fireworks AI (Whisper-v3-turbo) transcription                            │
│  • DeepSeek topic extraction                                                 │
│  • Generate main topics + detailed topics with timestamps                    │
│  • Auto-detect breaks (pauses ≥8min)                                        │
│  • Save to: media/user_{user_id}/transcriptions/{recording_id}/             │
│    - words.txt (words + timestamps)                                         │
│    - segments.txt (segments)                                                │
│    - topics.json (structured topics)                                        │
│    - master.json (metadata)                                                 │
│  Status: TRANSCRIBING → TRANSCRIBED                                         │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STAGE 5: SUBTITLE GENERATION                                                │
│  • Convert transcription to SRT/VTT                                          │
│  • Format lines with timestamps                                              │
│  • Save to: transcription_dir/subtitles.(srt|vtt)                           │
│  Optional stage                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STAGE 6: UPLOAD                                                             │
│  • Format description with timestamps                                        │
│  • Upload to YouTube and/or VK                                               │
│  • Upload subtitles (YouTube only)                                           │
│  • Upload thumbnails                                                         │
│  • Add to playlists/albums                                                   │
│  Status: UPLOADING → UPLOADED                                               │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    OUTPUT: Published Videos                                  │
│  • YouTube: video + description + timestamps + subtitles + thumbnail        │
│  • VK: video + description + timestamps + thumbnail                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Processing Status Flow

```
INITIALIZED → DOWNLOADING → DOWNLOADED → PROCESSING → PROCESSED →
TRANSCRIBING → TRANSCRIBED → UPLOADING → UPLOADED
```

**Special statuses:**
- `SKIPPED` - Пропущено (не matched к template или user choice)
- `FAILED` - Ошибка на одном из этапов
- `EXPIRED` - Устарело (TTL exceeded)

### Template-Driven Processing

**Config Hierarchy (Deep Merge):**
```
User Default Config ← Template Config ← Recording Override Config
```

**Example:**
```python
# User default
user_config = {"transcription": {"language": "ru"}}

# Template config
template_config = {
    "transcription": {"enable_topics": True, "language": "en"},
    "video": {"remove_silence": True}
}

# Recording override
override_config = {"transcription": {"language": "ru"}}

# Final (deep merge)
final = {
    "transcription": {
        "language": "ru",           # override wins
        "enable_topics": True       # from template
    },
    "video": {"remove_silence": True}  # from template
}
```

**Documentation:** [TEMPLATES.md](TEMPLATES.md)

---

## REST API

### API Statistics

**84 endpoints** across 15 routers:

| Category | Count | Description |
|----------|-------|-------------|
| 🔐 **Authentication** | 6 | Register, Login, Refresh, Logout, Profile |
| 👤 **User Management** | 6 | Profile, Config, Password, Account |
| 👔 **Admin** | 3 | Stats, Users, Quotas |
| 🎥 **Recordings** | 16 | CRUD, Pipeline, Batch operations |
| 📋 **Templates** | 8 | CRUD, Matching, Re-match |
| 🔑 **Credentials** | 6 | CRUD, Platform management |
| 🔌 **OAuth** | 6 | YouTube, VK, Zoom flows |
| 🤖 **Automation** | 6 | Jobs, Scheduling, Celery Beat |
| 📊 **Tasks** | 4 | Async task monitoring |
| 📥 **Input Sources** | 6 | Zoom sources, Sync |
| 📤 **Output Presets** | 5 | Upload presets |
| 🖼️ **Thumbnails** | 4 | Upload, Management |
| 💚 **Health** | 1 | System status |
| 🔧 **User Config** | 2 | User-specific settings |
| **TOTAL** | **84** | **100% Production Ready** |

### Pydantic Schemas

**118+ models** with full type safety:

- Request/Response models для всех endpoints
- Nested typing (templates, presets, configs)
- 6 Enums (`ProcessingStatus`, `YouTubePrivacy`, `VKPrivacyLevel`, etc.)
- 100% OpenAPI documentation coverage

**Documentation:** [API_GUIDE.md](API_GUIDE.md)

### Key Endpoint Groups

#### Recordings Pipeline

```bash
# Full pipeline
POST /api/v1/recordings/{id}/full-pipeline

# Individual stages
POST /api/v1/recordings/{id}/download
POST /api/v1/recordings/{id}/process
POST /api/v1/recordings/{id}/transcribe
POST /api/v1/recordings/{id}/upload/{platform}

# Batch operations
POST /api/v1/recordings/batch-process
POST /api/v1/recordings/batch-upload
```

#### Template Management

```bash
# CRUD
GET /api/v1/templates
POST /api/v1/templates
GET /api/v1/templates/{id}
PATCH /api/v1/templates/{id}
DELETE /api/v1/templates/{id}

# Matching
POST /api/v1/templates/{id}/preview-match
POST /api/v1/templates/{id}/rematch
POST /api/v1/templates/{id}/preview-rematch
```

#### OAuth Flows

```bash
# YouTube
GET /api/v1/oauth/youtube/authorize
GET /api/v1/oauth/youtube/callback

# VK
GET /api/v1/oauth/vk/authorize
POST /api/v1/oauth/vk/token/submit  # Implicit Flow

# Zoom
GET /api/v1/oauth/zoom/authorize
GET /api/v1/oauth/zoom/callback
```

### API Documentation

**Interactive documentation:**
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- OpenAPI JSON: http://localhost:8000/openapi.json

---

## Security

### Multi-Tenant Isolation

**3-Layer Security:**

**1. Database Level:**
- Все таблицы имеют `user_id` с индексами
- Foreign Key constraints: `ON DELETE CASCADE`
- Row-level filtering в queries

**2. Repository Level:**
- Автоматическая фильтрация по `user_id` во всех запросах
- Validation в `find_by_id`, `find_all`, `update`, `delete`

**3. Service Level:**
- `ServiceContext` передает правильный `user_id`
- Validation на существование ресурса и ownership

**4. API Level:**
- JWT token validation через `get_current_user` dependency
- Автоматическая инъекция `user_id` в `ServiceContext`

### Authentication & Authorization

**JWT (JSON Web Tokens):**
- Access token: 15 минут
- Refresh token: 30 дней
- Stored in database (`refresh_tokens` table)
- Automatic rotation

**OAuth 2.0:**
- YouTube: Authorization Code Flow
- VK: Implicit Flow (2026 policy)
- Zoom: OAuth 2.0 / Server-to-Server
- CSRF protection через Redis state tokens

**RBAC (Role-Based Access Control):**
```python
class UserModel:
    role: str  # "user", "admin"
    
    # Permissions
    can_transcribe: bool
    can_process_video: bool
    can_upload: bool
    can_create_templates: bool
    can_delete_recordings: bool
    can_manage_credentials: bool
```

**Documentation:** [OAUTH.md](OAUTH.md)

### Credentials Encryption

**Fernet (Symmetric Encryption):**

```python
from cryptography.fernet import Fernet

# Encrypt
encrypted_data = fernet.encrypt(json.dumps(credentials).encode())

# Store in DB
user_credentials.encrypted_data = encrypted_data.decode()

# Decrypt
decrypted = json.loads(fernet.decrypt(encrypted_data.encode()))
```

**Key Management:**
- Encryption key stored in environment variable: `ENCRYPTION_KEY`
- Key rotation support через `encryption_key_version`
- Never log or expose credentials

**Encrypted Platforms:**
- Zoom (OAuth tokens, Server-to-Server credentials)
- YouTube (OAuth tokens)
- VK (access tokens)
- Fireworks API keys
- DeepSeek API keys

### Rate Limiting

**API Rate Limits:**
- Per minute: 60 requests
- Per hour: 1000 requests
- 429 Too Many Requests response

**Quota System:**
- Monthly recordings limit (by plan)
- Storage limit (by plan)
- Concurrent tasks limit
- Automation jobs limit

### Security Best Practices

**Environment Variables:**
```bash
# Never commit these
API_JWT_SECRET_KEY=your-secret-key-change-in-production
ENCRYPTION_KEY=your-fernet-key-here
DATABASE_PASSWORD=secure-password
```

**CORS Configuration:**
```python
# Production: strict origins
ALLOWED_ORIGINS = ["https://yourdomain.com"]

# Development: localhost only
ALLOWED_ORIGINS = ["http://localhost:3000"]
```

**HTTPS Only:**
- All OAuth redirects must use HTTPS in production
- Secure cookies (`SameSite=Lax`, `Secure=True`)

---

## Development Guide

### Setup

**Requirements:**
- Python 3.11+
- PostgreSQL 12+
- Redis
- FFmpeg

**Installation:**
```bash
# 1. Clone repository
git clone <repo-url>
cd ZoomUploader

# 2. Install dependencies (UV recommended)
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync

# 3. Setup environment
cp .env.example .env
# Edit .env with your credentials

# 4. Start infrastructure
make docker-up

# 5. Initialize database
make init-db

# 6. Run API
make api
```

### Project Commands

**Development:**
```bash
make api          # Start FastAPI server
make worker       # Start Celery worker
make beat         # Start Celery beat (scheduling)
make flower       # Start Flower (monitoring)
```

**Database:**
```bash
make init-db      # Initialize database + migrations
make migrate      # Apply migrations
make migrate-down # Rollback migration
make db-version   # Show current version
make db-history   # Show migration history
make recreate-db  # Drop + recreate (⚠️ data loss)
```

**Code Quality:**
```bash
make lint         # Run ruff linter
make format       # Format code with ruff
make type-check   # Run type checking (planned)
```

### Running Tests

**Unit Tests:**
```bash
pytest tests/unit/
```

**Integration Tests:**
```bash
pytest tests/integration/
```

**E2E Tests:**
```bash
pytest tests/e2e/
```

### Adding New Features

**1. Create migration:**
```bash
alembic revision -m "add_new_feature"
# Edit migration file
alembic upgrade head
```

**2. Add models:**
```python
# database/models.py
class NewModel(Base):
    __tablename__ = "new_table"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"))  # Multi-tenant
```

**3. Add repository:**
```python
# api/repositories/new_repository.py
class NewRepository:
    async def find_all(self, user_id: int) -> list[NewModel]:
        # Auto-filter by user_id
        pass
```

**4. Add service:**
```python
# api/services/new_service.py
class NewService:
    def __init__(self, repo: NewRepository):
        self.repo = repo
```

**5. Add schemas:**
```python
# api/schemas/new/schemas.py
class NewCreate(BaseModel):
    name: str = Field(..., min_length=1)
    
class NewResponse(BaseModel):
    id: int
    name: str
```

**6. Add router:**
```python
# api/routers/new.py
@router.get("/new")
async def list_new(ctx: ServiceContext = Depends(get_service_context)):
    service = NewService(NewRepository(ctx.session))
    return await service.list(ctx.user_id)
```

### Environment Variables

**Required:**
```bash
# Database
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_NAME=zoom_manager
DATABASE_USERNAME=postgres
DATABASE_PASSWORD=postgres

# API
API_JWT_SECRET_KEY=your-secret-key
ENCRYPTION_KEY=your-fernet-key

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# Celery
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
```

**Optional:**
```bash
# AI Services
FIREWORKS_API_KEY=your-key
DEEPSEEK_API_KEY=your-key

# OAuth
# See config/oauth_*.json files
```

### Debugging

**Enable debug logging:**
```python
# logger.py
LOG_LEVEL = "DEBUG"
```

**View logs:**
```bash
# Docker
docker-compose logs -f api
docker-compose logs -f worker

# Local
tail -f logs/api.log
tail -f logs/worker.log
```

**Redis inspection:**
```bash
redis-cli
> KEYS *
> GET oauth:state:abc-123
```

**Database inspection:**
```bash
psql -U postgres -d zoom_manager
> \dt  # List tables
> SELECT * FROM recordings WHERE user_id=1;
```

---

## Performance

### Optimization Strategies

**1. Lazy Loading:**
- `ConfigHelper` создается только при первом обращении
- SQLAlchemy relationships с `lazy="selectin"`

**2. Async Operations:**
- Все I/O операции асинхронные (FastAPI, SQLAlchemy)
- Concurrent transcription/upload (с ограничением)

**3. Database Indexing:**
- Все foreign keys имеют индексы
- Composite indexes для часто используемых queries

**4. Caching:**
- Redis для OAuth state tokens
- Token caching в memory (planned)

**5. Connection Pooling:**
- SQLAlchemy async connection pool
- Redis connection pool

### Monitoring

**Metrics:**
- API response time (via middleware)
- Database query performance (slow query log)
- Celery task duration (via Flower)
- Quota usage tracking

**Tools:**
- Flower: http://localhost:5555 (Celery monitoring)
- PostgreSQL slow query log
- Redis monitoring via redis-cli

---

## Related Documentation

**Core Guides:**
- [INDEX.md](INDEX.md) - Documentation index
- [README.md](../README.md) - Project overview
- [DEPLOYMENT.md](DEPLOYMENT.md) - Production deployment
- [CHANGELOG.md](CHANGELOG.md) - Version history

**Features:**
- [TEMPLATES.md](TEMPLATES.md) - Template-driven automation
- [OAUTH.md](OAUTH.md) - OAuth integration
- [VK_INTEGRATION.md](VK_INTEGRATION.md) - VK Implicit Flow
- [BULK_OPERATIONS_GUIDE.md](BULK_OPERATIONS_GUIDE.md) - Batch processing

**Architecture:**
- [DATABASE_DESIGN.md](DATABASE_DESIGN.md) - Database schema
- [ADR_OVERVIEW.md](ADR_OVERVIEW.md) - Architecture decisions
- [ADR_FEATURES.md](ADR_FEATURES.md) - Feature ADRs
- [API_GUIDE.md](API_GUIDE.md) - API schemas & best practices

---

## Quick Reference

**API Endpoints:** 84 (production-ready)  
**Database Tables:** 12 (multi-tenant)  
**Migrations:** 19 (auto-init)  
**Pydantic Models:** 118+ (fully typed)  
**Processing Modules:** 7 (video, transcription, upload)  
**OAuth Platforms:** 3 (YouTube, VK, Zoom)  
**AI Models:** 2 (Whisper, DeepSeek)

**Technology Stack:**  
Python 3.11+ • FastAPI • SQLAlchemy 2.0 • PostgreSQL 12+ • Redis • Celery • FFmpeg

**Documentation:** 14 comprehensive guides

---

**Version:** v0.9.3 (January 2026)  
**Status:** Development  
**License:** Business Source License 1.1
