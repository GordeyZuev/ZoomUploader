# Zoom Publishing Platform

> **Production-Ready Multi-Tenant Platform для автоматической обработки и публикации видеоконтента**

Полнофункциональная платформа с REST API для автоматизации полного цикла обработки образовательного видеоконтента. Система забирает видеозаписи из различных источников, обрабатывает их с использованием AI-технологий для транскрибации и структурирования, автоматически генерирует метаданные с таймкодами и публикует на целевые платформы.

**Версия:** v2.1 - Production-Ready with Async Processing

**Ключевые возможности:**
- REST API (49 endpoints) с JWT аутентификацией
- Multi-tenancy архитектура с полной изоляцией данных
- Асинхронная обработка задач (Celery + Redis)
- Система шаблонов для автоматизации
- Роли, права доступа и квоты
- Progress tracking в реальном времени

---

## Описание проекта

**Zoom Publishing Platform** — автоматизированный пайплайн для превращения записей Zoom-лекций в готовые к публикации видео с AI-структурированием контента.

### Основная цель

Автоматизация процесса публикации учебных лекций с использованием современных AI-технологий для транскрибации и структурирования контента, минимизация ручной работы и обеспечение единообразного качества публикаций.

### Целевая аудитория

**Учебные заведения**
- Оперативная публикация занятий с удобной навигацией по темам
- Автоматизация процесса публикации учебного контента

**Преподаватели и студенты**
- Быстрый доступ к структурированным лекциям с таймкодами
- Автоматическая генерация оглавления и субтитров

**Контент-команды**
- Быстрый конвейер «запись → оформленное видео → публикация»
- Batch processing для массовой обработки

### Преимущества

**Экономия времени**
- Сокращение времени обработки на 80%+
- Полная автоматизация от загрузки до публикации

**Качество контента**
- Удаление тишины и технических пауз
- Профессиональное оформление с таймкодами
- Автоматическая генерация субтитров

**Масштабируемость**
- Multi-tenant архитектура
- Асинхронная обработка
- Horizontal scaling

---

## Функциональность

### Полный цикл обработки

**1. Получение исходных данных**
- Синхронизация с Zoom API (OAuth 2.0)
- Загрузка локальных файлов
- Поддержка различных источников (планируется расширение)

**2. Обработка видео**
- Детекция и удаление тишины (FFmpeg)
- Обрезка пустого начала и конца
- Удаление длинных пауз
- Извлечение аудиодорожки

**3. AI-обработка контента**
- Транскрибация через Fireworks AI (whisper-v3-turbo)
- Извлечение тем через DeepSeek
- Определение основных и детализированных тем
- Автоматическое обнаружение перерывов
- Генерация субтитров (SRT, VTT)

**4. Формирование метаданных**
- Создание структурированного описания
- Таймкоды в формате HH:MM:SS
- Автоматический подбор миниатюр
- Применение шаблонов оформления

**5. Публикация**
- Загрузка на YouTube с субтитрами
- Загрузка на VK
- Добавление в плейлисты/альбомы
- Tracking статусов

**6. Мониторинг и управление**
- Журнал операций
- Progress tracking
- Обработка ошибок
- Automatic retry

---

## Технологический стек

### Backend & Infrastructure

**Core**
- Python 3.11+ (asyncio, type hints)
- FastAPI (async web framework)
- PostgreSQL 12+ (реляционная БД)
- Redis (кэширование, очереди задач)

**ORM & Migrations**
- SQLAlchemy 2.0 (async ORM)
- Alembic (управление схемой БД)
- Asyncpg (PostgreSQL driver)

**Task Queue & Processing**
- Celery (асинхронная обработка)
- Flower (мониторинг задач)
- FFmpeg (обработка видео/аудио)

**Validation & Configuration**
- Pydantic (валидация данных)
- Pydantic Settings (конфигурация)
- Python-dotenv (переменные окружения)

### AI & ML Services

**Транскрибация**
- Fireworks AI (whisper-v3-turbo)
- Поддержка больших файлов
- Автоматические retry
- Ограничение параллелизма

**Структурирование контента**
- DeepSeek API (deepseek-chat)
- Извлечение тем
- Генерация таймкодов
- Определение перерывов

### External APIs

**Интеграции**
- Zoom API (OAuth 2.0) — получение записей
- YouTube Data API v3 — загрузка видео и субтитров
- VK API — публикация в сообществах

### Security

**Аутентификация и авторизация**
- JWT tokens (access + refresh)
- Fernet encryption для credentials
- PBKDF2 password hashing
- Role-based access control (RBAC)

### Development Tools

**Development & Testing**
- UV (быстрый менеджер пакетов)
- Ruff (современный линтер)
- Docker & Docker Compose
- Make (автоматизация команд)

**Мониторинг**
- Structured logging
- Flower (Celery monitoring)
- Health check endpoints

---

## Быстрый старт

### Требования

**Обязательные компоненты:**
- Python 3.8+ (рекомендуется 3.11+)
- PostgreSQL 12+
- Redis (для Celery)
- FFmpeg

**Рекомендуемые характеристики:**
- CPU: 4+ ядра
- RAM: 8+ GB
- Диск: SSD, 100+ GB для видео
- Сеть: 10+ Мбит/с

**API ключи:**
- Zoom API (OAuth 2.0 credentials)
- YouTube Data API v3 (Google Cloud OAuth)
- VK API (Access Token)
- Fireworks AI (API key)
- DeepSeek (API key)

### Установка

```bash
# 1. Установка UV (рекомендуется)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 2. Установка зависимостей
uv sync

# Альтернативно через pip
pip install -r requirements.txt
```

### Настройка

**1. База данных**

```bash
# Запуск PostgreSQL через Docker
make docker-up

# Инициализация БД (создание + миграции)
make init-db
```

**2. Переменные окружения**

Создайте файл `.env`:

```env
# Database
DATABASE_HOST=localhost
DATABASE_PORT=5432
DATABASE_NAME=zoom_manager
DATABASE_USERNAME=postgres
DATABASE_PASSWORD=postgres

# API
API_JWT_SECRET_KEY=your-secret-key-change-in-production

# Celery (optional)
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0

# General
TIMEZONE=Europe/Moscow
```

**3. API ключи**

Создайте файлы конфигурации в папке `config/`:
- `zoom_creds.json`
- `youtube_creds.json`
- `vk_creds.json`
- `fireworks_creds.json`
- `deepseek_creds.json`

Подробные инструкции: [Руководство по развертыванию](docs/DEPLOYMENT.md)

### Запуск

**Вариант 1: Docker Compose (рекомендуется для production)**

```bash
# Запуск всего стека
docker-compose up -d

# Проверка статуса
docker-compose ps

# Просмотр логов
docker-compose logs -f celery_worker
```

**Вариант 2: Локальная разработка**

```bash
# Terminal 1: Инфраструктура (Postgres + Redis)
make docker-up

# Terminal 2: FastAPI
make api

# Terminal 3: Celery Worker
make celery

# Terminal 4: Flower (мониторинг, опционально)
make flower
```

**Доступ к сервисам:**
- API: http://localhost:8000
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc
- Flower: http://localhost:5555

### Основные команды

```bash
# Синхронизация с Zoom
python main.py sync --last 7

# Полный пайплайн
python main.py full-process --all

# Просмотр записей
python main.py list --last 7

# Генерация субтитров
python main.py subtitles --all

# Добавление локального видео
python main.py add-video "/path/to/video.mp4" --name "Лекция 1"
```

Полный список команд: [Техническая документация](docs/TECHNICAL.md)

---

## REST API

### Endpoints (49 total)

Платформа предоставляет полноценный production-ready REST API:

**Authentication** (`/api/v1/auth`)
- POST `/register` — регистрация
- POST `/login` — вход
- POST `/refresh` — обновление токена
- POST `/logout` — выход
- GET `/me` — информация о пользователе

**User Management** (`/api/v1/users`)
- PATCH `/me` — обновление профиля
- POST `/me/password` — смена пароля
- DELETE `/me` — удаление аккаунта

**Recordings** (`/api/v1/recordings`)
- GET `/` — список записей (с фильтрацией)
- POST `/` — добавление локального видео
- POST `/{id}/download` — загрузка из Zoom
- POST `/{id}/process` — обработка видео
- POST `/{id}/transcribe` — транскрибация
- POST `/{id}/upload/{platform}` — публикация
- POST `/{id}/full-pipeline` — полный цикл
- POST `/batch-process` — массовая обработка

**Credentials** (`/api/v1/credentials`)
- GET `/` — список credentials
- POST `/` — создание
- PUT `/{id}` — обновление
- DELETE `/{id}` — удаление

**Templates, Sources, Presets** (`/api/v1/*`)
- Полный CRUD для шаблонов обработки
- Управление источниками данных
- Настройка пресетов публикации

**Tasks** (`/api/v1/tasks`)
- GET `/{id}` — статус задачи
- DELETE `/{id}` — отмена задачи

Полная документация API: [Техническая документация](docs/TECHNICAL.md#rest-api-endpoints)

### Автоматизация через шаблоны

Система поддерживает автоматическое применение правил обработки:

```json
{
  "name": "Лекции ML",
  "matching_rules": {
    "name_pattern": "Лекция*",
    "source_type": "ZOOM"
  },
  "processing_config": {
    "video": {"remove_silence": true},
    "transcription": {"model": "whisper-v3-turbo"}
  },
  "metadata_config": {
    "title_template": "{original_title} - {date}",
    "description_template": "Темы:\n{topics_list}"
  }
}
```

---

## Multi-Tenancy архитектура

### Изоляция данных

**Database Level**
- Все таблицы с user_id
- Автоматическая фильтрация по пользователю
- Индексы для производительности

**Service Level**
- ServiceContext pattern
- ConfigHelper для credentials
- Factory pattern для создания сервисов

**File System**
- Изоляция: `media/user_{user_id}/`
- Автоматическое управление путями
- UserPathManager

### Безопасность

**Аутентификация**
- JWT tokens (access + refresh)
- Secure password hashing (PBKDF2)
- Token rotation

**Шифрование**
- Fernet для credentials в БД
- Автоматическое дешифрование через CredentialService
- Защита от утечек

**Авторизация**
- Role-based access (admin/user)
- Endpoint-level permissions
- Resource ownership validation

### Управление ресурсами

**Квоты**
- API requests per minute/hour
- Storage limits
- Processing limits
- Concurrent tasks

**Rate Limiting**
- 60 requests/minute
- 1000 requests/hour
- Автоматическая блокировка при превышении

**Мониторинг**
- Usage tracking
- Audit logging
- Performance metrics

---

## Архитектура и компоненты

### Модульная структура

**API Module**
- FastAPI endpoints
- JWT authentication
- Request validation
- Error handling

**Database Module**
- SQLAlchemy models
- Alembic migrations
- Repository pattern
- Async operations

**Processing Modules**
- Video download
- FFmpeg processing
- Transcription (Fireworks AI)
- Topic extraction (DeepSeek)
- Subtitle generation
- Upload (YouTube, VK)

**Background Tasks**
- Celery integration
- Progress tracking
- Automatic retry
- Result storage

### Ключевые паттерны

**ServiceContext**
- Централизованный контекст выполнения
- Передача session + user_id
- Lazy-loading ConfigHelper

**ConfigHelper**
- Унифицированный доступ к credentials
- Автоматическое дешифрование
- Platform-specific методы

**Factory Pattern**
- TranscriptionServiceFactory
- UploaderFactory
- Создание сервисов с правильными credentials

**Repository Pattern**
- Изоляция доступа к данным
- Автоматическая фильтрация по user_id
- Асинхронные операции

Подробнее: [Техническая документация](docs/TECHNICAL.md)

---

## Статусы обработки

| Статус | Описание |
|--------|----------|
| INITIALIZED | Инициализировано |
| DOWNLOADING | Загрузка из источника |
| DOWNLOADED | Загружено |
| PROCESSING | Обработка видео |
| PROCESSED | Обработано |
| TRANSCRIBING | Транскрибация |
| TRANSCRIBED | Транскрибировано |
| UPLOADING | Публикация |
| UPLOADED | Опубликовано |
| FAILED | Ошибка |
| SKIPPED | Пропущено |
| EXPIRED | Устарело |

---

## Документация

### Основные документы

**[План ВКР](docs/PLAN.md)**
- Цели и задачи проекта
- Исследовательская часть
- Планируемое развитие

**[История проекта](docs/WHAT_WAS_DONE.md)**
- Детальная хронология всех изменений
- Реализованные функции
- Технические детали

**[Архитектурные решения](docs/ADR.md)**
- Ключевые технические решения
- Обоснования выбора технологий
- Lessons learned

**[Техническая документация](docs/TECHNICAL.md)**
- Архитектура системы
- REST API (49 endpoints)
- Настройка БД и миграции
- Модули обработки
- Безопасность

**[Руководство по развертыванию](docs/DEPLOYMENT.md)**
- Установка и настройка
- Production deployment
- Мониторинг
- Troubleshooting

---

## Последние обновления

### v2.1 (2026-01-05) - Async Processing

**Новое:**
- Асинхронная обработка задач (Celery + Redis)
- Progress tracking в реальном времени
- Automatic retry на ошибках
- Horizontal scaling support
- Flower для мониторинга задач

**Улучшения:**
- API response time < 50ms
- Unlimited concurrent users
- Improved error handling
- Better logging

### v2.0 (2025-01-02) - Production-Ready

**Новое:**
- REST API (49 endpoints)
- JWT аутентификация
- Multi-tenancy архитектура
- Система шаблонов
- Роли и права доступа
- Квоты и rate limiting

**База данных:**
- 4 новые таблицы (templates, sources, presets, configs)
- Template Matcher
- UserPathManager
- Credential encryption

### v0.7.3 - Core Features

**Функциональность:**
- Асинхронный TokenManager для Zoom
- Fireworks ASR с валидацией
- Извлечение тем через DeepSeek
- Генерация субтитров (SRT, VTT)
- Нормализованные модели БД
- Multi-source/multi-output support

Полная история: [История проекта](docs/WHAT_WAS_DONE.md)

---

## Лицензия

См. файл [LICENSE](LICENSE)

---

## Контакты и поддержка

**Документация:** [docs/](docs/)
**API Docs:** http://localhost:8000/docs
**Issues:** Создавайте issue в репозитории

---

**Версия:** v2.1  
**Статус:** Production-Ready  
**Последнее обновление:** 5 января 2026
