# Zoom Video Processing Pipeline

Автоматизированная система для загрузки, обработки и публикации записей Zoom встреч на различных платформах (YouTube, VK).

## Возможности

- 🔄 **Автоматическая синхронизация** записей из Zoom API
- 📥 **Загрузка видео** с фильтрацией по длительности
- 🎬 **Обработка видео** с помощью FFmpeg (обрезка, сжатие, улучшение качества)
- 📤 **Загрузка на платформы** YouTube и VK с автоматическим созданием плейлистов/альбомов
- 🗄️ **База данных** для отслеживания статуса обработки
- 📊 **Детальное логирование** всех операций
- 🎯 **Интерактивный режим** для выбора записей

## Структура проекта

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

## Быстрый старт

### 1. Установка зависимостей

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
python main.py init-db
```

### 4. Синхронизация записей

```bash
python main.py sync --last 7
```

### 5. Полный пайплайн обработки

```bash
python main.py full-process --all
```

## Команды

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

## Статусы обработки

- `PENDING` - Ожидает обработки
- `DOWNLOADING` - В процессе загрузки
- `DOWNLOADED` - Загружено
- `PROCESSING` - В процессе обработки
- `PROCESSED` - Обработано
- `UPLOADING` - В процессе загрузки на платформу
- `UPLOADED` - Загружено на платформу
- `FAILED` - Ошибка обработки
- `SKIPPED` - Пропущено

## Конфигурация

### Zoom API
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

### YouTube API
```json
{
  "client_secrets_file": "path/to/client_secrets.json",
  "credentials_file": "path/to/credentials.json"
}
```

### VK API
```json
{
  "access_token": "your_vk_access_token",
  "group_id": "your_group_id"
}
```

## Архитектура

Система построена на модульной архитектуре:

- **API модуль** - работа с Zoom API
- **Download модуль** - загрузка видео файлов
- **Processing модуль** - обработка видео с FFmpeg
- **Upload модуль** - загрузка на платформы
- **Database модуль** - управление состоянием
- **Pipeline Manager** - координация всего процесса

## Требования

- Python 3.8+
- FFmpeg
- Доступ к Zoom API
- Учетные данные для YouTube/VK (опционально)

## Логирование

Все операции логируются в файлы:
- `logs/app.log` - общие логи
- `logs/error.log` - ошибки

## Лицензия

MIT License
