# Fireworks Batch API Integration

**Экономия ~50% на транскрибации** через Batch API.

## Что это

Fireworks предоставляет два API для транскрибации:
- **Sync API** (по умолчанию) - немедленная обработка, дороже
- **Batch API** - фоновая обработка, дешевле ~50%

Документация: [Fireworks Batch API](https://docs.fireworks.ai/api-reference/create-batch-request)

## Настройка

Добавьте `account_id` в `config/fireworks_creds.json`:

```json
{
  "api_key": "fw_...",
  "account_id": "YOUR_ACCOUNT_ID",
  ...
}
```

**Где найти account_id:**
1. Откройте [Fireworks Dashboard](https://fireworks.ai/account)
2. Account Settings → API Keys
3. Скопируйте Account ID

## Использование

### Single Recording

```bash
# Sync API (default, быстрее)
POST /api/v1/recordings/123/transcribe

# Batch API (дешевле ~50%)
POST /api/v1/recordings/123/transcribe?use_batch_api=true
```

### Response

```json
{
  "task_id": "abc-123",
  "batch_id": "batch_xyz",
  "mode": "batch_api",
  "status": "queued",
  "check_status_url": "/api/v1/tasks/abc-123"
}
```

### Check Progress

```bash
GET /api/v1/tasks/abc-123
```

## Сравнение

| Аспект | Sync API | Batch API |
|--------|----------|-----------|
| **Стоимость** | 100% | ~50% |
| **Response time** | < 50ms | < 50ms |
| **Обработка** | Немедленно | 2-10 минут |
| **Progress tracking** | ✅ | ✅ |
| **Use case** | Real-time | Background jobs |

## Рекомендации

**Используйте Batch API когда:**
- ✅ Обрабатываете большие объемы записей
- ✅ Нет срочности (фоновая обработка)
- ✅ Важна экономия (до 50%)

**Используйте Sync API когда:**
- ✅ Нужен немедленный результат
- ✅ Одна запись в реальном времени
- ✅ Стоимость не критична

## Технические детали

**Polling:**
- Интервал: 10 секунд
- Max wait time: 1 час (3600s)
- Автоматический retry при ошибках

**Progress tracking:**
- 0-20%: Waiting for batch submission
- 20-80%: Batch processing (estimated)
- 80-100%: Parsing & saving result

**Celery task:**
```python
batch_transcribe_recording_task(
    recording_id=123,
    user_id=1,
    batch_id="batch_xyz",
    poll_interval=10.0,
    max_wait_time=3600.0
)
```

## Troubleshooting

**"account_id не настроен":**
- Добавьте `account_id` в `config/fireworks_creds.json`

**"Batch job не завершился за 3600s":**
- Увеличьте `max_wait_time` или проверьте Fireworks dashboard

**"Batch API вернул ошибку":**
- Проверьте API key и account_id
- Проверьте размер файла (max 1GB)

