# 📁 Storage Structure - Final Design

**Version:** 2.0  
**Date:** 2026-01-16  
**Status:** Approved for implementation

---

## 🎯 Design Principles

1. **S3-Local Parity:** Абсолютно идентичная структура для local и S3
2. **Recording-Centric:** Все файлы одной записи в одном месте
3. **No Duplication:** Shared resources с fallback, не копировать
4. **Clear Lifecycle:** Файлы живут до expired статуса
5. **Breaking Change OK:** Полная реорганизация

---

## 📂 Directory Structure

```
storage/                             # Root (configurable: local path or S3 bucket)
│
├── shared/                          # Глобальные ресурсы (read-only для всех)
│   └── thumbnails/
│       ├── applied_python.png       # ~200KB each
│       ├── machine_learning.png
│       ├── big_data.png
│       └── ...                      # Total: 22 files (~5MB)
│
├── users/                           # User-specific storage
│   └── {user_id}/                   # Integer ID (UUID migration later)
│       └── recordings/
│           └── {recording_id}/      # All files for one recording
│               │
│               ├── source.mp4       # Original video from Zoom/URL
│               ├── video.mp4        # Processed/trimmed video
│               ├── audio.mp3        # Extracted audio for transcription
│               │
│               ├── transcription/   # All transcription-related files
│               │   ├── master.json          # Full transcription with words
│               │   ├── topics_v1.json       # Topics extraction (versioned)
│               │   ├── topics_v2.json       # Updated topics (if re-extracted)
│               │   ├── subtitles.srt        # Subtitles (SRT format)
│               │   └── subtitles.vtt        # Subtitles (VTT format)
│               │
│               └── assets/          # Recording-specific assets
│                   ├── custom_thumbnail.png  # User-uploaded thumbnail
│                   └── metadata.json         # Additional metadata
│
└── temp/                            # Temporary processing files
    └── {user_id}/
        └── {job_id}/                # UUID for each processing job
            ├── processing.mp4       # Temp file during FFmpeg
            ├── download.mp4         # Temp during download
            └── audio_extract.wav    # Temp during extraction
```

---

## 🔑 Key Design Decisions

### 1. Why `storage/` instead of `media/`?

**Reasoning:**
- More professional and clear
- "Media" implies content, "Storage" implies infrastructure
- Easier to understand for DevOps (storage = files)

### 2. Why `recordings/{id}/` flat structure?

**Advantages:**
```python
# Easy cleanup - delete ALL files for recording:
shutil.rmtree(f"storage/users/{user_id}/recordings/{rec_id}")

# Easy size calculation:
def get_recording_size(user_id, rec_id):
    return sum(f.stat().st_size for f in Path(...).rglob("*") if f.is_file())

# Easy to find all files:
recording_files = list(Path(f"storage/users/{user_id}/recordings/{rec_id}").rglob("*"))
```

**vs Type-based:**
```python
# Hard cleanup - need to track multiple locations:
unlink(f"storage/users/{user_id}/videos/{rec_id}_original.mp4")
unlink(f"storage/users/{user_id}/videos/{rec_id}_processed.mp4")
unlink(f"storage/users/{user_id}/audio/{rec_id}.mp3")
rmtree(f"storage/users/{user_id}/transcriptions/{rec_id}")
# ❌ Error-prone, easy to miss files
```

### 3. Why `shared/` instead of `templates/`?

**Future-proof:**
```
shared/
├── thumbnails/        # Current
├── intros/           # Future: intro videos
├── outros/           # Future: outro videos
├── watermarks/       # Future: watermarks
└── backgrounds/      # Future: background music
```

### 4. Why simple filenames (`source.mp4` not `142_original.mp4`)?

**Reasoning:**
- Recording ID already in path: `recordings/142/`
- Shorter paths (better for logs, debugging)
- No encoding issues (no display_name in filename)
- Clear purpose: `source` = what we got, `video` = what we processed

### 5. Why `temp/{user_id}/{job_id}/`?

**Advantages:**
- Isolated per job (parallel processing safe)
- Easy cleanup: delete by job_id
- User-level isolation maintained
- UUID job_id = no collisions

---

## 📋 File Naming Conventions

### Video Files
- `source.mp4` - Original video (from Zoom, URL, upload)
- `video.mp4` - Processed video (trimmed, converted)

### Audio Files
- `audio.mp3` - Extracted audio (64kbps, mono, 16kHz for transcription)

### Transcription Files
- `master.json` - Full transcription (words + segments + metadata)
- `topics_v{N}.json` - Topics extraction (versioned, N = 1, 2, 3...)
- `subtitles.{format}` - Subtitles (srt, vtt, etc)

### Assets
- `custom_thumbnail.png` - User-uploaded thumbnail
- `metadata.json` - Additional metadata (tags, notes, etc)

---

## 🔄 Lifecycle Management

### File Retention Policy

| File Type | Retention | Notes |
|-----------|-----------|-------|
| `source.mp4` | Until expired | Original for re-processing |
| `video.mp4` | Until expired | For uploads/re-uploads |
| `audio.mp3` | Until expired | For re-transcription |
| `transcription/*` | Until expired | For API responses |
| `assets/*` | Until expired | User data |
| `temp/*` | 24 hours | Auto-cleanup |

### Expired Status Cleanup

```python
# When recording.status = EXPIRED:
1. Delete storage/users/{user_id}/recordings/{recording_id}/
2. Update quota_usage (decrement storage_bytes)
3. Delete DB record
```

---

## 🌐 S3 Compatibility

### Local Path
```python
Path("storage/users/5/recordings/142/source.mp4")
```

### S3 Path (identical structure!)
```python
s3://my-bucket/storage/users/5/recordings/142/source.mp4
```

### Implementation

```python
# storage/backends/base.py
class StorageBackend(ABC):
    @abstractmethod
    async def save(self, path: str, content: bytes) -> str:
        """Save file, return full path"""
    
    @abstractmethod
    async def load(self, path: str) -> bytes:
        """Load file content"""
    
    @abstractmethod
    async def delete(self, path: str) -> bool:
        """Delete file"""
    
    @abstractmethod
    async def exists(self, path: str) -> bool:
        """Check if file exists"""

# storage/backends/local.py
class LocalStorageBackend(StorageBackend):
    def __init__(self, base_path: str = "storage"):
        self.base = Path(base_path)
    
    async def save(self, path: str, content: bytes) -> str:
        full_path = self.base / path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(content)
        return str(full_path)

# storage/backends/s3.py
class S3StorageBackend(StorageBackend):
    def __init__(self, bucket: str, prefix: str = "storage"):
        self.bucket = bucket
        self.prefix = prefix
    
    async def save(self, path: str, content: bytes) -> str:
        s3_key = f"{self.prefix}/{path}"
        await s3.put_object(Bucket=self.bucket, Key=s3_key, Body=content)
        return f"s3://{self.bucket}/{s3_key}"
```

---

## 🛠️ StoragePathBuilder API

```python
from storage.path_builder import StoragePathBuilder

builder = StoragePathBuilder()

# Shared resources
builder.shared_thumbnail("ml_extra.png")
# → "storage/shared/thumbnails/ml_extra.png"

# Recording files
builder.recording_source(user_id=5, recording_id=142)
# → "storage/users/5/recordings/142/source.mp4"

builder.recording_video(user_id=5, recording_id=142)
# → "storage/users/5/recordings/142/video.mp4"

builder.transcription_master(user_id=5, recording_id=142)
# → "storage/users/5/recordings/142/transcription/master.json"

builder.transcription_topics(user_id=5, recording_id=142, version=2)
# → "storage/users/5/recordings/142/transcription/topics_v2.json"

# Temp files
builder.temp_file(user_id=5, job_id="uuid-123", filename="processing.mp4")
# → "storage/temp/5/uuid-123/processing.mp4"

# Helpers
builder.delete_recording_files(user_id=5, recording_id=142)
# Deletes entire recording directory

builder.get_recording_size(user_id=5, recording_id=142)
# Returns total size in bytes
```

---

## 📊 Migration from Old Structure

### Before (media/)
```
media/
├── data.db                          # ❌ Wrong place
├── video/                           # ❌ Legacy
├── transcriptions/                  # ❌ Legacy
├── templates/thumbnails/            # ✅ Keep as shared
└── user_4/
    ├── video/
    │   ├── unprocessed/
    │   │   └── Тюлягин_GenDL_25-12-25_12-55.mp4
    │   └── processed/
    │       └── Тюлягин_GenDL_25-12-25_12-55_processed.mp4
    ├── audio/processed/
    │   └── Тюлягин_GenDL_25-12-25_12-55_processed.mp3
    ├── processed_audio/             # ❌ Duplicate
    └── transcriptions/
        └── 21/
            ├── master.json
            └── topics_v1.json
```

### After (storage/)
```
storage/
├── shared/
│   └── thumbnails/                  # Moved from media/templates
└── users/
    └── 4/
        └── recordings/
            └── 21/                  # Clean, organized
                ├── source.mp4       # From unprocessed
                ├── video.mp4        # From processed
                ├── audio.mp3        # From audio/processed
                └── transcription/
                    ├── master.json
                    └── topics_v1.json
```

### Migration Script

```bash
# Run migration
python scripts/migrate_to_new_structure.py

# Before:
$ du -sh media/
5.2G    media/

# After:
$ du -sh storage/
4.1G    storage/         # ~20% smaller (no duplicates!)
```

---

## ✅ Benefits Summary

| Aspect | Old (media/) | New (storage/) |
|--------|-------------|----------------|
| Structure | Inconsistent | Consistent |
| Duplication | audio/ + processed_audio/ | Single audio.mp3 |
| Cleanup | Manual, error-prone | `rm -rf recordings/{id}` |
| S3 Migration | Complex | Copy structure as-is |
| File Finding | Search multiple dirs | Single recording dir |
| Size Calculation | Walk all dirs | Single directory walk |
| Encoding Issues | Cyrillic in filenames | Only IDs in paths |
| Quota Tracking | Manual calculation | Automatic on save/delete |

---

## 🚀 Implementation Checklist

- [ ] Create `storage/path_builder.py`
- [ ] Create `storage/backends/base.py`
- [ ] Create `storage/backends/local.py`
- [ ] Create `storage/backends/s3.py` (ФАЗА 5)
- [ ] Create migration script
- [ ] Update all file operations to use `StoragePathBuilder`
- [ ] Update database paths
- [ ] Test on dev environment
- [ ] Run migration on production
- [ ] Verify all files migrated
- [ ] Delete old `media/` directory
- [ ] Update documentation

---

**Status:** Ready for implementation  
**Estimated time:** 1 day (migration included)  
**Breaking change:** Yes (acceptable per requirements)
