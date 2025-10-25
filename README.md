# Zoom Video Processing Pipeline

Автоматизированная система для загрузки, обработки и публикации записей Zoom на видео-платформы (YouTube, VK).

## 🎯 Возможности

- 🔄 **Автоматическая синхронизация** записей из Zoom API
- 📥 **Многопоточная загрузка** видео с фильтрацией по длительности
- 🎬 **Обработка видео** с помощью FFmpeg (обрезка, сжатие, улучшение качества)
- 📤 **Загрузка на платформы** YouTube и VK с автоматическим созданием плейлистов/альбомов
- 🗄️ **База данных** для отслеживания статуса обработки
- 📊 **Детальное логирование** всех операций
- 🎯 **Интерактивный режим** для выбора записей

## 🔧 Как это работает

### Процесс обработки

Система работает в несколько этапов:

1. **Синхронизация** (`sync`)
   - Получение списка записей из Zoom API
   - Фильтрация по длительности (>30 мин) и размеру (>40 МБ)
   - Сохранение метаданных в базу данных
   - Проверка маппинга названий записей

2. **Загрузка** (`download`)
   - Многопоточное скачивание видео файлов с Zoom
   - Отслеживание прогресса загрузки
   - Сохранение в `video/unprocessed_video/`
   - Обновление статуса на `DOWNLOADED`

3. **Обработка** (`process`)
   - Детекция сегментов с отсутствием звука
   - Обрезка "тихих" частей из видео (пустое начало и конец)
   - Экспорт в `video/processed_video/`
   - Обновление статуса на `PROCESSED`

4. **Загрузка на платформы** (`upload`)
   - Получение метаданных из конфигурации
   - Загрузка на YouTube с миниатюрой
   - Загрузка в VK с добавлением в альбомы
   - Управление превью и описаниями
   - Обновление статусов платформ

### Управление состоянием

Система использует статусы для отслеживания прогресса:
- `ProcessingStatus` - общий статус обработки (INITIALIZED → DOWNLOADED → PROCESSED → UPLOADED)
- `PlatformStatus` - статус загрузки на конкретные платформы (youtube, vk)

### Маппинг записей

Система автоматически сопоставляет названия Zoom записей с метаданными:
- Подбор подходящего превью из каталога
- Выбор категории и настроек обработки
- Настройка параметров загрузки для платформ

## 🎛️ Команды

### Просмотр записей
```bash
python main.py list                              # Записи за сегодня
python main.py list --last 7                     # За последние 7 дней
python main.py list --from 2024-10-01            # С определенной даты
```

### Синхронизация
```bash
python main.py sync                              # Синхронизация за 14 дней
python main.py sync --last 7                     # За 7 дней
```

### Загрузка видео
```bash
python main.py download --all                    # Все записи >30 мин
python main.py download --recordings "1,4,7"     # По ID
```

### Обработка видео
```bash
python main.py process --all                     # Обработать все
python main.py process --recordings "1,4,7"      # По ID
```

### Загрузка на платформы
```bash
python main.py upload --youtube --all            # На YouTube
python main.py upload --all-platforms --all      # На все платформы
python main.py upload --youtube --all -i         # Интерактивно
```

### Полный пайплайн
```bash
python main.py full-process --all                # Скачать + обработать + загрузить
python main.py full-process --youtube --all -i   # Интерактивно
```

### Управление
```bash
python main.py reset                             # Сбросить статусы
python main.py clean --days 14                   # Очистить старые записи
```

## 📊 Статусы обработки

- `INITIALIZED` - Инициализировано (загружено из Zoom API)
- `DOWNLOADING` - В процессе загрузки
- `DOWNLOADED` - Загружено
- `PROCESSING` - В процессе обработки
- `PROCESSED` - Обработано
- `UPLOADING` - В процессе загрузки на платформу
- `UPLOADED` - Загружено на платформу
- `FAILED` - Ошибка обработки
- `SKIPPED` - Пропущено
- `EXPIRED` - Устарело (очищено)



## 🛠️ Используемые технологии

### Управление зависимостями и разработка
- **`UV`** - быстрый пакетный менеджер для Python
- **`Ruff`** - линтер и форматтер кода Python

### Backend
- **`Python 3.8+`** - основной язык разработки
- **`asyncio`** - асинхронное программирование для эффективной обработки I/O
- **`aiohttp`** - асинхронный HTTP клиент
- **`SQLAlchemy 2.0+`** - ORM для работы с базой данных
- **`asyncpg`** - асинхронный драйвер PostgreSQL

### API и интеграции
- **`httpx`** - современный HTTP клиент
- **`Zoom API`** - получение списка и загрузка записей
- **`YouTube Data API v3`** - загрузка видео и управление плейлистами
- **`google-api-python-client`** - клиент для Google API
- **`google-auth`** - аутентификация Google
- **`google-auth-oauthlib`** - OAuth 2.0 для Google
- **`google-auth-httplib2`** - HTTP библиотека для Google Auth
- **`VK API`** - загрузка видео и работа с альбомами
- **`vk-api`** - клиент для VK API
- **`OAuth 2.0`** - аутентификация с платформами

### Обработка видео
- **`ffmpeg-python`** - Python обертка для FFmpeg

### База данных
- **`PostgreSQL`** - реляционная БД для хранения метаданных
- **`Alembic`** - управление миграциями схемы БД

### CLI и UI
- **`Click`** - работа с аргументами командной строки
- **`Rich`** - красивое форматирование вывода и прогресс-бары

### Утилиты
- **`loguru`** - продвинутое логирование
- **`pydantic-settings`** - валидация конфигурации
- **`python-dotenv`** - загрузка переменных окружения

## 🏗️ Архитектура

Система построена на модульной архитектуре:

- **API модуль** - работа с Zoom API
- **Download модуль** - многопоточная загрузка видео файлов
- **Processing модуль** - обработка видео с FFmpeg
- **Upload модуль** - загрузка на платформы
- **Database модуль** - управление состоянием
- **Pipeline Manager** - координация всего процесса

## 📁 Структура проекта

```
├── api/                       # Zoom API клиент
├── config/                    # Конфигурация и учетные данные
├── database/                  # Модели и управление БД
├── models/                    # Модели данных
├── utils/                     # Утилиты и вспомогательные функции
├── video_download_module/     # Модуль загрузки видео
├── video_processing_module/   # Модуль обработки видео
├── video_upload_module/       # Модуль загрузки на платформы
│   ├── platforms/             # Платформы (YouTube, VK)
│   └── core/                  # Базовые классы
├── video/                     # Папки для видео
│   ├── unprocessed_video/     # Исходные видео
│   ├── processing/            # Видео в обработке
│   └── processed_video/       # Обработанные видео
├── thumbnails/                # Превью для видео
├── main.py                    # Основной скрипт
├── pipeline_manager.py        # Менеджер пайплайна
└── requirements.txt           # Зависимости
```

## 🚀 Быстрый старт

### 1. Установка зависимостей

Рекомендуется использовать UV:

```bash
# Установка UV (если еще не установлен)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Установка зависимостей
uv sync
```

Или используйте pip:

```bash
pip install -r requirements.txt
```

### 2. Настройка конфигурации

Создайте файлы с учетными данными в папке `config/`:
- `zoom_creds.json` - для Zoom API
- `youtube_creds.json` - для YouTube API  
- `vk_creds.json` - для VK API


### 3. Инициализация базы данных

```bash
uv run python main.py init-db
# или
python main.py init-db
```

### 4. Синхронизация записей

```bash
uv run python main.py sync --last 7
```

### 5. Полный пайплайн обработки

```bash
uv run python main.py full-process --all
```

## 📋 Требования

### Обязательные

- **Python 3.8+** - основной язык разработки (рекомендуется 3.11+)
- **FFmpeg** - обработка и конвертация видео
  - Установка: `brew install ffmpeg` (macOS) или `sudo apt install ffmpeg` (Ubuntu)
- **PostgreSQL 12+** - база данных для хранения метаданных
  - Установка: [PostgreSQL Downloads](https://www.postgresql.org/download/)
- **Доступ к Zoom API** - получение записей
- **Учетные данные** для YouTube/VK API

### Рекомендуемые (для производительности)

- **UV** - для быстрой установки зависимостей
- **Многоядерный процессор** - для параллельной обработки видео
- **SSD накопитель** - для быстрого доступа к видео файлам
- **Стабильное интернет-соединение** - для загрузки/выгрузки видео
- **Не менее 4 ГБ RAM** - для обработки нескольких видео одновременно

### Система поддерживает

- **Многопоточность** - одновременная загрузка и обработка нескольких видео
- **Асинхронные операции** - эффективная работа с I/O операциями
- **Мониторинг прогресса** - отслеживание статуса обработки в реальном времени

## ⚙️ Конфигурация

Все файлы конфигурации должны быть размещены в папке `config/`. Примеры конфигурации ниже.

### Zoom API

**Файл:** `config/zoom_creds.json`

Система поддерживает работу с несколькими аккаунтами Zoom. Добавьте все необходимые аккаунты в массив `accounts`:

```json
{
  "accounts": [
    {
      "account": "user@example.com",
      "account_id": "account_id",
      "client_id": "client_id",
      "client_secret": "client_secret"
    },
    {
      "account": "second.user@example.com",
      "account_id": "second_account_id",
      "client_id": "second_client_id",
      "client_secret": "second_client_secret"
    }
  ]
}
```

**Как получить учетные данные:**
1. Зарегистрируйте приложение в [Zoom Marketplace](https://marketplace.zoom.us/)
2. Выберите OAuth тип приложения
3. Скопируйте Client ID и Client Secret
4. Получите Account ID из [Zoom Account](https://zoom.us/account)

### YouTube API

**Файл:** `config/youtube_creds.json`

```json
{
  "client_secrets_file": "path/to/client_secrets.json",
  "credentials_file": "path/to/credentials.json"
}
```

**Дополнительно нужно:**
- `client_secrets.json` - файл с секретами приложения (скачать из Google Cloud Console)
- `credentials.json` - файл с токенами (создается автоматически при первом запуске)

**Как получить учетные данные:**
1. Создайте проект в [Google Cloud Console](https://console.cloud.google.com/)
2. Включите YouTube Data API v3
3. Создайте OAuth 2.0 учетные данные
4. Скачайте файл `client_secrets.json`
5. При первом запуске откроется браузер для авторизации
6. После авторизации будет создан файл `credentials.json`

### VK API

**Файл:** `config/vk_creds.json`

```json
{
  "access_token": "your_vk_access_token",
  "group_id": "your_group_id"
}
```

**Параметры:**
- `access_token` - токен доступа VK API
- `group_id` - ID группы/сообщества, в которую будут загружаться видео

**Как получить токен:**
1. Создайте приложение в [VK Developer](https://dev.vk.com/)
2. Получите Access Token с правами: `video`, `groups`
3. Для группы: создайте токен с правами администратора группы
4. ID группы можно найти в настройках группы или использовать числовой ID

### Основная конфигурация

**Файл:** `config/app_config.json`

Универсальная конфигурация для настройки поведения системы включает несколько разделов:

**1. Маппинг видео заголовков (`video_title_mapping`):**
Система автоматически сопоставляет названия Zoom записей с метаданными для загрузки на платформы.

```json
{
  "video_title_mapping": {
    "mapping_rules": [
      {
        "pattern": "Название курса из Zoom",
        "youtube_title_template": "(Л) Название ({date})",
        "thumbnail": "thumbnails/course.png",
        "youtube_playlist_id": "PLAYLIST_ID",
        "vk_album_id": "ALBUM_ID"
      }
    ],
    "default_rules": {
      "youtube_title_template": "{original_title} ({date})",
      "thumbnail": "thumbnails/ml_extra.png"
    },
    "date_format": "DD.MM.YYYY",
    "thumbnail_directory": "thumbnails/"
  }
}
```

**Параметры:**
- `mapping_rules` - правила сопоставления названий (паттерн → метаданные)
- `pattern` - паттерн для поиска в названии Zoom записи
- `youtube_title_template` - шаблон названия для YouTube
- `thumbnail` - путь к превью
- `youtube_playlist_id` - ID плейлиста YouTube
- `vk_album_id` - ID альбома VK
- `date_format` - формат даты в названии
- `thumbnail_directory` - директория для превью

**2. Настройки платформ (`platforms`):**

```json
{
  "platforms": {
    "youtube": {
      "enabled": true,
      "default_privacy": "unlisted",
      "default_language": "ru",
      "credentials_file": "config/youtube_creds.json"
    },
    "vk": {
      "enabled": true,
      "group_id": 123456,
      "default_privacy": "0",
      "privacy_comment": "1",
      "no_comments": false,
      "repeat": false,
      "credentials_file": "config/vk_creds.json"
    }
  }
}
```

**3. Настройки загрузки (`upload_settings`):**

```json
{
  "upload_settings": {
    "max_file_size_mb": 5000,
    "supported_formats": ["mp4", "avi", "mov"],
    "retry_attempts": 3,
    "retry_delay": 5
  }
}
```
