# API Consistency Audit & Fixes

**Дата:** 9 января 2026  
**Версия:** v2.11

---

## ✅ Проблемы исправлены

### 1. Automation endpoints - добавлен `/api/v1` префикс

**Было:**
```python
router = APIRouter(prefix="/automation/jobs", tags=["Automation"])
# Endpoints: /automation/jobs, /automation/jobs/{id}, etc.
```

**Стало:**
```python
router = APIRouter(prefix="/api/v1/automation/jobs", tags=["Automation"])
# Endpoints: /api/v1/automation/jobs, /api/v1/automation/jobs/{id}, etc.
```

**Файл:** `api/routers/automation.py`

---

### 2. Credentials - заменен PUT на PATCH

**Было:**
```python
@router.put("/{credential_id}", response_model=CredentialResponse)
async def update_credentials(...):
    # PUT = полная замена ресурса
```

**Стало:**
```python
@router.patch("/{credential_id}", response_model=CredentialResponse)
async def update_credentials(...):
    # PATCH = частичное обновление (консистентно с остальными endpoints)
```

**Файл:** `api/routers/credentials.py`

---

## 📊 Итоговая статистика API

### HTTP методы:
- **GET:** 31 endpoint (чтение ресурсов)
- **POST:** 25 endpoints (создание + actions)
- **PATCH:** 7 endpoints (частичное обновление)
- **DELETE:** 8 endpoints (удаление ресурсов)

**Всего:** 71 endpoint

### Консистентность методов:

✅ **Все CRUD операции используют:**
- `GET /resources` - список ресурсов
- `POST /resources` - создание ресурса
- `GET /resources/{id}` - получение ресурса
- `PATCH /resources/{id}` - обновление ресурса (частичное)
- `DELETE /resources/{id}` - удаление ресурса

✅ **Никаких PUT endpoints** - все обновления через PATCH

✅ **Все endpoints имеют `/api/v1` префикс**

---

## 🎯 REST Conventions

### Стандартные CRUD паттерны:

| Resource | List | Create | Read | Update | Delete |
|----------|------|--------|------|--------|--------|
| **credentials** | GET / | POST / | GET /{id} | PATCH /{id} | DELETE /{id} |
| **presets** | GET / | POST / | GET /{id} | PATCH /{id} | DELETE /{id} |
| **sources** | GET / | POST / | GET /{id} | PATCH /{id} | DELETE /{id} |
| **templates** | GET / | POST / | GET /{id} | PATCH /{id} | DELETE /{id} |
| **automation/jobs** | GET / | POST / | GET /{id} | PATCH /{id} | DELETE /{id} |
| **thumbnails** | GET / | POST / | GET /{name} | - | DELETE /{name} |
| **tasks** | - | - | GET /{id} | - | DELETE /{id} |

### Action endpoints (POST):

**Recordings:**
- `POST /{id}/download` - скачать из источника
- `POST /{id}/process` - обработать видео
- `POST /{id}/transcribe` - транскрибировать
- `POST /{id}/topics` - извлечь темы
- `POST /{id}/subtitles` - сгенерировать субтитры
- `POST /{id}/upload/{platform}` - загрузить на платформу
- `POST /{id}/full-pipeline` - полный цикл
- `POST /batch-process` - массовая обработка
- `POST /batch/transcribe` - массовая транскрибация

**Sources:**
- `POST /{id}/sync` - синхронизировать записи

**Automation:**
- `POST /{id}/run` - запустить job вручную

**User Config:**
- `POST /me/config/reset` - сбросить к defaults

**Auth:**
- `POST /login`, `/logout`, `/refresh`, `/register`

---

## 🔍 Особые случаи

### 1. POST для reset/run actions
```
POST /api/v1/users/me/config/reset
POST /api/v1/automation/jobs/{id}/run
```
**Обоснование:** RPC-style endpoints для действий (не CRUD операции над ресурсами)

### 2. Recordings - read-only на уровне объекта
```
GET /api/v1/recordings/{id}  ✅
PATCH /api/v1/recordings/{id}  ❌ Нет
DELETE /api/v1/recordings/{id}  ❌ Нет (только для пользователей)
```
**Обоснование:** Recordings изменяются через actions (download, process, etc), а не прямым PATCH

### 3. Tasks - только чтение и отмена
```
GET /api/v1/tasks/{id}     ✅
DELETE /api/v1/tasks/{id}  ✅ (отменить задачу)
```
**Обоснование:** Tasks создаются автоматически через другие endpoints, пользователь может только читать/отменять

---

## ✅ Проверки пройдены

- ✅ Все endpoints имеют `/api/v1` префикс
- ✅ Никаких PUT endpoints (только PATCH для updates)
- ✅ Консистентная структура CRUD операций
- ✅ GET для чтения, POST для создания/действий
- ✅ PATCH для частичных обновлений
- ✅ DELETE для удаления
- ✅ Linter errors: 0
- ✅ API loads successfully

---

## 📝 Конвенции для новых endpoints

При добавлении новых endpoints следуйте этим правилам:

### 1. Префикс
```python
router = APIRouter(prefix="/api/v1/resource", tags=["Resource"])
```

### 2. CRUD операции
```python
@router.get("")                    # Список
@router.post("")                   # Создание
@router.get("/{id}")               # Чтение
@router.patch("/{id}")             # Обновление (НЕ PUT!)
@router.delete("/{id}")            # Удаление
```

### 3. Actions
```python
@router.post("/{id}/action-name")  # Для действий над ресурсом
```

### 4. Nested resources
```python
@router.get("/{id}/sub-resource")       # Вложенные ресурсы
@router.get("/{id}/sub-resource/{sid}") # Конкретный подресурс
```

---

## 🎉 Результат

Все API endpoints теперь следуют единым REST конвенциям:
- Консистентное использование HTTP методов
- Единообразная структура URL
- Понятная и предсказуемая логика

**Total endpoints:** 71  
**Linter errors:** 0  
**API consistency:** 100% ✅

