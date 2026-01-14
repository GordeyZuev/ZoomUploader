# Architecture Decision Records - Features

**Проект:** LEAP Platform  
**Версия:** 2.0 (Актуализировано: январь 2026)  
**Статус:** Production Features

---

## 📋 Содержание

1. [ADR-010: Automation System](#adr-010-automation-system)
2. [ADR-011: Async Processing (Celery)](#adr-011-async-processing-celery)
3. [ADR-012: Quotas & Subscriptions](#adr-012-quotas--subscriptions)
4. [ADR-013: Audit Logging](#adr-013-audit-logging)
5. [ADR-014: Notifications](#adr-014-notifications)
6. [ADR-015: FSM для надежной обработки](#adr-015-fsm-для-надежной-обработки)

---

## ADR-010: Automation System

**Статус:** ✅ Полностью реализовано  
**Дата:** Январь 2026

### Решение

Template-driven automation с scheduled jobs через Celery Beat.

### Архитектура

```
┌─────────────────────────────────────────┐
│        Automation Architecture          │
└─────────────────────────────────────────┘

automation_jobs (schedule config)
    ↓
Celery Beat (scheduler)
    ↓
Celery Worker (execution)
    ↓
1. Sync sources → find new recordings
2. Match to templates → auto-assign
3. Process matched recordings
4. Upload to platforms
```

### Ключевые компоненты

**1. Automation Jobs (database):**
```python
class AutomationJob:
    name: str
    schedule_config: dict  # Cron-like config
    template_id: int       # Template to apply
    enabled: bool
    last_run_at: datetime
    next_run_at: datetime
```

**2. Schedule Types:**
```python
{
  "type": "daily",       # Daily at specific time
  "time": "06:00",
  "timezone": "UTC"
}

{
  "type": "hours",       # Every N hours
  "hours": 6
}

{
  "type": "weekdays",    # Specific days + time
  "days": [1, 3, 5],     # Mon, Wed, Fri
  "time": "08:00"
}

{
  "type": "cron",        # Custom cron
  "expression": "0 */6 * * *"
}
```

**3. Execution Flow:**
```python
async def execute_automation_job(job_id: int):
    """
    1. Sync sources linked to template
    2. Find recordings with template_id
    3. Filter by status (INITIALIZED, etc.)
    4. Trigger full pipeline
    5. Track progress in processing_stages
    """
    job = await get_job(job_id)
    template = await get_template(job.template_id)
    
    # Sync
    new_recordings = await sync_sources(template.source_ids)
    
    # Filter + Process
    to_process = await filter_recordings(
        template_id=template.id,
        status="INITIALIZED",
        exclude_blank=True
    )
    
    # Batch process
    await bulk_process_recordings(to_process)
```

### Quota Management

**Limits:**
- `max_automation_jobs` - макс. количество jobs (по плану)
- `min_job_interval` - мин. интервал между запусками (anti-spam)

**Checks:**
```python
# Before creating job
if user.jobs_count >= plan.max_automation_jobs:
    raise QuotaExceededError("Max automation jobs reached")

# Before running
if job.last_run_at + min_interval > now():
    skip_run("Too frequent")
```

### Реализация

**Файлы:**
- `database/automation_models.py` - AutomationJob, ProcessingStage
- `api/routers/automation.py` - CRUD endpoints
- `api/tasks/automation.py` - Celery tasks
- `api/services/automation_service.py` - logic

**Endpoints:**
- `GET /automation/jobs` - list jobs
- `POST /automation/jobs` - create job
- `PATCH /automation/jobs/{id}` - update job
- `DELETE /automation/jobs/{id}` - delete job
- `POST /automation/jobs/{id}/run` - manual trigger
- `POST /automation/jobs/{id}/dry-run` - preview

**Статус:** ✅ Реализовано

**См. также:** [TECHNICAL.md](TECHNICAL.md) - Automation system implementation

---

## ADR-011: Async Processing (Celery)

**Статус:** ✅ Полностью реализовано  
**Дата:** Январь 2026

### Решение

Celery + Redis для асинхронной обработки длительных задач.

### Архитектура

```
┌─────────────────────────────────────────┐
│        Celery Architecture              │
└─────────────────────────────────────────┘

FastAPI → Celery Task → Redis (broker)
             ↓
        Celery Worker (3 workers)
             ↓
        Processing (CPU: 2 workers)
        Upload (I/O: 1 worker)
        Automation (1 worker)
             ↓
        Result → Redis (backend)
             ↓
        Client polls task status
```

### Queues

**Queue Structure:**
```
processing:    Video processing (FFmpeg, heavy CPU)
upload:        API calls to YouTube/VK (I/O bound)
automation:    Scheduled jobs (Celery Beat)
```

**Worker Configuration:**
```bash
# Processing worker (CPU-intensive)
celery -A api.celery_app worker \
  --queues=processing \
  --concurrency=2 \
  --pool=prefork \
  --max-tasks-per-child=5

# Upload worker (I/O-intensive)
celery -A api.celery_app worker \
  --queues=upload \
  --concurrency=4 \
  --pool=gevent

# Automation worker
celery -A api.celery_app worker \
  --queues=automation \
  --concurrency=1
```

### Task Types

**Processing Tasks:**
- `download_recording_task` - download from source
- `process_video_task` - FFmpeg processing
- `transcribe_recording_task` - AI transcription
- `extract_topics_task` - AI topic extraction
- `generate_subtitles_task` - SRT/VTT generation

**Upload Tasks:**
- `upload_to_platform_task` - upload to YouTube/VK
- `retry_failed_uploads_task` - retry failed

**Batch Tasks:**
- `bulk_process_recordings_task` - batch processing
- `bulk_sync_sources_task` - batch sync

**Automation Tasks:**
- `execute_automation_job_task` - run scheduled job

### Progress Tracking

**Task Status:**
```python
{
  "task_id": "abc-123",
  "status": "PROCESSING",  # PENDING, PROCESSING, SUCCESS, FAILURE
  "progress": 45,          # 0-100%
  "current_step": "Transcribing audio...",
  "result": None,          # Result when complete
  "error": None            # Error message if failed
}
```

**API:**
```
GET /tasks/{task_id} - Get task status
DELETE /tasks/{task_id} - Cancel task
GET /tasks - List user's tasks
```

### Реализация

**Файлы:**
- `api/celery_app.py` - Celery config
- `api/tasks/` - task definitions (6 файлов)
- `api/services/task_service.py` - task management
- `docker-compose.yml` - Redis + Celery services

**Monitoring:**
- Flower UI: `http://localhost:5555`
- Prometheus metrics (опционально)

**Статус:** ✅ Реализовано

---

## ADR-012: Quotas & Subscriptions

**Статус:** ✅ Полностью реализовано  
**Дата:** Январь 2026

### Решение

План-based subscriptions с flexible quotas и usage tracking.

### Архитектура

```
┌─────────────────────────────────────────┐
│        Subscription System              │
└─────────────────────────────────────────┘

subscription_plans (4 plans: Free/Plus/Pro/Enterprise)
    ↓
user_subscriptions (user ← plan + custom_quotas)
    ↓
quota_usage (tracking по периодам YYYYMM)
    ↓
quota_change_history (audit trail)
```

### Subscription Plans

| Plan | Recordings/mo | Storage | Tasks | Jobs | Price |
|------|--------------|---------|-------|------|-------|
| **Free** | 10 | 5 GB | 1 | 0 | $0 |
| **Plus** | 50 | 25 GB | 2 | 3 | $10 |
| **Pro** | 200 | 100 GB | 5 | 10 | $30 |
| **Enterprise** | ∞ | ∞ | 10 | ∞ | Custom |

### Quota Types

**Resource Quotas:**
```python
{
  "max_recordings_per_month": 50,      # Monthly limit
  "max_storage_gb": 25,                # Total storage
  "max_concurrent_tasks": 2,           # Parallel processing
  "max_automation_jobs": 3,            # Scheduled jobs
  "max_input_sources": 10,             # Input sources
  "max_output_presets": 10,            # Output presets
  "max_templates": 20                  # Templates
}
```

**Custom Quotas:**
```python
# Override for VIP users
{
  "user_id": 123,
  "plan_id": 2,  # Plus plan
  "custom_quotas": {
    "max_recordings_per_month": 100,  # Override: 50 → 100
    "max_storage_gb": 50              # Override: 25 → 50
  }
}
```

### Usage Tracking

**Period-based tracking:**
```python
# quota_usage table
{
  "user_id": 1,
  "period": "202601",  # YYYYMM
  "recordings_count": 15,
  "storage_used_gb": 3.2,
  "tasks_run_count": 45,
  "automation_runs_count": 12
}
```

**Quota Checks:**
```python
async def check_quota(user_id: int, quota_type: str):
    """
    1. Get user subscription + plan
    2. Get quota limit (plan + custom overrides)
    3. Get current usage for period
    4. Check if under limit
    5. Raise QuotaExceededError if over
    """
    pass

# Before operation
await check_quota(user_id, "max_recordings_per_month")
```

### Admin API

**Endpoints:**
```
GET /admin/stats/overview - Platform stats
GET /admin/stats/users - User stats
GET /admin/stats/quotas - Quota usage
POST /admin/users/{id}/quota - Override quota
GET /admin/users/{id}/usage - User usage history
```

### Реализация

**Файлы:**
- `database/subscription_models.py` - models (4 tables)
- `api/services/quota_service.py` - quota logic
- `api/routers/admin.py` - admin endpoints
- `api/middleware/quota_middleware.py` - checks

**Статус:** ✅ Реализовано

**См. также:** [API_GUIDE.md](API_GUIDE.md) - Admin & Quota API

---

## ADR-013: Audit Logging

**Статус:** 🚧 Частично реализовано (базовый logging)  
**Приоритет:** Medium (для compliance)

### Решение

Structured logging + audit trail для критичных операций.

### Что логируется

**Critical Operations:**
- Authentication (login, logout, token refresh)
- Credential management (create, update, delete)
- Recording operations (create, delete, reset)
- Template changes (create, update, delete, rematch)
- Quota overrides (admin actions)
- Automation job runs (start, end, errors)

**Audit Log Format:**
```python
{
  "timestamp": "2026-01-14T10:30:00Z",
  "user_id": 123,
  "action": "recording.delete",
  "resource_type": "recording",
  "resource_id": 456,
  "ip_address": "192.168.1.1",
  "user_agent": "Mozilla/5.0...",
  "details": {
    "recording_name": "Lecture 1",
    "status": "UPLOADED"
  },
  "result": "success"  # success, failure, partial
}
```

### Реализация (текущая)

**Structured Logging:**
- Python `logging` module
- JSON format для production
- Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
- Rotation: daily, 30 days retention

**Будущее (полный audit):**
```sql
CREATE TABLE audit_logs (
    id SERIAL PRIMARY KEY,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    user_id INT REFERENCES users(id),
    action VARCHAR(100),
    resource_type VARCHAR(50),
    resource_id INT,
    ip_address INET,
    user_agent TEXT,
    details JSONB,
    result VARCHAR(20)
);

CREATE INDEX idx_audit_user ON audit_logs(user_id, timestamp DESC);
CREATE INDEX idx_audit_action ON audit_logs(action, timestamp DESC);
CREATE INDEX idx_audit_resource ON audit_logs(resource_type, resource_id);
```

**Endpoints (будущее):**
```
GET /admin/audit - Admin audit log
GET /users/me/activity - User activity log
```

**Статус:** 🚧 Базовый logging реализован, полный audit - TODO

---

## ADR-014: Notifications

**Статус:** 🚧 Частично реализовано (error logging)  
**Приоритет:** Low (nice to have)

### Решение

Multi-channel notifications для критичных событий.

### Notification Types

**Error Notifications:**
- Processing failure after retries
- Transcription failure (quota, API error)
- Upload failure (auth, quota, network)
- Automation job failure

**Success Notifications (опционально):**
- Recording uploaded successfully
- Automation job completed
- Daily/weekly summary

**Quota Notifications:**
- 80% quota reached
- 100% quota reached
- Overage usage

### Channels

**Email (primary):**
- SMTP integration
- Template-based messages
- HTML + plain text fallback

**Webhook (future):**
- POST to user-defined URL
- JSON payload with event data
- Retry logic with exponential backoff

**In-app (future):**
- Notification center в UI
- Real-time via WebSocket
- Persistent storage в БД

### Реализация (текущая)

**Error Logging:**
- Все ошибки логируются
- Email уведомления - TODO

**Будущее:**
```python
# Notification Service
class NotificationService:
    async def send_error_notification(
        user_id: int,
        error_type: str,
        details: dict
    ):
        # Send via configured channels
        pass
    
    async def send_quota_warning(
        user_id: int,
        quota_type: str,
        usage_percent: float
    ):
        pass
```

**Статус:** 🚧 Базовый logging, notifications - TODO

---

## ADR-015: FSM для надежной обработки

**Статус:** ✅ Полностью реализовано  
**Дата:** Январь 2026

### Решение

Finite State Machine для гарантированных state transitions.

### FSM Diagram

```
┌─────────────────────────────────────────┐
│        Processing State Machine         │
└─────────────────────────────────────────┘

INITIALIZED
    ↓
DOWNLOADING → DOWNLOADED
    ↓
PROCESSING → PROCESSED
    ↓
TRANSCRIBING → TRANSCRIBED
    ↓
UPLOADING → UPLOADED

Any state → FAILED (with failed_at_stage)
FAILED → retry → continue from failed stage
```

### State Definitions

**Processing States:**
- `INITIALIZED` - Запись создана, готова к обработке
- `DOWNLOADING` - Скачивается из источника
- `DOWNLOADED` - Скачана, готова к processing
- `PROCESSING` - FFmpeg обработка (trim silence)
- `PROCESSED` - Обработана, готова к transcription
- `TRANSCRIBING` - AI транскрибация
- `TRANSCRIBED` - Транскрибирована, готова к upload
- `UPLOADING` - Загрузка на платформы
- `UPLOADED` - Успешно загружена везде
- `FAILED` - Ошибка (с указанием стадии)
- `SKIPPED` - Пропущена (blank record, user skip)

### Transition Rules

**Allowed Transitions:**
```python
ALLOWED_TRANSITIONS = {
    "INITIALIZED": ["DOWNLOADING", "FAILED", "SKIPPED"],
    "DOWNLOADING": ["DOWNLOADED", "FAILED"],
    "DOWNLOADED": ["PROCESSING", "FAILED"],
    "PROCESSING": ["PROCESSED", "FAILED"],
    "PROCESSED": ["TRANSCRIBING", "FAILED"],
    "TRANSCRIBING": ["TRANSCRIBED", "FAILED"],
    "TRANSCRIBED": ["UPLOADING", "FAILED"],
    "UPLOADING": ["UPLOADED", "FAILED"],
    "UPLOADED": [],  # Terminal state
    "FAILED": ["DOWNLOADING", "PROCESSING", "TRANSCRIBING", "UPLOADING"],  # Retry
    "SKIPPED": []  # Terminal state
}
```

**Validation:**
```python
def validate_transition(from_status: str, to_status: str) -> bool:
    """Check if transition is allowed"""
    return to_status in ALLOWED_TRANSITIONS[from_status]

# Usage
if not validate_transition(recording.status, new_status):
    raise InvalidTransitionError(f"{recording.status} → {new_status}")
```

### Output Target FSM

**Separate FSM для каждой платформы:**
```python
class OutputTarget:
    target_type: str  # youtube, vk
    status: TargetStatus  # Enum
    
    # Transitions
    NOT_UPLOADED → UPLOADING → UPLOADED
    NOT_UPLOADED → FAILED
    UPLOADING → FAILED
    FAILED → UPLOADING  # Retry
```

**Преимущества:**
- ✅ Независимые статусы для каждой платформы
- ✅ Partial success (YouTube ok, VK failed)
- ✅ Retry только failed platforms

### Failed Handling

**Failed Flag:**
```python
class Recording:
    status: ProcessingStatus  # Current stage
    failed: bool              # Is in failed state?
    failed_at_stage: str      # Stage where failed
    retry_count: int          # Number of retries
    error_message: str        # Last error
```

**Retry Logic:**
```python
async def retry_recording(recording_id: int):
    """
    1. Check failed=True
    2. Get failed_at_stage
    3. Reset failed=False
    4. Continue from failed_at_stage
    5. Increment retry_count
    """
    recording = await get_recording(recording_id)
    
    if not recording.failed:
        raise ValueError("Recording not failed")
    
    # Continue from failed stage
    stage = recording.failed_at_stage
    recording.failed = False
    recording.retry_count += 1
    
    if stage == "DOWNLOADING":
        await download_task(recording_id)
    elif stage == "PROCESSING":
        await process_task(recording_id)
    # etc.
```

### Processing Stages Tracking

**Table: processing_stages**
```python
class ProcessingStage:
    recording_id: int
    stage_name: str  # download, process, transcribe, upload
    status: str      # pending, running, completed, failed
    started_at: datetime
    completed_at: datetime
    error_message: str
    metadata: dict   # Stage-specific data
```

**Usage:**
- Детальное отслеживание progress
- Debugging failed recordings
- Analytics (avg time per stage)

### Реализация

**Файлы:**
- `models/recording.py` - ProcessingStatus enum
- `database/models.py` - RecordingModel with FSM fields
- `database/automation_models.py` - ProcessingStage model
- Service layer - FSM validation

**Endpoints:**
```
POST /recordings/{id}/retry - Retry failed recording
POST /recordings/{id}/reset - Reset to INITIALIZED
GET /recordings/{id}/stages - Get processing stages
```

**Статус:** ✅ Реализовано

---

## Итоговая таблица статусов

| ADR | Feature | Status | Priority | Notes |
|-----|---------|--------|----------|-------|
| ADR-010 | Automation | ✅ Done | High | Celery Beat |
| ADR-011 | Async Processing | ✅ Done | High | Celery + Redis |
| ADR-012 | Quotas & Subscriptions | ✅ Done | High | 4 plans |
| ADR-013 | Audit Logging | 🚧 Partial | Medium | Basic logging |
| ADR-014 | Notifications | 🚧 Partial | Low | Logging only |
| ADR-015 | FSM | ✅ Done | High | Production-ready |

---

## См. также

### Детальная документация
- [TECHNICAL.md](TECHNICAL.md) - Automation system implementation
- [API_GUIDE.md](API_GUIDE.md) - Admin & Quota API
- [TECHNICAL.md](TECHNICAL.md) - Техническая документация

### Архитектура
- [ADR_OVERVIEW.md](ADR_OVERVIEW.md) - Основные ADR решения
- [DATABASE_DESIGN.md](DATABASE_DESIGN.md) - Схемы БД

---

**Документ обновлен:** Январь 2026  
**Статус фич:** 4/6 fully done, 2/6 partial
