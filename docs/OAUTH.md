# OAuth Integration Guide

**Полное руководство по OAuth 2.0 интеграции для YouTube, VK, Zoom**

**Статус:** ✅ Production Ready

---

## 📋 Содержание

1. [Quick Start (30 мин)](#quick-start-30-мин)
2. [Architecture](#architecture)
3. [Platform Setup](#platform-setup)
4. [Integration with Uploaders](#integration-with-uploaders)
5. [Testing & Troubleshooting](#testing--troubleshooting)

---

## Quick Start (30 мин)

### 🎯 Что получите

- ✅ OAuth приложение Google (для YouTube)
- ✅ OAuth приложение VK
- ✅ Zoom OAuth (опционально)
- ✅ Все необходимые credentials
- ✅ Настроенные redirect URIs

### ⏱️ Шаг 1: Google Cloud Console (15 мин)

**YouTube Data API v3 setup:**

1. **Открыть:** https://console.cloud.google.com/
2. **Создать проект:** "ZoomUploader"
3. **Включить API:** YouTube Data API v3
4. **Настроить OAuth consent screen:**
   - External
   - App name: ZoomUploader
   - Scopes: `youtube.upload`, `youtube.force-ssl`
   - **Добавить себя в Test users** (важно!)
5. **Создать credentials:**
   - Type: Web application
   - Redirect URI: `http://localhost:8000/api/v1/oauth/youtube/callback`
6. **Скопировать:**
   - Client ID
   - Client Secret

**Создать файл:** `config/oauth_google.json`

```json
{
  "client_id": "YOUR_CLIENT_ID",
  "client_secret": "YOUR_CLIENT_SECRET",
  "project_id": "zoomuploader",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token"
}
```

### ⏱️ Шаг 2: VK Application (10 мин)

**VK Video API setup:**

1. **Открыть:** https://vk.com/apps?act=manage
2. **Создать приложение:**
   - Название: ZoomUploader
   - Платформа: Веб-сайт
   - Адрес: `http://localhost:8000`
3. **Настроить:**
   - Redirect URI: `http://localhost:8000/api/v1/oauth/vk/callback`
   - Скопировать App ID и Защищённый ключ

**Создать файл:** `config/oauth_vk.json`

```json
{
  "app_id": "YOUR_APP_ID",
  "client_secret": "YOUR_SECRET",
  "redirect_uri": "http://localhost:8000/api/v1/oauth/vk/callback"
}
```

### ⏱️ Шаг 3: Проверка

```bash
# Запустить API
make api

# Открыть браузер
http://localhost:8000/api/v1/oauth/youtube/authorize
http://localhost:8000/api/v1/oauth/vk/authorize
```

✅ Проверить: credentials сохранены в БД после авторизации

---

## Architecture

### 🏗️ Components

```
┌─────────────────────────────────────────┐
│        OAuth Architecture                │
└─────────────────────────────────────────┘

User → /oauth/{platform}/authorize
    ↓
Generate state token (Redis, TTL 10min)
    ↓
Redirect to Platform OAuth
    ↓
Platform → /oauth/{platform}/callback
    ↓
Validate state, Exchange code for tokens
    ↓
Save encrypted credentials to DB
    ↓
Return success page
```

### OAuth State Manager

**Purpose:** CSRF protection через Redis

**Structure:**
```python
# Redis key-value
oauth:state:{uuid} → {
  "user_id": int,
  "platform": str,
  "created_at": timestamp,
  "ip_address": str
}
TTL: 600 seconds
```

**Usage:**
```python
# Generate state
state = await oauth_state_manager.create_state(
    user_id=user_id,
    platform="youtube",
    ip_address=request.client.host
)

# Validate state
data = await oauth_state_manager.validate_state(state)
```

### Token Refresh

**Automatic refresh:**
- YouTube: `refresh_token` used to get new `access_token`
- VK: Implicit Flow tokens expire (no refresh)
- Zoom: Server-to-Server or OAuth refresh

**Implementation:**
```python
class YouTubeUploader:
    async def authenticate(self):
        if self.is_token_expired():
            await self.refresh_access_token()
            # Auto-save to DB
            await self.credential_provider.update_credentials(
                self.credentials
            )
```

### Multi-tenant Isolation

**Per-user credentials:**
- Stored in `user_credentials` table
- Encrypted with Fernet
- Filtered by `user_id`

**API endpoints:**
```
POST /api/v1/oauth/{platform}/authorize - Start OAuth flow
GET /api/v1/oauth/{platform}/callback - OAuth callback
GET /api/v1/credentials - List user credentials
DELETE /api/v1/credentials/{id} - Revoke credentials
```

---

## Platform Setup

### 📹 YouTube (Google OAuth 2.0)

**Flow:** Authorization Code Flow

**Scopes:**
- `https://www.googleapis.com/auth/youtube.upload`
- `https://www.googleapis.com/auth/youtube.force-ssl`

**Configuration:**
```python
YOUTUBE_CONFIG = OAuthPlatformConfig(
    name="YouTube",
    platform_id="youtube",
    authorization_url="https://accounts.google.com/o/oauth2/v2/auth",
    token_url="https://oauth2.googleapis.com/token",
    scopes=["youtube.upload", "youtube.force-ssl"],
    access_type="offline",  # Get refresh token
    response_type="code"
)
```

**Credentials Format (DB):**
```json
{
  "access_token": "ya29.xxx",
  "refresh_token": "1//xxx",
  "token_uri": "https://oauth2.googleapis.com/token",
  "client_id": "xxx.apps.googleusercontent.com",
  "client_secret": "xxx",
  "scopes": ["youtube.upload"],
  "expiry": "2026-01-15T12:00:00Z"
}
```

**Token Refresh:**
- Auto-refresh когда `expiry < now()`
- Использует `refresh_token`
- Сохраняет новый `access_token` в БД

---

### 🌐 VK (VK OAuth 2.1)

**Два режима:**

#### 1. VK ID OAuth 2.1 (для legacy apps)
- **Flow:** Authorization Code with PKCE
- **Требуется:** VK App approval
- **Token lifetime:** Long-lived

#### 2. Implicit Flow API (рекомендуется)
- **Flow:** Implicit Flow
- **Доступно:** Всем пользователям без approval
- **Token lifetime:** 24 hours (no refresh)

**Configuration:**
```python
VK_CONFIG = OAuthPlatformConfig(
    name="VK",
    platform_id="vk_video",
    authorization_url="https://id.vk.com/authorize",  # VK ID
    # or
    authorization_url="https://oauth.vk.com/authorize",  # Implicit
    scopes=["video", "offline"],
    response_type="token"  # Implicit Flow
)
```

**Implicit Flow Endpoint:**
```
POST /api/v1/oauth/vk/token/submit
Body: {
  "access_token": "token_from_vk",
  "user_id": 123,
  "expires_in": 86400
}
```

**Credentials Format (Implicit):**
```json
{
  "access_token": "vk1.a.xxx",
  "user_id": 123456789,
  "expires_in": 86400,
  "created_at": "2026-01-14T10:00:00Z"
}
```

**⚠️ VK Policy Update (2026):**
- Новые проекты: используйте Implicit Flow API
- Legacy apps: можете продолжать использовать VK ID OAuth
- **Нет approval required** для Implicit Flow

---

### 📹 Zoom (Dual Mode)

**Два режима OAuth:**

#### 1. OAuth 2.0 (user-level)
- **Flow:** Authorization Code Flow
- **Scopes:** `recording:read`, `recording:write`
- **Use case:** Multi-user SaaS

```python
ZOOM_OAUTH_CONFIG = OAuthPlatformConfig(
    name="Zoom OAuth",
    platform_id="zoom",
    authorization_url="https://zoom.us/oauth/authorize",
    token_url="https://zoom.us/oauth/token",
    scopes=["recording:read:admin"],
    response_type="code"
)
```

#### 2. Server-to-Server OAuth
- **Flow:** Client Credentials
- **Scopes:** Account-level
- **Use case:** Single account automation

**Auto-detection:**
```python
# System auto-detects credentials type
credentials = await get_zoom_credentials(user_id, account_name)

if "refresh_token" in credentials:
    # OAuth 2.0 mode
    zoom_client = ZoomOAuthClient(credentials)
else:
    # Server-to-Server mode
    zoom_client = ZoomServerToServerClient(credentials)
```

---

## Integration with Uploaders

### Credential Provider Pattern

**Два режима:**

#### 1. Database Credentials (recommended)
```python
from video_upload_module.uploader_factory import create_youtube_uploader_from_db

uploader = await create_youtube_uploader_from_db(
    credential_id=5,
    session=db_session
)

# Auto-refresh, auto-save
await uploader.authenticate()
```

#### 2. File Credentials (legacy)
```python
from video_upload_module.platforms.youtube.uploader import YouTubeUploader

config = YouTubeUploadConfig(
    enabled=True,
    client_secrets_file="config/youtube_creds.json",
    credentials_file="config/youtube_token.json"
)

uploader = YouTubeUploader(config=config)
await uploader.authenticate()
```

### Universal Factory

**Platform-agnostic:**
```python
from video_upload_module.uploader_factory import create_uploader_from_db

# Works for YouTube, VK
uploader = await create_uploader_from_db(
    platform="youtube",  # or "vk_video"
    credential_id=credential_id,
    session=session
)
```

### UploaderFactory Methods

```python
class UploaderFactory:
    # By platform
    @staticmethod
    async def create_uploader(session, user_id, platform: str):
        """Create uploader by platform name"""
        
    # By credential ID
    @staticmethod
    async def create_youtube_uploader(session, user_id, credential_id: int):
        """Create YouTube uploader from specific credential"""
        
    # By preset ID
    @staticmethod
    async def create_uploader_by_preset_id(session, user_id, preset_id: int):
        """Create uploader from output preset"""
```

### Auto-refresh Flow

```
Upload task started
    ↓
uploader.authenticate()
    ↓
Check token expiry
    ↓
If expired → refresh_access_token()
    ↓
Save new token to DB (DatabaseCredentialProvider)
    ↓
Proceed with upload
```

**Key advantage:** Tokens always fresh, no manual intervention needed

---

## Testing & Troubleshooting

### Testing OAuth Flow

**Manual testing:**
```bash
# 1. Start API
make api

# 2. Get JWT token
TOKEN=$(curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"password"}' \
  | jq -r '.access_token')

# 3. Start OAuth flow
curl http://localhost:8000/api/v1/oauth/youtube/authorize \
  -H "Authorization: Bearer $TOKEN"

# 4. Complete authorization in browser
# 5. Check credentials saved
curl http://localhost:8000/api/v1/credentials \
  -H "Authorization: Bearer $TOKEN"
```

### Common Issues

**Issue 1: "redirect_uri_mismatch"**
```
Error: The redirect URI in the request does not match
```

**Solution:**
- Check `config/oauth_google.json` → redirect_uri
- Must match exactly: `http://localhost:8000/api/v1/oauth/youtube/callback`
- Add to Google Cloud Console → Credentials → Authorized redirect URIs

---

**Issue 2: "access_denied" (Google)**
```
Error: User not in test users
```

**Solution:**
- Google Cloud Console → OAuth consent screen
- Add your email to "Test users"
- Wait 5 minutes for propagation

---

**Issue 3: VK Token Expired**
```
Error: Token expired (24 hours)
```

**Solution:**
- VK Implicit Flow tokens expire after 24h
- Re-authorize: `GET /api/v1/oauth/vk/authorize`
- Or use VK ID OAuth 2.1 (requires app approval)

---

**Issue 4: Zoom Token Refresh Failed**
```
Error: invalid_grant
```

**Solution:**
- Check `account_id` in credentials
- Verify Server-to-Server app is activated
- Re-authorize if OAuth 2.0: `/api/v1/oauth/zoom/authorize`

---

### Debug Mode

**Enable OAuth debug logging:**
```python
# In api/config/settings.py
LOG_LEVEL = "DEBUG"

# View OAuth flow logs
docker-compose logs -f api | grep "OAuth"
```

**Check Redis state:**
```bash
redis-cli
> KEYS oauth:state:*
> GET oauth:state:abc-123-def
```

### Production Checklist

- [ ] Replace `localhost` with production domain in all redirect URIs
- [ ] Update OAuth consent screen (YouTube) to production branding
- [ ] Enable HTTPS for all OAuth callbacks
- [ ] Set secure environment variables (CLIENT_SECRET, etc.)
- [ ] Configure CORS for frontend domain
- [ ] Test OAuth flow from production URL
- [ ] Monitor token refresh errors (set up alerts)

---

## API Endpoints Reference

### OAuth Flow

```
GET /api/v1/oauth/youtube/authorize - Start YouTube OAuth
GET /api/v1/oauth/youtube/callback - YouTube OAuth callback

GET /api/v1/oauth/vk/authorize - Start VK OAuth
GET /api/v1/oauth/vk/callback - VK OAuth callback
POST /api/v1/oauth/vk/token/submit - VK Implicit Flow token submit

GET /api/v1/oauth/zoom/authorize - Start Zoom OAuth
GET /api/v1/oauth/zoom/callback - Zoom OAuth callback
```

### Credentials Management

```
GET /api/v1/credentials - List all user credentials
GET /api/v1/credentials/{platform} - Get credentials for platform
POST /api/v1/credentials - Create credential (manual)
PATCH /api/v1/credentials/{id} - Update credential
DELETE /api/v1/credentials/{id} - Delete (revoke) credential
GET /api/v1/credentials/{id}/status - Check credential status
```

---

## Architecture Files

**Core components:**
- `api/config/oauth_platforms.py` - Platform configurations
- `api/services/oauth_state.py` - State manager (Redis)
- `api/routers/oauth/` - OAuth routers (YouTube, VK, Zoom)
- `api/services/credential_service.py` - Credentials management
- `video_upload_module/uploader_factory.py` - Uploader factories
- `video_upload_module/credential_provider.py` - Credential providers

**Config files:**
- `config/oauth_google.json` - YouTube OAuth config
- `config/oauth_vk.json` - VK OAuth config
- `config/oauth_zoom.json` - Zoom OAuth config (optional)

---

## Credentials Formats

### YouTube OAuth Credentials

```json
{
  "access_token": "ya29.a0AfB_byD...",
  "refresh_token": "1//0gKxxx...",
  "token_uri": "https://oauth2.googleapis.com/token",
  "client_id": "xxx.apps.googleusercontent.com",
  "client_secret": "GOCSPX-xxx",
  "scopes": ["youtube.upload", "youtube.force-ssl"],
  "expiry": "2026-01-15T12:00:00Z"
}
```

### VK Implicit Flow Credentials

```json
{
  "access_token": "vk1.a.xxx",
  "user_id": 123456789,
  "expires_in": 86400,
  "created_at": "2026-01-14T10:00:00Z"
}
```

### Zoom OAuth Credentials

```json
{
  "access_token": "xxx",
  "refresh_token": "xxx",
  "token_type": "bearer",
  "expires_in": 3600,
  "scope": "recording:read:admin"
}
```

### Zoom Server-to-Server Credentials

```json
{
  "account_id": "xxx",
  "client_id": "xxx",
  "client_secret": "xxx"
}
```

---

## См. також

- [VK_INTEGRATION.md](VK_INTEGRATION.md) - VK детали
- [DEPLOYMENT.md](DEPLOYMENT.md) - Production deployment

---

**Документ обновлен:** Январь 2026  
**Статус:** Production Ready ✅
