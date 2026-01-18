# 🎯 План развития LEAP API

## 📊 Текущее состояние

### ✅ Что работает отлично
- Multi-tenancy isolation (95%)
- Authentication & Authorization (JWT + OAuth)
- Celery tasks с progress tracking
- Template matching system
- 42 database indexes
- 84 REST API endpoints

### 🎉 Недавно очищено (2026-01-18)
- ✅ **pipeline_manager.py** (1086 строк) - удален, функции перенесены в RecordingService
- ✅ **utils/file_utils.py** - объединен с formatting.py
- ✅ **utils/interactive_mapper.py** (234 строки) - удален CLI код
- ✅ **rich library** - удалена (CLI зависимость)
- ✅ **api/config/oauth_platforms.py** - удален дубликат
- ✅ **os.path → Path** - заменено в thumbnail managers
- ✅ **deprecated base_dir** - удален из TranscriptionManager
- **Итого:** -1500+ строк мертвого кода

### 🔧 Критические проблемы

#### 1. Конфигурация (хаос)
- `api/config.py` + `config/settings.py` - два источника настроек
- Retry values захардкожены в декораторах задач
- API keys в JSON файлах вместо env
- Нет централизованного `.env.example`

#### 2. Логгирование (базовое)
- Нет structured logging (JSON для production)
- Нет correlation ID для трейсинга
- Нет context propagation (user_id, task_id)
- Нет интеграции с Sentry/ELK

#### 3. Архитектурные костыли
- `MeetingRecording` vs `RecordingModel` - дублирование (21 файл)
- `FileCredentialProvider` - legacy система
- `load_config_from_file()` - обратная совместимость
- `_find_matching_template()` в router (должен быть в service)

#### 4. Медиа-система (10 критических проблем)
- **Orphaned files** - delete recording не удаляет файлы → storage leak
- **Дублирование** - `audio/processed` vs `processed_audio`, thumbnails копируются
- **Display_name в путях** - кириллица, коллизии, длинные имена
- **Legacy директории** - `media/video/`, `media/transcriptions/`, `media/data.db`
- **Нет cleanup** - temp files, expired recordings накапливаются
- **Quota не автоматический** - ручной подсчет, неточный billing
- **Хаотичная структура** - файлы разбросаны, сложно управлять
- **Не S3-ready** - миграция на S3 будет сложной
- **temp_processing пустые** - создаются, но не используются

**Детали:** См. `docs/MEDIA_SYSTEM_AUDIT.md` и `MEDIA_ISSUES_SUMMARY.md`

---

## 🚀 План реализации

### **ФАЗА 1: Единая система конфигурации** (1-2 дня)
**Цель:** Все настройки через env, единый источник истины

#### 1.1. Создать unified config (2 часа)
- [ ] Создать `config/settings.py` с полной конфигурацией (Pydantic BaseSettings)
- [ ] Секции: APP, SERVER, DATABASE, REDIS, CELERY, SECURITY, STORAGE, LOGGING, MONITORING, OAUTH, FEATURES
- [ ] Celery retry values настраиваемые через env:
  - `CELERY_DOWNLOAD_MAX_RETRIES`, `CELERY_DOWNLOAD_RETRY_DELAY`
  - `CELERY_UPLOAD_MAX_RETRIES`, `CELERY_UPLOAD_RETRY_DELAY`
  - `CELERY_PROCESSING_MAX_RETRIES`, `CELERY_PROCESSING_RETRY_DELAY`
- [ ] Validators для production (JWT_SECRET_KEY min 32 chars)
- [ ] Singleton pattern `get_settings()`

#### 1.2. Создать .env.example (30 мин)
- [ ] Полный пример всех переменных с комментариями
- [ ] Секции: APP, DATABASE, REDIS, CELERY, SECURITY, STORAGE, LOGGING, MONITORING, EXTERNAL APIS, OAUTH
- [ ] Указать обязательные поля для production

#### 1.3. Обновить Celery tasks (1 час)
- [ ] Заменить hardcoded values на `settings.CELERY_*_MAX_RETRIES`
- [ ] Обновить все `@celery_app.task` декораторы (8 файлов)
- [ ] `soft_time_limit` и `time_limit` из config

#### 1.4. Удалить legacy config (30 мин)
- [ ] Удалить `api/config.py` (APISettings)
- [ ] Мигрировать все импорты на unified `get_settings()`
- [ ] Удалить дублирующиеся настройки

---

### **ФАЗА 2: Structured Logging** (1 день)
**Цель:** Production-ready логгирование с контекстом

#### 2.1. Создать logger module (2 часа)
- [ ] `logger/config.py` с context vars:
  - `request_id_var` - для трейсинга HTTP requests
  - `user_id_var` - для multi-tenancy
  - `task_id_var` - для Celery tasks
- [ ] `setup_logging()` с двумя режимами:
  - Text format (development) - цветной вывод
  - JSON format (production) - structured logs
- [ ] File rotation (configurable: size, retention)
- [ ] `get_logger(module_name)` - возвращает logger с контекстом

#### 2.2. FastAPI middleware (30 мин)
- [ ] `LoggingMiddleware` для автоматического:
  - Генерации/извлечения `X-Request-ID`
  - Установки `user_id` из JWT
  - Логирования request/response с duration
  - Добавления headers в response

#### 2.3. Celery integration (30 мин)
- [ ] `set_task_context(task_id, user_id)` helper
- [ ] Обновить `BaseTask.__call__()` для установки контекста
- [ ] Обновить `on_failure/on_success` для structured logs

#### 2.4. Sentry integration (30 мин)
- [ ] `pip install sentry-sdk[loguru]`
- [ ] Инициализация в `setup_logging()`
- [ ] Настройки: DSN, environment, traces_sample_rate
- [ ] Auto-capture exceptions с контекстом

---

### **ФАЗА 3: Media System Overhaul** (3-4 дня)
**Цель:** Полная реорганизация файловой системы, устранение дублирования и leaks

#### 3.0. Аудит текущих проблем ✅

**Найденные критические проблемы:**
1. **Дублирование директорий** - `audio/processed` vs `processed_audio`
2. **Thumbnails копируются** - 22 файла * N users = waste
3. **Orphaned files** - delete recording не удаляет файлы
4. **Display_name в именах** - коллизии, кириллица, длинные имена
5. **Legacy директории** - `media/video/`, `media/transcriptions/`, `media/data.db`
6. **Нет cleanup** - temp files, expired recordings, orphaned files
7. **Quota не автоматический** - нужно вызывать вручную
8. **temp_processing не очищается** - накопление временных файлов
9. **Paths как strings** - проблемы при миграции на S3
10. **Нет atomic operations** - race conditions при сохранении

---

### **ФАЗА 3.1: Security & File Naming** (2-3 дня)
**Цель:** Устранить уязвимости безопасности и проблемы именования файлов

#### 3.1.1. User ID Migration - UUID (2 часа + миграция БД)

##### 3.1.1.1. Анализ вариантов
- [ ] **UUID** (рекомендуется) - полная непредсказуемость
  - Плюсы: industry standard, distributed-friendly
  - Минусы: 16 bytes, требует миграцию БД
- [ ] **Hashid** - obfuscation для API
  - Плюсы: никакой миграции БД
  - Минусы: security by obscurity
- [ ] **ULID** - sortable UUID
  - Плюсы: timestamp + random, URL-safe
  - Минусы: новый стандарт

##### 3.1.1.2. Реализация (UUID)
- [ ] Создать Alembic migration:
  ```python
  # Add uuid column
  op.add_column('users', sa.Column('uuid', UUID(as_uuid=True), default=uuid.uuid4))
  # Populate UUIDs for existing users
  # Add unique constraint on uuid
  # Optionally: migrate foreign keys (or keep integer internally)
  ```
- [ ] Выбрать стратегию:
  - **A**: Полная миграция (uuid везде) - сложно, долго
  - **B**: Hybrid (int internal, uuid в API) - рекомендуется
- [ ] Обновить API responses:
  ```python
  class UserResponse(BaseModel):
      id: str  # UUID as string for API
      email: str
  ```

##### 3.1.1.3. API Layer (рекомендуется Hybrid)
- [ ] `api/helpers/user_id_converter.py`:
  ```python
  async def resolve_user_id(uuid_or_int: str) -> int:
      """Convert public UUID to internal int ID"""
      if is_uuid(uuid_or_int):
          user = await UserRepository.get_by_uuid(uuid_or_int)
          return user.id
      return int(uuid_or_int)  # Backward compatibility
  ```
- [ ] Обновить path parameters: `{user_id: str}` → резолвить в int

#### 3.1.2. File Naming - ID-based (1 день)

##### 3.1.2.1. Создать PathBuilder helper (2 часа)
- [ ] `utils/path_builder.py`:
  ```python
  class RecordingPathBuilder:
      """Generate secure, ID-based file paths"""
      
      @staticmethod
      def video_original(user_id: int, recording_id: int) -> Path:
          return Path(f"media/user_{user_id}/video/unprocessed/{recording_id}_original.mp4")
      
      @staticmethod
      def video_processed(user_id: int, recording_id: int) -> Path:
          return Path(f"media/user_{user_id}/video/processed/{recording_id}_trimmed.mp4")
      
      @staticmethod
      def audio_processed(user_id: int, recording_id: int) -> Path:
          return Path(f"media/user_{user_id}/audio/{recording_id}_processed.mp3")
      
      @staticmethod
      def transcription_dir(user_id: int, recording_id: int) -> Path:
          return Path(f"media/user_{user_id}/transcriptions/{recording_id}")
      
      @staticmethod
      def transcription_master(user_id: int, recording_id: int) -> Path:
          return RecordingPathBuilder.transcription_dir(user_id, recording_id) / "master.json"
  ```

##### 3.1.2.2. Обновить code base (3 часа)
- [ ] Заменить во всех местах:
  - ❌ `f"{sanitize_filename(recording.display_name)}_{date}.mp3"`
  - ✅ `PathBuilder.audio_processed(user_id, recording_id)`
- [ ] Файлы для изменения (4):
  - `api/tasks/processing.py` - download, trim, audio extraction
  - `pipeline_manager.py` - legacy (если используется)
  - `video_processing_module/video_processor.py`
  - `transcription_module/` - все операции с файлами

##### 3.1.2.3. Миграция существующих файлов (1 час)
- [ ] `scripts/migrate_filenames.py`:
  ```python
  async def migrate_recording_files(recording_id: int):
      """Rename files from display_name to ID-based"""
      recording = await get_recording(recording_id)
      
      # Find old files (by display_name pattern)
      old_audio = find_audio_file(recording.user_id, recording.display_name)
      
      if old_audio:
          new_audio = PathBuilder.audio_processed(recording.user_id, recording.id)
          shutil.move(old_audio, new_audio)
          # Update DB
          recording.processed_audio_path = str(new_audio)
  ```
- [ ] Dry-run mode для проверки
- [ ] Batch processing всех recordings

##### 3.1.2.4. Обновить database paths (30 мин)
- [ ] Migration для обновления stored paths:
  ```sql
  UPDATE recordings 
  SET processed_audio_path = concat('media/user_', user_id, '/audio/', id, '_processed.mp3')
  WHERE processed_audio_path IS NOT NULL;
  ```

#### 3.1.3. Security hardening (1 час)

##### 3.1.3.1. Defense-in-depth для файлов
- [ ] Добавить `user_id` filter в OutputTarget queries (2 места)
  ```python
  # api/repositories/recording_repos.py:244, 342
  stmt = select(OutputTargetModel).where(
      OutputTargetModel.recording_id == recording.id,
      OutputTargetModel.user_id == recording.user_id,  # ← ADD
      OutputTargetModel.target_type == target_type,
  )
  ```
- [ ] Validate file access в storage layer
- [ ] Add rate limiting per user (not global)

##### 3.1.3.2. Composite indexes
- [ ] Migration:
  ```sql
  CREATE INDEX idx_recordings_user_status ON recordings(user_id, status);
  CREATE INDEX idx_recordings_user_template ON recordings(user_id, template_id);
  CREATE INDEX idx_output_targets_user_status ON output_targets(user_id, status);
  ```

---

### **ФАЗА 3.2: File Lifecycle Management** (1-2 дня)
**Цель:** Автоматическая очистка, quota tracking, orphaned files

#### 3.2.1. File Manager с lifecycle (3 часа)
- [ ] `storage/file_manager.py`:
  ```python
  class FileManager:
      """Centralized file operations with lifecycle tracking"""
      
      async def save_file(self, path: Path, content: bytes, recording_id: int, user_id: int) -> Path:
          """Save file + track in quota"""
          # 1. Save file
          # 2. Update quota_usage (storage_bytes)
          # 3. Return path
      
      async def delete_file(self, path: Path, recording_id: int, user_id: int) -> bool:
          """Delete file + update quota"""
          # 1. Delete file
          # 2. Update quota_usage (decrement storage_bytes)
          # 3. Log operation
      
      async def delete_recording_files(self, recording: RecordingModel) -> dict:
          """Delete ALL files for recording"""
          deleted = {
              "video_original": False,
              "video_processed": False,
              "audio": False,
              "transcriptions": False,
              "thumbnails": False,
          }
          
          # Delete video files
          if recording.local_video_path:
              deleted["video_original"] = await self.delete_file(...)
          
          # Delete audio
          if recording.processed_audio_path:
              deleted["audio"] = await self.delete_file(...)
          
          # Delete transcription directory
          if recording.transcription_dir:
              shutil.rmtree(recording.transcription_dir)
              deleted["transcriptions"] = True
          
          return deleted
  ```

#### 3.2.2. Обновить delete recording (1 час)
- [ ] `api/repositories/recording_repos.py`:
  ```python
  async def delete(self, recording: RecordingModel) -> None:
      # 1. Delete files FIRST
      file_manager = FileManager()
      deleted_files = await file_manager.delete_recording_files(recording)
      logger.info(f"Deleted files for recording {recording.id}: {deleted_files}")
      
      # 2. Delete DB record
      await self.session.delete(recording)
      await self.session.flush()
  ```

#### 3.2.3. Cleanup utilities (2 часа)
- [ ] `scripts/cleanup_media.py`:
  ```python
  async def find_orphaned_files(user_id: int) -> list[Path]:
      """Find files without DB records"""
      # 1. Get all files in user directory
      # 2. Get all recording paths from DB
      # 3. Return difference
  
  async def cleanup_temp_files(user_id: int, max_age_hours: int = 24):
      """Delete old temp_processing files"""
      temp_dir = path_manager.get_temp_processing_dir(user_id)
      cutoff = datetime.now() - timedelta(hours=max_age_hours)
      
      for file in temp_dir.glob("*"):
          if file.stat().st_mtime < cutoff.timestamp():
              file.unlink()
  
  async def cleanup_expired_recordings():
      """Delete recordings past expire_at"""
      # Query recordings where expire_at < now()
      # Delete files + DB records
  ```

#### 3.2.4. Automatic quota tracking (2 часа)
- [ ] Интегрировать в `FileManager`:
  ```python
  async def _update_quota(self, user_id: int, bytes_delta: int):
      """Update quota_usage automatically"""
      from api.services.quota_service import QuotaService
      
      if bytes_delta > 0:
          await QuotaService.track_storage_added(user_id, bytes_delta)
      else:
          await QuotaService.track_storage_removed(user_id, abs(bytes_delta))
  ```
- [ ] Добавить в все file operations (save, delete)
- [ ] Background job для sync quota (раз в час)

#### 3.2.5. Celery periodic tasks (1 час)
- [ ] `api/tasks/maintenance.py`:
  ```python
  @celery_app.task(name="maintenance.cleanup_temp_files")
  def cleanup_temp_files_task():
      """Run every hour"""
      for user_id in get_all_user_ids():
          cleanup_temp_files(user_id, max_age_hours=24)
  
  @celery_app.task(name="maintenance.cleanup_expired_recordings")
  def cleanup_expired_task():
      """Run daily at 3am"""
      cleanup_expired_recordings()
  
  @celery_app.task(name="maintenance.sync_quota")
  def sync_quota_task():
      """Recalculate quota from actual files (hourly)"""
      for user_id in get_all_user_ids():
          actual_size = path_manager.get_user_storage_size(user_id)
          # Update quota_usage.storage_bytes
  ```
- [ ] Добавить в `celerybeat_schedule`

---

### **ФАЗА 3.3: Directory Structure Cleanup** (1 день)
**Цель:** Унифицировать структуру, удалить дублирование

#### 3.3.1. Унифицировать audio directories (2 часа)
- [ ] **Решение:** Использовать `user_{id}/audio/` (не `processed_audio`)
- [ ] Обновить `UserPathManager.get_audio_dir()`:
  ```python
  def get_audio_dir(self, user_id: int) -> Path:
      return self.get_user_root(user_id) / "audio"  # ← Убрать processed_audio
  ```
- [ ] Migration script:
  ```python
  # scripts/migrate_audio_dirs.py
  for user_id in get_all_user_ids():
      old_dir = Path(f"media/user_{user_id}/processed_audio")
      new_dir = Path(f"media/user_{user_id}/audio")
      
      if old_dir.exists():
          if not new_dir.exists():
              old_dir.rename(new_dir)
          else:
              # Merge directories
              for file in old_dir.glob("*"):
                  shutil.move(file, new_dir / file.name)
              old_dir.rmdir()
  ```

#### 3.3.2. Thumbnail optimization (2 часа)
- [ ] **Решение:** Не копировать templates, использовать fallback
- [ ] Обновить `ThumbnailManager.initialize_user_thumbnails()`:
  ```python
  def initialize_user_thumbnails(self, user_id: int, copy_templates: bool = False):
      # ❌ НЕ копировать по умолчанию
      self.ensure_user_thumbnails_dir(user_id)
      # Templates доступны через fallback в get_thumbnail_path()
  ```
- [ ] Cleanup script:
  ```python
  # scripts/cleanup_duplicate_thumbnails.py
  for user_id in get_all_user_ids():
      user_thumbs = path_manager.get_user_thumbnails_dir(user_id)
      
      for thumb in user_thumbs.glob("*.png"):
          # Check if identical to template
          template_thumb = templates_dir / thumb.name
          if template_thumb.exists() and files_identical(thumb, template_thumb):
              thumb.unlink()  # Delete duplicate
              logger.info(f"Removed duplicate thumbnail: {thumb}")
  ```

#### 3.3.3. Remove legacy directories (1 час)
- [ ] Проверить, что не используются:
  - `media/video/` - legacy, заменено на `user_{id}/video/`
  - `media/transcriptions/` - legacy, заменено на `user_{id}/transcriptions/`
  - `media/data.db` - переместить в root или удалить
- [ ] Migration script:
  ```python
  # scripts/cleanup_legacy_dirs.py
  legacy_dirs = [
      "media/video/temp_processing",
      "media/video/unprocessed",
      "media/transcriptions",
  ]
  
  for dir_path in legacy_dirs:
      path = Path(dir_path)
      if path.exists() and not any(path.iterdir()):  # Empty
          path.rmdir()
          logger.info(f"Removed empty legacy directory: {dir_path}")
  
  # Move data.db if exists
  if Path("media/data.db").exists():
      shutil.move("media/data.db", "data.db")
  ```

#### 3.3.4. Финальная структура storage (Breaking Change) (1 день)

**Решение:** Полная реорганизация в `storage/` (вместо `media/`)

**Ключевые решения:**
1. ✅ **S3-parity:** Абсолютно идентичная структура для S3 и local
2. ✅ **Recording-centric:** Все файлы одной записи в `recordings/{id}/`
3. ✅ **User thumbnails:** Отдельная папка `users/{user_id}/thumbnails/`
4. ✅ **No temp dir:** Используем `tempfile` module (system temp)
5. ✅ **Topics versioning:** Все версии в одном `topics.json` (текущая реализация ✅)
6. ✅ **No duplication:** Shared thumbnails с fallback, не копировать

**Новая структура:**
```
storage/
├── shared/
│   └── thumbnails/              # 22 глобальных шаблона (~5MB)
└── users/
    └── {user_id}/
        ├── thumbnails/          # User-uploaded (переиспользование)
        └── recordings/
            └── {recording_id}/  # ВСЕ файлы вместе
                ├── source.mp4
                ├── video.mp4
                ├── audio.mp3
                └── transcription/
                    ├── master.json
                    ├── topics.json  # Версии внутри
                    └── subtitles.srt
```

**Что убрали:**
- ❌ `media/video/`, `media/transcriptions/` - legacy
- ❌ `temp/` - используем system temp
- ❌ `assets/` внутри recording - thumbnails в `users/{user_id}/thumbnails/`
- ❌ `audio/processed` vs `processed_audio` - только `audio.mp3`
- ❌ Display_name в путях - только ID-based

**Преимущества:**
- ✅ S3-ready: `storage/users/5/recordings/142/source.mp4`
- ✅ Easy cleanup: `rm -rf recordings/142/`
- ✅ -20% storage (нет дублирования)
- ✅ Чистая иерархия: source → video → audio → transcription
- ✅ No encoding issues (только ID в путях)

**Реализация:**
- [ ] `storage/path_builder.py` - `StoragePathBuilder` class
- [ ] `scripts/migrate_to_new_structure.py` - полная миграция
- [ ] Обновить все импорты `UserPathManager` → `StoragePathBuilder`
- [ ] Update database paths в recordings
- [ ] Test на dev, затем production
- [ ] Cleanup старой структуры `media/`

**Документация:** См. `docs/STORAGE_STRUCTURE.md` (детальное описание)

---

### **ФАЗА 4: Архитектурная чистка** (2-3 дня)
**Цель:** Убрать костыли, legacy код, дублирование

#### 3.1. Унифицировать модели (3 часа)
- [ ] **Решение:** `RecordingModel` (database/) - единственная ORM модель
- [ ] Pydantic schemas в `api/schemas/recording/` - для API
- [ ] Удалить `models/recording.py` - класс `MeetingRecording`
- [ ] Сохранить Enums в `models/recording.py` (ProcessingStatus, SourceType, etc)
- [ ] Обновить импорты в 21 файле:
  - `from models import MeetingRecording` → `from database.models import RecordingModel`

#### 3.2. Удалить FileCredentialProvider (2 часа)
- [ ] Удалить `video_upload_module/credentials_provider.py` - `FileCredentialProvider` class
- [ ] Использовать ТОЛЬКО `DatabaseCredentialProvider`
- [ ] Все credentials в `user_credentials` table (encrypted)
- [ ] Удалить JSON credential files (youtube_creds.json, vk_creds.json)

#### 3.3. Переместить бизнес-логику из routers (2 часа)
- [ ] Переместить `_find_matching_template()` из `api/routers/input_sources.py`
- [ ] В `api/services/template_matcher.py` - метод `find_matching_template()`
- [ ] Вынести всю логику matching rules в service layer
- [ ] Routers должны быть thin - только валидация + вызов сервисов

#### 3.4. Удалить ZoomConfig legacy (1 час)
- [ ] Удалить `class ZoomConfig` из `config/settings.py`
- [ ] Удалить `load_config_from_file()` функцию
- [ ] Zoom credentials только через OAuth или БД
- [ ] Обновить 9 файлов, использующих `config.settings`

#### 4.5. Рефакторинг импортов (1 час)
- [ ] Создать `scripts/refactor_imports.py` для автоматизации
- [ ] Замены:
  - `from models import MeetingRecording` → `from database.models import RecordingModel`
  - `from config.settings import settings` → `from config.settings import get_settings`
  - `from api.config import get_settings` → `from config.settings import get_settings`
- [ ] Прогон linter после изменений

---

### **ФАЗА 5: Storage Abstraction** (2-3 дня)
**Цель:** S3 + Local storage с единым интерфейсом

#### 5.1. Создать storage interface (2 часа)
- [ ] `storage/backends/base.py`:
  ```python
  class StorageBackend(ABC):
      async def upload_file(local_path, remote_path) -> str
      async def download_file(remote_path, local_path) -> Path
      async def delete_file(remote_path) -> bool
      async def get_file_url(remote_path, expires_in) -> str
      async def file_exists(remote_path) -> bool
  ```

#### 5.2. Local backend (1 час)
- [ ] `storage/backends/local.py` - `LocalStorageBackend`
- [ ] Сохранить совместимость с `UserPathManager`
- [ ] File operations через `aiofiles`

#### 5.3. S3 backend (3 часа)
- [ ] `storage/backends/s3.py` - `S3StorageBackend`
- [ ] Dependencies: `aioboto3`, `types-aioboto3[s3]`
- [ ] Config: bucket, region, access keys, endpoint URL
- [ ] Presigned URLs для приватных файлов
- [ ] Multipart upload для больших файлов

#### 5.4. Storage manager (2 часа)
- [ ] `storage/manager.py` - factory pattern
- [ ] `get_storage_backend()` - возвращает backend по config
- [ ] Fallback: если S3 недоступен → local
- [ ] Интеграция с quota tracking

#### 5.5. Migration tool (2 часа)
- [ ] `scripts/migrate_to_s3.py` - перенос существующих файлов
- [ ] Batch processing + progress bar
- [ ] Валидация после миграции
- [ ] Возможность rollback

---

### **ФАЗА 6: External Sources** (5-6 дней)

#### 6.1. yt-dlp Integration (2-3 дня)

##### 6.1.1. URL Downloader (1 день)
- [ ] `video_download_module/url_downloader.py`:
  - `URLDownloader.download(url, output_path, format)`
  - `URLDownloader.get_video_info(url)` - metadata без скачивания
  - Progress callback для Celery
- [ ] Supported platforms: YouTube, VK, Vimeo, Dailymotion, etc (1000+ sites)
- [ ] Dependency: `yt-dlp==2024.1.7`

##### 6.1.2. API endpoints (1 день)
- [ ] `POST /recordings/from-url`:
  - Body: `{url, display_name?, template_id?}`
  - Валидация URL через `URLDownloader.get_video_info()`
  - Создание recording + Celery task
- [ ] `POST /input-sources` - добавить `source_type: "url"`

##### 6.1.3. Celery task (0.5 дня)
- [ ] `@celery_app.task download_from_url_task(url, recording_id, user_id)`
- [ ] Quota check перед скачиванием
- [ ] Progress updates через `update_progress()`

#### 6.2. Yandex Disk Integration (3-4 дня)

##### 6.2.1. Input - Download (1.5 дня)
- [ ] `video_download_module/yandex_downloader.py`:
  - `download_by_public_link(public_url)` - публичные ссылки
  - `download_from_private(path, oauth_token)` - приватные файлы
  - `list_folder(path, oauth_token, recursive)` - scan папки
- [ ] API: `POST /recordings/from-yandex-disk`
  - `{source_type: "public_link" | "private_path" | "folder_scan", url_or_path, recursive?}`

##### 6.2.2. Output - Upload (1.5 дня)
- [ ] `video_upload_module/platforms/yandex/uploader.py`:
  - `YandexDiskUploader(BaseUploader)`
  - Upload flow: GET upload URL → PUT file → Publish (optional)
- [ ] Metadata: folder_path, publish (make public)

##### 6.2.3. OAuth 2.0 (1 день)
- [ ] `api/routers/oauth.py`:
  - `GET /oauth/yandex/authorize`
  - `GET /oauth/yandex/callback`
  - Scopes: `cloud_api:disk.read`, `cloud_api:disk.write`
- [ ] Token refresh logic
- [ ] Store в `user_credentials` table

---

### **ФАЗА 7: Testing** (5-7 дней)
**Цель:** Coverage 60%+, критические пути 80%+

#### 7.1. Test infrastructure (1 день)
- [ ] `tests/conftest.py`:
  - DB fixtures (test database)
  - User fixtures (free, plus, pro)
  - Auth fixtures (tokens)
  - Mock external APIs
- [ ] Dependencies: `pytest`, `pytest-asyncio`, `pytest-cov`, `httpx`, `faker`

#### 7.2. Unit tests (2 дня)
- [ ] `tests/unit/test_auth.py` - password hashing, JWT, permissions
- [ ] `tests/unit/test_quota.py` - quota calculations, pay-as-you-go
- [ ] `tests/unit/test_template_matcher.py` - matching rules logic
- [ ] `tests/unit/test_config_resolver.py` - config hierarchy
- [ ] `tests/unit/test_storage_backends.py` - local + S3

#### 7.3. Integration tests (2 дня)
- [ ] `tests/integration/test_api_auth.py` - register, login, refresh, logout
- [ ] `tests/integration/test_api_recordings.py`:
  - CRUD operations
  - User isolation (403/404)
  - Quota enforcement (429)
- [ ] `tests/integration/test_api_templates.py`
- [ ] `tests/integration/test_celery_tasks.py` - mock Celery

#### 7.4. E2E tests (2 дня)
- [ ] `tests/e2e/test_full_pipeline.py`:
  - Sync → Template match → Download → Process → Transcribe → Upload
- [ ] `tests/e2e/test_automation.py` - scheduled jobs
- [ ] Mock external APIs (YouTube, VK, Fireworks)

#### 7.5. CI/CD (0.5 дня)
- [ ] `.github/workflows/test.yml`:
  - Run on push/PR
  - Services: postgres, redis
  - Coverage report → Codecov

---

### **ФАЗА 8: Deployment & Documentation** (3-4 дня)

#### 8.1. Docker optimization (1 день)
- [ ] Multi-stage Dockerfile (builder + runtime)
- [ ] `.dockerignore` - exclude tests, docs
- [ ] Health checks для containers
- [ ] `docker-compose.prod.yml`:
  - API replicas: 2
  - Celery worker replicas: 3
  - Nginx reverse proxy
  - SSL certificates (Let's Encrypt)

#### 8.2. Kubernetes (1 день)
- [ ] `k8s/deployment.yml` - API + Celery workers
- [ ] `k8s/configmap.yml` - non-sensitive config
- [ ] `k8s/secret.yml` - credentials (sealed secrets)
- [ ] `k8s/ingress.yml` - HTTPS + routing
- [ ] `k8s/hpa.yml` - auto-scaling

#### 8.3. Monitoring (1 день)
- [ ] Prometheus metrics:
  - API: request latency, error rate
  - Celery: queue depth, task duration
  - DB: connection pool, query duration
- [ ] Grafana dashboards
- [ ] Alerts: high error rate, disk space, memory

#### 8.4. Documentation (1 день)
- [ ] `docs/getting-started/` - installation, configuration, first steps
- [ ] `docs/api/` - authentication, recordings, templates, webhooks
- [ ] `docs/guides/` - S3 setup, Yandex Disk, URL downloads, templates
- [ ] `docs/deployment/` - Docker, Kubernetes, AWS, monitoring
- [ ] `docs/development/` - architecture, testing, contributing
- [ ] Auto-generate API reference from OpenAPI

---

## 🎯 Приоритизация

| Задача | Приоритет | Impact | Effort | ROI |
|--------|-----------|--------|--------|-----|
| Unified Config | 🔴 Критично | ⭐⭐⭐⭐⭐ | 1д | ⭐⭐⭐⭐⭐ |
| Structured Logging | 🔴 Критично | ⭐⭐⭐⭐⭐ | 1д | ⭐⭐⭐⭐⭐ |
| **Security (UUID + Files)** | 🔴 Критично | ⭐⭐⭐⭐⭐ | 2д | ⭐⭐⭐⭐⭐ |
| Архитектурная чистка | 🟠 Высокий | ⭐⭐⭐⭐ | 3д | ⭐⭐⭐⭐ |
| S3 Storage | 🟠 Высокий | ⭐⭐⭐⭐ | 2д | ⭐⭐⭐⭐ |
| yt-dlp Integration | 🟡 Средний | ⭐⭐⭐⭐ | 2д | ⭐⭐⭐ |
| Yandex Disk | 🟡 Средний | ⭐⭐⭐ | 3д | ⭐⭐⭐ |
| Testing | 🟠 Высокий | ⭐⭐⭐⭐⭐ | 5д | ⭐⭐⭐⭐⭐ |
| Deployment | 🟡 Средний | ⭐⭐⭐⭐ | 3д | ⭐⭐⭐⭐ |

---

## 📅 Рекомендуемая последовательность

### **НЕДЕЛЯ 1: Чистая база (Clean Foundation)**
- **День 1:** ФАЗА 1 - Unified Config
- **День 2:** ФАЗА 2 - Structured Logging + Sentry
- **День 3-4:** ФАЗА 3 - Security & File Management (UUID + ID-based files)
- **День 5:** ФАЗА 4 - Архитектурная чистка (начало)

**Результат:** Production-ready кодовая база без технического долга и уязвимостей

### **НЕДЕЛЯ 2: Новые возможности (New Features)**
- **День 6-7:** ФАЗА 4 - Архитектурная чистка (завершение)
- **День 8-10:** ФАЗА 5 - S3 Storage
- **День 11-12:** ФАЗА 6.1 - yt-dlp
- **День 13-14:** ФАЗА 6.2 - Yandex Disk (начало)

**Результат:** Расширенная функциональность (storage + external sources)

### **НЕДЕЛЯ 3: Качество и релиз (Quality & Release)**
- **День 15-16:** ФАЗА 6.2 - Yandex Disk (завершение)
- **День 17-21:** ФАЗА 7 - Testing (60%+ coverage)
- **День 22:** ФАЗА 8 - Deployment + Documentation

**Результат:** Протестированная система, готовая к production deploy

---

## 🚨 НОВЫЕ КРИТИЧЕСКИЕ ЗАДАЧИ (после очистки 2026-01-18)

### 1. 🔴 КРИТИЧНО: Разбить гигантский роутер (2-3 дня)
**Проблема:** `api/routers/recordings.py` - **2510 строк** (нарушение SRP)

**Решение:**
```python
# Разбить на 3 файла:
api/routers/recordings/
├── __init__.py          # Re-export всех endpoints
├── list.py              # GET /recordings (фильтрация, пагинация) ~800 строк
├── operations.py        # POST /process, /upload, /subtitles ~900 строк
└── admin.py             # DELETE, reset, cleanup ~800 строк
```

**Реализация:**
- [ ] Создать `api/routers/recordings/` package
- [ ] Переместить endpoints по категориям
- [ ] Обновить импорты в `api/main.py`
- [ ] Тесты на совместимость API

### 2. 🟠 ВЫСОКИЙ: Заменить os.path → Path (1 день)
**Осталось 13 файлов:**
- [ ] `video_processing_module/video_processor.py`
- [ ] `fireworks_module/service.py`
- [ ] `subtitle_module/subtitle_generator.py`
- [ ] `database/manager.py`
- [ ] `config/unified_config.py`
- [ ] `deepseek_module/config.py`
- [ ] `fireworks_module/config.py`
- [ ] `utils/audio_compressor.py`
- [ ] `utils/user_paths.py`
- [ ] `logger.py`
- [ ] `api/services/oauth_platforms.py` (os.getenv можно оставить)
- [ ] `api/middleware/error_handler.py`

**Скрипт для автоматизации:**
```python
# scripts/refactor_os_to_path.py
replacements = [
    ("os.path.exists(", "Path().exists()"),
    ("os.path.getsize(", "Path().stat().st_size"),
    ("os.remove(", "Path().unlink()"),
    ("os.makedirs(", "Path().mkdir(parents=True, exist_ok=True)"),
]
```

### 3. 🟡 СРЕДНИЙ: Реализовать TODO в quota_service.py (2 часа)
**Проблема:** Quota tracking не автоматический

**TODO locations:**
- `api/services/quota_service.py:184` - `TODO: Implement actual count from automation_jobs`
- `api/services/quota_service.py:305` - `TODO: Get from automation_jobs table`

**Решение:**
```python
async def get_automation_jobs_count(user_id: int) -> int:
    """Get actual automation jobs count from database"""
    stmt = select(func.count(AutomationJobModel.id)).where(
        AutomationJobModel.user_id == user_id,
        AutomationJobModel.is_active == True
    )
    result = await session.execute(stmt)
    return result.scalar() or 0
```

### 4. 🟡 СРЕДНИЙ: Добавить миграцию для SKIPPED статуса (1 час)
**Проблема:** `models/recording.py:156` - `TODO: Добавить SKIPPED в БД через миграцию`

**Решение:**
```python
# alembic/versions/xxx_add_skipped_status.py
def upgrade():
    # Add SKIPPED to enum if not exists
    op.execute("""
        DO $$ BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_enum e
                JOIN pg_type t ON e.enumtypid = t.oid
                WHERE t.typname = 'processingstatus' AND e.enumlabel = 'SKIPPED'
            ) THEN
                ALTER TYPE processingstatus ADD VALUE 'SKIPPED';
            END IF;
        END $$;
    """)
```

### 5. 🟠 ВЫСОКИЙ: Рефакторинг больших файлов (3-4 дня)
**Проблема:** 3 файла >1000 строк

**Приоритет 1:** `api/tasks/processing.py` (1421 строк)
- Разбить на: `download.py`, `process.py`, `transcribe.py`, `upload.py`

**Приоритет 2:** `deepseek_module/topic_extractor.py` (1148 строк)
- Выделить: `prompts.py`, `parsers.py`, `validators.py`

**Приоритет 3:** `fireworks_module/service.py` (1026 строк)
- Разделить: `batch_api.py`, `streaming_api.py`, `utils.py`

## ⚡ Quick Wins (можно сделать прямо сейчас)

### 1. 🔴 CRITICAL: Fix delete recording (30 мин)
```python
# api/repositories/recording_repos.py:564
async def delete(self, recording: RecordingModel) -> None:
    # ❌ СЕЙЧАС: Только БД, файлы остаются
    # ✅ НУЖНО: Удалить файлы ПЕРЕД удалением записи
    
    # 1. Delete video files
    if recording.local_video_path and Path(recording.local_video_path).exists():
        Path(recording.local_video_path).unlink()
    
    if recording.processed_video_path and Path(recording.processed_video_path).exists():
        Path(recording.processed_video_path).unlink()
    
    # 2. Delete audio
    if recording.processed_audio_path and Path(recording.processed_audio_path).exists():
        Path(recording.processed_audio_path).unlink()
    
    # 3. Delete transcriptions
    if recording.transcription_dir and Path(recording.transcription_dir).exists():
        shutil.rmtree(recording.transcription_dir)
    
    # 4. Delete DB record
    await self.session.delete(recording)
    await self.session.flush()
```

### 2. Security: Fix OutputTarget queries (15 мин)
```python
# api/repositories/recording_repos.py (2 места: строки 244, 342)
stmt = select(OutputTargetModel).where(
    OutputTargetModel.recording_id == recording.id,
    OutputTargetModel.user_id == recording.user_id,  # ← ADD
    OutputTargetModel.target_type == target_type,
)
```

### 3. Add composite indexes (20 мин)
```sql
-- New Alembic migration
CREATE INDEX idx_recordings_user_status ON recordings(user_id, status);
CREATE INDEX idx_recordings_user_template ON recordings(user_id, template_id);
CREATE INDEX idx_output_targets_user_status ON output_targets(user_id, status);
```

### 4. Cleanup temp files script (20 мин)
```python
# scripts/cleanup_temp.py
from pathlib import Path
from datetime import datetime, timedelta

def cleanup_temp_files(max_age_hours=24):
    """Delete old temp_processing files"""
    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    
    for user_dir in Path("media").glob("user_*/video/temp_processing"):
        for file in user_dir.glob("*"):
            if file.stat().st_mtime < cutoff.timestamp():
                file.unlink()
                print(f"Deleted: {file}")

# Run: python scripts/cleanup_temp.py
```

### 5. Remove duplicate thumbnails (15 мин)
```python
# scripts/cleanup_duplicate_thumbnails.py
templates_dir = Path("media/templates/thumbnails")

for user_dir in Path("media").glob("user_*/thumbnails"):
    for thumb in user_dir.glob("*.png"):
        template_thumb = templates_dir / thumb.name
        
        # If identical to template, delete user copy
        if template_thumb.exists():
            if thumb.read_bytes() == template_thumb.read_bytes():
                thumb.unlink()
                print(f"Removed duplicate: {thumb}")
```

### 6. Create StoragePathBuilder (1 час)
```python
# storage/path_builder.py - начать новую архитектуру
class StoragePathBuilder:
    """Generate storage paths (S3-compatible)"""
    
    def recording_root(self, user_id: int, recording_id: int) -> Path:
        return Path(f"storage/users/{user_id}/recordings/{recording_id}")
    
    def recording_source(self, user_id: int, recording_id: int) -> Path:
        return self.recording_root(user_id, recording_id) / "source.mp4"
    
    # ... other methods
```

---

## 📝 Чек-лист перед началом

- [ ] Создать ветку `feature/clean-architecture`
- [ ] **Backup production database** (критично!)
- [ ] **Backup media files** → `cp -r media media_backup`
- [ ] Создать `.env.example` в корне проекта
- [ ] Обновить `requirements.txt` с версиями
- [ ] Создать `CHANGELOG.md` для отслеживания изменений
- [ ] Setup pre-commit hooks (ruff, mypy)

## 📚 Связанная документация

- **`docs/STORAGE_STRUCTURE.md`** - детальное описание новой структуры storage (15 страниц)
- **`docs/MEDIA_SYSTEM_AUDIT.md`** - полный аудит медиа-системы с проблемами (15 страниц)
- **`MEDIA_ISSUES_SUMMARY.md`** - краткая сводка проблем (2 страницы)
- **`docs/WHAT_WAS_DONE.md`** - история изменений проекта

---

## 🎓 Дополнительные улучшения (post-v1.0)

### Мониторинг и алерты
- [ ] Grafana dashboards (API, Celery, DB)
- [ ] Prometheus exporters
- [ ] PagerDuty/Opsgenie integration
- [ ] Custom metrics (quota usage trends, upload success rate)

### Безопасность
- [ ] Rate limiting per user (Celery rate limits)
- [ ] API key authentication (для programmatic access)
- [ ] Webhook signatures (HMAC verification)
- [ ] Audit logs (кто что изменил)

### Performance
- [ ] Redis caching (template configs, user quotas)
- [ ] CDN для static files
- [ ] Database read replicas
- [ ] Celery priority queues

### Фичи
- [ ] Webhooks для event notifications
- [ ] Email notifications (quota warnings, processing complete)
- [ ] Analytics dashboard API
- [ ] Batch operations API improvements
- [ ] Video preview/thumbnails generation

---

