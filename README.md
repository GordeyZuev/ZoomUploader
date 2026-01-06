# 🎥 Zoom Publishing Platform

> **Multi-Tenant Platform для автоматической обработки и публикации видеоконтента**

![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-async-green.svg)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-12+-blue.svg)
![License](https://img.shields.io/badge/license-BSL%201.1-orange.svg)

Production-ready платформа с полным `REST API` для автоматизации end-to-end обработки образовательного контента — от загрузки до публикации с AI-транскрибацией, структурированием и профессиональным оформлением.

**Версия:** `v0.9.1` (Dev Status)  
**Tech:** `Python 3.11+` • `FastAPI` • `PostgreSQL` • `Redis` • `Celery` • `AI` (Whisper, DeepSeek)

---

## 🎯 Use Cases

**🏫 Университеты и образовательные платформы**
- Автоматическая публикация тысяч лекций с минимальными усилиями
- AI-структурирование контента для удобной навигации
- Multi-tenant изоляция для разных кафедр/факультетов

**🎓 Онлайн-школы и EdTech**
- Быстрый time-to-market для образовательного контента
- Профессиональное оформление с таймкодами и субтитрами
- Scheduled automation для регулярных публикаций

**🎬 Контент-команды**
- Batch processing для массовой обработки архивов
- Template-based автоматизация для разных типов контента
- API-first подход для интеграции в существующие системы

**👨‍💼 Enterprise**
- Multi-tenancy для изоляции клиентов/проектов
- RBAC и квоты для контроля доступа
- Audit logs и usage tracking

---

## 🔄 Как это работает

Платформа автоматизирует полный цикл обработки видео от загрузки до публикации:

```
📥 Zoom/Файлы → ✂️ FFmpeg → 🤖 AI (Whisper+DeepSeek) → 📝 Метаданные → 📤 YouTube/VK
                Видео        Транскрипция+Темы        Таймкоды         Публикация
                  ↓              ↓                        ↓                 ↓
              Тишина       Структура контента      Описание+Субтитры   Multi-platform
              удалена      с таймкодами           Template-based       Auto-retry
```

### Этап 1: 📥 Получение контента

**Источники данных:**
- Синхронизация с `Zoom API` через `OAuth 2.0`
- Загрузка локальных файлов
- Automatic retry при сбоях

**Что происходит:**
- Система забирает записи из Zoom или загружает файлы
- Создает записи в БД с метаданными
- Скачивает видео в user-isolated storage

### Этап 2: ✂️ Обработка видео

**FFmpeg Processing:**
- Детекция и удаление тишины
- Обрезка пустого начала и конца
- Удаление длинных пауз
- Извлечение аудиодорожки для транскрибации

**Результат:**
- Чистое видео без технических пауз
- Оптимизированная длительность
- Готовый аудио-файл

### Этап 3: 🤖 AI-обработка

**Транскрибация (`Fireworks AI`):**
- `whisper-v3-turbo` для точной транскрибации
- Поддержка больших файлов
- Automatic chunking и retry

**Извлечение структуры (`DeepSeek`):**
- Определение основных и детализированных тем
- Автоматическая генерация таймкодов (`HH:MM:SS`)
- Обнаружение перерывов и пауз

**Субтитры:**
- Генерация `SRT` и `VTT` файлов
- Поддержка multiple языков

### Этап 4: 📝 Формирование метаданных

**Автоматическая генерация:**
- Структурированное описание с таймкодами
- Заголовок на основе шаблона
- Подбор миниатюр (thumbnails)
- Применение user config и templates

**Template-Based:**
- Matching rules для автоматического применения
- Пресеты для разных типов контента
- Настройка через API или config файлы

### Этап 5: 📤 Публикация

**YouTube:**
- Загрузка видео через `YouTube Data API v3`
- Автоматическая загрузка субтитров
- Добавление в плейлисты
- Настройка privacy и категории

**VK:**
- Загрузка в сообщества
- Добавление в альбомы
- Настройка видимости

**Multi-Platform:**
- Параллельная загрузка на несколько платформ
- Tracking статусов для каждой
- Retry при сбоях

### Этап 6: 📊 Мониторинг

**Real-Time Tracking:**
- Progress tracking для каждого этапа
- Журнал операций
- Usage tracking (AI costs, storage)
- Audit logs

**Automation:**
- Scheduled jobs через `Celery Beat`
- Automatic retry при ошибках
- Notifications (планируется)

---

## 🚀 Почему этот проект

### Enterprise-Ready Features

**⚡ 64 REST API Endpoints**
- Полноценный `CRUD` для всех сущностей
- `JWT` аутентификация + `RBAC`
- `OpenAPI` документация (`Swagger`, `ReDoc`)
- Асинхронная архитектура на `FastAPI`

**👥 Multi-Tenancy из коробки**
- Полная изоляция данных пользователей
- Шифрование credentials (`Fernet`)
- User-isolated file storage
- Квоты и rate limiting

**🔐 Production Security**
- `OAuth 2.0` интеграция (YouTube, VK)
- Automatic token refresh
- `CSRF` protection через `Redis`
- Encrypted credentials в БД

**🤖 Smart Automation**
- `Celery Beat` scheduling
- Declarative job configuration
- Automatic sync + process + upload
- Dry-run mode для preview

**📊 AI-Powered Processing**
- `Fireworks AI` (`whisper-v3-turbo`) для транскрибации
- `DeepSeek` для извлечения тем
- Автоматическая генерация таймкодов
- Генерация субтитров (`SRT`, `VTT`)

---

## 📈 Key Metrics

```
📊 API Endpoints:        64
🗄️  Database Migrations:  14
🔌 Platform Integrations: 3 (Zoom, YouTube, VK)
🤖 AI Models:            2 (Whisper, DeepSeek)
🔒 Security Features:    JWT + OAuth2 + RBAC + Encryption
⚡ Processing Pipeline:  6 stages, fully automated
```

---

## 💎 Ключевые преимущества

### ⚡ Производительность

**80%+ экономия времени**
- Полная автоматизация: от синхронизации до публикации
- Batch processing для массовой обработки
- Concurrent execution с оптимизацией ресурсов
- Scheduled automation — публикация в фоне

**Масштабируемость**
- Multi-tenant архитектура для тысяч пользователей
- Horizontal scaling через `Celery` workers
- Async-first для высокой пропускной способности
- Resource quotas для fair usage

### 🤖 AI-Powered Intelligence

**Smart Content Processing**
- `Fireworks AI` (`whisper-v3-turbo`) — точная транскрибация
- `DeepSeek` — интеллектуальное извлечение тем
- Автоматические таймкоды для навигации
- Генерация субтитров (`SRT`, `VTT`)

**Video Enhancement**
- `FFmpeg` — удаление тишины и пауз
- Automatic trimming начала/конца
- Audio extraction для AI processing
- Quality optimization

### 🏢 Enterprise-Grade

**Security & Compliance**
- `OAuth 2.0` + `JWT` authentication
- `Fernet` encryption для credentials
- `RBAC` для управления доступом
- Audit logs и usage tracking

**Production-Ready**
- 64 REST API endpoints с `OpenAPI` docs
- Health checks и monitoring (`Flower`)
- Automatic retry mechanisms
- Error handling и graceful degradation

---

## 🛠️ Технологический стек

### Modern Python Stack

**Core Framework**
```
Python 3.11+ • FastAPI (async) • SQLAlchemy 2.0 (async ORM)
PostgreSQL 12+ • Redis • Celery + Beat • Alembic
```

**AI & ML**
```
Fireworks AI (whisper-v3-turbo) • DeepSeek API
FFmpeg • Pydantic V2
```

**External Integrations**
```
Zoom API (OAuth 2.0) • YouTube Data API v3 • VK API
```

**Security Stack**
```
JWT Authentication • OAuth 2.0 • Fernet Encryption
PBKDF2 Hashing • RBAC • CSRF Protection
```

**DevOps & Tools**
```
Docker & Docker Compose • UV (package manager)
Ruff (linter) • Flower (monitoring) • Make
```

### Архитектурные паттерны

- **Repository Pattern** — изоляция доступа к данным
- **Factory Pattern** — создание сервисов с credentials
- **Service Context** — централизованный контекст выполнения
- **Config-Driven** — template-based автоматизация
- **Async-First** — полностью асинхронная архитектура

---

## 🚀 Быстрый старт

### Production Deployment

```bash
# Docker Compose (рекомендуется)
docker-compose up -d

# Проверка статуса
docker-compose ps
```

**Доступ:**
- API: http://localhost:8000
- Swagger UI: http://localhost:8000/docs
- Flower: http://localhost:5555

### Development Setup

```bash
# 1. Установка зависимостей (UV рекомендуется)
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync

# 2. Запуск инфраструктуры
make docker-up

# 3. Инициализация БД
make init-db

# 4. Запуск API
make api
```

### Требования

**Система:**
- `Python 3.11+` • `PostgreSQL 12+` • `Redis` • `FFmpeg`
- CPU: 4+ cores • RAM: 8+ GB • SSD: 100+ GB

**API Keys:**
- `Zoom` • `YouTube` • `VK` • `Fireworks AI` • `DeepSeek`

📖 Подробные инструкции: [DEPLOYMENT.md](docs/DEPLOYMENT.md) • [OAUTH_SETUP.md](docs/OAUTH_SETUP.md)

---

## 🌐 REST API (64 endpoints)

Production-ready `REST API` с полной `OpenAPI` документацией:

### Основные группы

| Группа | Endpoints | Описание |
|--------|-----------|----------|
| 🔐 **Authentication** | 5 | Register, Login, Refresh, Logout, Profile |
| 👤 **User Management** | 6 | Profile, Config, Password, Account deletion |
| 🎥 **Recordings** | 15+ | CRUD, Processing pipeline, Batch operations |
| 🔑 **Credentials** | 4 | Encrypted storage для API keys |
| 📋 **Templates** | 8+ | Template-based automation rules |
| 🔌 **OAuth** | 4 | YouTube & VK OAuth 2.0 flows |
| 🤖 **Automation** | 6 | Scheduled jobs, Celery Beat integration |
| 📊 **Tasks** | 4+ | Async task monitoring & management |
| 🖼️ **Thumbnails** | 4 | Multi-tenant thumbnail system |
| 🎯 **Sources & Presets** | 8+ | Data sources, Upload presets |

**Документация:**
- 📖 Interactive API: http://localhost:8000/docs (`Swagger UI`)
- 📘 Alternative Docs: http://localhost:8000/redoc (`ReDoc`)
- 🔧 Technical Details: [TECHNICAL.md](docs/TECHNICAL.md#rest-api-endpoints)

### Template-Based Automation Example

```json
{
  "name": "ML Lectures Auto-Publish",
  "matching_rules": {
    "name_pattern": "Лекция*",
    "source_type": "ZOOM"
  },
  "processing_config": {
    "video": {"remove_silence": true},
    "transcription": {"model": "whisper-v3-turbo"}
  },
  "output_targets": {
    "youtube": {"playlist_id": "PLxxx", "privacy": "public"},
    "vk": {"album_id": "12345"}
  }
}
```

---

## 🏗️ Enterprise Architecture

### Multi-Tenancy

**3-Level Data Isolation**
```
Database:    user_id filtering + indexes
Service:     ServiceContext + ConfigHelper
File System: media/user_{user_id}/ isolation
```

### Security

**Authentication & Authorization**
- `JWT` (access + refresh) • `OAuth 2.0` • `RBAC`
- `Fernet` encryption • `PBKDF2` hashing
- `CSRF` protection via `Redis`

**Resource Management**
- Rate limiting (60/min, 1000/hr)
- Storage & processing quotas
- Concurrent task limits
- Usage tracking & audit logs

### Модульная структура

```
api/                 ← FastAPI endpoints, JWT auth, validation
database/            ← SQLAlchemy models, Alembic migrations
*_module/            ← Processing modules (video, transcription, upload)
api/services/        ← Business logic layer
api/repositories/    ← Data access layer (Repository pattern)
api/tasks/           ← Celery background tasks
```

**Design Patterns:**
- **Repository** — data access isolation
- **Factory** — service creation with credentials
- **Service Context** — unified execution context
- **Config-Driven** — template-based automation

📖 Детали: [TECHNICAL.md](docs/TECHNICAL.md) • [ADR.md](docs/ADR.md)

---

## 📊 Processing Pipeline

**Status Flow:**
```
INITIALIZED → DOWNLOADING → DOWNLOADED → 
PROCESSING → PROCESSED → PREPARING → 
TRANSCRIBED → UPLOADING → READY
```

**Special Statuses:**
- `SKIPPED` — пропущено (config-driven)
- `EXPIRED` — устарело (TTL exceeded)

---

## 📚 Документация

| Документ | Описание |
|----------|----------|
| 📖 [TECHNICAL.md](docs/TECHNICAL.md) | Полная техническая документация (API, Architecture, Security) |
| 🚀 [DEPLOYMENT.md](docs/DEPLOYMENT.md) | Production deployment guide |
| 🏛️ [ADR.md](docs/ADR.md) | Architecture Decision Records |
| 📜 [WHAT_WAS_DONE.md](docs/WHAT_WAS_DONE.md) | Детальная история проекта |
| 🎯 [PLAN.md](docs/PLAN.md) | Цели и задачи проекта |

**OAuth & Automation:**
- 🔐 [OAUTH_SETUP.md](docs/OAUTH_SETUP.md) — настройка за 30 минут
- 🔧 [OAUTH_TECHNICAL.md](docs/OAUTH_TECHNICAL.md) — техническая спецификация
- 🤖 [AUTOMATION_IMPLEMENTATION_PLAN.md](docs/AUTOMATION_IMPLEMENTATION_PLAN.md) — система автоматизации

---

## 🆕 Latest Release: v0.9.1

**Major Features:**

🔐 **OAuth 2.0 Integration**
- Web-based flow для YouTube & VK
- Auto-refresh tokens • CSRF protection
- Multi-tenant credential management

🤖 **Automation System**
- Celery Beat scheduling
- Declarative config (time/cron/weekdays)
- Dry-run mode • Quota management

⭐ **Config-Driven Architecture**
- Template-based automation
- Deep merge updates • FSM state management
- SKIPPED records handling

📊 **Enhanced Processing**
- Decoupled pipeline (transcribe → topics → subtitles)
- Topic versioning • Cost tracking
- Multi-tenant thumbnails system

**Statistics:**
```
API Endpoints:  49 → 64 (+15)
DB Migrations:  8 → 14 (+6)
New Models:     AutomationJobModel, FSM fields
New Statuses:   PREPARING, READY
```

📜 Полная история: [WHAT_WAS_DONE.md](docs/WHAT_WAS_DONE.md)

---

## 📄 Лицензия

**Business Source License 1.1**

Проект распространяется под лицензией Business Source License 1.1. См. файл [LICENSE](LICENSE) для полной информации.

---

## 📞 Контакты

**Документация:** [папка `docs`](docs/)

---

**Версия:** `v0.9.1` • **Статус:** Dev Status
