# 🚀 Руководство по развертыванию

Данное руководство описывает процесс развертывания системы автоматизации публикации лекций.

## Требования к системе

### Обязательные компоненты

- **`Python 3.8+`** (рекомендуется 3.11+)
- **`PostgreSQL 12+`**
- **`FFmpeg`**
- **API ключи** для всех используемых сервисов

### Рекомендуемые характеристики

- **CPU**: Многоядерный процессор (4+ ядра)
- **RAM**: Минимум 4 ГБ (рекомендуется 8+ ГБ)
- **Диск**: SSD накопитель для быстрого доступа
- **Сеть**: Стабильное интернет-соединение (минимум 10 Мбит/с)

## Установка зависимостей

### Использование UV (рекомендуется)

```bash
# Установка UV
curl -LsSf https://astral.sh/uv/install.sh | sh

# Установка зависимостей проекта
uv sync
```

### Использование pip

```bash
pip install -r requirements.txt
```

## Настройка базы данных

### Создание базы данных `PostgreSQL`

```bash
# Создание базы данных
createdb zoom_publishing

# Или через psql
psql -U postgres
CREATE DATABASE zoom_publishing;
```

### Инициализация схемы

База данных создается автоматически при первом использовании. Для пересоздания:

```bash
uv run python main.py recreate-db
```

> ⚠️ **Внимание:** Команда `recreate-db` полностью удаляет базу данных и создает её заново. Все данные будут потеряны!

## Настройка конфигурации

### 1. `Zoom API`

Создайте файл `config/zoom_creds.json`:

```json
{
  "accounts": [
    {
      "account": "user@example.com",
      "account_id": "account_id",
      "client_id": "client_id",
      "client_secret": "client_secret"
    }
  ]
}
```

**Как получить учетные данные:**
1. Зарегистрируйте приложение в [`Zoom Marketplace`](https://marketplace.zoom.us/)
2. Выберите `OAuth` тип приложения
3. Скопируйте `Client ID` и `Client Secret`
4. Получите `Account ID` из [`Zoom Account`](https://zoom.us/account)

### 2. `Fireworks API`

> 📖 **Документация:** [Fireworks Audio API - Transcribe audio](https://fireworks.ai/docs/api-reference/audio-transcriptions)

Создайте файл `config/fireworks_creds.json`:

```json
{
  "api_key": "your_fireworks_api_key",
  "model": "whisper-v3-turbo",
  "base_url": "https://audio-turbo.api.fireworks.ai",
  "language": "ru",
  "response_format": "verbose_json",
  "timestamp_granularities": ["segment"],
  "prompt": "Это лекция магистратуры по Computer Science со специализацией в Machine Learning и Data Science. Сохраняй правильное написание профильных терминов (включая английские), латинских обозначений, аббревиатур, элементов кода и имён собственных.",
  "enable_vad": false,
  "diarization": false,
  "temperature": 0.0,
  "max_file_size_mb": 25,
  "audio_bitrate": "64k",
  "audio_sample_rate": 16000,
  "retry_attempts": 1,
  "retry_delay": 2.0
}
```

> ℹ️ Для детерминированных ответов мы отключаем VAD и повторные попытки, а также не используем `alignment_model`. Эти параметры могут по-разному разбивать аудио или вызывать дополнительные запросы, что приводит к расхождениям в транскрипции даже при нулевой температуре.

**Как получить API ключ:**
1. Зарегистрируйтесь на [`Fireworks AI`](https://fireworks.ai/)
2. Создайте API ключ в разделе `API Keys`
3. Скопируйте ключ в файл конфигурации

**📖 Документация:**
- [`Fireworks Audio API` - Transcribe audio](https://fireworks.ai/docs/api-reference/audio-transcriptions)

### 3. `DeepSeek API`

Создайте файл `config/deepseek_creds.json`:

```json
{
  "api_key": "your_deepseek_api_key",
  "model": "deepseek-chat",
  "base_url": "https://api.deepseek.com/v1",
  "temperature": 0.0,
  "max_tokens": 8000,
  "timeout": 120.0
}
```

> ℹ️ Для максимальной детерминированности ставим `temperature` в `0.0`, не включаем `top_p`/`frequency_penalty` одновременно и не задаём `seed` — DeepSeek официально его не документирует и может игнорировать.

**Как получить API ключ:**
1. Зарегистрируйтесь на [`DeepSeek Platform`](https://platform.deepseek.com/)
2. Создайте API ключ в разделе `API Keys`
3. Скопируйте ключ в файл конфигурации

### 4. `YouTube API`

Создайте файл `config/youtube_creds.json`:

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
1. Создайте проект в [`Google Cloud Console`](https://console.cloud.google.com/)
2. Включите `YouTube Data API v3`
3. Создайте `OAuth 2.0` учетные данные
4. Скачайте файл `client_secrets.json`
5. При первом запуске откроется браузер для авторизации
6. После авторизации будет создан файл `credentials.json`

### 5. `VK API`

Создайте файл `config/vk_creds.json`:

```json
{
  "access_token": "your_vk_access_token",
  "group_id": "your_group_id"
}
```

**Как получить токен:**
1. Создайте приложение в [`VK Developer`](https://dev.vk.com/)
2. Получите `Access Token` с правами: `video`, `groups`
3. Для группы: создайте токен с правами администратора группы
4. `ID` группы можно найти в настройках группы или использовать числовой `ID`

### 6. Основная конфигурация

Создайте файл `config/app_config.json`:

```json
{
  "video_title_mapping": {
    "mapping_rules": [
      {
        "pattern": "Название курса из Zoom",
        "title_template": "(Л) Название ({date})",
        "thumbnail": "thumbnails/course.png",
        "youtube_playlist_id": "PLAYLIST_ID",
        "vk_album_id": "ALBUM_ID"
      }
    ],
    "default_rules": {
      "title_template": "{original_title} ({date})",
      "thumbnail": "thumbnails/ml_extra.png"
    },
    "date_format": "DD.MM.YYYY",
    "thumbnail_directory": "thumbnails/"
  },
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
  },
  "upload_settings": {
    "max_file_size_mb": 5000,
    "supported_formats": ["mp4", "avi", "mov"],
    "retry_attempts": 3,
    "retry_delay": 5
  }
}
```

## Первый запуск

### 1. Синхронизация записей

```bash
uv run python main.py sync --last 7
```

### 2. Проверка списка записей

```bash
uv run python main.py list
```

### 3. Тестовый запуск полного пайплайна

```bash
uv run python main.py full-process --all
```

## Развертывание в production

### Переменные окружения

Создайте файл `.env`:

```bash
# База данных
DATABASE_URL=postgresql://user:password@localhost:5432/zoom_publishing

# Логирование
LOG_LEVEL=INFO
LOG_FILE=logs/app.log
ERROR_LOG_FILE=logs/error.log
```

### Systemd сервис (Linux)

Создайте файл `/etc/systemd/system/zoom-publishing.service`:

```ini
[Unit]
Description=Zoom Publishing Platform
After=network.target postgresql.service

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/ZoomTest
Environment="PATH=/path/to/ZoomTest/.venv/bin"
ExecStart=/path/to/ZoomTest/.venv/bin/python main.py sync --last 1
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Активируйте сервис:

```bash
sudo systemctl enable zoom-publishing
sudo systemctl start zoom-publishing
```

### Cron для автоматической синхронизации

Добавьте в crontab:

```bash
# Синхронизация каждый день в 2:00
0 2 * * * cd /path/to/ZoomTest && /path/to/.venv/bin/python main.py sync --last 1

# Полный пайплайн каждый день в 3:00
0 3 * * * cd /path/to/ZoomTest && /path/to/.venv/bin/python main.py full-process --all
```

## Мониторинг

### Логи

Логи сохраняются в:
- `logs/app.log` - общие логи
- `logs/error.log` - ошибки

### Проверка статуса

```bash
# Проверка статуса записей
uv run python main.py list

# Проверка статуса базы данных
psql -U postgres -d zoom_publishing -c "SELECT COUNT(*) FROM recordings;"
```

## Резервное копирование

### База данных

```bash
# Создание бэкапа
pg_dump -U postgres zoom_publishing > backup_$(date +%Y%m%d).sql

# Восстановление
psql -U postgres zoom_publishing < backup_YYYYMMDD.sql
```

### Конфигурация

```bash
# Бэкап конфигурации
tar -czf config_backup_$(date +%Y%m%d).tar.gz config/
```

## Обновление

### Обновление кода

```bash
git pull origin main
uv sync
```

### Миграции базы данных

```bash
# Применение миграций
alembic upgrade head
```

## Устранение неполадок

### Проблемы с базой данных

```bash
# Проверка подключения
psql -U postgres -d zoom_publishing -c "SELECT 1;"

# Пересоздание БД (⚠️ удалит все данные)
uv run python main.py recreate-db
```

### Проблемы с API

- Проверьте API ключи в конфигурации
- Убедитесь, что ключи не истекли
- Проверьте лимиты API

### Проблемы с видео

- Проверьте наличие `FFmpeg`: `ffmpeg -version`
- Убедитесь в наличии свободного места на диске
- Проверьте права доступа к папкам `video/`

