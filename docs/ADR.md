# ADR: Architecture Decision Records

**Проект:** Zoom Publishing Platform  
**Версия:** 1.0  

---

## Содержание

1. [Обзор](#обзор)
2. [Контекст и мотивация](#контекст-и-мотивация)
3. [Архитектурные решения](#архитектурные-решения)
4. [Схема базы данных](#схема-базы-данных)
5. [Иерархия конфигураций](#иерархия-конфигураций)
6. [Потоки данных](#потоки-данных)
7. [Существующая функциональность обработки](#существующая-функциональность-обработки)
8. [Безопасность и изоляция](#безопасность-и-изоляция)
9. [API спецификация](#api-спецификация)
10. [Технические детали реализации](#технические-детали-реализации)
11. [Обработка ошибок и надежность](#обработка-ошибок-и-надежность)
12. [Сравнение с альтернативными подходами](#сравнение-с-альтернативными-подходами)
13. [Архитектурный стиль](#архитектурный-стиль)
14. [Миграционная стратегия](#миграционная-стратегия)
15. [ADR-011: Очереди задач (будущее)](#adr-011-очереди-задач-будущее)
16. [ADR-012: Квоты и лимиты (MVP)](#adr-012-квоты-и-лимиты-mvp)
17. [ADR-013: Аудит (позже)](#adr-013-аудит-позже)
18. [ADR-014: Уведомления (позже)](#adr-014-уведомления-позже)
19. [ADR-015: FSM для надежной обработки](#adr-015-fsm-для-надежной-обработки)
20. [Следующие шаги](#следующие-шаги)

---

## Обзор

### Цель документа

Данный документ описывает архитектурные решения для трансформации Zoom Publishing Platform из `CLI`-приложения в multi-tenant `SaaS` платформу с `REST API`.

### Ключевые решения

**Архитектурные решения (планируемые для multi-tenancy):**
- **Multi-tenancy**: Shared Database с изоляцией через `user_id`
- **Аутентификация**: `JWT` Tokens
- **Авторизация**: Роли (`admin`, `user`) + флаги разрешений
- **Конфигурации**: Иерархическая система (глобальный → пользовательский → шаблон)
- **Хранение данных**: `PostgreSQL` с `JSONB` для гибких конфигураций
- **Изоляция файлов**: Структура `media/user_{id}/`

**Существующая функциональность (реализована):**
- **Обработка видео**: FFmpeg для детекции тишины и обрезки (без перекодирования)
- **Транскрибация**: Fireworks Audio API (whisper-v3-turbo) с поддержкой больших файлов
- **Извлечение тем**: DeepSeek API для структурирования контента и генерации оглавления
- **Генерация субтитров**: SRT/VTT из транскрипций с форматированием
- **Загрузка на платформы**: YouTube (OAuth 2.0) и VK (Access Token) с управлением метаданными
- **Модульная архитектура**: Четкое разделение ответственности между модулями

---

## Контекст и мотивация

### Текущее состояние

Система представляет собой `CLI`-приложение для автоматизированной обработки видеоконтента:
- Загрузка записей из `Zoom API`
- Обработка видео (удаление тишины)
- Транскрибация через `Fireworks AI`
- Извлечение тем через `DeepSeek`
- Публикация на `YouTube`/`VK`

**Ограничения:**
- Все данные в единой БД без разделения
- Конфигурации в `JSON` файлах
- Нет `API` для интеграций
- Нет аутентификации/авторизации

### Бизнес-требования

1. **Multi-tenancy**: Каждый пользователь должен иметь изолированные данные
2. **Гибкость конфигурации**: Пользователи настраивают свои источники и выходы
3. **Автоматизация**: Шаблоны для автоматической обработки записей
4. **API-first**: `REST API` для интеграций и автоматизации
5. **Масштабируемость**: Поддержка роста числа пользователей

### Технические требования

- Сохранение существующей функциональности
- Обратная совместимость с `CLI` (опционально)
- Безопасное хранение credentials
- Производительность при росте нагрузки

---

## Архитектурные решения

### ADR-001: Модель Multi-Tenancy

**Решение:** Shared Database с изоляцией через `user_id` (`tenant ID`)

**Схема изоляции:**
```
┌─────────────────────────────────────────────────────────────┐
│              Multi-Tenancy Architecture                     │
└─────────────────────────────────────────────────────────────┘

                    ┌──────────────┐
                    │   User A     │
                    │  (user_id=1) │
                    └──────┬───────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
   ┌────▼─────┐      ┌─────▼──────┐    ┌─────▼──────┐
   │Recordings│      │ Templates  │    │Credentials │
   │user_id=1 │      │user_id=1   │    │user_id=1   │
   └──────────┘      └────────────┘    └────────────┘

                    ┌──────────────┐
                    │   User B     │
                    │  (user_id=2) │
                    └──────┬───────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
   ┌────▼─────┐      ┌─────▼──────┐    ┌─────▼──────┐
   │Recordings│      │ Templates  │    │Credentials │
   │user_id=2 │      │user_id=2   │    │user_id=2   │
   └──────────┘      └────────────┘    └────────────┘

        ┌────────────────────────────────────┐
        │   Shared `PostgreSQL` Database       │
        │   (Единая БД для всех пользователей│
        │    с фильтрацией по user_id)       │
        └────────────────────────────────────┘

Принцип изоляции:
- Все запросы к базе данных автоматически фильтруются по `user_id`
- Middleware извлекает `user_id` из `JWT` токена и добавляет его в контекст запроса
- Repository Layer гарантирует изоляцию данных на уровне доступа к БД
- Доступ к данным других пользователей невозможен благодаря фильтрации на всех уровнях архитектуры
```

**Обоснование:**

**Варианты:**
1. **Shared Database + Tenant ID** (выбрано)
2. Separate Databases
3. Separate Schemas (`PostgreSQL`)

**Преимущества выбранного решения:**
- Простота управления (одна БД, единые миграции)
- Эффективное использование ресурсов
- Легко масштабировать горизонтально
- Проще бэкапы и восстановление

**Риски и митигация:**
- **Риск утечки данных**: Всегда фильтровать по `user_id` во всех запросах
- **Производительность**: Индексы на `user_id` во всех таблицах
- **Сложность запросов**: Использовать `ORM` с автоматической фильтрацией

**Миграционная стратегия:**
Начать с Shared Database, в будущем возможна миграция на Separate Databases при необходимости.

---

### ADR-002: Аутентификация и авторизация

**Решение:** `JWT` Tokens для пользователей

**Обоснование:**

**Варианты:**
1. **`JWT` Tokens** (выбрано)
2. `API Keys`
3. `OAuth 2.0` / `OIDC`

**Преимущества:**
- Stateless архитектура
- Масштабируемость
- Подходит для `REST API`
- Возможность refresh tokens

**Структура авторизации:**

**Роли:**
- `admin` — полный доступ, управление пользователями, глобальные настройки
- `user` — доступ к своим данным согласно флагам разрешений

**Флаги разрешений:**
- `can_transcribe` — транскрибация
- `can_process_video` — обработка видео
- `can_upload` — загрузка на платформы
- `can_create_templates` — создание шаблонов
- `can_delete_recordings` — удаление записей
- `can_update_uploaded_videos` — обновление загруженных видео
- `can_manage_credentials` — управление credentials
- `can_export_data` — экспорт данных

**Лимиты пользователей:**
- `max_concurrent_processes` — максимум одновременных обработок
- `max_recordings_per_month` — квота записей в месяц
- `quota_disk_space_gb` — квота дискового пространства
- `max_file_size_mb` — максимальный размер файла
- `rate_limit_per_minute` — лимит запросов в минуту

---

### ADR-003: Хранение конфигураций

**Решение:** Иерархическая система конфигураций в БД (`JSONB`)

**Обоснование:**

**Варианты:**
1. **В БД (`JSONB`)** (выбрано)
2. В файлах (как сейчас)
3. Hybrid (БД + файлы)

**Преимущества:**
- Централизованное хранение
- Версионирование через БД
- Шифрование чувствительных данных
- Проще бэкапы
- Гибкость через `JSONB`

**Иерархия конфигураций:**

```
Глобальный базовый конфиг (base_configs WHERE user_id IS NULL)
  └─ Системные настройки (video_codec, model, topic_model)
  └─ Дефолтные пользовательские настройки

Пользовательский базовый конфиг (base_configs WHERE user_id = X)
  └─ Переопределяет глобальный
  └─ Пользовательские настройки по умолчанию

Шаблон записи (recording_templates)
  └─ Переопределяет пользовательский базовый
  └─ Специфичные настройки для типа записей

Запись (recordings)
  └─ Использует шаблон (если найден) или базовый конфиг
```

**Принцип слияния:**
При применении конфигурации к записи выполняется глубокое слияние (deep merge) с приоритетом: шаблон > пользовательский базовый > глобальный базовый. Слияние происходит на уровне вложенных словарей, что позволяет переопределять только отдельные параметры без полной замены конфигурации.

---

### ADR-004: Хранение credentials

**Решение:** Шифрование в БД через `pgcrypto`

**Обоснование:**

**Варианты:**
1. **`pgcrypto` (`PostgreSQL`)** (выбрано)
2. Application-level encryption (`Python`)
3. Внешний секрет-менеджер (`Vault`, `AWS Secrets Manager`)

**Преимущества:**
- Шифрование на уровне БД
- Простота использования
- Не требует дополнительной инфраструктуры

**Структура хранения:**

Таблица `user_credentials`:
- `encrypted_data` (`BYTEA`) — зашифрованные данные
- `metadata` (JSONB) — несекретные метаданные

**Типы credentials:**
- `zoom` — `Zoom API` (account_id, client_id, client_secret)
- `youtube` — `YouTube OAuth 2.0` (весь `JSON` bundle: client_secrets + token + scopes)
- `vk` — `VK API` (access_token, group_id)
- `yandex_disk` — `Yandex Disk API` (`OAuth` token)
- `fireworks` — `Fireworks AI API` (api_key)
- `deepseek` — `DeepSeek API` (api_key)

**Важно:** Для `YouTube` хранится весь `JSON` bundle как есть, так как `Google OAuth` требует именно такую структуру.

---

### ADR-005: Output Presets

**Решение:** Предустановленные аккаунты для вывода (только credentials, без настроек платформы)

**Обоснование:**

Пользователь создает preset (например, "YouTube Основной", "VK Группа 1"), который содержит только credentials. Настройки платформы (playlist_id, privacy, album_id и т.д.) задаются в шаблоне записи.

**Преимущества:**
- Переиспользование credentials в разных шаблонах
- Гибкость настройки для каждого шаблона
- Простота управления аккаунтами
- Разделение ответственности: preset = аккаунт, шаблон = настройки

**Структура:**
- Preset содержит: название, описание, ссылку на credential, метаданные
- В шаблоне выбирается preset и задаются настройки платформы
- Один preset на один credential (не дублируем)

---

### ADR-006: Input Sources

**Решение:** Настроенные источники данных с ручной синхронизацией

**Обоснование:**

Пользователь настраивает источники через таблицу `input_sources`, затем синхронизирует записи по кнопке "Sync".

**Типы источников:**
- `ZOOM` — `Zoom API` (credentials + настройки синхронизации)
- `YANDEX_DISK` — `Yandex Disk` (credentials + folder_path/folder_url, может быть открытая ссылка или через `API`)
- `LOCAL` — Локальные файлы (без credentials)

**Синхронизация:**
- Ручная синхронизация через `API` endpoint
- В будущем: автоматическая синхронизация по расписанию

---

### ADR-007: Шаблоны записей

**Решение:** Шаблоны с правилами сопоставления и настройками обработки

**Обоснование:**

Шаблон содержит:
- **Правила сопоставления** (matching_rules) — по названию, source_type, account
- **Настройки обработки** — переопределяют базовый конфиг
- **Настройки транскрибации** — переопределяют базовый конфиг
- **Метаданные публикации** — шаблоны названия/описания с переменными, настройки топиков
- **Output configs** — выбранные presets + настройки платформы

**Создание шаблона:**
- Из записи: если запись не нашла шаблон, создается draft-шаблон (`is_draft = true`)
- Пользователь донастраивает и сохраняет → `is_draft = false`

**Переменные в шаблонах:**
- `{original_title}` — оригинальное название
- `{topic}` — первая/главная тема
- `{topics_list}` — список топиков (форматированный)
- `{date}` — дата в формате DD.MM.YYYY
- `{duration}` — длительность (Xч Yм)
- `{source_name}` — название источника

---

### ADR-008: Изоляция файлов

**Решение:** Структура `media/user_{user_id}/`

**Обоснование:**

**Структура:**
```
media/
└── user_{user_id}/
    ├── video/
    │   ├── unprocessed/
    │   ├── processed/
    │   └── temp_processing/
    ├── processed_audio/
    ├── transcriptions/
    │   └── {recording_id}/
    └── thumbnails/
        └── *.png
```

**Преимущества:**
- Простота реализации
- Легко бэкапить по пользователю
- Легко удалять данные пользователя
- Понятная структура

**Будущее:**
Возможна миграция на `Object Storage` (`S3`-совместимое) для масштабирования.

---

## Схемы и диаграммы

### Общая архитектура системы

```
┌─────────────────────────────────────────────────────────────────┐
│                         Client Layer                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │   Web UI     │  │   Mobile App │  │   CLI Tool   │         │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘         │
│         │                 │                  │                 │
│         └─────────────────┼──────────────────┘                 │
│                           │                                    │
└───────────────────────────┼────────────────────────────────────┘
                            │ `HTTP`/`REST`
┌───────────────────────────▼────────────────────────────────────┐
│                      API Layer (`FastAPI`)                       │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │  Middleware Pipeline                                    │  │
│  │  CORS → Auth (`JWT`) → Rate Limiting → Request Handler   │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  Auth        │  │  Recordings  │  │  Templates   │       │
│  │  Endpoints   │  │  Endpoints   │  │  Endpoints   │       │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
│         │                 │                  │               │
│  ┌──────▼───────┐  ┌──────▼───────┐  ┌──────▼───────┐       │
│  │  Credentials │  │  Input       │  │  Output      │       │
│  │  Endpoints   │  │  Sources     │  │  Presets     │       │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
└─────────┼──────────────────┼──────────────────┼───────────────┘
          │                  │                  │
┌─────────▼──────────────────▼──────────────────▼───────────────┐
│                   Service Layer                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  AuthService │ RecordingService │ TemplateService       │ │
│  │  ConfigService │ SyncService │ ProcessingService        │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────┬─────────────────────────────────────────┘
                      │
┌─────────────────────▼─────────────────────────────────────────┐
│              Processing Modules (Существующие)                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  API Module  │  │ Download     │  │ Processing   │       │
│  │  (Zoom API)  │  │ Module       │  │ Module       │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ Transcription│  │ DeepSeek    │  │ Subtitle     │       │
│  │ Module       │  │ Module      │  │ Module       │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
│  ┌──────────────┐  ┌──────────────┐                         │
│  │ Upload       │  │ Pipeline     │                         │
│  │ Module       │  │ Manager      │                         │
│  └──────────────┘  └──────────────┘                         │
└─────────────────────┬─────────────────────────────────────────┘
                      │
┌─────────────────────▼─────────────────────────────────────────┐
│                  Repository Layer                             │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  UserRepo │ RecordingRepo │ TemplateRepo │ ConfigRepo  │ │
│  │  CredentialRepo │ PresetRepo │ SourceRepo              │ │
│  └─────────────────────────────────────────────────────────┘ │
└─────────────────────┬─────────────────────────────────────────┘
                      │
┌─────────────────────▼─────────────────────────────────────────┐
│              Infrastructure Layer                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │  `PostgreSQL`  │  │ File System  │  │  External    │       │
│  │  Database    │  │   (media/)   │  │  APIs        │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
│                                                               │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │   `Zoom API`   │  │  `YouTube API` │  │  `Fireworks`   │       │
│  │              │  │  `VK API`      │  │  `DeepSeek`    │       │
│  └──────────────┘  └──────────────┘  └──────────────┘       │
└───────────────────────────────────────────────────────────────┘
```

### Диаграмма компонентов

```
┌─────────────────────────────────────────────────────────────┐
│                    `FastAPI` Application                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────┐      ┌──────────────┐                   │
│  │   `API`        │──────│   Service    │                   │
│  │   Routes     │      │   Layer      │                   │
│  └──────────────┘      └──────┬───────┘                   │
│         │                     │                            │
│         │                     │                            │
│  ┌──────▼─────────────────────▼───────┐                   │
│  │        Repository Layer            │                   │
│  │  (Data Access Abstraction)         │                   │
│  └──────┬─────────────────────────────┘                   │
│         │                                                  │
└─────────┼──────────────────────────────────────────────────┘
          │
          │ `SQLAlchemy` ORM
          │
┌─────────▼──────────────────────────────────────────────────┐
│                  `PostgreSQL` Database                        │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐    │
│  │    users     │  │ recordings   │  │  templates   │    │
│  │ base_configs │  │credentials   │  │   presets    │    │
│  │input_sources │  │ thumbnails   │  │ matching_    │    │
│  │              │  │              │  │   rules      │    │
│  └──────────────┘  └──────────────┘  └──────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

---

## Схема базы данных

### Общая архитектура

Схемы, представленные ниже, описывают целевую архитектуру системы для multi-tenant SaaS платформы. Реализация будет выполняться поэтапно с сохранением обратной совместимости.

Система использует `PostgreSQL` с 11 основными таблицами:

**Multi-tenancy таблицы (новые):**
1. **users** — Пользователи, роли, права, лимиты
2. **base_configs** — Глобальный и пользовательские базовые конфиги
3. **user_credentials** — `API` ключи и учетные данные (зашифрованные)
4. **output_presets** — Предустановленные аккаунты для вывода
5. **input_sources** — Настроенные источники данных
6. **thumbnails** — Миниатюры
7. **recording_templates** — Шаблоны записей
8. **template_matching_rules** — Правила сопоставления шаблонов

**Таблицы записей (существующие, будут обновлены для multi-tenancy):**
9. **recordings** — Записи (планируется добавление: user_id, template_id, input_source_id)
10. **source_metadata** — Метаданные источника записи (1:1 с recordings)
11. **output_targets** — Целевые платформы (планируется добавление: preset_id, last_updated_at)

### Диаграмма связей (Entity Relationship Diagram)

```
┌─────────────────────────────────────────────────────────────┐
│                         USERS                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ id (PK)                                             │   │
│  │ email (UNIQUE)                                      │   │
│  │ password_hash                                       │   │
│  │ role, can_*, max_*, quota_*                        │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                            │
            ┌───────────────┼───────────────┬───────────────┐
            │               │               │               │
            │ 1             │ 1             │ 1             │ 1
            │               │               │               │
┌───────────▼───────┐ ┌─────▼───────────┐ ┌▼──────────────┐ ┌▼────────────┐
│  BASE_CONFIGS     │ │ USER_CREDENTIALS│ │OUTPUT_PRESETS │ │INPUT_SOURCES│
│  ┌─────────────┐  │ │ ┌─────────────┐ │ │┌────────────┐ │ │┌──────────┐ │
│  │ id (PK)     │  │ │ │ id (PK)     │ │ ││ id (PK)    │ │ ││ id (PK)  │ │
│  │ user_id(FK) │  │ │ │ user_id(FK) │ │ ││ user_id(FK)│ │ ││ user_id  │ │
│  │ *_config    │  │ │ │ type, key   │ │ ││ name, type │ │ ││ type,name│ │
│  │ (JSONB)     │  │ │ │ encrypted_  │ │ ││ cred_id(FK)│ │ ││ cred_id  │ │
│  └─────────────┘  │ │ │   data      │ │ │└────────────┘ │ ││(FK)      │ │
└───────────────────┘ │ │ metadata    │ │ └───────────────┘ │ └──────────┘ │
                      │ └─────────────┘ │                   │              │
                      └─────────────────┘                   │              │
                              │                             │              │
                              │ 1                           │              │
                              │                             │              │
                              │                    ┌────────┘              │
                              │                    │ N                     │
                              │                    │                       │
                      ┌───────▼───────────┐       │                       │
                      │ USER_CREDENTIALS  │◄──────┘                       │
                      │ (referenced by)   │                               │
                      └───────────────────┘                               │
                                                                            │
┌──────────────────────────────────────────────────────────────────────────┘
│                                   1
│                                   │
│                      ┌────────────┼────────────┐
│                      │            │            │
│                      │ N         │ N          │ N
│                      │            │            │
│            ┌─────────▼─────┐ ┌───▼─────────┐ ┌▼──────────────┐
│            │RECORDING_     │ │  THUMBNAILS │ │OUTPUT_PRESETS │
│            │TEMPLATES      │ │  ┌────────┐ │ │ (referenced)  │
│            │┌────────────┐ │ │  │ id(PK) │ │ └───────────────┘
│            ││ id (PK)    │ │ │  │user_id │ │
│            ││ user_id(FK)│ │ │  │name    │ │
│            ││ name, *_   │ │ │  │file_   │ │
│            ││ configs    │ │ │  │  path  │ │
│            │└────────────┘ │ │  └────────┘ │
│            └────────┬──────┘ └─────────────┘
│                     │ 1
│                     │
│                     │ N
│            ┌────────▼─────────────────┐
│            │ TEMPLATE_MATCHING_RULES  │
│            │ ┌──────────────────────┐ │
│            │ │ id (PK)              │ │
│            │ │ template_id (FK)     │ │
│            │ │ match_type, pattern  │ │
│            │ │ source_id (FK)       │ │
│            │ └──────────────────────┘ │
│            └──────────────────────────┘
│
└───────────────────────────────────────────────────────────────┐
                                                                │
┌───────────────────────────────────────────────────────────────┐
│                        RECORDINGS                             │
│  ┌─────────────────────────────────────────────────────┐     │
│  │ id (PK)                                             │     │
│  │ user_id (FK) ───────────────────────────────┐      │     │
│  │ template_id (FK) ──────┐                    │      │     │
│  │ input_source_id (FK)───┼──────────────────┐ │      │     │
│  │ display_name, status   │                  │ │      │     │
│  │ file_paths, metadata   │                  │ │      │     │
│  └────────────────────────┼──────────────────┼─┼──────┘     │
└───────────────────────────┼──────────────────┼─┼────────────┘
                            │                  │ │
                            │ 1                │ │ 1
                            │                  │ │
                            │                  │ │
                    ┌───────▼─────────┐  ┌─────▼─▼──────────┐
                    │ OUTPUT_TARGETS  │  │  SOURCE_METADATA │
                    │ ┌─────────────┐ │  │  ┌─────────────┐ │
                    │ │ id (PK)     │ │  │  │ id (PK)     │ │
                    │ │ recording_  │ │  │  │ recording_  │ │
                    │ │   id (FK)   │ │  │  │   id (FK)   │ │
                    │ │ preset_id   │ │  │  │ source_type │ │
                    │ │ target_type │ │  │  │ source_key  │ │
                    │ │ status      │ │  │  │ metadata    │ │
                    │ │ target_meta │ │  │  └─────────────┘ │
                    │ │ updated_at  │ │  │                  │
                    │ └─────────────┘ │  │                  │
                    └─────────────────┘  └──────────────────┘
                              │
                              │ N
                              │
                    ┌─────────▼──────────┐
                    │ OUTPUT_PRESETS     │
                    │ (referenced by     │
                    │  output_targets)   │
                    └────────────────────┘
```

### Визуализация связей таблиц

```
                    ┌─────────┐
                    │  USERS  │
                    └────┬────┘
                         │
        ┌────────────────┼────────────────┐
        │                │                │
   ┌────▼────┐     ┌─────▼─────┐    ┌────▼─────┐
   │ BASE_   │     │ USER_     │    │ INPUT_   │
   │ CONFIGS │     │ CREDENTIALS    │ SOURCES  │
   └─────────┘     └─────┬─────┘    └────┬─────┘
                         │                │
                    ┌────┴─────┐          │
                    │ OUTPUT_  │          │
                    │ PRESETS  │          │
                    └────┬─────┘          │
                         │                │
                         │                │
        ┌────────────────┘                │
        │                                 │
   ┌────▼───────────┐                    │
   │ RECORDING_     │                    │
   │ TEMPLATES      │                    │
   └────┬───────────┘                    │
        │                                │
        │                                │
   ┌────▼────────────────────┐           │
   │ TEMPLATE_MATCHING_RULES │           │
   └─────────────────────────┘           │
                                         │
                              ┌──────────▼─────────┐
                              │    RECORDINGS      │
                              └──────────┬─────────┘
                                         │
                    ┌────────────────────┼────────────────────┐
                    │                    │                    │
              ┌─────▼──────┐      ┌─────▼──────┐      ┌─────▼──────┐
              │ SOURCE_    │      │ OUTPUT_    │      │ THUMBNAILS │
              │ METADATA   │      │ TARGETS    │      │            │
              └────────────┘      └────────────┘      └────────────┘
```

### Полные SQL схемы таблиц

#### 1. `users` — Пользователи

```sql
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    
    -- Основная информация
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,  -- bcrypt hash
    name VARCHAR(255),
    
    -- Роль
    role VARCHAR(20) DEFAULT 'user' CHECK (role IN ('admin', 'user')),
    
    -- Флаги разрешений
    can_transcribe BOOLEAN DEFAULT TRUE,
    can_process_video BOOLEAN DEFAULT TRUE,
    can_upload BOOLEAN DEFAULT TRUE,
    can_create_templates BOOLEAN DEFAULT TRUE,
    can_delete_recordings BOOLEAN DEFAULT TRUE,
    can_update_uploaded_videos BOOLEAN DEFAULT TRUE,
    can_manage_credentials BOOLEAN DEFAULT TRUE,
    can_export_data BOOLEAN DEFAULT TRUE,
    
    -- Лимиты
    max_concurrent_processes INT DEFAULT 2,
    max_recordings_per_month INT DEFAULT NULL,  -- NULL = безлимит
    quota_disk_space_gb INT DEFAULT NULL,  -- NULL = безлимит
    max_file_size_mb INT DEFAULT 5000,
    rate_limit_per_minute INT DEFAULT 100,
    
    -- Метаданные
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last_login_at TIMESTAMP WITH TIME ZONE
);

CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_users_active ON users(is_active);
CREATE INDEX idx_users_role ON users(role);
```

#### 2. `base_configs` — Базовые конфиги

```sql
CREATE TABLE base_configs (
    id SERIAL PRIMARY KEY,
    
    -- Привязка (NULL = глобальный дефолт, user_id = пользовательский)
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    
    -- Системные настройки обработки (НЕ задаются пользователем)
    system_processing_config JSONB DEFAULT '{}',
    -- {
    --   "video_codec": "copy",
    --   "audio_codec": "copy",
    --   "video_bitrate": "original",
    --   "audio_bitrate": "original",
    --   "resolution": "original",
    --   "fps": 0,
    --   "output_format": "mp4"
    -- }
    
    -- Системные настройки транскрибации
    system_transcription_config JSONB DEFAULT '{}',
    -- {
    --   "model": "fireworks",
    --   "topic_model": "deepseek"
    -- }
    
    -- Пользовательские настройки обработки
    processing_config JSONB DEFAULT '{}',
    -- {
    --   "enable_processing": true,
    --   "audio_detection": true,
    --   "silence_threshold": -40.0,
    --   "min_silence_duration": 2.0,
    --   "padding_before": 5.0,
    --   "padding_after": 5.0
    -- }
    
    -- Пользовательские настройки транскрибации
    transcription_config JSONB DEFAULT '{}',
    -- {
    --   "enable_transcription": true,
    --   "language": "ru",
    --   "prompt": "",
    --   "temperature": 0.0,
    --   "enable_topics": true,
    --   "topic_mode": "long",
    --   "enable_subtitles": true,
    --   "enable_translation": false,
    --   "translation_language": "en"
    -- }
    
    -- Метаданные по умолчанию
    default_metadata_config JSONB DEFAULT '{}',
    -- {
    --   "title_template": "{original_title} | {topic} ({date})",
    --   "description_template": "",
    --   "default_thumbnail_path": null,
    --   "tags": [],
    --   "category": null
    -- }
    
    -- Выходы по умолчанию
    default_output_configs JSONB DEFAULT '[]',
    -- [
    --   {
    --     "target_type": "youtube",
    --     "enabled": false,
    --     "privacy": "unlisted",
    --     "default_language": "ru"
    --   }
    -- ]
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT unique_user_config UNIQUE (user_id)
);

CREATE INDEX idx_base_configs_user ON base_configs(user_id);
```

#### 3. `user_credentials` — API ключи и учетные данные

```sql
CREATE TABLE user_credentials (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Тип провайдера
    credential_type VARCHAR(50) NOT NULL,
    -- 'zoom', 'youtube', 'vk', 'yandex_disk', 'google_drive', 'fireworks', 'deepseek'
    
    -- Идентификатор (для Zoom - email, для других - название)
    credential_key VARCHAR(255) NOT NULL,
    -- Для Zoom: "user@example.com"
    -- Для других: может быть пустым или название аккаунта
    
    -- Зашифрованные данные
    encrypted_data BYTEA NOT NULL,
    -- Зашифрованный JSON (используется pgp_sym_encrypt/pgp_sym_decrypt)
    -- Для YouTube: весь bundle JSON (client_secrets + token + scopes)
    -- Для Zoom: {"account_id": "...", "client_id": "...", "client_secret": "..."}
    -- Для VK: {"access_token": "...", "group_id": 123}
    -- Для Fireworks/DeepSeek: {"api_key": "..."}
    
    -- Метаданные (не зашифрованные, для быстрого поиска)
    metadata JSONB DEFAULT '{}',
    -- {
    --   "account_id": "...",  -- для Zoom (не секретное)
    --   "description": "Основной аккаунт",
    --   "last_sync_at": "2025-01-10T12:00:00Z"
    -- }
    
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT unique_user_credential UNIQUE (user_id, credential_type, credential_key)
);

CREATE INDEX idx_credentials_user_type ON user_credentials(user_id, credential_type, is_active);

-- Для использования pgcrypto нужно установить расширение:
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

#### 4. `output_presets` — Предустановленные аккаунты для вывода

```sql
CREATE TABLE output_presets (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    name VARCHAR(255) NOT NULL,  -- "YouTube Основной", "VK Группа 1"
    description TEXT,
    
    -- Платформа
    target_type VARCHAR(50) NOT NULL,  -- YOUTUBE, VK, YANDEX_DISK, LOCAL, etc.
    
    -- Ссылка на credentials (только креды, без настроек!)
    credential_id INT NOT NULL REFERENCES user_credentials(id) ON DELETE CASCADE,
    
    -- Метаданные (опциональные)
    metadata JSONB DEFAULT '{}',
    -- {"notes": "Основной канал", "created_by": "admin"}
    
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT unique_user_preset_name UNIQUE (user_id, name)
);

CREATE INDEX idx_output_presets_user ON output_presets(user_id, target_type, is_active);
CREATE INDEX idx_output_presets_credential ON output_presets(credential_id);
```

#### 5. `input_sources` — Источники данных

```sql
CREATE TABLE input_sources (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    source_type VARCHAR(50) NOT NULL,  -- ZOOM, YANDEX_DISK, LOCAL
    name VARCHAR(255) NOT NULL,  -- "Zoom Основной", "Yandex Disk Лекции"
    
    -- Ссылка на credentials (для Zoom/Yandex Disk)
    credential_id INT REFERENCES user_credentials(id) ON DELETE CASCADE,
    
    -- Настройки источника (JSONB)
    source_settings JSONB DEFAULT '{}',
    -- Для Zoom:
    --   {
    --     "sync_automatically": false,
    --     "sync_schedule": null,  -- Cron expression для будущего
    --     "sync_last_run": null
    --   }
    -- Для Yandex Disk:
    --   {
    --     "folder_path": "/Videos/Lectures",
    --     "folder_url": "https://disk.yandex.ru/d/...",
    --     "use_api": true,  -- true = через API, false = открытая ссылка
    --     "sync_automatically": false
    --   }
    -- Для LOCAL: {}
    
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT unique_user_source_name UNIQUE (user_id, source_type, name)
);

CREATE INDEX idx_input_sources_user ON input_sources(user_id, source_type, is_active);
CREATE INDEX idx_input_sources_credential ON input_sources(credential_id);
```

#### 6. `thumbnails` — Миниатюры

```sql
CREATE TABLE thumbnails (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Название миниатюры (для идентификации)
    name VARCHAR(255) NOT NULL,
    
    -- Путь к файлу (относительно media/user_{id}/thumbnails/)
    file_path VARCHAR(1000) NOT NULL,
    -- Пример: "gen_models_base.png"
    -- Полный путь: media/user_1/thumbnails/gen_models_base.png
    
    -- Метаданные
    file_size INT,  -- в байтах
    mime_type VARCHAR(50) DEFAULT 'image/png',
    width INT,
    height INT,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT unique_user_thumbnail_name UNIQUE (user_id, name)
);

CREATE INDEX idx_thumbnails_user ON thumbnails(user_id);
```

#### 7. `recording_templates` — Шаблоны записей

```sql
CREATE TABLE recording_templates (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Основная информация
    name VARCHAR(255) NOT NULL,
    description TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    is_draft BOOLEAN DEFAULT FALSE,  -- Черновик (создан из записи, но не сохранен)
    priority INT DEFAULT 0,
    
    -- Настройки обработки (переопределяют базовый конфиг)
    processing_config JSONB DEFAULT '{}',
    -- {
    --   "enable_processing": true,
    --   "audio_detection": true,
    --   "silence_threshold": -40.0,
    --   "min_silence_duration": 2.0,
    --   "padding_before": 5.0,
    --   "padding_after": 5.0
    -- }
    
    -- Настройки транскрибации (переопределяют базовый конфиг)
    transcription_config JSONB DEFAULT '{}',
    -- {
    --   "enable_transcription": true,
    --   "language": "ru",
    --   "prompt": "",
    --   "temperature": 0.0,
    --   "enable_topics": true,
    --   "topic_mode": "long",
    --   "enable_subtitles": true,
    --   "enable_translation": false,
    --   "translation_language": "en"
    -- }
    
    -- Метаданные для публикации
    metadata_config JSONB DEFAULT '{}',
    -- {
    --   "title_template": "(Л) Генеративные модели [base] | {topic} ({date})",
    --   "description_template": "Лекция по генеративным моделям.\n\nТемы:\n{topics_list}",
    --   "thumbnail_path": "thumbnails/gen_models_base.png",
    --   "tags": ["лекция", "ml"],
    --   "category": "Education",
    --   "topics_display": {
    --     "enabled": true,
    --     "max_count": 10,
    --     "min_length": 5,
    --     "max_length": 100,
    --     "display_location": "description",
    --     "format": "numbered_list",
    --     "separator": "\n",
    --     "prefix": "Темы:",
    --     "include_timestamps": false
    --   }
    -- }
    
    -- Настройки вывода (массив preset'ов с настройками платформы)
    output_configs JSONB DEFAULT '[]',
    -- [
    --   {
    --     "preset_id": 1,
    --     "enabled": true,
    --     "playlist_id": "PL...",
    --     "privacy": "unlisted",
    --     "default_language": "ru",
    --     "upload_captions": true,
    --     "category_id": "27"
    --   }
    -- ]
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT unique_user_template_name UNIQUE (user_id, name)
);

CREATE INDEX idx_templates_user_active ON recording_templates(user_id, is_active, is_draft, priority DESC);
```

#### 8. `template_matching_rules` — Правила сопоставления

```sql
CREATE TABLE template_matching_rules (
    id SERIAL PRIMARY KEY,
    template_id INT NOT NULL REFERENCES recording_templates(id) ON DELETE CASCADE,
    
    match_type VARCHAR(20) NOT NULL CHECK (match_type IN ('exact', 'regex', 'contains')),
    -- 'exact' - точное совпадение
    -- 'regex' - регулярное выражение (начинается с ^ и заканчивается $)
    -- 'contains' - содержит подстроку
    
    pattern VARCHAR(500) NOT NULL,
    
    -- Опциональные условия
    match_source_type VARCHAR(50),  -- ZOOM, LOCAL_FILE, etc.
    match_source_id INT REFERENCES input_sources(id),  -- Конкретный источник
    match_account VARCHAR(255),     -- Email Zoom аккаунта (для обратной совместимости)
    
    rule_priority INT DEFAULT 0,
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT unique_template_pattern UNIQUE (template_id, match_type, pattern)
);

CREATE INDEX idx_matching_rules_template ON template_matching_rules(template_id, rule_priority DESC);
CREATE INDEX idx_matching_rules_pattern ON template_matching_rules(pattern);
CREATE INDEX idx_matching_rules_source ON template_matching_rules(match_source_id);
```

#### 9. `recordings` — Записи (существующая таблица, будет обновлена)

```sql
CREATE TABLE recordings (
    id SERIAL PRIMARY KEY,
    
    -- Основные поля
    display_name VARCHAR(500) NOT NULL,
    start_time TIMESTAMP WITH TIME ZONE NOT NULL,
    duration INTEGER NOT NULL,  -- в минутах
    status VARCHAR(50) NOT NULL DEFAULT 'initialized',
    -- INITIALIZED, DOWNLOADING, DOWNLOADED, PROCESSING, PROCESSED,
    -- TRANSCRIBING, TRANSCRIBED, UPLOADING, UPLOADED, SKIPPED, EXPIRED
    -- При ошибке статус остается на текущем этапе, устанавливается failed=true
    is_mapped BOOLEAN DEFAULT FALSE,
    expire_at TIMESTAMP WITH TIME ZONE,
    
    -- Multi-tenancy (планируемые поля)
    user_id INT REFERENCES users(id) ON DELETE CASCADE,
    template_id INT REFERENCES recording_templates(id) ON DELETE SET NULL,
    input_source_id INT REFERENCES input_sources(id) ON DELETE SET NULL,
    base_config_snapshot JSONB,  -- Снимок базового конфига на момент создания
    
    -- Пути (относительно media/user_{user_id}/)
    local_video_path VARCHAR(1000),  -- Исходное видео
    processed_video_path VARCHAR(1000),  -- Обработанное видео
    processed_audio_dir VARCHAR(1000),  -- Директория с аудио
    transcription_dir VARCHAR(1000),  -- Директория с транскрипцией
    downloaded_at TIMESTAMP WITH TIME ZONE,
    
    -- Дополнительные поля
    video_file_size INTEGER,  -- Размер файла в байтах
    transcription_info JSONB,  -- Метаданные транскрипции
    -- {
    --   "model": "fireworks",
    --   "language": "ru",
    --   "segments_count": 450,
    --   "primary_audio": "path/to/audio.mp3"
    -- }
    topic_timestamps JSONB,  -- Темы с таймкодами
    -- [
    --   {
    --     "topic": "Нейронные сети",
    --     "start": 120,  -- секунды
    --     "end": 1800
    --   }
    -- ]
    main_topics JSONB,  -- Основные темы
    -- ["Нейронные сети", "Обратное распространение ошибки"]
    
    -- Временные метки
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX idx_recordings_user ON recordings(user_id);
CREATE INDEX idx_recordings_template ON recordings(template_id);
CREATE INDEX idx_recordings_input_source ON recordings(input_source_id);
CREATE INDEX idx_recordings_status ON recordings(status);
CREATE INDEX idx_recordings_start_time ON recordings(start_time);
CREATE INDEX idx_recordings_user_status ON recordings(user_id, status);
```

#### 10. `source_metadata` — Метаданные источника (существующая таблица)

```sql
CREATE TABLE source_metadata (
    id SERIAL PRIMARY KEY,
    recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    
    source_type VARCHAR(50) NOT NULL,
    -- ZOOM, LOCAL_FILE, YOUTUBE, VK, HTTP_LINK, YANDEX_DISK_API
    
    source_key VARCHAR(1000) NOT NULL,
    -- Уникальный ключ источника (например, meeting_uuid для Zoom)
    
    metadata JSONB,
    -- Сырые данные от источника
    -- Для Zoom: полный ответ API (zoom_api_response, zoom_api_details)
    -- Для других: специфичные метаданные
    
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT unique_source_per_recording UNIQUE (source_type, source_key, recording_id)
);

CREATE INDEX idx_source_metadata_recording ON source_metadata(recording_id);
CREATE INDEX idx_source_metadata_type_key ON source_metadata(source_type, source_key);
```

#### 11. `output_targets` — Целевые платформы (существующая таблица, будет обновлена)

```sql
CREATE TABLE output_targets (
    id SERIAL PRIMARY KEY,
    recording_id INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    
    target_type VARCHAR(50) NOT NULL,
    -- YOUTUBE, VK, YANDEX_DISK, LOCAL, WEBHOOK, GDRIVE
    
    status VARCHAR(50) NOT NULL DEFAULT 'not_uploaded',
    -- NOT_UPLOADED, UPLOADING, UPLOADED, FAILED
    -- При ошибке во время загрузки: статус остается UPLOADING, failed=true
    -- После исчерпания всех retry: статус FAILED, failed=true
    
    -- Multi-tenancy (планируемые поля)
    preset_id INT REFERENCES output_presets(id) ON DELETE SET NULL,
    last_updated_at TIMESTAMP WITH TIME ZONE,  -- Время последнего обновления через API
    
    target_meta JSONB,
    -- Метаданные платформы
    -- {
    --   "target_link": "https://youtube.com/watch?v=abc123",
    --   "video_id": "abc123",
    --   "playlist_id": "PL...",
    --   "album_id": "46",
    --   "privacy": "unlisted"
    -- }
    
    uploaded_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    CONSTRAINT unique_target_per_recording UNIQUE (recording_id, target_type)
);

CREATE INDEX idx_output_targets_recording ON output_targets(recording_id);
CREATE INDEX idx_output_targets_preset ON output_targets(preset_id);
CREATE INDEX idx_output_targets_status ON output_targets(status);
CREATE INDEX idx_output_targets_updated ON output_targets(last_updated_at);
```

### Описание таблиц

#### users
Хранит информацию о пользователях, их роли, флаги разрешений и лимиты.

**Ключевые поля:**
- `role` — роль (admin, user)
- Флаги разрешений (`can_transcribe`, `can_process_video`, и т.д.)
- Лимиты (`max_concurrent_processes`, `quota_disk_space_gb`, и т.д.)

#### base_configs
Хранит базовые конфигурации: глобальный (user_id = NULL) и пользовательские.

**Структура JSONB полей:**
- `system_processing_config` — системные настройки обработки (не задаются пользователем)
- `system_transcription_config` — системные настройки транскрибации
- `processing_config` — пользовательские настройки обработки
- `transcription_config` — пользовательские настройки транскрибации
- `default_metadata_config` — метаданные по умолчанию
- `default_output_configs` — выходы по умолчанию

#### user_credentials
Хранит зашифрованные учетные данные для различных провайдеров.

**Ключевые поля:**
- `credential_type` — тип провайдера (zoom, youtube, vk, и т.д.)
- `encrypted_data` — зашифрованные данные (`BYTEA`)
- `metadata` — несекретные метаданные (JSONB)

#### output_presets
Предустановленные аккаунты для вывода (только credentials, без настроек платформы).

**Ключевые поля:**
- `target_type` — тип платформы (YOUTUBE, VK, YANDEX_DISK, и т.д.)
- `credential_id` — ссылка на user_credentials

#### input_sources
Настроенные источники данных (Zoom аккаунты, Yandex Disk папки, Local).

**Ключевые поля:**
- `source_type` — тип источника (ZOOM, YANDEX_DISK, LOCAL)
- `credential_id` — ссылка на user_credentials (для Zoom/Yandex Disk)
- `source_settings` — настройки источника (JSONB)

#### recording_templates
Шаблоны записей с настройками обработки, транскрибации и публикации.

**Ключевые поля:**
- `is_draft` — черновик (создан из записи, но не сохранен)
- `processing_config` — настройки обработки (JSONB)
- `transcription_config` — настройки транскрибации (JSONB)
- `metadata_config` — метаданные публикации (JSONB, включает `topics_display`)
- `output_configs` — массив preset'ов с настройками платформы (JSONB)

#### template_matching_rules
Правила сопоставления записей шаблонам.

**Ключевые поля:**
- `match_type` — тип сопоставления (exact, regex, contains)
- `pattern` — паттерн для сопоставления
- `match_source_type` — ограничение по типу источника
- `match_source_id` — ограничение по конкретному источнику
- `rule_priority` — приоритет правила

#### recordings
Основная таблица записей видео. Хранит метаданные, статусы обработки, пути к файлам и результаты транскрибации.

**Ключевые поля:**
- `display_name` — название записи
- `status` — статус обработки (INITIALIZED → DOWNLOADED → PROCESSED → TRANSCRIBED → UPLOADED)
- `failed` — флаг ошибки (true если текущий этап завершился с ошибкой, см. ADR-015)
- `failed_at` — время последнего сбоя
- `failed_reason` — сообщение об ошибке
- `retry_count` — количество попыток retry (0-2)
- `user_id` — владелец записи (multi-tenancy, планируется)
- `template_id` — примененный шаблон (если найден, планируется)
- `input_source_id` — источник данных (планируется)
- `local_video_path` — путь к исходному видео
- `processed_video_path` — путь к обработанному видео
- `transcription_dir` — директория с транскрипцией
- `topic_timestamps` — темы с таймкодами (JSONB)
- `main_topics` — основные темы (JSONB)

#### source_metadata
Метаданные источника записи (1:1 с recordings). Хранит сырые данные от источника (Zoom API, Yandex Disk и т.д.).

**Ключевые поля:**
- `source_type` — тип источника (ZOOM, LOCAL_FILE, YOUTUBE, VK, HTTP_LINK, YANDEX_DISK_API)
- `source_key` — уникальный ключ источника (например, meeting_uuid для Zoom)
- `metadata` — сырые данные от источника (JSONB)

#### output_targets
Целевые платформы для публикации (1:N с recordings). Хранит статусы загрузки и метаданные для каждой платформы.

**Ключевые поля:**
- `target_type` — тип платформы (YOUTUBE, VK, YANDEX_DISK, LOCAL, WEBHOOK, GDRIVE)
- `status` — статус загрузки (NOT_UPLOADED, UPLOADING, UPLOADED, FAILED)
- `failed` — флаг ошибки (true если загрузка завершилась с ошибкой, см. ADR-015)
- `failed_at` — время последнего сбоя
- `failed_reason` — сообщение об ошибке
- `retry_count` — количество попыток retry (0-2)
- `preset_id` — использованный preset для загрузки (планируется)
- `target_meta` — метаданные платформы (ссылки, ID, настройки)
- `last_updated_at` — время последнего обновления через API (планируется)

---

## Иерархия конфигураций

### Принцип наследования

Конфигурации применяются в следующем порядке (приоритет снизу вверх):

```
┌─────────────────────────────────────────────────────────┐
│              Иерархия конфигураций                      │
└─────────────────────────────────────────────────────────┘

                    ┌──────────────────────┐
                    │  Template Config     │  ← Наивысший приоритет
                    │  (recording_         │     (переопределяет все)
                    │   templates)         │
                    └──────────┬───────────┘
                               │
                               │ deep_merge
                               │
                    ┌──────────▼───────────┐
                    │  User Base Config    │  ← Средний приоритет
                    │  (base_configs       │     (переопределяет глобальный)
                    │   WHERE user_id=X)   │
                    └──────────┬───────────┘
                               │
                               │ deep_merge
                               │
                    ┌──────────▼───────────┐
                    │  Global Base Config  │  ← Базовый уровень
                    │  (base_configs       │     (значения по умолчанию)
                    │   WHERE user_id NULL)│
                    └──────────────────────┘

                    ┌──────────────────────┐
                    │  Final Merged Config │  ← Результат слияния
                    │  (применяется к      │
                    │   записи)            │
                    └──────────────────────┘
```

### Схема слияния конфигураций

```
Пример слияния processing_config:

┌─────────────────────────────────┐
│ Global Base Config              │
│ {                               │
│   "enable_processing": true,    │
│   "audio_detection": true,      │
│   "silence_threshold": -40.0    │
│ }                               │
└──────────────┬──────────────────┘
               │
               │ deep_merge
               │
┌──────────────▼──────────────────┐
│ User Base Config                │
│ {                               │
│   "silence_threshold": -35.0,   │  ← переопределяет
│   "padding_before": 5.0         │  ← добавляет
│ }                               │
└──────────────┬──────────────────┘
               │
               │ deep_merge
               │
┌──────────────▼──────────────────┐
│ Template Config                 │
│ {                               │
│   "padding_before": 10.0        │  ← переопределяет
│ }                               │
└──────────────┬──────────────────┘
               │
               │
┌──────────────▼──────────────────┐
│ Final Merged Config             │
│ {                               │
│   "enable_processing": true,    │  ← из Global
│   "audio_detection": true,      │  ← из Global
│   "silence_threshold": -35.0,   │  ← из User (переопределено)
│   "padding_before": 10.0        │  ← из Template (переопределено)
│ }                               │
└─────────────────────────────────┘
```

### Алгоритм применения

1. Загружается глобальный базовый конфиг
2. Загружается пользовательский базовый конфиг (если есть)
3. Ищется подходящий шаблон для записи
4. Выполняется глубокое слияние (deep merge) конфигураций
5. Применяется итоговая конфигурация к записи

### Пример слияния

**Глобальный базовый:**
```json
{
  "processing_config": {
    "enable_processing": true,
    "audio_detection": true,
    "silence_threshold": -40.0
  }
}
```

**Пользовательский базовый:**
```json
{
  "processing_config": {
    "silence_threshold": -35.0,
    "padding_before": 5.0
  }
}
```

**Шаблон:**
```json
{
  "processing_config": {
    "padding_before": 10.0
  }
}
```

**Результат:**
```json
{
  "processing_config": {
    "enable_processing": true,
    "audio_detection": true,
    "silence_threshold": -35.0,  // из пользовательского
    "padding_before": 10.0       // из шаблона
  }
}
```

---

## Потоки данных

### Поток обработки записи

```
┌─────────────────────────────────────────────────────────────────┐
│                    SYNCHRONIZATION PHASE                        │
└─────────────────────────────────────────────────────────────────┘
                            │
              ┌─────────────▼─────────────┐
              │  Sync Input Source        │
              │  (Zoom/Yandex Disk/Local) │
              └─────────────┬─────────────┘
                            │
              ┌─────────────▼─────────────┐
              │  Create Recording Record  │
              │  user_id, input_source_id │
              │  status = INITIALIZED     │
              └─────────────┬─────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                    TEMPLATE MATCHING PHASE                      │
└───────────────────────────┬─────────────────────────────────────┘
                            │
              ┌─────────────▼─────────────┐
              │  Find Template            │
              │  (check matching_rules)   │
              └─────┬───────────────┬─────┘
                    │               │
          ┌─────────▼────┐  ┌──────▼──────────┐
          │ Template     │  │ No Template     │
          │ Found        │  │ Found           │
          └─────┬────────┘  └──────┬──────────┘
                │                  │
                │          ┌───────▼──────────┐
                │          │ Create Draft     │
                │          │ Template         │
                │          │ Use Base Config  │
                │          └───────┬──────────┘
                │                  │
┌───────────────┴──────────────────▼─────────────────────────────┐
│                 CONFIGURATION MERGE PHASE                      │
└───────────────┬──────────────────┬─────────────────────────────┘
                │                  │
      ┌─────────▼────────┐ ┌───────▼────────┐
      │ Global Base      │ │ User Base      │
      │ Config           │ │ Config         │
      └─────────┬────────┘ └───────┬────────┘
                │                  │
                └────────┬─────────┘
                         │
                ┌────────▼────────┐
                │ Template Config │
                │ (if exists)     │
                └────────┬────────┘
                         │
                ┌────────▼────────┐
                │ Merged Config   │
                │ (Final)         │
                └────────┬────────┘
                         │
┌────────────────────────▼───────────────────────────────────────┐
│                    PROCESSING PHASE                            │
└────────────────────────┬───────────────────────────────────────┘
                         │
         ┌───────────────▼───────────────┐
         │  Download Video               │
         │  (if needed)                  │
         │  status = DOWNLOADING         │
         └───────────────┬───────────────┘
                         │
         ┌───────────────▼───────────────┐
         │  Process Video                │
         │  (if enable_processing)       │
         │  status = PROCESSING          │
         └───────────────┬───────────────┘
                         │
         ┌───────────────▼───────────────┐
         │  Transcribe Audio             │
         │  (if enable_transcription)    │
         │  status = TRANSCRIBING        │
         └───────────────┬───────────────┘
                         │
         ┌───────────────▼───────────────┐
         │  Extract Topics               │
         │  (if enable_topics)           │
         └───────────────┬───────────────┘
                         │
         ┌───────────────▼───────────────┐
         │  Generate Subtitles           │
         │  (if enable_subtitles)        │
         └───────────────┬───────────────┘
                         │
┌────────────────────────▼───────────────────────────────────────┐
│                    PUBLICATION PHASE                           │
└────────────────────────┬───────────────────────────────────────┘
                         │
         ┌───────────────▼───────────────┐
         │  Format Metadata              │
         │  (title, description)         │
         │  with variables               │
         └───────────────┬───────────────┘
                         │
         ┌───────────────▼───────────────┐
         │  Get Output Presets           │
         │  (from template config)       │
         └───────────────┬───────────────┘
                         │
         ┌───────────────▼───────────────┐
         │  Decrypt Credentials          │
         │  (from presets)               │
         └───────────────┬───────────────┘
                         │
         ┌───────────────▼───────────────┐
         │  Upload to Platforms          │
         │  (YouTube, VK, etc.)          │
         │  status = UPLOADING           │
         └───────────────┬───────────────┘
                         │
         ┌───────────────▼───────────────┐
         │  Save Output Targets          │
         │  status = UPLOADED            │
         └───────────────────────────────┘
```

### Поток создания шаблона из записи

```
1. Запись не нашла шаблон
   └─ Создается draft-шаблон (is_draft = true)
   └─ Копируются данные записи (название, source_type)
   └─ Создается matching_rule (точное совпадение)

2. Пользователь донастраивает
   └─ Редактирует настройки обработки
   └─ Редактирует настройки транскрибации
   └─ Настраивает метаданные и output configs
   └─ Добавляет/редактирует matching_rules

3. Сохранение
   └─ is_draft = false
   └─ Шаблон становится активным
   └─ Будущие записи будут использовать этот шаблон
```

### Поток обновления загруженного видео

```
1. Пользователь запрашивает обновление
   └─ `POST /api/v1/recordings/{id}/update-video`
   └─ Передает обновления (название, описание, тэги, и т.д.)

2. Проверка прав
   └─ can_update_uploaded_videos = true

3. Обновление на платформах
   └─ Для каждого output_target с status = UPLOADED
   └─ Получение preset'а
   └─ Расшифровка credentials
   └─ Обновление через `API` платформы

4. Обновление БД
   └─ last_updated_at = NOW()
   └─ Обновление метаданных в output_targets.target_meta
```

---

## Существующая функциональность обработки

### ADR-009: Архитектура обработки видео

**Решение:** Модульная архитектура с четким разделением ответственности

Система построена на модульной архитектуре, где каждый модуль отвечает за конкретный этап обработки:

```
┌─────────────────────────────────────────────────────────┐
│                    Pipeline Manager                      │
│              (Координация всего процесса)                │
└─────────────────────────────────────────────────────────┘
         │         │         │         │         │
         ▼         ▼         ▼         ▼         ▼
    ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
    │  API   │ │Download│ │Process │ │Transcr.│ │ Upload │
    │ Module │ │ Module │ │ Module │ │Module  │ │ Module │
    └────────┘ └────────┘ └────────┘ └────────┘ └────────┘
```

### Модули системы

#### API Module (`api/`)
**Ответственность:** Работа с внешними API (Zoom, YouTube, VK)

**Функциональность:**
- Работа с Zoom API через OAuth 2.0
- Получение списка записей с метаданными
- Поддержка нескольких Zoom аккаунтов
- **TokenManager** — централизованное управление токенами:
  - Кэширование и автоматическое обновление
  - Защита от одновременных запросов
  - Автоматические повторные попытки при ошибках

**Технические детали:**
- Асинхронные HTTP запросы через `httpx`
- Обработка OAuth 2.0 flow для Zoom
- Фильтрация записей по длительности (>30 минут) и размеру (>40 МБ)

#### Download Module (`video_download_module/`)
**Ответственность:** Загрузка видео файлов из источников

**Функциональность:**
- Многопоточная загрузка видео файлов
- Отслеживание прогресса загрузки
- Обработка ошибок и повторные попытки
- Сохранение в `media/user_{id}/video/unprocessed/`

**Технические детали:**
- Использование `download_access_token` от Zoom API
- Многопоточность для параллельной загрузки
- Обновление статуса: `INITIALIZED → DOWNLOADING → DOWNLOADED`

#### Processing Module (`video_processing_module/`)
**Ответственность:** Обработка видео (удаление тишины, обрезка)

**Функциональность:**
- Детекция сегментов с отсутствием звука через FFmpeg
- Обрезка "тихих" частей из видео:
  - Удаление пустого начала
  - Удаление пустого конца
  - Удаление длинных пауз
- Использование FFmpeg для обработки (без перекодирования, кодек: copy)
- Экспорт обработанного видео в `media/user_{id}/video/processed/`
- Извлечение аудио в `media/user_{id}/processed_audio/`

**Технические детали:**

**AudioDetector:**
- Использует FFmpeg `silencedetect` фильтр
- Параметры:
  - `silence_threshold` — порог тишины в дБ (default: -40.0)
  - `min_silence_duration` — минимальная длительность тишины в секундах (default: 2.0)
- Определяет границы звука (первый и последний звук)

**VideoProcessor:**
- Обрезка видео через FFmpeg:
  - `-ss` и `-t` для обрезки по времени
  - `-c:v copy` и `-c:a copy` — без перекодирования (сохранение качества)
- Padding: `padding_before` и `padding_after` (default: 5.0 секунд)
- Статус: `DOWNLOADED → PROCESSING → PROCESSED`

**Сегментация:**
- Определение сегментов с звуком
- Удаление длинных пауз (настраивается)
- Сохранение качества исходного видео

#### Transcription Module (`transcription_module/`)
**Ответственность:** Координация транскрибации и извлечения тем

**Функциональность:**
- Координация транскрибации через Fireworks
- Обработка результатов транскрибации
- Извлечение тем через DeepSeek / Fireworks DeepSeek
- Сохранение транскрипций в структурированных папках
- Параллельная транскрибация с ограничением

**Технические детали:**
- Статус: `PROCESSED → TRANSCRIBING → TRANSCRIBED`
- Сохранение в `media/user_{id}/transcriptions/{recording_id}/`:
  - `words.txt` — слова с точными таймкодами (мс)
  - `segments.txt` — сегменты транскрипции
  - `segments_auto.txt` — автоматически сгенерированные сегменты
- Интеграция с Fireworks Module и DeepSeek Module

#### Fireworks Module (`fireworks_module/`)
**Ответственность:** Транскрибация через Fireworks Audio API

**Функциональность:**
- Транскрибация через Fireworks Audio API
  - 📖 [Документация](https://fireworks.ai/docs/api-reference/audio-transcriptions)
- Модель `whisper-v3-turbo`
- Поддержка больших файлов (без разбиения)
- Валидация конфигурации через Pydantic
- Автоопределение `base_url` по модели
- Поддержка прямых ответов SRT/VTT и verbose JSON

**Технические детали:**
- **Модель:** `whisper-v3-turbo`
- **Alignment model:** `mms_fa` (для точных таймкодов по словам)
- **Форматы ответа:**
  - `verbose_json` — полный JSON с words, segments, text
  - `srt` / `vtt` — прямые субтитры
- **Retry:** 3 попытки с экспоненциальной задержкой
- **Параллелизм:** максимум 2 одновременных транскрибации
- **Промпт:** динамический (с названием записи для контекста)

**Конфигурация:**
```json
{
  "model": "whisper-v3-turbo",
  "response_format": "verbose_json",
  "timestamp_granularities": ["word", "segment"],
  "language": "ru",
  "prompt": "Динамический промпт с названием записи"
}
```

#### DeepSeek Module (`deepseek_module/`)
**Ответственность:** Извлечение тем из транскрипции

**Функциональность:**
- Извлечение тем из транскрипции через DeepSeek API
- Определение перерывов (паузы ≥8 минут)
- Структурирование контента
- Генерация оглавления
- Поддержка двух провайдеров:
  - Прямой DeepSeek (`--topic-model deepseek`)
  - Fireworks DeepSeek (`--topic-model fireworks_deepseek`)

**Технические детали:**

**Режимы детализации (`--topic-mode`):**
- `short` — короткие темы (3-6 минут)
- `long` — длинные темы (6-12 минут)

**Алгоритм извлечения:**
1. Анализ полной транскрипции
2. Определение основных тем (1 тема, без жесткой обрезки до 3 слов)
3. Создание детализированных тем с таймкодами:
   - 3-6 слов на тему (обрезка только если >7 слов или >150 символов)
   - Максимальная длительность: ≤12 минут
   - Автоматическое разбиение длинных тем
4. Автоматическое определение перерывов (паузы ≥8 минут)
5. Добавление перерывов в список тем

**Динамический расчет количества тем:**
- По длительности записи
- По режиму (`short` / `long`)
- Минимум: 10 тем, максимум: 30 тем

**Провайдеры:**
- **DeepSeek:** OpenAI-compatible API через `AsyncOpenAI`
- **Fireworks DeepSeek:** Прямой HTTP-запрос через `httpx` (специфичные параметры)

#### Subtitle Module (`subtitle_module/`)
**Ответственность:** Генерация субтитров из транскрипций

**Функциональность:**
- Генерация субтитров SRT/VTT из транскрипций
- Чтение из `words.txt` или `segments.txt`
- Форматирование строк (ограничение по длине и количеству строк)
- Команда `python main.py subtitles --format srt,vtt`
- Загрузка субтитров на YouTube (VK пока без upload captions)

**Технические детали:**
- Форматирование строк:
  - Ограничение по длине строки
  - Ограничение по количеству строк на субтитр
  - Разбиение длинных строк
- Сохранение в `transcription_dir/subtitles.srt` и `subtitles.vtt`
- Таймкоды с миллисекундами

#### Upload Module (`video_upload_module/`)
**Ответственность:** Загрузка на платформы (YouTube, VK)

**Функциональность:**
- Загрузка на YouTube и VK
- Управление плейлистами и альбомами
- Обработка миниатюр
- Форматирование описаний с таймкодами
- Загрузка субтитров на YouTube (VTT/SRT)
- Обновление загруженных видео через API

**Технические детали:**

**YouTube Upload:**
- OAuth 2.0 аутентификация
- Загрузка видео с указанием языка (RU):
  - `defaultLanguage`: язык метаданных видео
  - `defaultAudioLanguage`: язык аудиодорожки
- Управление плейлистами
- Установка миниатюры
- Настройка приватности
- Загрузка субтитров (VTT/SRT)
- Обновление описания через API

**VK Upload:**
- Access Token аутентификация
- Загрузка видео
- Добавление в альбом
- Установка миниатюры
- Настройки приватности
- Обновление описания

**Форматирование описания:**
- Раздел "🔹 Темы лекции:" с таймкодами
- Формат: `HH:MM:SS — Название темы`
- Автоматическое добавление перерывов (без дубликатов)
- Лимит: 5000 символов для всех платформ
- Служебная информация (дата публикации, P.S.)

**Статусы:**
- `TRANSCRIBED → UPLOADING → UPLOADED`
- Для каждой платформы отдельно в `output_targets`

### Полный пайплайн обработки

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           НАЧАЛО: Zoom Запись                                │
│                    (Видео файл в облаке Zoom)                                │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  ЭТАП 1: СИНХРОНИЗАЦИЯ (sync)                                               │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ 1. Запрос к Zoom API (OAuth 2.0)                                    │  │
│  │ 2. Получение списка записей с метаданными                            │  │
│  │ 3. Фильтрация:                                                       │  │
│  │    • Длительность > 30 минут                                         │  │
│  │    • Размер файла > 40 МБ                                            │  │
│  │ 4. Сохранение метаданных в PostgreSQL                               │  │
│  │ 5. Проверка маппинга названий (TitleMapper)                          │  │
│  │ 6. Статус: INITIALIZED → DOWNLOADING                                 │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  ЭТАП 2: ЗАГРУЗКА (download)                                                 │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ 1. Многопоточное скачивание видео файлов из Zoom                    │  │
│  │ 2. Отслеживание прогресса загрузки                                  │  │
│  │ 3. Сохранение в: video/unprocessed/                                 │  │
│  │ 4. Обновление путей в БД                                            │  │
│  │ 5. Статус: DOWNLOADING → DOWNLOADED                                 │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  ЭТАП 3: ОБРАБОТКА ВИДЕО (process)                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ 1. Анализ аудиодорожки (FFmpeg)                                    │  │
│  │ 2. Детекция сегментов с отсутствием звука:                         │  │
│  │    • Порог тишины (silence_threshold)                               │  │
│  │    • Минимальная длительность тишины                                │  │
│  │ 3. Обрезка "тихих" частей:                                          │  │
│  │    • Удаление пустого начала                                        │  │
│  │    • Удаление пустого конца                                         │  │
│  │    • Удаление длинных пауз                                          │  │
│  │ 4. Экспорт обработанного видео:                                      │  │
│  │    • Сохранение в: video/processed/                                 │  │
│  │    • Извлечение аудио: processed_audio/                              │  │
│  │ 5. Статус: PROCESSING → PROCESSED                                   │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  ЭТАП 4: ТРАНСКРИБАЦИЯ (transcribe)                                         │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ 4.1. Подготовка аудио                                                │  │
│  │    • Fireworks поддерживает большие файлы без разбиения             │  │
│  │                                                                      │  │
│  │ 4.2. Транскрибация через Fireworks                                  │  │
│  │    • whisper-v3-turbo                                                │  │
│  │    • alignment_model: mms_fa                                         │  │
│  │    • Динамический промпт                                             │  │
│  │    • Параллельная обработка (макс. 2 одновременно)                  │  │
│  │    • Результат: {text, segments[], words[], language}               │  │
│  │                                                                      │  │
│  │ 4.3. Извлечение тем через DeepSeek API                               │  │
│  │    • Анализ полной транскрипции                                     │  │
│  │    • Определение основных тем (1 тема)                               │  │
│  │    • Создание детализированных тем с таймкодами:                    │  │
│  │      - 3-6 слов на тему (обрезка только если >7 слов)               │  │
│  │      - Максимальная длительность: ≤12 минут                         │  │
│  │      - Автоматическое разбиение длинных тем                         │  │
│  │    • Автоматическое определение перерывов (паузы ≥8 минут)          │  │
│  │    • Добавление перерывов в список тем                              │  │
│  │                                                                      │  │
│  │ 4.4. Сохранение результатов                                         │  │
│  │    • Транскрипция: transcription_dir (words/segments/subtitles)   │  │
│  │    • Обновление БД с путями и метаданными                           │  │
│  │    • Статус: PROCESSED → TRANSCRIBING → TRANSCRIBED               │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  ЭТАП 4.5: СУБТИТРЫ (subtitles)                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ 1. Чтение transcription_dir (words.txt или segments.txt)            │  │
│  │ 2. Генерация SRT/VTT (разбиение строк, таймкоды с мс)                │  │
│  │ 3. Сохранение в transcription_dir/subtitles.(srt|vtt)               │  │
│  │ 4. Опция загрузки на платформы: upload --upload-captions (YouTube)  │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  ЭТАП 5: ЗАГРУЗКА НА ПЛАТФОРМЫ (upload)                                     │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │ 5.1. Подготовка метаданных                                           │  │
│  │    • Получение названия из маппинга (TitleMapper)                    │  │
│  │    • Формирование описания:                                          │  │
│  │      - Раздел "🔹 Темы лекции:" с таймкодами                         │  │
│  │      - Формат: HH:MM:SS — Название темы                              │  │
│  │      - Автоматическое добавление перерывов (без дубликатов)          │  │
│  │      - Лимит: 5000 символов для всех платформ                        │  │
│  │    • Выбор миниатюры из каталога (thumbnails/)                        │  │
│  │                                                                      │  │
│  │ 5.2. Загрузка на платформы                                           │  │
│  │    ┌──────────────────────────┬──────────────────────────┐          │  │
│  │    │  YouTube                 │  VK                      │          │  │
│  │    ├──────────────────────────┼──────────────────────────┤          │  │
│  │    │ • OAuth 2.0 аутентификация│ • Access Token аутентификация│     │  │
│  │    │ • Загрузка видео          │ • Загрузка видео         │          │  │
│  │    │ • Указание языка (RU)    │ • Добавление в альбом     │          │  │
│  │    │ • Установка миниатюры    │ • Установка миниатюры     │          │  │
│  │    │ • Добавление в плейлист   │ • Настройка приватности  │          │  │
│  │    │ • Настройка приватности  │ • Обновление описания    │          │  │
│  │    │ • Загрузка субтитров     │                          │          │  │
│  │    │ • Обновление описания    │                          │          │  │
│  │    └──────────────────────────┴──────────────────────────┘          │  │
│  │                                                                      │  │
│  │ 5.3. Обновление статусов                                             │  │
│  │    • Статус платформы: UPLOADING → UPLOADED                         │  │
│  │    • Сохранение URL видео в БД                                      │  │
│  │    • Сохранение ID видео для управления                             │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    РЕЗУЛЬТАТ: Опубликованное видео                           │
│  ┌──────────────────────────┬──────────────────────────┐                 │  │
│  │  YouTube                 │  VK                      │                 │  │
│  │  • Видео с оглавлением   │  • Видео с оглавлением    │                 │  │
│  │  • Таймкоды в описании    │  • Таймкоды в описании   │                 │  │
│  │  • Миниатюра             │  • Миниатюра              │                 │  │
│  │  • В плейлисте           │  • В альбоме              │                 │  │
│  │  • Субтитры (опционально)│                          │                 │  │
│  └──────────────────────────┴──────────────────────────┘                 │  │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Управление состоянием

Система использует статусы для отслеживания прогресса:

**ProcessingStatus:**
- `INITIALIZED` — Инициализировано (загружено из Zoom API)
- `DOWNLOADING` — В процессе загрузки
- `DOWNLOADED` — Загружено
- `PROCESSING` — В процессе обработки
- `PROCESSED` — Обработано
- `TRANSCRIBING` — В процессе транскрибации
- `TRANSCRIBED` — Транскрибировано
- `UPLOADING` — В процессе загрузки на платформу
- `UPLOADED` — Загружено на платформу
- `SKIPPED` — Пропущено
- `EXPIRED` — Устарело (очищено)

**Примечание:** При ошибке на любом этапе статус откатывается к предыдущему завершенному этапу, устанавливается флаг `failed=true` и сохраняется `failed_at_stage` (этап, на котором произошла ошибка). Это позволяет удобно делать retry, начиная с правильного этапа. См. [ADR-015: FSM для надежной обработки](#adr-015-fsm-для-надежной-обработки) для подробностей.

**TargetStatus:**
- `NOT_UPLOADED` — Не загружено
- `UPLOADING` — В процессе загрузки
- `UPLOADED` — Загружено успешно
- `FAILED` — Загрузка провалилась (после всех попыток retry)

**Примечание:** 
- Во время загрузки: статус `UPLOADING`, при ошибке `failed=true` (статус остается `UPLOADING`)
- После исчерпания всех попыток retry: статус переходит в `FAILED`, `failed=true`
- Каждая платформа (YouTube, VK) имеет независимый статус. См. [ADR-015: FSM для надежной обработки](#adr-015-fsm-для-надежной-обработки) для подробностей.

### FSM (Finite State Machine) для надежной обработки

Система использует явную FSM-модель для гарантии надежности и возможности восстановления после сбоев. Каждый этап обработки является отдельным состоянием с четко определенными переходами.

**Принципы FSM:**
1. **Детерминированные переходы** — каждое состояние может переходить только в определенные следующие состояния
2. **Изоляция состояний** — сбой на одном этапе не влияет на уже завершенные этапы
3. **Возможность перезапуска** — любое состояние можно перезапустить независимо от других
4. **Отслеживание сбоев** — при ошибке сохраняется информация о сломанном этапе для последующего перезапуска

Подробнее см. [ADR-015: FSM для надежной обработки](#adr-015-fsm-для-надежной-обработки)

### Структура файловой системы

```
media/
└── user_{user_id}/
    ├── video/
    │   ├── unprocessed/          # Исходные видео
    │   │   └── recording_*.mp4
    │   ├── processed/            # Обработанные видео
    │   │   └── recording_*_processed.mp4
    │   └── temp_processing/      # Временные файлы
    ├── processed_audio/          # Извлеченное аудио
    │   └── recording_*_processed.mp3
    ├── transcriptions/           # Транскрипции
    │   └── {recording_id}/
    │       ├── words.txt         # Слова с таймкодами (мс)
    │       ├── segments.txt      # Сегменты транскрипции
    │       ├── segments_auto.txt # Автосегментация из слов
    │       ├── subtitles.srt     # Субтитры SRT (опционально)
    │       └── subtitles.vtt     # Субтитры VTT (опционально)
    └── thumbnails/               # Миниатюры
        └── *.png
```

### Технические детали реализации

**Асинхронное программирование:**
- Использование `asyncio` для эффективной обработки I/O
- Параллельная обработка нескольких видео
- Асинхронные HTTP запросы

**Обработка ошибок:**
- Повторные попытки при сетевых ошибках
- Экспоненциальная задержка между попытками
- Различение типов ошибок (сетевые, аутентификация, неожиданные)
- Подробное логирование для диагностики
- Graceful degradation при частичных сбоях

**Производительность:**
- Многопоточная загрузка видео
- Параллельная обработка нескольких записей
- Кэширование конфигурации
- Контроль параллелизма (ограничение одновременных транскрибаций)
- Централизованное управление токенами (предотвращение дублирования запросов)

---

## Безопасность и изоляция

### Изоляция данных

**Принцип:** Всегда фильтровать по `user_id`

**Реализация:**
- Middleware автоматически добавляет `user_id` из `JWT` token
- Все запросы к БД фильтруются по `user_id`
- `ORM` использует автоматическую фильтрацию
- Валидация на уровне `API` (проверка прав доступа)

**Защита от утечек:**
- Нет запросов без фильтрации по `user_id`
- Тестирование на утечки данных
- Аудит доступа к данным

### Шифрование credentials

**Метод:** `PostgreSQL` `pgcrypto` extension

**Алгоритм:**
- Симметричное шифрование (`AES`)
- Ключ шифрования в переменных окружения
- Шифрование на уровне БД (pgp_sym_encrypt/pgp_sym_decrypt)

**Хранение:**
- Зашифрованные данные в `encrypted_data` (`BYTEA`)
- Метаданные (несекретные) в `metadata` (`JSONB`)

### Аутентификация

**Метод:** `JWT` Tokens

**Структура токена:**
- `user_id` — идентификатор пользователя
- `role` — роль пользователя
- `exp` — время истечения
- `iat` — время выдачи

**Безопасность:**
- Короткоживущие access tokens (15-60 минут)
- Долгоживущие refresh tokens (7-30 дней)
- Хранение в `HTTP-only cookies` (для веб) или `localStorage` (для `SPA`)

### Авторизация

**Уровни:**
1. **Роль** — базовая авторизация (admin, user)
2. **Флаги разрешений** — детальная авторизация (can_transcribe, и т.д.)
3. **Лимиты** — ограничения ресурсов (max_concurrent_processes, и т.д.)

**Проверка:**
- Middleware проверяет `JWT` token
- Извлекает `user_id` и `role`
- Проверяет флаги разрешений для конкретного действия
- Проверяет лимиты перед выполнением операции

### Валидация данных

**Метод:** `Pydantic` Models

**Проверки:**
- Типы данных
- Ограничения (min, max, regex)
- Обязательные поля
- Кастомная валидация

**Защита:**
- Автоматическая защита от `SQL injection` (параметризованные запросы)
- Защита от `XSS` (экранирование данных)
- Rate limiting на уровне пользователя

---

## Миграционная стратегия

### Фаза 1: Подготовка

1. Создание новых таблиц (users, base_configs, и т.д.)
2. Обновление существующих таблиц (добавление user_id, и т.д.)
3. Создание миграций `Alembic`

### Фаза 2: Миграция данных

1. **Создание default пользователя**
   - Email: `default@system.local`
   - Роль: `admin`
   - Все существующие данные привязываются к этому пользователю

2. **Миграция записей**
   - `UPDATE recordings SET user_id = 1 WHERE user_id IS NULL`

3. **Миграция файлов**
   - Перемещение `media/video/` → `media/user_1/video/`
   - Перемещение `media/processed_audio/` → `media/user_1/processed_audio/`
   - Перемещение `media/transcriptions/` → `media/user_1/transcriptions/`

4. **Миграция конфигураций**
   - Чтение существующих `JSON` файлов
   - Создание записей в `base_configs` (глобальный конфиг)
   - Создание записей в `user_credentials` (с шифрованием)
   - Создание записей в `recording_templates` (из app_config.json)

### Фаза 3: Тестирование

1. Проверка целостности данных
2. Тестирование изоляции данных
3. Тестирование миграции файлов
4. Тестирование работы с новыми таблицами

### Фаза 4: Развертывание

1. Бэкап существующей БД
2. Применение миграций
3. Миграция файлов
4. Проверка работоспособности
5. Откат при необходимости

---

## ADR-010: Автоматизация обработки записей

**Решение:** Фоновая автоматизация через APScheduler с группировкой задач по времени и retry механизмом

### Контекст

Требуется автоматизировать процесс синхронизации и загрузки записей:
- Синхронизация новых записей из Zoom API
- Автоматическая обработка записей, попадающих под активные шаблоны
- Настройка расписания для каждого шаблона индивидуально
- Обработка ошибок с retry механизмом

### Архитектурное решение

#### 1. Хранение настроек автоматизации

**Глобальные настройки (base_configs.automation_config):**
```json
{
  "enabled": true,
  "default_schedule": {
    "type": "daily",
    "time": "06:00",
    "timezone": "Europe/Moscow"
  },
  "default_sync_days": 1,
  "retry": {
    "max_attempts": 3,
    "delay_seconds": 300
  }
}
```

**Настройки в шаблоне (recording_templates.automation_config):**
```json
{
  "enabled": true,
  "schedule": {
    "type": "daily",
    "time": "08:00",
    "timezone": "Europe/Moscow"
  },
  "sync_days": 2,
  "auto_upload": true
}
```

**Принцип слияния:**
- Шаблон переопределяет глобальные настройки
- Если `automation.enabled = false` в шаблоне → шаблон пропускается
- Если глобально `enabled = false` → автоматизация отключена для всех шаблонов пользователя

#### 2. Оптимизация APScheduler

**Проблема:** При большом количестве шаблонов создается много задач в scheduler'е.

**Решение: Группировка задач по времени выполнения**

**Алгоритм:**
1. При инициализации APScheduler:
   - Загружаем все активные шаблоны всех пользователей с `automation.enabled = true`
   - Группируем шаблоны по уникальному времени выполнения (time + timezone)
   - Создаем одну задачу на каждое уникальное время
   - Внутри задачи обрабатываем все шаблоны с этим временем параллельно

2. При изменении шаблона:
   - Перезагружаем расписание для этого пользователя
   - Обновляем соответствующие задачи в scheduler'е

3. При добавлении нового шаблона:
   - Проверяем, существует ли задача на это время
   - Если да → добавляем шаблон в список обработки
   - Если нет → создаем новую задачу

**Пример группировки:**
```
Шаблоны:
- Template 1: 06:00 (user_1)
- Template 2: 06:00 (user_1)
- Template 3: 08:00 (user_1)
- Template 4: 06:00 (user_2)

Группировка:
- Задача 1: 06:00 → обрабатывает [Template 1, Template 2, Template 4]
- Задача 2: 08:00 → обрабатывает [Template 3]
```

**Преимущества:**
- Минимальное количество задач в scheduler'е
- Эффективное использование ресурсов
- Параллельная обработка шаблонов с одинаковым временем

#### 3. Логика обработки шаблона

**Алгоритм `process_template_automation`:**
```
1. Загрузить шаблон и проверить:
   - automation.enabled = true
   - is_draft = false
   - is_active = true

2. Получить настройки автоматизации:
   - Слить глобальные + шаблонные настройки
   - Определить sync_days (из шаблона или глобально)
   - Определить schedule (из шаблона или глобально)

3. Выполнить синхронизацию:
   - sync_zoom_recordings(configs, from_date, to_date)
   - from_date = today - sync_days
   - to_date = today

4. Найти записи для обработки:
   - status = INITIALIZED
   - template_id = текущий шаблон
   - created_at >= from_date (чтобы не обрабатывать старые записи)

5. Получить платформы из output_configs:
   - Фильтровать по enabled = true
   - Извлечь список платформ (youtube, vk)

6. Запустить full-process:
   - Для каждой записи: download → process → transcribe → upload
   - Параллельная обработка записей

7. Обработка ошибок:
   - При ошибке → retry с задержкой
   - После max_attempts → пометить запись как failed=true (см. ADR-015)
   - Статус записи остается на текущем этапе, устанавливается failed=true
```

#### 4. Retry механизм

**Стратегия:**
- Максимальное количество попыток: `retry.max_attempts` (по умолчанию 3)
- Задержка между попытками: `retry.delay_seconds` (по умолчанию 300 сек = 5 мин)
- Экспоненциальная задержка: `delay * (2 ^ attempt_number)`

**Обработка ошибок:**
```python
async def process_with_retry(template_id: int, user_id: int):
    max_attempts = get_retry_max_attempts(user_id)
    delay = get_retry_delay(user_id)
    
    for attempt in range(1, max_attempts + 1):
        try:
            result = await process_template_automation(template_id, user_id)
            if result.success:
                await mark_template_success(template_id)
                return result
        except Exception as e:
            logger.error(f"Template {template_id}, attempt {attempt}/{max_attempts}: {e}")
            
            if attempt < max_attempts:
                # Экспоненциальная задержка
                wait_time = delay * (2 ** (attempt - 1))
                await asyncio.sleep(wait_time)
            else:
                # Последняя попытка неудачна
                await mark_template_failed(template_id, error=str(e))
                raise
```

#### 5. Отслеживание выполнения

**Таблица `automation_runs`:**
```sql
CREATE TABLE automation_runs (
    id SERIAL PRIMARY KEY,
    template_id INT NOT NULL REFERENCES recording_templates(id) ON DELETE CASCADE,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    status VARCHAR(20) NOT NULL CHECK (status IN ('running', 'success', 'failed', 'skipped')),
    -- running - выполняется
    -- success - успешно завершено
    -- failed - ошибка после всех retry
    -- skipped - пропущено (нет записей для обработки)
    
    started_at TIMESTAMP WITH TIME ZONE NOT NULL,
    completed_at TIMESTAMP WITH TIME ZONE,
    
    sync_count INT DEFAULT 0,  -- количество синхронизированных записей
    processed_count INT DEFAULT 0,  -- количество обработанных записей
    uploaded_count INT DEFAULT 0,  -- количество загруженных записей
    
    error_message TEXT,
    retry_count INT DEFAULT 0,
    
    metadata JSONB DEFAULT '{}'  -- дополнительная информация
    
    CONSTRAINT unique_template_run UNIQUE (template_id, started_at)
);

CREATE INDEX idx_automation_runs_template ON automation_runs(template_id, started_at DESC);
CREATE INDEX idx_automation_runs_user ON automation_runs(user_id, started_at DESC);
CREATE INDEX idx_automation_runs_status ON automation_runs(status, started_at DESC);
```

**Использование:**
- История выполнения автоматизации
- Отладка проблем
- Метрики и аналитика
- Предотвращение дублирования (если задача уже выполняется)

#### 6. Предотвращение конфликтов

**Проблема:** Одна запись может подходить под несколько шаблонов.

**Решение:**
- При синхронизации запись сопоставляется с шаблоном по приоритету (`priority DESC`)
- Первый подходящий шаблон назначается записи (`template_id`)
- Автоматизация обрабатывает только записи с `template_id = X`
- Конфликтов не возникает, т.к. каждая запись привязана к одному шаблону

#### 7. Оптимизация производительности

**Запросы к БД:**
- Использовать индексы: `(user_id, is_active, is_draft)`, `(template_id, status)`
- Batch-загрузка шаблонов при инициализации
- Кэширование настроек автоматизации (TTL = 5 минут)

**Параллельная обработка:**
- Шаблоны с одинаковым временем обрабатываются параллельно (`asyncio.gather`)
- Записи внутри шаблона обрабатываются параллельно (уже реализовано в `run_full_pipeline`)

**Ограничения:**
- Максимум параллельных задач: `max_concurrent_processes` из настроек пользователя
- Timeout для каждой задачи: 2 часа (защита от зависших задач)

#### 8. Структура сервиса

**AutomationService:**
```python
class AutomationService:
    """
    Сервис автоматизации обработки записей.
    
    Ответственность:
    - Управление APScheduler
    - Группировка задач по времени
    - Обработка шаблонов с retry
    - Логирование выполнения
    """
    
    async def start(self):
        """Запуск scheduler'а и загрузка всех активных шаблонов"""
        
    async def stop(self):
        """Остановка scheduler'а"""
        
    async def reload_user_templates(self, user_id: int):
        """Перезагрузка шаблонов пользователя"""
        
    async def process_template_automation(self, template_id: int, user_id: int):
        """Обработка одного шаблона"""
        
    async def process_templates_at_time(self, time_key: str):
        """Обработка всех шаблонов с определенным временем"""
```

**CLI команды:**
```bash
# Запуск автоматизации
python main.py automation start

# Остановка автоматизации
python main.py automation stop

# Тест одного шаблона
python main.py automation test --template-id 1

# Перезагрузка шаблонов пользователя
python main.py automation reload --user-id 1

# Статус автоматизации
python main.py automation status
```

### Обоснование

**Почему APScheduler, а не cron:**
- Гибкость: можно динамически изменять расписание
- Интеграция: работает в том же процессе
- Мониторинг: проще отслеживать статус задач
- Retry: встроенная поддержка повторных попыток

**Почему группировка по времени:**
- Масштабируемость: 100 шаблонов → 5-10 задач вместо 100
- Эффективность: меньше накладных расходов scheduler'а
- Простота: проще управлять и отлаживать

**Почему настройки в БД (JSONB):**
- Консистентность: все настройки в одном месте
- Multi-tenancy: изоляция по user_id
- Версионирование: можно добавить history
- Производительность: быстрые запросы с индексами

### Риски и митигация

**Риск 1: Долгие задачи блокируют scheduler**
- Митигация: Задачи выполняются асинхронно, не блокируют event loop

**Риск 2: Много одновременных задач**
- Митигация: Ограничение через `max_concurrent_processes`, семафоры

**Риск 3: Изменение шаблона во время выполнения**
- Митигация: Делаем snapshot настроек в начале обработки

**Риск 4: Перезапуск процесса теряет задачи**
- Митигация: При старте перезагружаем все активные шаблоны из БД

**Риск 5: Ошибки внешних API**
- Митигация: Retry механизм, timeout'ы, circuit breaker (в будущем)

### Миграционная стратегия

1. **Фаза 1:** Добавить поля `automation_config` в `base_configs` и `recording_templates`
2. **Фаза 2:** Создать таблицу `automation_runs`
3. **Фаза 3:** Реализовать `AutomationService`
4. **Фаза 4:** Добавить CLI команды
5. **Фаза 5:** Тестирование и мониторинг

### Будущие улучшения

- Уведомления об ошибках (email, Telegram)
- Веб-интерфейс для управления автоматизацией
- Метрики и дашборд (Prometheus, Grafana)
- Circuit breaker для внешних API
- Очередь задач (Celery/RQ) для очень больших нагрузок

---

## ADR-011: Очереди задач (будущее)

**Статус:** Запланировано на будущее  
**Приоритет:** Низкий (для MVP не требуется)

### Решение

**Текущий подход (MVP):** Использование `asyncio` для параллельной обработки без очередей.

**Будущий подход:** Миграция на очереди задач (Celery/RQ) при росте нагрузки.

### Текущая ситуация

Система использует **asyncio** для параллельной обработки:
- Операции выполняются через `asyncio.gather()`
- API возвращает `202 Accepted` для длительных операций
- Статус отслеживается через поле `status` в БД
- Все выполняется в процессе API сервера

**Преимущества текущего подхода:**
- Проще в разработке и отладке
- Меньше зависимостей (не нужен Redis/RabbitMQ)
- Проще деплой (один процесс)
- Логи и ошибки видны сразу

### Когда очереди НЕ нужны (текущий подход достаточен)

✅ **Подходит для:**
- Небольшое количество пользователей (< 50)
- Небольшое количество одновременных задач (< 10)
- Обработка запускается вручную через CLI или API
- Нет критических требований к отказоустойчивости
- Простота архитектуры важнее масштабируемости

### Когда очереди НУЖНЫ

❌ **Требуется если:**
- Много пользователей (> 100) и много одновременных задач
- Нужна гарантия выполнения задач (даже при падении API)
- Нужна приоритизация задач (high/medium/low)
- Нужна возможность отложенного выполнения (scheduled tasks)
- Нужна возможность retry с задержкой
- Нужна возможность отмены задач
- Нужна возможность мониторинга очереди (сколько задач в очереди)

### Критерии для миграции на очереди

Миграция на очереди потребуется когда:
- **> 50 активных пользователей**
- **> 20 одновременных задач**
- Появятся требования к **гарантии выполнения** (даже при падении API)
- Потребуется **приоритизация задач**
- Потребуется **отложенное выполнение** задач

### Архитектура для будущего

**Принцип:** Спроектировать код так, чтобы легко добавить очереди позже.

**Текущая реализация:**
```python
async def process_recording(recording_id: int):
    # Прямой вызов
    await pipeline.process(recording)
```

**Будущая реализация (легко мигрировать):**
```python
async def process_recording(recording_id: int):
    # Добавляем в очередь
    task = celery_app.send_task('process_recording', args=[recording_id])
    return {"task_id": task.id}
```

**Рекомендуемый подход:**
- Использовать абстракцию для выполнения задач
- Создать интерфейс `TaskExecutor` с двумя реализациями:
  - `AsyncTaskExecutor` (текущий, для MVP)
  - `QueueTaskExecutor` (будущий, для масштабирования)

### Выбранная технология (для будущего)

**Варианты:**
1. **Celery** (выбрано для будущего)
2. **RQ** (Redis Queue)
3. **Dramatiq**

**Обоснование выбора Celery:**
- Широкая поддержка брокеров (Redis, RabbitMQ, SQS)
- Мощные возможности (retry, scheduling, monitoring)
- Хорошая документация
- Активное сообщество

**Брокер:** Redis (уже используется для кэширования)

### Миграционная стратегия

1. **Фаза 1 (MVP):** Использовать `asyncio` + `FastAPI BackgroundTasks`
2. **Фаза 2 (Рост):** Добавить абстракцию `TaskExecutor`
3. **Фаза 3 (Масштабирование):** Реализовать `QueueTaskExecutor` на Celery
4. **Фаза 4 (Оптимизация):** Настроить приоритизацию и мониторинг

---

## ADR-012: Квоты и лимиты (MVP)

**Статус:** Реализовать в MVP  
**Приоритет:** Высокий

### Решение

Реализовать систему квот и лимитов для контроля использования ресурсов пользователями.

### Цели

Квоты нужны для:
- **Ограничения использования ресурсов** — защита инфраструктуры
- **Защиты от злоупотреблений** — предотвращение DDoS и злоупотреблений
- **Планирования инфраструктуры** — понимание нагрузки
- **Монетизации** — разные тарифы = разные квоты

### Типы квот

#### 1. Квоты на обработку

Уже определены в таблице `users`:
- `max_concurrent_processes` — максимум одновременных обработок (default: 2)
- `max_recordings_per_month` — максимум записей в месяц (default: NULL = безлимит)
- `quota_disk_space_gb` — квота дискового пространства в GB (default: NULL = безлимит)
- `max_file_size_mb` — максимальный размер файла в MB (default: 5000)

#### 2. Квоты на API запросы

- `rate_limit_per_minute` — лимит запросов в минуту (default: 100)

### Схема базы данных

#### Таблица quota_usage

```sql
CREATE TABLE quota_usage (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Счетчики
    active_processes_count INT DEFAULT 0,
    recordings_this_month INT DEFAULT 0,
    recordings_month_year INT NOT NULL,  -- YYYYMM для месяца (202501)
    disk_usage_bytes BIGINT DEFAULT 0,
    
    -- Timestamps
    last_reset_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    UNIQUE(user_id, recordings_month_year)
);

CREATE INDEX idx_quota_usage_user ON quota_usage(user_id);
CREATE INDEX idx_quota_usage_month ON quota_usage(recordings_month_year);
```

**Преимущества отдельной таблицы:**
- Можно хранить историю использования
- Легче делать reset по месяцам
- Можно делать аналитику использования
- Не засоряет таблицу `users`

### Механизм проверки квот

#### Шаг 1: Проверка перед операцией

```python
class QuotaService:
    async def check_quota(
        self, 
        user_id: int, 
        operation: str,  # 'process', 'transcribe', 'upload'
        resource_amount: int = 1
    ) -> tuple[bool, str | None]:
        """
        Проверяет квоту пользователя.
        
        Returns:
            (is_allowed, error_message)
        """
        user = await self.get_user(user_id)
        quota = await self.get_user_quota(user_id)
        
        if operation == 'process':
            # Проверка concurrent processes
            if quota.active_processes_count >= user.max_concurrent_processes:
                return False, f"Превышен лимит одновременных обработок: {user.max_concurrent_processes}"
            
            # Проверка monthly quota
            if user.max_recordings_per_month:
                if quota.recordings_this_month >= user.max_recordings_per_month:
                    return False, f"Превышена месячная квота: {user.max_recordings_per_month}"
        
        elif operation == 'upload':
            # Проверка дискового пространства
            if user.quota_disk_space_gb:
                quota_bytes = user.quota_disk_space_gb * 1024 * 1024 * 1024
                if quota.disk_usage_bytes + resource_amount > quota_bytes:
                    return False, f"Превышена квота дискового пространства: {user.quota_disk_space_gb} GB"
        
        return True, None
```

#### Шаг 2: Atomic обновление счетчиков

```python
async def start_processing(user_id: int, recording_id: int):
    """Начинает обработку с проверкой и обновлением квот"""
    
    # Проверяем квоту
    allowed, error = await quota_service.check_quota(user_id, 'process')
    if not allowed:
        raise HTTPException(status_code=429, detail=error)
    
    # Atomic обновление счетчика
    async with db.transaction():
        # Увеличиваем счетчик активных процессов
        await db.execute("""
            UPDATE quota_usage
            SET active_processes_count = active_processes_count + 1,
                updated_at = NOW()
            WHERE user_id = :user_id
        """, {"user_id": user_id})
        
        # Начинаем обработку
        await start_recording_processing(recording_id)
```

#### Шаг 3: Освобождение квоты при завершении

```python
async def finish_processing(user_id: int, recording_id: int):
    """Завершает обработку и освобождает квоту"""
    
    async with db.transaction():
        # Уменьшаем счетчик активных процессов
        await db.execute("""
            UPDATE quota_usage
            SET active_processes_count = GREATEST(0, active_processes_count - 1),
                recordings_this_month = recordings_this_month + 1,
                updated_at = NOW()
            WHERE user_id = :user_id
        """, {"user_id": user_id})
        
        # Обновляем статус записи
        await update_recording_status(recording_id, 'PROCESSED')
```

### Reset квот (ежемесячный)

```python
async def reset_monthly_quotas():
    """Сбрасывает месячные квоты (вызывается cron job 1-го числа каждого месяца)"""
    
    current_month = datetime.now().strftime('%Y%m')
    
    async with db.transaction():
        # Сбрасываем счетчики для всех пользователей
        await db.execute("""
            UPDATE quota_usage
            SET recordings_this_month = 0,
                last_reset_at = NOW(),
                updated_at = NOW()
            WHERE recordings_month_year < :current_month
        """, {"current_month": int(current_month)})
        
        # Создаем записи для нового месяца
        await db.execute("""
            INSERT INTO quota_usage (user_id, recordings_month_year, recordings_this_month)
            SELECT id, :current_month, 0
            FROM users
            WHERE id NOT IN (
                SELECT user_id FROM quota_usage 
                WHERE recordings_month_year = :current_month
            )
        """, {"current_month": int(current_month)})
```

### API для проверки квот

```python
@router.get("/api/v1/quota/status")
async def get_quota_status(user: User = Depends(get_current_user)):
    """Получить текущее использование квот"""
    
    quota = await quota_service.get_user_quota(user.id)
    
    return {
        "concurrent_processes": {
            "used": quota.active_processes_count,
            "limit": user.max_concurrent_processes,
            "available": user.max_concurrent_processes - quota.active_processes_count
        },
        "recordings_this_month": {
            "used": quota.recordings_this_month,
            "limit": user.max_recordings_per_month,
            "available": user.max_recordings_per_month - quota.recordings_this_month if user.max_recordings_per_month else None
        },
        "disk_space": {
            "used_gb": quota.disk_usage_bytes / (1024**3),
            "limit_gb": user.quota_disk_space_gb,
            "available_gb": (user.quota_disk_space_gb * 1024**3 - quota.disk_usage_bytes) / (1024**3) if user.quota_disk_space_gb else None
        }
    }
```

### Обработка ошибок превышения квоты

```python
class QuotaExceededError(Exception):
    pass

@router.post("/api/v1/recordings/{id}/process")
async def process_recording(
    recording_id: int,
    user: User = Depends(get_current_user)
):
    try:
        # Проверяем квоту
        allowed, error = await quota_service.check_quota(user.id, 'process')
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "QUOTA_EXCEEDED",
                    "message": error
                }
            )
        
        # Запускаем обработку
        await start_processing(recording_id, user.id)
        
        return {"status": "processing", "recording_id": recording_id}
        
    except QuotaExceededError as e:
        raise HTTPException(status_code=429, detail=str(e))
```

### Миграционная стратегия

1. **Фаза 1:** Создать таблицу `quota_usage`
2. **Фаза 2:** Реализовать `QuotaService`
3. **Фаза 3:** Добавить проверки квот во все операции
4. **Фаза 4:** Настроить cron job для reset квот
5. **Фаза 5:** Добавить API для просмотра квот

---

## ADR-013: Аудит (позже)

**Статус:** Реализовать позже (после MVP)  
**Приоритет:** Средний

### Решение

Реализовать систему аудита для логирования всех критичных операций пользователей.

### Цели

Аудит нужен для:
- **Безопасности** — кто что делал, когда, с какими данными
- **Отладки** — история изменений для диагностики проблем
- **Compliance** — соответствие требованиям (GDPR, SOC2)
- **Аналитики** — понимание использования системы

### Принципы аудита

1. **Неизменяемость** — логи нельзя изменять или удалять
2. **Полнота** — логируем все критичные операции
3. **Производительность** — не должно замедлять основную работу
4. **Структурированность** — легко искать и анализировать
5. **Конфиденциальность** — не логируем чувствительные данные (пароли, tokens)

### Схема базы данных

```sql
CREATE TABLE audit_logs (
    id BIGSERIAL PRIMARY KEY,
    
    -- Кто
    user_id INT REFERENCES users(id) ON DELETE SET NULL,
    user_email VARCHAR(255),  -- Сохраняем email на случай удаления пользователя
    user_role VARCHAR(20),  -- Сохраняем роль на момент действия
    
    -- Что
    action VARCHAR(100) NOT NULL,  -- 'recording.created', 'template.updated', 'credential.deleted'
    resource_type VARCHAR(50) NOT NULL,  -- 'recording', 'template', 'credential'
    resource_id INT,  -- ID ресурса
    
    -- Когда
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    
    -- Где
    ip_address INET,
    user_agent TEXT,
    request_id VARCHAR(100),  -- Для связи с логами запросов
    
    -- Что изменилось
    changes JSONB,  -- Что изменилось (для update операций)
    -- Пример: {"status": {"old": "INITIALIZED", "new": "PROCESSING"}}
    
    -- Результат
    status VARCHAR(20) NOT NULL,  -- 'success', 'failure', 'partial'
    error_message TEXT,  -- Если была ошибка
    
    -- Контекст
    metadata JSONB DEFAULT '{}',  -- Дополнительная информация
    -- Пример: {"platform": "youtube", "file_size": 1234567}
    
    CONSTRAINT valid_status CHECK (status IN ('success', 'failure', 'partial'))
);

-- Индексы для производительности
CREATE INDEX idx_audit_logs_user ON audit_logs(user_id, timestamp DESC);
CREATE INDEX idx_audit_logs_action ON audit_logs(action, timestamp DESC);
CREATE INDEX idx_audit_logs_resource ON audit_logs(resource_type, resource_id, timestamp DESC);
CREATE INDEX idx_audit_logs_timestamp ON audit_logs(timestamp DESC);
```

### Типы действий для логирования

#### Критичные (логируем всегда):

```python
# Recordings
'recording.created'      # Создание записи
'recording.deleted'      # Удаление записи
'recording.status_changed'  # Изменение статуса
'recording.processed'    # Запуск обработки
'recording.uploaded'     # Загрузка на платформу

# Templates
'template.created'       # Создание шаблона
'template.updated'      # Обновление шаблона
'template.deleted'      # Удаление шаблона
'template.activated'    # Активация шаблона

# Credentials
'credential.created'     # Создание credential
'credential.updated'     # Обновление credential
'credential.deleted'     # Удаление credential
'credential.used'        # Использование credential (для API вызовов)

# Users (admin only)
'user.created'          # Создание пользователя
'user.updated'          # Обновление пользователя
'user.deleted'          # Удаление пользователя
'user.role_changed'     # Изменение роли

# Authentication
'auth.login'           # Успешный вход
'auth.login_failed'    # Неудачная попытка входа
'auth.logout'          # Выход
'auth.token_refreshed' # Обновление токена

# Data access (важно для безопасности)
'data.exported'        # Экспорт данных
'data.accessed'        # Доступ к данным другого пользователя (admin)
```

### Реализация Audit Service

```python
class AuditService:
    """Сервис для логирования действий пользователей"""
    
    async def log(
        self,
        user_id: Optional[int],
        action: str,
        resource_type: str,
        resource_id: Optional[int] = None,
        status: str = 'success',
        changes: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        request_id: Optional[str] = None,
    ):
        """
        Логирует действие пользователя.
        
        Важно: Выполняется асинхронно, не блокирует основную операцию.
        """
        # Получаем информацию о пользователе (если есть)
        user_email = None
        user_role = None
        if user_id:
            user = await self.db.get_user(user_id)
            if user:
                user_email = user.email
                user_role = user.role
        
        # Сохраняем в БД (асинхронно, не блокируем основную операцию)
        try:
            await self.db.execute("""
                INSERT INTO audit_logs (
                    user_id, user_email, user_role,
                    action, resource_type, resource_id,
                    timestamp, ip_address, user_agent, request_id,
                    changes, status, error_message, metadata
                ) VALUES (
                    :user_id, :user_email, :user_role,
                    :action, :resource_type, :resource_id,
                    NOW(), :ip_address, :user_agent, :request_id,
                    :changes, :status, :error_message, :metadata
                )
            """, {
                'user_id': user_id,
                'user_email': user_email,
                'user_role': user_role,
                'action': action,
                'resource_type': resource_type,
                'resource_id': resource_id,
                'ip_address': ip_address,
                'user_agent': user_agent,
                'request_id': request_id,
                'changes': json.dumps(changes) if changes else None,
                'status': status,
                'error_message': error_message,
                'metadata': json.dumps(metadata) if metadata else None,
            })
        except Exception as e:
            # Логируем ошибку, но не прерываем основную операцию
            logger.error(f"Failed to write audit log: {e}")
```

### API для просмотра логов

```python
@router.get("/api/v1/audit-logs")
async def get_audit_logs(
    user: User = Depends(get_current_user),
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[int] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    page: int = 1,
    per_page: int = 50,
):
    """Получить логи аудита (только свои действия, админы видят все)"""
    
    # Обычные пользователи видят только свои логи
    # Админы видят все логи
    user_id_filter = None if user.role == 'admin' else user.id
    
    logs = await audit_service.get_logs(
        user_id=user_id_filter,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        from_date=from_date,
        to_date=to_date,
        page=page,
        per_page=per_page,
    )
    
    return logs
```

### Retention policy

```sql
-- Автоматическое удаление старых логов (через cron job)
-- Удаляем логи старше 1 года
DELETE FROM audit_logs 
WHERE timestamp < NOW() - INTERVAL '1 year';

-- Или архивируем в отдельную таблицу
INSERT INTO audit_logs_archive 
SELECT * FROM audit_logs 
WHERE timestamp < NOW() - INTERVAL '1 year';

DELETE FROM audit_logs 
WHERE timestamp < NOW() - INTERVAL '1 year';
```

### Миграционная стратегия

1. **Фаза 1:** Создать таблицу `audit_logs`
2. **Фаза 2:** Реализовать `AuditService`
3. **Фаза 3:** Добавить логирование в критичные операции
4. **Фаза 4:** Добавить API для просмотра логов
5. **Фаза 5:** Настроить retention policy

---

## ADR-014: Уведомления (позже)

**Статус:** Реализовать позже (после MVP)  
**Приоритет:** Средний

### Решение

Реализовать систему уведомлений по email для критических ошибок и ежедневных сводок.

### Требования

1. **Email при ошибках:** Отправлять на почту при критических ошибках
2. **Ежедневная сводка:** Отправлять каждый день сводку (можно отключить)
3. **Настройки:** Позже добавим настройки уведомлений (webhooks, Telegram, etc.)

### Типы уведомлений

#### Критические ошибки (отправляем сразу):

```python
# Ошибки обработки
'processing.failed'       # Ошибка при обработке записи
'transcription.failed'    # Ошибка при транскрибации
'upload.failed'          # Ошибка при загрузке на платформу

# Ошибки системы
'system.error'           # Критическая ошибка системы
'quota.exceeded'         # Превышение квоты (критично)
'database.error'         # Ошибка БД
'external_api.error'     # Ошибка внешнего API (Zoom, YouTube, etc.)
```

#### Ежедневная сводка:

```python
# Статистика за день
- Обработано записей: X
- Транскрибировано: Y
- Загружено на платформы: Z
- Ошибок: N
- Использование квот: X/Y
```

### Схема базы данных

```sql
CREATE TABLE notifications (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- Тип уведомления
    notification_type VARCHAR(50) NOT NULL,
    -- 'error', 'daily_summary', 'quota_warning', 'processing_complete'
    
    -- Статус
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    -- 'pending', 'sent', 'failed'
    
    -- Содержимое
    subject VARCHAR(255) NOT NULL,
    body_text TEXT NOT NULL,
    body_html TEXT,  -- HTML версия (опционально)
    
    -- Метаданные
    metadata JSONB DEFAULT '{}',
    -- Для ошибок: {"recording_id": 123, "error": "..."}
    -- Для сводки: {"processed": 5, "errors": 1, ...}
    
    -- Время
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    sent_at TIMESTAMP WITH TIME ZONE,
    attempts INT DEFAULT 0,
    last_error TEXT,
    
    CONSTRAINT valid_status CHECK (status IN ('pending', 'sent', 'failed'))
);

CREATE INDEX idx_notifications_user_status ON notifications(user_id, status, created_at DESC);
CREATE INDEX idx_notifications_pending ON notifications(status, created_at) WHERE status = 'pending';
```

### Настройки уведомлений

```sql
-- Добавляем в таблицу users
ALTER TABLE users ADD COLUMN email_notifications_enabled BOOLEAN DEFAULT TRUE;
ALTER TABLE users ADD COLUMN daily_summary_enabled BOOLEAN DEFAULT TRUE;
ALTER TABLE users ADD COLUMN error_notifications_enabled BOOLEAN DEFAULT TRUE;
```

### Реализация Notification Service

```python
class NotificationService:
    """Сервис для отправки уведомлений по email"""
    
    async def send_error_notification(
        self,
        user_id: int,
        error_type: str,
        error_message: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Отправляет уведомление об ошибке"""
        
        user = await self.db.get_user(user_id)
        if not user or not user.error_notifications_enabled:
            return
        
        subject = f"❌ Ошибка: {error_type}"
        body = f"""
Произошла ошибка при обработке:

Тип ошибки: {error_type}
Сообщение: {error_message}

Дополнительная информация:
{json.dumps(metadata, indent=2, ensure_ascii=False) if metadata else 'Нет'}

---
Zoom Publishing Platform
        """.strip()
        
        await self._send_email(user.email, subject, body, 'error', metadata)
    
    async def send_daily_summary(
        self,
        user_id: int,
        summary_data: Dict[str, Any]
    ):
        """Отправляет ежедневную сводку"""
        
        user = await self.db.get_user(user_id)
        if not user or not user.daily_summary_enabled:
            return
        
        subject = "📊 Ежедневная сводка"
        body = f"""
Ежедневная сводка за {summary_data.get('date', 'сегодня')}:

📹 Обработано записей: {summary_data.get('processed', 0)}
🎤 Транскрибировано: {summary_data.get('transcribed', 0)}
📤 Загружено на платформы: {summary_data.get('uploaded', 0)}
❌ Ошибок: {summary_data.get('errors', 0)}

Использование квот:
- Одновременных обработок: {summary_data.get('active_processes', 0)}/{summary_data.get('max_processes', 'N/A')}
- Записей в этом месяце: {summary_data.get('recordings_this_month', 0)}/{summary_data.get('max_recordings_per_month', 'N/A')}
- Дисковое пространство: {summary_data.get('disk_usage_gb', 0):.2f} GB / {summary_data.get('disk_quota_gb', 'N/A')} GB

---
Zoom Publishing Platform
        """.strip()
        
        await self._send_email(user.email, subject, body, 'daily_summary', summary_data)
```

### Cron job для ежедневной сводки

```python
async def send_daily_summaries():
    """Отправляет ежедневные сводки всем пользователям (вызывается cron в 00:00)"""
    
    users = await db.get_all_active_users()
    
    for user in users:
        if not user.daily_summary_enabled:
            continue
        
        # Собираем статистику за вчера
        yesterday = datetime.now() - timedelta(days=1)
        
        summary = {
            'date': yesterday.strftime('%Y-%m-%d'),
            'processed': await count_processed_recordings(user.id, yesterday),
            'transcribed': await count_transcribed_recordings(user.id, yesterday),
            'uploaded': await count_uploaded_recordings(user.id, yesterday),
            'errors': await count_errors(user.id, yesterday),
            'active_processes': await get_active_processes_count(user.id),
            'max_processes': user.max_concurrent_processes,
            'recordings_this_month': await get_recordings_this_month(user.id),
            'max_recordings_per_month': user.max_recordings_per_month,
            'disk_usage_gb': await get_disk_usage_gb(user.id),
            'disk_quota_gb': user.quota_disk_space_gb,
        }
        
        await notification_service.send_daily_summary(user.id, summary)
```

### Настройка SMTP

```python
# В config/settings.py
class NotificationConfig(BaseSettings):
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str
    smtp_password: str
    from_email: str = "noreply@yourdomain.com"
    from_name: str = "Zoom Publishing Platform"
```

### Миграционная стратегия

1. **Фаза 1:** Создать таблицу `notifications`
2. **Фаза 2:** Добавить настройки в `users`
3. **Фаза 3:** Реализовать `NotificationService`
4. **Фаза 4:** Добавить отправку уведомлений при ошибках
5. **Фаза 5:** Настроить cron job для ежедневной сводки
6. **Фаза 6 (будущее):** Добавить webhooks, Telegram, и другие каналы

---

## ADR-015: FSM для надежной обработки

**Статус:** Планируется  
**Приоритет:** Высокий

### Контекст

В текущей реализации система использует линейные статусы (`ProcessingStatus`, `TargetStatus`) для отслеживания прогресса обработки. При сбое на любом этапе запись переходит в состояние `FAILED`, но нет возможности точно определить, на каком этапе произошла ошибка, и перезапустить только сломанный этап, не затрагивая уже успешно выполненные.

**Проблемы текущей реализации:**
1. При сбое на этапе `UPLOADING` вся запись помечается как `FAILED`, хотя предыдущие этапы (download, processing, transcription) уже выполнены
2. Нет возможности перезапустить только сломанный этап — приходится начинать с начала
3. Не ясно, какой именно этап сломался при общем статусе `FAILED`
4. Нет механизма для автоматического retry сломанных этапов

### Решение

Реализовать явную FSM (Finite State Machine) модель для каждого этапа обработки с отдельным отслеживанием состояния и возможностью независимого перезапуска.

**Ключевые принципы:**
1. **Откат к предыдущему статусу при ошибке** — при ошибке статус откатывается к предыдущему завершенному этапу (например, ошибка на `DOWNLOADING` → откат к `INITIALIZED`)
2. **Сохранение контекста ошибки** — при сбое сохраняется `failed_at_stage`, указывающий этап, на котором произошла ошибка (для аналитики и мониторинга)
3. **Булев атрибут для ошибок** — при сбое устанавливается флаг `failed = true`, указывающий что переход на следующий этап не удался
4. **Детерминированные переходы** — каждое состояние может переходить только в определенные следующие состояния
5. **Возможность перезапуска** — любой сломанный этап можно перезапустить через API (максимум 2 попытки), статус уже готов к retry благодаря откату
6. **Идемпотентность** — повторный запуск успешно выполненного этапа не должен вызывать ошибки
7. **Комбинированный подход для частичного успеха** — при загрузке на несколько платформ, если хотя бы одна успешна, используется `UPLOADED` с `failed=true` для индикации частичного успеха

### Архитектура FSM

#### Граф состояний основного пайплайна

```
┌─────────────────────────────────────────────────────────────────┐
│                  FSM Pipeline States                            │
└─────────────────────────────────────────────────────────────────┘

    INITIALIZED
         │
         ▼
    DOWNLOADING ────(success)───► DOWNLOADED
         │
         │ (error: откат к INITIALIZED, failed=true, failed_at_stage=DOWNLOADING)
         │
         ▼ (retry через API, максимум 2 попытки)
    [INITIALIZED, failed=true, failed_at_stage=DOWNLOADING] ──► DOWNLOADING ────► DOWNLOADED
         │
         │
         ▼
    PROCESSING ────(success)───► PROCESSED
         │
         │ (error: откат к DOWNLOADED, failed=true, failed_at_stage=PROCESSING)
         │
         ▼ (retry через API)
    [DOWNLOADED, failed=true, failed_at_stage=PROCESSING] ──► PROCESSING ────► PROCESSED
         │
         │
         ▼
    TRANSCRIBING ────(success)───► TRANSCRIBED
         │
         │ (error: откат к PROCESSED, failed=true, failed_at_stage=TRANSCRIBING)
         │
         ▼ (retry через API)
    [PROCESSED, failed=true, failed_at_stage=TRANSCRIBING] ──► TRANSCRIBING ────► TRANSCRIBED
         │
         │
         ▼
    UPLOADING ────(success)───► UPLOADED
         │
         │ (error: откат к TRANSCRIBED, failed=true, failed_at_stage=UPLOADING)
         │
         ▼ (retry через API)
    [TRANSCRIBED, failed=true, failed_at_stage=UPLOADING] ──► UPLOADING ────► UPLOADED

Принцип:
- При успехе: статус переходит на следующий этап, failed=false, failed_at_stage=NULL
- При ошибке: статус откатывается к предыдущему завершенному этапу, failed=true, failed_at_stage=этап_с_ошибкой
- Retry: через API можно перезапустить этап (максимум 2 попытки), статус уже готов к retry
```

#### Граф состояний для платформ (TargetStatus)

```
┌─────────────────────────────────────────────────────────────────┐
│                  FSM Target States                              │
└─────────────────────────────────────────────────────────────────┘

    NOT_UPLOADED
         │
         ▼
    UPLOADING ────(success)───► UPLOADED
         │
         │ (error: failed=true, status остаётся UPLOADING)
         │
         ▼ (retry через API, максимум 2 попытки)
    [UPLOADING, failed=true] ──► UPLOADING ────► UPLOADED
         │                                          │
         │ (все retry исчерпаны)                    │
         ▼                                          │
    FAILED (failed=true)                            │
                                                    │
                                                    ▼
                                             (все платформы в финальном состоянии)

Принцип:
- Во время загрузки: UPLOADING (при ошибке failed=true)
- После исчерпания всех retry: FAILED (failed=true)
- При успехе: UPLOADED (failed=false)

Каждая платформа (YouTube, VK) имеет независимый граф состояний.
```

#### Логика ProcessingStatus при загрузке на несколько платформ

При загрузке на несколько платформ (`output_targets`):

**Сценарий 1: Все платформы успешны**
- Все targets: `UPLOADED`, `failed=false`
- `ProcessingStatus`: `UPLOADED`, `failed=false`

**Сценарий 2: Частичный успех (одна успешна, другая нет)**
- YouTube target: `UPLOADED`, `failed=false`
- VK target: `UPLOADING`, `failed=true` (или `FAILED`, `failed=true` после всех retry)
- `ProcessingStatus`: `UPLOADING`, `failed=true` (пока есть незавершенные платформы)
- После завершения всех платформ: `ProcessingStatus`: `UPLOADED`, `failed=true` (комбинированный подход)

**Сценарий 3: Все платформы провалились**
- Все targets: `FAILED`, `failed=true`
- `ProcessingStatus`: `UPLOADING`, `failed=true`

**Сценарий 4: Все платформы в финальном состоянии (успех или провал)**
- Когда все targets в финальном состоянии (`UPLOADED` или `FAILED`)
- Если все платформы успешны: `ProcessingStatus` = `UPLOADED`, `failed=false`
- Если частичный успех (одна успешна, другая провалилась): `ProcessingStatus` = `UPLOADED`, `failed=true`
- Если все провалились: `ProcessingStatus` = `TRANSCRIBED`, `failed=true`, `failed_at_stage=UPLOADING` (можно retry)

**Сценарий 5: Дозагрузка на дополнительные платформы**
- Запись уже загружена на одну или несколько платформ (статус `UPLOADED`, `failed=false`)
- Пользователь добавляет новую платформу через API или изменение шаблона
- Создается новый target со статусом `NOT_UPLOADED`
- `ProcessingStatus` переходит обратно к `UPLOADING` (для запуска загрузки на новую платформу)
- Существующие платформы остаются в статусе `UPLOADED`
- После завершения загрузки на новую платформу статус снова определяется функцией `_determine_final_upload_status()`

Пример:
- Изначально: VK target = `UPLOADED`, ProcessingStatus = `UPLOADED`
- Добавлен YouTube target = `NOT_UPLOADED`
- ProcessingStatus → `UPLOADING` (есть незавершенные платформы)
- После загрузки на YouTube: YouTube = `UPLOADED`, VK = `UPLOADED`
- ProcessingStatus → `UPLOADED`, `failed=false` (все платформы успешны)

**Сценарий 5: Дозагрузка на дополнительные платформы**
- Запись уже загружена на одну или несколько платформ (статус `UPLOADED`, `failed=false`)
- Пользователь добавляет новую платформу через API или изменение шаблона
- Создается новый target со статусом `NOT_UPLOADED`
- `ProcessingStatus` переходит обратно к `UPLOADING` (для запуска загрузки на новую платформу)
- Существующие платформы остаются в статусе `UPLOADED`
- После завершения загрузки на новую платформу статус снова определяется функцией `_determine_final_upload_status()`

Пример:
- Изначально: VK target = `UPLOADED`, ProcessingStatus = `UPLOADED`
- Добавлен YouTube target = `NOT_UPLOADED`
- ProcessingStatus → `UPLOADING` (есть незавершенные платформы)
- После загрузки на YouTube: YouTube = `UPLOADED`, VK = `UPLOADED`
- ProcessingStatus → `UPLOADED`, `failed=false` (все платформы успешны)

**Логика определения ProcessingStatus:**

Функция `_determine_final_upload_status()` возвращает tuple `(ProcessingStatus, bool)`:
- Если не все платформы в финальном состоянии → `(UPLOADING, False)`
- Если все успешны → `(UPLOADED, False)`
- Если частичный успех → `(UPLOADED, True)` (комбинированный подход)
- Если все провалились → `(TRANSCRIBED, False)` (mark_failure сделает откат)

### Модель данных

#### Обновление таблицы `recordings`

```sql
ALTER TABLE recordings ADD COLUMN failed BOOLEAN DEFAULT FALSE;
ALTER TABLE recordings ADD COLUMN failed_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE recordings ADD COLUMN failed_reason TEXT;
ALTER TABLE recordings ADD COLUMN failed_at_stage VARCHAR(20);
ALTER TABLE recordings ADD COLUMN retry_count INT DEFAULT 0;

CREATE INDEX idx_recordings_failed ON recordings(status, failed) 
    WHERE failed = TRUE;
CREATE INDEX idx_recordings_failed_at ON recordings(failed_at DESC) 
    WHERE failed = TRUE;
CREATE INDEX idx_recordings_failed_at_stage ON recordings(failed_at_stage) 
    WHERE failed = TRUE AND failed_at_stage IS NOT NULL;
```

Поля: `failed` (флаг ошибки), `failed_at` (время ошибки), `failed_reason` (сообщение), `failed_at_stage` (этап ошибки: 'downloading', 'processing', 'transcribing', 'uploading'), `retry_count` (количество попыток, максимум 2).

#### Обновление `ProcessingStatus` enum

`ProcessingStatus` содержит методы:
- `can_have_failed_flag` — проверяет, может ли статус иметь `failed=true` (только для DOWNLOADING, PROCESSING, TRANSCRIBING, UPLOADING)
- `can_transition_to()` — проверяет допустимость перехода к следующему статусу согласно графу состояний

#### Обновление `TargetStatus` enum

`TargetStatus` имеет аналогичную структуру: `can_have_failed_flag` (только для UPLOADING) и `can_transition_to()` для проверки допустимых переходов согласно графу состояний платформ.

#### Обновление таблицы `output_targets`

```sql
ALTER TABLE output_targets ADD COLUMN failed BOOLEAN DEFAULT FALSE;
ALTER TABLE output_targets ADD COLUMN failed_at TIMESTAMP WITH TIME ZONE;
ALTER TABLE output_targets ADD COLUMN failed_reason TEXT;
ALTER TABLE output_targets ADD COLUMN retry_count INT DEFAULT 0;

CREATE INDEX idx_output_targets_failed ON output_targets(status, failed) 
    WHERE failed = TRUE OR status = 'failed';
```

Аналогичные поля для платформ с той же логикой.

### Логика обработки с FSM

#### Обработка перехода состояний

`StateTransitionManager` управляет переходами состояний:

- `mark_success()` — переводит на следующий этап, сбрасывает флаги ошибки и `failed_at_stage`
- `mark_failure()` — откатывает к предыдущему статусу, сохраняет этап ошибки в `failed_at_stage`
- `get_previous_status()` — возвращает предыдущий статус для отката (DOWNLOADING → INITIALIZED, PROCESSING → DOWNLOADED и т.д.)
- `can_retry()` — проверяет возможность retry (есть ошибка, не превышен лимит попыток, `failed_at_stage` валиден)
- `prepare_retry()` — восстанавливает статус из `failed_at_stage`, увеличивает `retry_count`, сбрасывает `failed`

#### Обработка сбоев с сохранением контекста

Обработка проходит через этапы: download → process → transcribe → upload. Для каждого этапа:

1. Определяется начальный этап через `_determine_start_stage()` (использует `failed_at_stage` при retry)
2. Если это retry, вызывается `prepare_retry()` для восстановления статуса этапа
3. При успехе — `mark_success()` переводит на следующий этап
4. При ошибке — `mark_failure()` откатывает к предыдущему статусу, сохраняет контекст в `failed_at_stage`

Для этапа загрузки на платформы используется комбинированный подход:
- Все успешны → `UPLOADED`, `failed=false`
- Частичный успех → `UPLOADED`, `failed=true`, `failed_at_stage=UPLOADING`
- Все провалились → откат к `TRANSCRIBED`, `failed=true`, `failed_at_stage=UPLOADING`

Вспомогательные функции:
- `_determine_start_stage()` — определяет начальный этап (использует `failed_at_stage` при retry, иначе по текущему статусу)
- `_determine_final_upload_status()` — возвращает tuple `(ProcessingStatus, bool)` для определения финального статуса загрузки

#### Дозагрузка на дополнительные платформы

После успешной загрузки на платформы (статус `UPLOADED`) можно добавить дополнительные платформы для дозагрузки:

1. **Добавление новой платформы:**
   - Создается новый `OutputTarget` со статусом `NOT_UPLOADED` через `ensure_target()` или API
   - `ProcessingStatus` автоматически переходит к `UPLOADING` (есть незавершенные платформы)
   - Существующие платформы остаются в статусе `UPLOADED`

2. **Запуск загрузки:**
   - При следующем запуске обработки определяется, что есть платформы со статусом `NOT_UPLOADED`
   - Загрузка выполняется только для новых платформ (уже загруженные пропускаются)
   - Используется тот же процесс загрузки, но только для незавершенных платформ

3. **Определение финального статуса:**
   - После загрузки на новую платформу вызывается `_determine_final_upload_status()`
   - Если все платформы успешны → `UPLOADED`, `failed=false`
   - Если частичный успех → `UPLOADED`, `failed=true` (комбинированный подход)
   - Если все провалились → откат к `TRANSCRIBED`, `failed=true`, `failed_at_stage=UPLOADING`

**Пример:**
- Изначально: VK target = `UPLOADED`, ProcessingStatus = `UPLOADED`, `failed=false`
- Добавлен YouTube target = `NOT_UPLOADED` через API или изменение шаблона
- ProcessingStatus → `UPLOADING` (есть незавершенные платформы)
- После загрузки на YouTube: YouTube = `UPLOADED`, VK = `UPLOADED`
- ProcessingStatus → `UPLOADED`, `failed=false` (все платформы успешны)

**API для добавления платформы:**
- `POST /api/v1/recordings/{recording_id}/targets` — добавить новую платформу для загрузки
- Или изменение шаблона записи с добавлением новых платформ в `output_configs`

### API для управления FSM

#### Перезапуск сломанных этапов

API endpoints:
- `POST /api/v1/recordings/{recording_id}/retry` — перезапускает этап из `failed_at_stage`, проверяет `can_retry()`, вызывает `prepare_retry()` и запускает обработку
- `GET /api/v1/recordings/failed` — возвращает записи с `failed=true`, опциональный фильтр по `failed_at_stage` (этап ошибки)

#### Автоматический retry механизм

Функция `auto_retry_failed_stages()` (вызывается cron):
- Получает записи с `failed=true` и `retry_count < MAX_RETRY_COUNT`
- Проверяет `can_retry()` для каждой
- Вызывает `prepare_retry()` и запускает обработку с `force_retry=False`

### Преимущества

1. **Надежность** — каждый этап изолирован, сбой на одном не влияет на другие
2. **Восстановимость** — можно перезапустить только сломанный этап
3. **Прозрачность** — ясно видно, какой именно этап сломался
4. **Гибкость** — можно перезапускать конкретные этапы независимо
5. **Мониторинг** — легко отслеживать сбои по этапам
6. **Автоматизация** — можно настроить автоматический retry для определенных типов ошибок

### Недостатки и ограничения

1. **Ограничение retry** — максимум 2 попытки, после этого требуется ручное вмешательство
2. **Миграция** — нужно удалить статус `FAILED` из enum и обновить существующие записи (если есть в БД)
3. **Частичные результаты** — нужно аккуратно обрабатывать случаи, когда часть этапов выполнена успешно

### Миграционная стратегия

1. **Фаза 1:** Добавить новые поля в таблицы (`failed`, `failed_at`, `failed_reason`, `retry_count`)
2. **Фаза 2:** Удалить статус `FAILED` из enum `ProcessingStatus` (но оставить в `TargetStatus`)
3. **Фаза 3:** Реализовать `StateTransitionManager` с методами `mark_success`, `mark_failure`, `prepare_retry`
4. **Фаза 4:** Обновить логику обработки для использования булевого флага `failed`
5. **Фаза 5:** Мигрировать существующие записи (если есть):
   - Записи со статусом `FAILED` преобразовать по контексту
   - Определить этап по наличию файлов, метаданных
   - Установить соответствующий статус этапа и `failed=true`
6. **Фаза 6:** Добавить API endpoints для retry (`POST /api/v1/recordings/{id}/retry`)
7. **Фаза 7:** Реализовать автоматический retry механизм (опционально, через cron)

### Миграция существующих данных

Если в базе данных есть записи со статусом `FAILED`, их нужно мигрировать:
- Определить этап по контексту (наличие файлов, метаданных)
- Установить соответствующий статус этапа (DOWNLOADING, PROCESSING, TRANSCRIBING, UPLOADING)
- Установить `failed=true`
- Установить `failed_reason` из доступных данных (если есть)

---

## API спецификация

### Архитектурный стиль `API`

**Выбранный стиль:** `RESTful API` (`REST`)

**Обоснование:**
- Стандартизация и предсказуемость
- Широкая поддержка клиентских библиотек
- Простота интеграции
- Соответствие `HTTP` стандартам

**Альтернативы:**
- `GraphQL` — избыточен для текущих требований, усложняет кэширование
- `gRPC` — требует генерации кодов, менее совместим с веб-клиентами
- `WebSockets` — не нужен для синхронных операций, добавим позже для real-time обновлений

### Базовые принципы

**URL структура:**
```
`/api/v1/{resource}/{id}/{sub-resource}/{sub-id}`
```

**`HTTP` методы:**
- `GET` — получение ресурсов (список, детали)
- `POST` — создание ресурсов, действия
- `PUT` — полное обновление ресурса
- `PATCH` — частичное обновление ресурса
- `DELETE` — удаление ресурсов

**Коды ответов:**
- `200 OK` — успешный запрос
- `201 Created` — ресурс создан
- `204 No Content` — успешное удаление
- `400 Bad Request` — неверные входные данные
- `401 Unauthorized` — требуется аутентификация
- `403 Forbidden` — недостаточно прав
- `404 Not Found` — ресурс не найден
- `409 Conflict` — конфликт данных (например, дублирование)
- `422 Unprocessable Entity` — ошибка валидации
- `429 Too Many Requests` — превышен лимит запросов
- `500 Internal Server Error` — внутренняя ошибка сервера
- `503 Service Unavailable` — сервис временно недоступен

**Формат данных:**
- Request/Response: `JSON`
- Content-Type: `application/json`
- Encoding: `UTF-8`

**Аутентификация:**
- Header: `Authorization: Bearer {JWT_TOKEN}`
- Время жизни токена: 60 минут
- Refresh token: 7 дней

### Детальная спецификация endpoints

#### Authentication

**`POST /api/v1/auth/register`**

Регистрация нового пользователя.

**Request:**
```json
{
  "email": "user@example.com",
  "password": "SecurePassword123!",
  "name": "John Doe"
}
```

**Response 201:**
```json
{
  "id": 1,
  "email": "user@example.com",
  "name": "John Doe",
  "role": "user",
  "created_at": "2025-01-10T12:00:00Z"
}
```

**Ошибки:**
- `400` — неверный формат email или слабый пароль
- `409` — email уже зарегистрирован

---

**`POST /api/v1/auth/login`**

Вход пользователя, получение `JWT` токена.

**Request:**
```json
{
  "email": "user@example.com",
  "password": "SecurePassword123!"
}
```

**Response 200:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 3600,
  "user": {
    "id": 1,
    "email": "user@example.com",
    "name": "John Doe",
    "role": "user"
  }
}
```

**Ошибки:**
- `401` — неверный email или пароль

---

**`POST /api/v1/auth/refresh`**

Обновление access token через refresh token.

**Request:**
```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

**Response 200:**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 3600
}
```

**Ошибки:**
- `401` — неверный или истекший refresh token

---

**`GET /api/v1/auth/me`**

Получение информации о текущем пользователе.

**Headers:**
```
Authorization: Bearer {JWT_TOKEN}
```

**Response 200:**
```json
{
  "id": 1,
  "email": "user@example.com",
  "name": "John Doe",
  "role": "user",
  "can_transcribe": true,
  "can_process_video": true,
  "can_upload": true,
  "max_concurrent_processes": 2,
  "quota_disk_space_gb": null,
  "created_at": "2025-01-10T12:00:00Z",
  "last_login_at": "2025-01-10T14:30:00Z"
}
```

---

#### Recordings

**`GET /api/v1/recordings`**

Получение списка записей с фильтрацией и пагинацией.

**Query параметры:**
- `status` — фильтр по статусу (initialized, downloading, downloaded, processing, processed, transcribing, transcribed, uploading, uploaded, skipped, expired)
- `failed` — фильтр по наличию ошибки (true/false)
- `source_type` — фильтр по типу источника (zoom, local_file, youtube, vk)
- `from_date` — фильтр по дате начала (ISO 8601)
- `to_date` — фильтр по дате окончания (ISO 8601)
- `template_id` — фильтр по шаблону
- `input_source_id` — фильтр по источнику
- `page` — номер страницы (default: 1)
- `per_page` — записей на страницу (default: 20, max: 100)
- `sort` — сортировка (created_at, start_time, duration) (default: start_time)
- `order` — порядок (asc, desc) (default: desc)

**Response 200:**
```json
{
  "items": [
    {
      "id": 1,
      "display_name": "ИИ_1 курс_НИС \"Машинное обучение\"",
      "start_time": "2025-01-10T15:00:00Z",
      "duration": 120,
      "status": "transcribed",
      "is_mapped": true,
      "template_id": 5,
      "input_source_id": 2,
      "source": {
        "source_type": "zoom",
        "source_key": "meeting_uuid_123",
        "metadata": {}
      },
      "outputs": [
        {
          "id": 1,
          "target_type": "youtube",
          "status": "uploaded",
          "preset_id": 1,
          "target_meta": {
            "target_link": "https://youtube.com/watch?v=abc123"
          },
          "uploaded_at": "2025-01-10T16:30:00Z"
        }
      ],
      "video_file_size": 2147483648,
      "created_at": "2025-01-10T15:00:00Z",
      "updated_at": "2025-01-10T16:30:00Z"
    }
  ],
  "pagination": {
    "page": 1,
    "per_page": 20,
    "total": 150,
    "total_pages": 8
  }
}
```

**Ошибки:**
- `400` — неверные параметры фильтрации

---

**`GET /api/v1/recordings/{id}`**

Получение детальной информации о записи.

**Response 200:**
```json
{
  "id": 1,
  "display_name": "ИИ_1 курс_НИС \"Машинное обучение\"",
  "start_time": "2025-01-10T15:00:00Z",
  "duration": 120,
  "status": "transcribed",
  "is_mapped": true,
  "template_id": 5,
  "input_source_id": 2,
  "source": {
    "source_type": "zoom",
    "source_key": "meeting_uuid_123",
    "metadata": {
      "account": "user@example.com",
      "meeting_id": "123456789"
    }
  },
  "outputs": [
    {
      "id": 1,
      "target_type": "youtube",
      "status": "uploaded",
      "preset_id": 1,
      "target_meta": {
        "target_link": "https://youtube.com/watch?v=abc123",
        "video_id": "abc123"
      },
      "uploaded_at": "2025-01-10T16:30:00Z",
      "last_updated_at": null
    }
  ],
  "file_paths": {
    "local_video_path": "user_1/video/unprocessed/recording_1.mp4",
    "processed_video_path": "user_1/video/processed/recording_1_processed.mp4",
    "transcription_dir": "user_1/transcriptions/recording_1/"
  },
  "transcription_info": {
    "model": "fireworks",
    "language": "ru",
    "segments_count": 450
  },
  "main_topics": [
    "Нейронные сети",
    "Обратное распространение ошибки",
    "Обучение модели"
  ],
  "topic_timestamps": [
    {"topic": "Нейронные сети", "start": 120, "end": 1800},
    {"topic": "Обратное распространение ошибки", "start": 1800, "end": 3600}
  ],
  "created_at": "2025-01-10T15:00:00Z",
  "updated_at": "2025-01-10T16:30:00Z"
}
```

**Ошибки:**
- `404` — запись не найдена или принадлежит другому пользователю

---

**`POST /api/v1/recordings/{id}/process`**

Запуск обработки записи (скачивание → обработка → транскрибация → публикация).

**Response 202:**
```json
{
  "message": "Обработка запущена",
  "recording_id": 1,
  "status": "processing",
  "estimated_time": 3600
}
```

**Ошибки:**
- `404` — запись не найдена
- `403` — недостаточно прав или превышен лимит concurrent_processes
- `409` — запись уже обрабатывается

---

**`POST /api/v1/recordings/{id}/update-video`**

Обновление загруженного видео на платформах (название, описание, тэги).

**Request:**
```json
{
  "title": "Новое название",
  "description": "Новое описание",
  "tags": ["новый", "тег"],
  "thumbnail_path": "thumbnails/new_thumbnail.png"
}
```

**Response 200:**
```json
{
  "message": "Видео обновлено",
  "recording_id": 1,
  "updated_platforms": ["youtube", "vk"],
  "last_updated_at": "2025-01-10T17:00:00Z"
}
```

**Ошибки:**
- `404` — запись не найдена
- `403` — недостаточно прав (can_update_uploaded_videos)
- `400` — видео не загружено на платформы

---

**`DELETE /api/v1/recordings/{id}`**

Удаление записи и связанных файлов.

**Response 204:** No Content

**Ошибки:**
- `404` — запись не найдена
- `403` — недостаточно прав (can_delete_recordings)

---

#### Templates

**`GET /api/v1/templates`**

Список шаблонов пользователя.

**Query параметры:**
- `is_draft` — фильтр по черновикам (true/false)
- `is_active` — фильтр по активным (true/false)

**Response 200:**
```json
{
  "items": [
    {
      "id": 1,
      "name": "Лекции ML",
      "description": "Шаблон для лекций по машинному обучению",
      "is_active": true,
      "is_draft": false,
      "priority": 10,
      "matching_rules_count": 3,
      "created_at": "2025-01-05T10:00:00Z",
      "updated_at": "2025-01-08T14:30:00Z"
    }
  ]
}
```

---

**`GET /api/v1/templates/{id}`**

Детальная информация о шаблоне.

**Response 200:**
```json
{
  "id": 1,
  "name": "Лекции ML",
  "description": "Шаблон для лекций по машинному обучению",
  "is_active": true,
  "is_draft": false,
  "priority": 10,
  "processing_config": {
    "enable_processing": true,
    "audio_detection": true,
    "silence_threshold": -40.0
  },
  "transcription_config": {
    "enable_transcription": true,
    "language": "ru",
    "enable_topics": true,
    "topic_mode": "long"
  },
  "metadata_config": {
    "title_template": "(Л) Машинное обучение | {topic} ({date})",
    "description_template": "Лекция по машинному обучению.\n\nТемы:\n{topics_list}",
    "thumbnail_path": "thumbnails/ml.png",
    "topics_display": {
      "enabled": true,
      "max_count": 10,
      "format": "numbered_list"
    }
  },
  "output_configs": [
    {
      "preset_id": 1,
      "enabled": true,
      "playlist_id": "PL...",
      "privacy": "unlisted"
    }
  ],
  "matching_rules": [
    {
      "id": 1,
      "match_type": "exact",
      "pattern": "ИИ_1 курс_НИС \"Машинное обучение\"",
      "match_source_type": "zoom",
      "rule_priority": 0
    }
  ],
  "created_at": "2025-01-05T10:00:00Z",
  "updated_at": "2025-01-08T14:30:00Z"
}
```

---

**`POST /api/v1/templates`**

Создание нового шаблона.

**Request:**
```json
{
  "name": "Новый шаблон",
  "description": "Описание шаблона",
  "is_active": true,
  "priority": 5,
  "processing_config": {},
  "transcription_config": {},
  "metadata_config": {
    "title_template": "{original_title} | {topic} ({date})"
  },
  "output_configs": [],
  "matching_rules": [
    {
      "match_type": "contains",
      "pattern": "ML",
      "match_source_type": "zoom",
      "rule_priority": 0
    }
  ]
}
```

**Response 201:**
```json
{
  "id": 5,
  "name": "Новый шаблон",
  "created_at": "2025-01-10T18:00:00Z"
}
```

**Ошибки:**
- `400` — неверные данные (валидация)
- `403` — недостаточно прав (can_create_templates)
- `409` — шаблон с таким именем уже существует

---

**`PUT /api/v1/templates/{id}`**

Полное обновление шаблона.

**Request:** (аналогично POST, все поля)

**Response 200:** (обновленный шаблон)

---

**`DELETE /api/v1/templates/{id}`**

Удаление шаблона.

**Response 204:** No Content

**Ошибки:**
- `404` — шаблон не найден
- `409` — шаблон используется в записях (можно только деактивировать)

---

#### Input Sources

**`GET /api/v1/input-sources`**

Список источников данных пользователя.

**Response 200:**
```json
{
  "items": [
    {
      "id": 1,
      "source_type": "zoom",
      "name": "Zoom Основной",
      "credential_id": 2,
      "source_settings": {
        "sync_automatically": false
      },
      "is_active": true,
      "created_at": "2025-01-05T10:00:00Z"
    },
    {
      "id": 2,
      "source_type": "yandex_disk",
      "name": "Yandex Disk Лекции",
      "credential_id": 3,
      "source_settings": {
        "folder_path": "/Videos/Lectures",
        "folder_url": "https://disk.yandex.ru/d/...",
        "use_api": true
      },
      "is_active": true,
      "created_at": "2025-01-06T12:00:00Z"
    }
  ]
}
```

---

**`POST /api/v1/input-sources/{id}/sync`**

Синхронизация источника (получение новых записей).

**Response 202:**
```json
{
  "message": "Синхронизация запущена",
  "input_source_id": 1,
  "estimated_time": 300
}
```

**Ошибки:**
- `404` — источник не найден
- `400` — источник неактивен или нет credentials

---

#### Output Presets

**`GET /api/v1/output-presets`**

Список preset'ов пользователя.

**Response 200:**
```json
{
  "items": [
    {
      "id": 1,
      "name": "YouTube Основной",
      "description": "Основной YouTube канал",
      "target_type": "youtube",
      "credential_id": 4,
      "is_active": true,
      "created_at": "2025-01-05T10:00:00Z"
    }
  ]
}
```

---

**`POST /api/v1/output-presets`**

Создание нового preset'а.

**Request:**
```json
{
  "name": "VK Группа 1",
  "description": "Основная группа VK",
  "target_type": "vk",
  "credential_id": 5
}
```

**Response 201:**
```json
{
  "id": 3,
  "name": "VK Группа 1",
  "created_at": "2025-01-10T18:00:00Z"
}
```

---

#### Credentials

**`GET /api/v1/credentials`**

Список credentials пользователя (без расшифрованных данных).

**Response 200:**
```json
{
  "items": [
    {
      "id": 1,
      "credential_type": "zoom",
      "credential_key": "user@example.com",
      "metadata": {
        "account_id": "abc123",
        "description": "Основной аккаунт"
      },
      "is_active": true,
      "created_at": "2025-01-05T10:00:00Z"
    }
  ]
}
```

**Важно:** Зашифрованные данные никогда не передаются в API.

---

**`POST /api/v1/credentials`**

Создание нового credential.

**Request:**
```json
{
  "credential_type": "youtube",
  "credential_key": "main_account",
  "data": {
    "client_secrets": {...},
    "token": {...},
    "scopes": [...]
  }
}
```

**Response 201:**
```json
{
  "id": 6,
  "credential_type": "youtube",
  "credential_key": "main_account",
  "created_at": "2025-01-10T18:00:00Z"
}
```

**Ошибки:**
- `400` — неверный формат данных для типа credential
- `403` — недостаточно прав (can_manage_credentials)

---

#### Thumbnails

**`POST /api/v1/thumbnails`**

Загрузка миниатюры.

**Request:** multipart/form-data
- `file` — файл изображения (PNG, JPEG, max 5MB)
- `name` — название миниатюры

**Response 201:**
```json
{
  "id": 1,
  "name": "ml_thumbnail",
  "file_path": "thumbnails/ml_thumbnail.png",
  "file_size": 245760,
  "width": 1280,
  "height": 720,
  "created_at": "2025-01-10T18:00:00Z"
}
```

**Ошибки:**
- `400` — неверный формат файла или превышен размер
- `422` — файл не прошел валидацию (неверные пропорции, размер)

---

**`GET /api/v1/thumbnails/{id}/file`**

Получение файла миниатюры.

**Response 200:** image/png или image/jpeg

---

#### Configs

**`GET /api/v1/configs/base`**

Получение базового конфига пользователя.

**Response 200:**
```json
{
  "processing_config": {},
  "transcription_config": {},
  "default_metadata_config": {},
  "default_output_configs": []
}
```

---

**`PUT /api/v1/configs/base`**

Обновление базового конфига пользователя.

**Request:**
```json
{
  "processing_config": {
    "enable_processing": true,
    "audio_detection": true
  },
  "transcription_config": {
    "enable_transcription": true,
    "language": "ru"
  }
}
```

---

#### Health & Metrics

**`GET /api/v1/health`**

Health check системы.

**Response 200:**
```json
{
  "status": "healthy",
  "database": "connected",
  "disk_space": {
    "total_gb": 500,
    "used_gb": 120,
    "available_gb": 380
  },
  "version": "1.0.0"
}
```

---

**`GET /api/v1/metrics`**

Метрики текущего пользователя.

**Response 200:**
```json
{
  "user_id": 1,
  "recordings": {
    "total": 150,
    "by_status": {
      "initialized": 10,
      "downloaded": 20,
      "processed": 30,
      "transcribed": 50,
      "uploaded": 40
    }
  },
  "disk_usage": {
    "used_gb": 45.2,
    "quota_gb": null,
    "usage_percent": null
  },
  "processing": {
    "active": 2,
    "max_concurrent": 2
  }
}
```

---

## Технические детали реализации

### Архитектура приложения

**Выбранный подход:** Layered Architecture (Многослойная архитектура)

**Слои:**
1. **API Layer** — `FastAPI` endpoints, валидация, аутентификация
2. **Service Layer** — бизнес-логика, оркестрация
3. **Repository Layer** — доступ к данным, абстракция БД
4. **Infrastructure Layer** — внешние сервисы, файловая система

**Преимущества:**
- Четкое разделение ответственности
- Легкое тестирование (можно мокировать слои)
- Независимость от деталей реализации
- Возможность замены компонентов

### Обработка запросов

**Middleware Pipeline:**
```
┌─────────────────────────────────────────────────────────────────┐
│                    Request Flow                                 │
└─────────────────────────────────────────────────────────────────┘

    `HTTP` Request
         │
         ▼
┌────────────────┐
│ CORS Middleware│  ── Проверка CORS headers
│                │     Allow/Deny по настройкам
└────────┬───────┘
         │
         ▼
┌────────────────┐
│ Auth Middleware│  ── Извлечение JWT token
│                │     Валидация токена
│                │     Извлечение user_id, role
│                │     Добавление в request context
└────────┬───────┘
         │
         ▼
┌────────────────┐
│ Rate Limiting  │  ── Проверка лимита запросов
│ Middleware     │     Redis/in-memory cache
│                │     `Sliding window` algorithm
│                │     429 если превышен
└────────┬───────┘
         │
         ▼
┌────────────────┐
│ Request        │  ── Валидация входных данных (`Pydantic`)
│ Handler        │     Вызов Service Layer
│                │     Обработка бизнес-логики
│                │     Формирование ответа
└────────┬───────┘
         │
         ▼
    `HTTP` Response
         │
         ▼
┌────────────────┐
│ Error Handler  │  ── Обработка исключений
│ (if error)     │     Форматирование ошибок
│                │     Логирование
└────────────────┘
```

**Auth Middleware:**
- Извлекает `JWT` token из заголовка
- Валидирует токен
- Извлекает `user_id` и `role`
- Добавляет в request context
- Автоматически фильтрует запросы по `user_id`

**Rate Limiting Middleware:**
- Проверяет лимит пользователя (`rate_limit_per_minute`)
- Использует `Redis` или in-memory cache
- Возвращает `429` при превышении лимита
- Использует `sliding window` алгоритм

### Доступ к данным

**Выбранный подход:** Repository Pattern + `SQLAlchemy` `ORM`

**Структура:**
- Repository абстрагирует доступ к БД
- Использует `SQLAlchemy` для запросов
- Автоматическая фильтрация по `user_id`
- Connection pooling через `SQLAlchemy`

**Пример Repository:**
```python
class RecordingRepository:
    def __init__(self, session: AsyncSession, user_id: int):
        self.session = session
        self.user_id = user_id  # Автоматическая изоляция
    
    async def get_by_id(self, recording_id: int) -> Recording | None:
        # Автоматически фильтрует по user_id
        query = select(RecordingModel).where(
            RecordingModel.id == recording_id,
            RecordingModel.user_id == self.user_id
        )
        # ...
```

**Преимущества:**
- Изоляция данных на уровне репозитория
- Легко тестировать (можно мокировать)
- Переиспользование логики доступа к данным

### Управление транзакциями

**Подход:** Явные транзакции через async context manager

**Принцип:**
- Каждый бизнес-операция выполняется в транзакции
- Откат при ошибке
- Автоматический commit при успехе

**Надежность:**
- `ACID` гарантии `PostgreSQL`
- Защита от race conditions
- Консистентность данных

### Кэширование

**Стратегия:** Lazy caching для часто используемых данных

**Кэшируемые данные:**
- Базовые конфиги пользователей (`TTL`: 5 минут)
- Информация о пользователе (`TTL`: 1 минута)
- Список активных шаблонов (`TTL`: 1 минута)

**Используемые технологии:**
- `Redis` (для production)
- In-memory cache (для development)

**Инвалидация кэша:**
- При обновлении конфигов
- При изменении шаблонов
- По TTL

### Обработка длительных операций

**Проблема:** Обработка видео, транскрибация могут занимать часы.

**Решение:** Асинхронная обработка через фоновые задачи

**Подход:**
- API возвращает `202 Accepted` сразу
- Задача запускается в фоновом процессе
- Статус отслеживается через поле `status` в БД
- Пользователь может проверить статус через API

**Альтернативы:**
- `WebSockets` для real-time обновлений (добавим в будущем)
- Polling через `API` (текущий подход)

---

## Обработка ошибок и надежность

### Стратегия обработки ошибок

**Уровни обработки:**
1. **Validation Errors** — ошибки валидации входных данных (400, 422)
2. **Business Logic Errors** — бизнес-ошибки (403, 409)
3. **Not Found Errors** — ресурсы не найдены (404)
4. **System Errors** — внутренние ошибки (500, 503)

### Обработка ошибок на уровне API

**Стандартизированный формат ошибок:**
```json
{
  "error": {
    "code": "RECORDING_NOT_FOUND",
    "message": "Запись с ID 123 не найдена",
    "details": {
      "recording_id": 123,
      "user_id": 1
    },
    "timestamp": "2025-01-10T18:00:00Z"
  }
}
```

**Коды ошибок:**
- `VALIDATION_ERROR` — ошибка валидации
- `AUTHENTICATION_REQUIRED` — требуется аутентификация
- `PERMISSION_DENIED` — недостаточно прав
- `RESOURCE_NOT_FOUND` — ресурс не найден
- `RESOURCE_CONFLICT` — конфликт ресурсов
- `RATE_LIMIT_EXCEEDED` — превышен лимит запросов
- `PROCESSING_ERROR` — ошибка обработки
- `EXTERNAL_SERVICE_ERROR` — ошибка внешнего сервиса
- `INTERNAL_ERROR` — внутренняя ошибка

### Обработка ошибок при обработке записей

**Retry Strategy:**
- Экспоненциальная задержка (2s → 4s → 8s)
- Максимум 3 попытки
- Для критических операций (транскрибация, загрузка)

**Обработка частичных сбоев:**
- Сохранение промежуточного состояния
- Возможность продолжения с последнего успешного шага
- Статусы для отслеживания прогресса

**Статусы обработки:**
- `INITIALIZED` — инициализировано
- `DOWNLOADING` — загрузка
- `DOWNLOADED` — загружено
- `PROCESSING` — обработка
- `PROCESSED` — обработано
- `TRANSCRIBING` — транскрибация
- `TRANSCRIBED` — транскрибировано
- `UPLOADING` — загрузка на платформы
- `UPLOADED` — загружено
- `SKIPPED` — пропущено

**Примечание:** При ошибке статус остается на текущем этапе, устанавливается `failed=true`. См. ADR-015.

### Надежность системы

**Гарантии:**
1. **Изоляция данных** — гарантия через фильтрацию по `user_id` на всех уровнях
2. **Транзакционность** — ACID гарантии PostgreSQL
3. **Отказоустойчивость** — retry механизмы, обработка сбоев
4. **Консистентность** — валидация на всех уровнях

**Мониторинг:**
- Логирование всех ошибок
- Метрики производительности
- Health checks
- Алерты при критических ошибках

### Обработка сбоев внешних сервисов

**Проблема:** Зависимость от внешних API (Zoom, YouTube, Fireworks, DeepSeek).

**Стратегия:**
- Timeout для всех внешних запросов
- Retry с экспоненциальной задержкой
- Circuit breaker для защиты от каскадных сбоев
- Fallback стратегии где возможно

**Обработка временных сбоев:**
- При ошибке: статус остается на текущем этапе, устанавливается `failed=true`
- Возможность retry через API (максимум 2 попытки)
- Сохранение контекста ошибки (`failed_reason`, `failed_at`)
- Уведомление пользователя (см. ADR-014)
- Подробнее см. [ADR-015: FSM для надежной обработки](#adr-015-fsm-для-надежной-обработки)

---

## Сравнение с альтернативными подходами

### ADR-001: Multi-Tenancy

**Выбрано:** Shared Database + Tenant ID

**Альтернативы:**

#### Separate Databases

**Преимущества:**
- Полная изоляция данных
- Легче бэкапы по клиентам
- Проще масштабировать отдельные клиенты

**Недостатки:**
- Сложнее управление (много БД)
- Сложнее миграции (нужно применять к каждой БД)
- Больше ресурсов (каждая БД потребляет память)
- Сложнее кросс-клиентские запросы (метрики, аналитика)

**Вывод:** Подходит для enterprise с небольшим количеством крупных клиентов. Для SaaS с множеством мелких клиентов — избыточно.

#### Separate Schemas (`PostgreSQL`)

**Преимущества:**
- Изоляция на уровне схем
- Легче бэкапы (можно бэкапить схему)
- Одна БД, но изоляция

**Недостатки:**
- Ограничения PostgreSQL (макс. схем)
- Сложнее кросс-схемные запросы
- Нужно динамически переключать схему в запросах
- Сложнее миграции

**Вывод:** Хороший компромисс, но усложняет архитектуру запросов.

**Итог:** Shared Database оптимален для текущих требований (много мелких пользователей, простота управления).

---

### ADR-002: Аутентификация

**Выбрано:** JWT Tokens

**Альтернативы:**

#### Session-based Authentication

**Преимущества:**
- Можно отозвать сессию
- Проще управление

**Недостатки:**
- Требует хранение сессий (Redis/БД)
- Не stateless
- Сложнее масштабировать

**Вывод:** Подходит для монолитных приложений, но для API-first архитектуры JWT предпочтительнее.

#### `OAuth 2.0` / `OIDC`

**Преимущества:**
- Стандартный протокол
- Интеграция с внешними провайдерами

**Недостатки:**
- Сложнее в реализации
- Overkill для внутренней аутентификации
- Требует дополнительной инфраструктуры

**Вывод:** Подходит если нужна интеграция с внешними провайдерами (Google, GitHub). Для начала достаточно JWT.

---

### ADR-003: Хранение конфигураций

**Выбрано:** JSONB в PostgreSQL

**Альтернативы:**

#### Отдельные таблицы для каждой настройки

**Преимущества:**
- Строгая типизация
- Легче делать запросы

**Недостатки:**
- Много JOIN'ов
- Сложнее расширять
- Много миграций при изменениях

**Вывод:** Избыточно для гибких конфигураций.

#### Отдельные JSON файлы

**Преимущества:**
- Простота
- Версионирование через Git

**Недостатки:**
- Сложнее управлять в multi-tenant
- Нет централизованного хранения
- Сложнее бэкапы
- Нет транзакционности

**Вывод:** Подходит для single-user, но не для multi-tenant.

**Итог:** JSONB оптимален для гибких конфигураций с возможностью запросов и индексации.

---

### ADR-004: Шифрование credentials

**Выбрано:** pgcrypto (PostgreSQL)

**Альтернативы:**

#### Application-level Encryption

**Преимущества:**
- Не зависит от БД
- Можно использовать разные алгоритмы

**Недостатки:**
- Шифрование/дешифрование в приложении
- Нужно хранить ключи в приложении
- Больше нагрузки на приложение

**Вывод:** Подходит если нужна независимость от БД или специфичные алгоритмы.

#### Внешний секрет-менеджер (`Vault`, `AWS Secrets Manager`)

**Преимущества:**
- Централизованное управление ключами
- Ротация ключей
- Аудит доступа

**Недостатки:**
- Дополнительная инфраструктура
- Сложнее setup
- Зависимость от внешнего сервиса

**Вывод:** Подходит для enterprise, но избыточно для MVP.

**Итог:** pgcrypto оптимален для баланса простоты и безопасности.

---

## Архитектурный стиль

### Общие принципы

**API-First Design:**
- API проектируется как основной интерфейс
- CLI и UI используют API
- Документация API через OpenAPI/Swagger

**Domain-Driven Design (`DDD`) элементы:**
- Четкое разделение доменов (recordings, templates, credentials)
- Репозитории для доступа к данным
- Сервисы для бизнес-логики

**`RESTful` принципы:**
- Ресурсо-ориентированный дизайн
- Стандартные HTTP методы
- Предсказуемые URL
- Стандартные коды ответов

### Паттерны проектирования

**`Repository Pattern`:**
- Абстракция доступа к данным
- Изоляция от деталей БД
- Легкое тестирование

**`Service Layer Pattern`:**
- Бизнес-логика в сервисах
- API layer только маршрутизация и валидация
- Переиспользование логики

**`Factory Pattern`:**
- Создание объектов конфигурации (ProcessingConfig, TranscriptionConfig)
- Валидация при создании

**`Strategy Pattern`:**
- Разные стратегии обработки для разных платформ (YouTube, VK)
- Разные стратегии сопоставления (exact, regex, contains)

### Принципы SOLID

**Single Responsibility:**
- Каждый класс отвечает за одну вещь
- Разделение concerns (API, бизнес-логика, данные)

**Open/Closed:**
- Открыт для расширения (новые платформы, новые типы источников)
- Закрыт для модификации (не меняем существующий код)

**Liskov Substitution:**
- Интерфейсы для платформ, источников
- Возможность замены реализации

**Interface Segregation:**
- Узкие интерфейсы (IUploader, ITranscriber)
- Клиенты не зависят от неиспользуемых методов

**Dependency Inversion:**
- Зависимость от абстракций, а не от конкретных классов
- Dependency Injection через конструкторы

### Масштабируемость

**Вертикальное масштабирование:**
- Оптимизация запросов к БД
- Индексы на часто используемых полях
- Connection pooling

**Горизонтальное масштабирование:**
- Stateless API (JWT tokens)
- Shared Database (легко масштабировать)
- Возможность добавления инстансов API

**Будущие улучшения:**
- Кэширование через Redis
- Очередь задач (`Celery`/`RQ`) для длительных операций
- `Object Storage` для файлов

---

## Приложение A: Структуры JSONB

### system_processing_config
Системные настройки обработки видео (не задаются пользователем).

```json
{
  "video_codec": "copy",
  "audio_codec": "copy",
  "video_bitrate": "original",
  "audio_bitrate": "original",
  "resolution": "original",
  "fps": 0,
  "output_format": "mp4"
}
```

### processing_config (user/template)
Пользовательские настройки обработки.

```json
{
  "enable_processing": true,
  "audio_detection": true,
  "silence_threshold": -40.0,
  "min_silence_duration": 2.0,
  "padding_before": 5.0,
  "padding_after": 5.0
}
```

### transcription_config
Настройки транскрибации.

```json
{
  "enable_transcription": true,
  "language": "ru",
  "prompt": "Это лекция по машинному обучению. Используй технические термины.",
  "temperature": 0.0,
  "enable_topics": true,
  "topic_mode": "long",
  "enable_subtitles": true,
  "enable_translation": false,
  "translation_language": "en"
}
```

### metadata_config
Метаданные для публикации.

```json
{
  "title_template": "(Л) Генеративные модели [base] | {topic} ({date})",
  "description_template": "Лекция по генеративным моделям.\n\nТемы:\n{topics_list}\n\nДлительность: {duration}",
  "thumbnail_path": "thumbnails/gen_models_base.png",
  "tags": ["лекция", "ml", "generative-models"],
  "category": "Education",
  "topics_display": {
    "enabled": true,
    "max_count": 10,
    "min_length": 5,
    "max_length": 100,
    "display_location": "description",
    "format": "numbered_list",
    "separator": "\n",
    "prefix": "Темы:",
    "include_timestamps": false
  }
}
```

### output_configs (в шаблоне)
Настройки вывода для каждой платформы.

```json
[
  {
    "preset_id": 1,
    "enabled": true,
    "playlist_id": "PLmA-1xX7IuzC-MkRlR8XdGJQlQUKigDR9",
    "privacy": "unlisted",
    "default_language": "ru",
    "upload_captions": true,
    "category_id": "27"
  },
  {
    "preset_id": 2,
    "enabled": true,
    "album_id": "46",
    "privacy_view": "0",
    "privacy_comment": "1",
    "no_comments": false
  }
]
```

---

## Приложение B: Переменные в шаблонах

### Доступные переменные

- `{original_title}` — Оригинальное название записи
- `{topic}` — Первая/главная тема из транскрибации
- `{topics_list}` — Список всех топиков (форматированный согласно `topics_display`)
- `{date}` — Дата в формате DD.MM.YYYY
- `{duration}` — Длительность (Xч Yм)
- `{source_name}` — Название источника (из `input_sources.name`)

### Примеры использования

**Шаблон названия:**
```
(Л) Генеративные модели | {topic} ({date})
```

**Результат:**
```
(Л) Генеративные модели | Нейронные сети и GPT ({25.12.2024})
```

**Шаблон описания:**
```
Лекция по генеративным моделям.

Темы:
{topics_list}

Длительность: {duration}
```

**Результат:**
```
Лекция по генеративным моделям.

Темы:
1. Нейронные сети и GPT
2. Трансформеры
3. Fine-tuning моделей

Длительность: 2ч 15м
```

---

## Приложение C: Схема файловой системы

### Структура директорий

```
media/
│
├── user_1/                          # Изоляция по пользователям
│   ├── video/
│   │   ├── unprocessed/             # Исходные видео
│   │   │   └── recording_123.mp4
│   │   ├── processed/               # Обработанные видео
│   │   │   └── recording_123_processed.mp4
│   │   └── temp_processing/         # Временные файлы
│   │       └── temp_*.mp4
│   │
│   ├── processed_audio/             # Извлеченное аудио
│   │   └── recording_123_processed.mp3
│   │
│   ├── transcriptions/              # Транскрипции
│   │   └── recording_123/
│   │       ├── words.txt
│   │       ├── segments.txt
│   │       ├── segments_auto.txt
│   │       ├── subtitles.srt
│   │       └── subtitles.vtt
│   │
│   └── thumbnails/                  # Миниатюры
│       ├── ml_thumbnail.png
│       └── gen_models_base.png
│
├── user_2/                          # Данные другого пользователя
│   └── ...
│
└── user_N/                          # Данные N-го пользователя
    └── ...
```

### Принципы организации

**Изоляция:**
- Каждый пользователь имеет свою директорию `user_{id}/`
- Невозможен доступ к файлам других пользователей
- Легко удалять данные пользователя (удаление директории)

**Бэкапы:**
- Можно бэкапить по пользователю (вся директория `user_{id}/`)
- Простое восстановление данных пользователя

**Масштабирование:**
- В будущем возможна миграция на `Object Storage` (`S3`)
- Структура директорий сохранится

---

## Приложение D: Схема аутентификации

### JWT Token Flow

```
┌─────────────────────────────────────────────────────────────┐
│                   Authentication Flow                       │
└─────────────────────────────────────────────────────────────┘

    ┌──────────┐                                    ┌──────────┐
    │  Client  │                                    │   API    │
    └────┬─────┘                                    └────┬─────┘
         │                                                │
         │  `POST /api/v1/auth/login`                      │
         │  { email, password }                          │
         ├───────────────────────────────────────────────►
         │                                                │
         │                                    ┌───────────▼──────┐
         │                                    │ Verify Credentials│
         │                                    │ (email, password) │
         │                                    └───────────┬──────┘
         │                                                │
         │                                    ┌───────────▼──────┐
         │                                    │ Generate JWT     │
         │                                    │ - user_id        │
         │                                    │ - role           │
         │                                    │ - exp (1 hour)   │
         │                                    └───────────┬──────┘
         │                                                │
         │  Response                                      │
         │  {                                             │
         │    access_token: "JWT_TOKEN",                  │
         │    refresh_token: "REFRESH_TOKEN",             │
         │    expires_in: 3600                            │
         │  }                                             │
         ◄───────────────────────────────────────────────┤
         │                                                │
         │  Store tokens                                  │
         │  (localStorage / HTTP-only cookie)             │
         │                                                │
         │  Subsequent Requests                           │
         │  `GET /api/v1/recordings`                        │
         │  Header: Authorization: Bearer {JWT_TOKEN}     │
         ├───────────────────────────────────────────────►
         │                                                │
         │                                    ┌───────────▼──────┐
         │                                    │ Validate JWT     │
         │                                    │ Extract user_id  │
         │                                    │ Add to context   │
         │                                    └───────────┬──────┘
         │                                                │
         │                                    ┌───────────▼──────┐
         │                                    │ Process Request  │
         │                                    │ Filter by user_id│
         │                                    └───────────┬──────┘
         │                                                │
         │  Response (filtered data)                      │
         ◄───────────────────────────────────────────────┤
```

### Token Refresh Flow

```
┌─────────────────────────────────────────────────────────────┐
│                  Token Refresh Flow                         │
└─────────────────────────────────────────────────────────────┘

    ┌──────────┐                                    ┌──────────┐
    │  Client  │                                    │   API    │
    └────┬─────┘                                    └────┬─────┘
         │                                                │
         │  `POST /api/v1/auth/refresh`                    │
         │  { refresh_token: "..." }                     │
         ├───────────────────────────────────────────────►
         │                                                │
         │                                    ┌───────────▼──────┐
         │                                    │ Validate Refresh │
         │                                    │ Token            │
         │                                    └───────────┬──────┘
         │                                                │
         │                                    ┌───────────▼──────┐
         │                                    │ Generate New     │
         │                                    │ Access Token     │
         │                                    └───────────┬──────┘
         │                                                │
         │  Response                                      │
         │  {                                             │
         │    access_token: "NEW_JWT_TOKEN",              │
         │    expires_in: 3600                            │
         │  }                                             │
         ◄───────────────────────────────────────────────┤
         │                                                │
         │  Update stored token                           │
```

---

## Следующие шаги

Подробный чеклист по этапам (в указанной очередности), отражающий решения `ADR` и снижающий риски миграции.

### Фаза 0: Stabilization & groundwork (1–2 недели)
- [ ] Зафиксировать зависимости (`requirements.txt` / `poetry.lock`) и единый стиль/линтинг (`ruff`, `black`, `mypy` при возможности).
- [ ] Создать baseline миграций `Alembic` и единый `.env` контракт (секреты для `pgcrypto`, секрет `JWT`, путь `media/user_{id}`).
- [ ] Включить базовое наблюдение: структурированное логирование, health-check `/api/v1/health`, метрики диска/CPU.

### Фаза 1: Данные и идентификация (2–3 недели)
- [ ] Применить миграции `Alembic` для `users`, `base_configs`, `user_credentials`, `output_presets`, `input_sources`, `recording_templates`, `template_matching_rules`, расширений `recordings` / `output_targets` / `source_metadata` (поля `user_id`, `preset_id`, `failed`, `failed_at_stage` и др. по `ADR-015`).
- [ ] Настроить `pgcrypto`, шифрование `user_credentials.encrypted_data`, валидацию `metadata`.
- [ ] Реализовать `JWT` аутентификацию + middleware, добавляющее `user_id` в контекст и фильтрацию запросов.
- [ ] Ввести `QuotaService` и таблицу `quota_usage` (ADR-012): проверки `max_concurrent_processes`, `max_recordings_per_month`, `max_file_size_mb`.
- [ ] Сконвертировать существующие данные: создать `default@system.local`, перенести медиа в `media/user_1/`, загрузить глобальный базовый конфиг.

### Фаза 2: API и многоарендность (2–3 недели)
- [ ] Реализовать CRUD `API` для `credentials`, `output_presets`, `input_sources`, `recordings`, `recording_templates`, `template_matching_rules` (валидация `Pydantic`, единый формат ошибок).
- [ ] Гарантировать изоляцию: репозитории принимают `user_id`, индексы по `user_id`, нормализация путей `media/user_{id}/...`.
- [ ] Добавить rate limiting per-user (`rate_limit_per_minute`) и флаги/роли (`admin`, `user`, `can_*`) в middleware.
- [ ] Реализовать deep-merge конфигов (`global` → `user` → `template`) и snapshot применённого конфига в `recordings`.

### Фаза 3: Пайплайн и FSM (3–4 недели)
- [ ] Внедрить `StateTransitionManager` (ADR-015) для `ProcessingStatus` и `TargetStatus`, заменить статус `FAILED` на флаг `failed` + `failed_at_stage`.
- [ ] Обновить pipeline (download → process → transcribe → upload) под FSM: откаты, `retry_count`, идемпотентность, частичный успех для нескольких платформ.
- [ ] Обновить `OutputTarget`: дозагрузки, частичные успехи, `POST /api/v1/recordings/{id}/retry`.
- [ ] Согласовать генерацию путей/метаданных с новой иерархией; включить схемы транскрипции/топиков в `recordings.transcription_info`.
- [ ] Покрыть тестами: unit для FSM переходов, интеграционные для полного пайплайна с моками внешних `API`.

### Фаза 4: Автоматизация и наблюдаемость (2–3 недели)
- [ ] Реализовать `AutomationService` на `APScheduler`: группировка по времени, TTL-кэш шаблонов, ограничения `max_concurrent_processes`.
- [ ] Добавить аудит (ADR-013, MVP): запись ключевых действий в `audit_logs`, API выборка с учётом `user_id` / `role`.
- [ ] Включить уведомления ядра (ADR-014, MVP): email об ошибках `processing/transcription/upload`, дневные сводки (опционально).
- [ ] Расширить метрики/алерты: этапы, `failed_at_stage`, использование квот, деградация внешних `API`.

### Фаза 5: Масштабирование и отказоустойчивость (будущее)
- [ ] Ввести `QueueTaskExecutor` на `Celery`/`Redis`, приоритизацию, отложенные задачи, circuit breaker для внешних `API`.
- [ ] Перенести медиа в `S3`-совместимое хранилище, добавить CDN/префетч для миниатюр.
- [ ] Расширить UI/UX: управление шаблонами/квотами/аудитом, real-time через `WebSocket`.
- [ ] Настроить retention: архивация `audit_logs` и `notifications`, очистка медиа по `expire_at`.

---

**Конец документа**

