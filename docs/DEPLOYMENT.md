# 🚀 Deployment Guide

**Complete guide: development → production**

---

## 📋 Содержание

1. [Development Setup](#development-setup)
2. [Production Infrastructure](#production-infrastructure)
3. [Configuration](#configuration)
4. [Monitoring](#monitoring)

---

## Development Setup

### Requirements

- **Python 3.11+**
- **PostgreSQL 14+**
- **Redis 7+**
- **FFmpeg**

### Quick Start

```bash
# Install UV
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install dependencies
uv sync

# Setup database
createdb zoom_manager
alembic upgrade head

# Configure
cp config/settings.py.example config/settings.py
# Edit config/settings.py

# Run
make api        # API (port 8000)
make worker     # Celery worker
make beat       # Celery beat
```

---

## Production Infrastructure

### Recommended: Hetzner CPX31

```
Provider:   Hetzner Cloud
Model:      CPX31
vCPU:       8 (AMD EPYC)
RAM:        16 GB
Storage:    160 GB NVMe SSD
Bandwidth:  20 TB/month
Cost:       €26/month (~$28)
```

### OS Setup

```bash
# Ubuntu 24.04 LTS
apt update && apt upgrade -y
apt install -y docker.io docker-compose ffmpeg postgresql-client

# Security
ufw enable
ufw allow 22,80,443/tcp
```

---

### Service Configuration

#### PostgreSQL 15

```yaml
# docker-compose.yml
postgres:
  image: postgres:15-alpine
  environment:
    POSTGRES_DB: zoom_manager
    POSTGRES_USER: postgres
    POSTGRES_PASSWORD: ${DB_PASSWORD}
  volumes:
    - postgres_data:/var/lib/postgresql/data
  deploy:
    resources:
      limits:
        memory: 4G
```

**postgresql.conf:**
```ini
shared_buffers = 1GB
effective_cache_size = 3GB
work_mem = 16MB
maintenance_work_mem = 256MB
max_connections = 100
```

#### Redis 7

```yaml
redis:
  image: redis:7-alpine
  command: redis-server --maxmemory 2gb --maxmemory-policy allkeys-lru
  deploy:
    resources:
      limits:
        memory: 2G
```

#### API (FastAPI)

```yaml
api:
  build: .
  command: uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 4
  deploy:
    resources:
      limits:
        memory: 4G
        cpus: "2"
  environment:
    DATABASE_URL: postgresql://postgres:${DB_PASSWORD}@postgres/zoom_manager
    REDIS_URL: redis://redis:6379
```

#### Celery Worker

```yaml
worker:
  build: .
  command: celery -A api.celery_app worker --loglevel=info --concurrency=4
  deploy:
    resources:
      limits:
        memory: 6G
        cpus: "4"
```

---

## Configuration

### Environment Variables

```bash
# Database
DATABASE_URL=postgresql://user:pass@localhost/zoom_manager

# Redis
REDIS_URL=redis://localhost:6379/0

# Security
SECRET_KEY=your-secret-key-here
ENCRYPTION_KEY=your-fernet-key-here

# Storage
MEDIA_ROOT=/app/media
MAX_FILE_SIZE=10737418240  # 10GB

# API Keys
FIREWORKS_API_KEY=your-key
```

### OAuth Configuration

```bash
# config/oauth_google.json
{
  "client_id": "xxx.apps.googleusercontent.com",
  "client_secret": "xxx",
  "redirect_uri": "https://yourdomain.com/api/v1/oauth/youtube/callback"
}

# config/oauth_vk.json
{
  "app_id": "xxx",
  "client_secret": "xxx",
  "redirect_uri": "https://yourdomain.com/api/v1/oauth/vk/callback"
}
```

### Database Migrations

```bash
# Run migrations
alembic upgrade head

# Create superuser
python -m utils.create_test_user --email admin@example.com --is-admin
```

---

## Monitoring

### Health Checks

```bash
# API health
curl http://localhost:8000/health

# Celery status
celery -A api.celery_app inspect active
```

### Logs

```bash
# Docker logs
docker-compose logs -f api
docker-compose logs -f worker

# Application logs
tail -f logs/api.log
tail -f logs/celery.log
```

### Resource Monitoring

```bash
# PostgreSQL
docker exec postgres psql -U postgres -c "
  SELECT pid, state, query_start, query 
  FROM pg_stat_activity 
  WHERE state != 'idle';
"

# Redis
docker exec redis redis-cli INFO memory

# Disk usage
df -h /app/media
```

---

## Backup Strategy

```bash
# PostgreSQL backup (daily)
pg_dump -U postgres zoom_manager | gzip > backup_$(date +%Y%m%d).sql.gz

# Media files backup (weekly)
tar -czf media_backup_$(date +%Y%m%d).tar.gz /app/media

# Retention: 7 daily, 4 weekly
```

---

## SSL/HTTPS (Production)

```bash
# Install certbot
apt install -y certbot python3-certbot-nginx

# Get certificate
certbot --nginx -d yourdomain.com

# Auto-renewal
systemctl enable certbot.timer
```

---

## Scaling (10+ users)

### Vertical Scaling
- Upgrade to CPX41 (16 vCPU, 32GB RAM)
- Increase worker concurrency: `--concurrency=8`

### Horizontal Scaling
- Add dedicated Celery workers
- Redis Sentinel for HA
- PostgreSQL read replicas

---

## Troubleshooting

### High Memory Usage

```bash
# Check processes
docker stats

# Restart services
docker-compose restart worker
```

### Slow Queries

```bash
# Enable slow query log
ALTER SYSTEM SET log_min_duration_statement = 1000;  # 1 second
SELECT pg_reload_conf();

# View slow queries
tail -f /var/log/postgresql/postgresql-15-main.log | grep "duration:"
```

### Disk Full

```bash
# Clean old recordings
find /app/media/user_*/videos -name "*.mp4" -mtime +30 -delete

# Clean thumbnails
find /app/media/user_*/thumbnails -mtime +90 -delete
```

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
# Создание базы данных (по умолчанию используется название zoom_manager)
createdb zoom_manager

# Или через psql
psql -U postgres
CREATE DATABASE zoom_manager;
```

> 💡 Название базы данных можно изменить через переменную окружения `DATABASE__DATABASE` в файле `.env`

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
  "timestamp_granularities": ["word"],
  "prompt": "Это лекция магистратуры по Computer Science со специализацией в Machine Learning и Data Science. Сохраняй правильное написание профильных терминов (включая английские), латинских обозначений, аббревиатур, элементов кода и имён собственных.",
  "diarize": false,
  "temperature": 0.05,
  "max_file_size_mb": 1024,
  "audio_bitrate": "64k",
  "audio_sample_rate": 16000,
  "retry_attempts": 3,
  "retry_delay": 2.0
}
```

> ℹ️ Для детерминированных ответов мы отключаем VAD и не используем `alignment_model`. Эти параметры могут по-разному разбивать аудио или вызывать дополнительные запросы, что приводит к расхождениям в транскрипции даже при нулевой температуре. Количество повторных попыток увеличено до 3 для повышения надежности.

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
# База данных (используется префикс DATABASE__)
DATABASE__HOST=localhost
DATABASE__PORT=5432
DATABASE__DATABASE=zoom_manager
DATABASE__USERNAME=postgres
DATABASE__PASSWORD=password

# Логирование (используется префикс LOGGING__)
LOGGING__LEVEL=INFO
LOGGING__FILE_PATH=logs/app.log

# Общие настройки
TIMEZONE=Europe/Moscow
DEBUG=false
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
psql -U postgres -d zoom_manager -c "SELECT COUNT(*) FROM recordings;"
```

## Резервное копирование

### База данных

```bash
# Создание бэкапа
pg_dump -U postgres zoom_manager > backup_$(date +%Y%m%d).sql

# Восстановление
psql -U postgres zoom_manager < backup_YYYYMMDD.sql
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
psql -U postgres -d zoom_manager -c "SELECT 1;"

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
- Проверьте права доступа к папкам `media/video/`, `media/processed_audio/`, `media/transcriptions/`

