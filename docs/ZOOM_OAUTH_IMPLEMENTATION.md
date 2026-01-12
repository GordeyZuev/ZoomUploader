# Zoom OAuth Implementation Summary

**Date:** January 10, 2026  
**Status:** ✅ **Production-Ready**

---

## Overview

Добавлена полная поддержка OAuth 2.0 авторизации для Zoom, аналогично существующим реализациям для YouTube и VK.

**Преимущества:**
- ✅ Multi-user support (каждый пользователь со своими credentials)
- ✅ Refresh token для автоматического обновления токенов
- ✅ Web-based authorization (не требует интерактивного CLI)
- ✅ Secure token storage (encrypted в БД)
- ✅ Automatic token refresh при истечении

---

## Architecture

### Zoom OAuth Flow

```
User → GET /api/v1/oauth/zoom/authorize → authorization_url
     → Zoom OAuth Page → User grants access
     → Zoom redirects → GET /api/v1/oauth/zoom/callback?code=...&state=...
     → Backend: exchange code → access_token + refresh_token
     → Save to DB (encrypted) → Redirect to frontend
```

### Components

1. **OAuth Platform Config** (`api/services/oauth_platforms.py`)
   - `create_zoom_config()` - загрузка конфигурации из `config/oauth_zoom.json`
   - Authorization URL: `https://zoom.us/oauth/authorize`
   - Token URL: `https://zoom.us/oauth/token`
   - Scopes: `cloud_recording:read:list_user_recordings`, `cloud_recording:read:recording`, `recording:write:recording`, `user:read:user`

2. **OAuth Service** (`api/services/oauth_service.py`)
   - `_exchange_zoom_token()` - обмен code на токены
   - `_refresh_zoom_token()` - обновление access token
   - `_validate_zoom_token()` - валидация токена через `/v2/users/me`
   - **Important:** Zoom использует Basic Auth (client_id:client_secret в Base64)

3. **OAuth Endpoints** (`api/routers/oauth.py`)
   - `GET /api/v1/oauth/zoom/authorize` - получить authorization URL
   - `GET /api/v1/oauth/zoom/callback` - обработать callback от Zoom

4. **Credentials Validation** (`api/schemas/credentials/platform_credentials.py`)
   - `ZoomCredentialsManual` - поддержка OAuth и Server-to-Server форматов

---

## OAuth Endpoints

### 1. Get Authorization URL

```bash
GET /api/v1/oauth/zoom/authorize
Authorization: Bearer YOUR_JWT_TOKEN
```

**Response:**
```json
{
  "authorization_url": "https://zoom.us/oauth/authorize?client_id=...&state=...&scope=...",
  "state": "uuid-state-token",
  "expires_in": 600,
  "platform": "zoom"
}
```

**User Flow:**
1. Frontend получает `authorization_url`
2. Redirect пользователя на `authorization_url`
3. Пользователь авторизуется в Zoom и дает доступ
4. Zoom редиректит на callback endpoint с `code` и `state`

### 2. OAuth Callback (Automatic)

```bash
GET /api/v1/oauth/zoom/callback?code=...&state=...
```

**Process:**
1. Валидация `state` token (CSRF protection)
2. Exchange `code` → `access_token` + `refresh_token`
3. Validate token через Zoom API
4. Save encrypted credentials to DB
5. Redirect to frontend: `http://localhost:8080/settings/platforms?oauth_success=true&platform=zoom`

---

## Configuration

### 1. Create Zoom OAuth App

1. Go to [Zoom App Marketplace](https://marketplace.zoom.us/)
2. **Develop** → **Build App** → **OAuth**
3. Fill app information
4. Add scopes (User-level, not admin):
   - `cloud_recording:read:list_user_recordings`
   - `cloud_recording:read:recording`
   - `recording:write:recording`
   - `user:read:user`
5. Add redirect URL: `http://localhost:8000/api/v1/oauth/zoom/callback`
6. Copy **Client ID** and **Client Secret**

### 2. Configure Application

Create `config/oauth_zoom.json`:

```json
{
  "client_id": "YOUR_ZOOM_CLIENT_ID",
  "client_secret": "YOUR_ZOOM_CLIENT_SECRET",
  "redirect_uri": "http://localhost:8000/api/v1/oauth/zoom/callback"
}
```

**Environment Variables (optional):**
```bash
export ZOOM_OAUTH_CONFIG="config/oauth_zoom.json"
export OAUTH_REDIRECT_BASE_URL="http://localhost:8000"
```

---

## Credentials Format

### OAuth 2.0 Format (Stored in DB)

```json
{
  "client_id": "Xyz789Abc",
  "client_secret": "verylongsecretstring123456",
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzUxMiIsInYiOiIyLjAiLCJraWQi...",
  "token_type": "bearer",
  "scope": "cloud_recording:read:list_user_recordings cloud_recording:read:recording recording:write:recording user:read:user",
  "expires_in": 3600,
  "expiry": "2026-01-10T12:00:00Z"
}
```

### Required Fields

| Field | Description |
|-------|-------------|
| `access_token` | JWT access token для Zoom API |
| `client_id` | Zoom OAuth client ID |
| `client_secret` | Zoom OAuth client secret |

### Optional Fields

| Field | Description |
|-------|-------------|
| `refresh_token` | Refresh token (required for long-term use) |
| `expiry` | Token expiry time (ISO 8601) |
| `token_type` | Token type (usually "bearer") |
| `scope` | Granted OAuth scopes |

---

## Zoom OAuth Specifics

### 1. Basic Authentication

Zoom OAuth требует Basic Auth при token exchange и refresh:

```python
auth_string = f"{client_id}:{client_secret}"
auth_b64 = base64.b64encode(auth_string.encode("ascii")).decode("ascii")
headers = {"Authorization": f"Basic {auth_b64}"}
```

### 2. Token Endpoint

```
POST https://zoom.us/oauth/token
Authorization: Basic <base64(client_id:client_secret)>
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code
&code=<authorization_code>
&redirect_uri=<redirect_uri>
```

### 3. Refresh Token

```
POST https://zoom.us/oauth/token
Authorization: Basic <base64(client_id:client_secret)>

grant_type=refresh_token
&refresh_token=<refresh_token>
```

### 4. Token Validation

```
GET https://api.zoom.us/v2/users/me
Authorization: Bearer <access_token>
```

---

## Testing

### Automated Tests

```bash
python test_zoom_oauth.py
```

**Tests:**
1. ✅ Zoom Configuration loading
2. ✅ Platform Registry registration
3. ✅ Authorization URL Generation
4. ✅ OAuth Service Methods
5. ✅ Credentials Validation (OAuth & Server-to-Server)

**Result:** All tests passed! 🎉

### Manual Testing

1. **Start API server:**
   ```bash
   uvicorn api.main:app --reload
   ```

2. **Get JWT token:**
   ```bash
   curl -X POST http://localhost:8000/api/v1/auth/login \
     -H "Content-Type: application/json" \
     -d '{"email":"test@test.com","password":"test123"}'
   ```

3. **Initiate OAuth:**
   ```bash
   curl -X GET http://localhost:8000/api/v1/oauth/zoom/authorize \
     -H "Authorization: Bearer YOUR_JWT_TOKEN"
   ```

4. **Visit authorization_url in browser**
5. **Grant access** → Zoom redirects to callback
6. **Check credentials:**
   ```bash
   curl -X GET http://localhost:8000/api/v1/credentials/ \
     -H "Authorization: Bearer YOUR_JWT_TOKEN"
   ```

---

## Files Created/Modified

### Created Files

1. `config/oauth_zoom.json.example` - OAuth configuration template
2. `test_zoom_oauth.py` - Automated test suite
3. `docs/ZOOM_OAUTH_IMPLEMENTATION.md` - This document

### Modified Files

1. `api/services/oauth_platforms.py`
   - Added `create_zoom_config()`
   - Added Zoom to `get_platform_config()`
   - Pre-loaded `ZOOM_CONFIG`

2. `api/services/oauth_service.py`
   - Added Zoom authorization URL parameters
   - Added `_exchange_zoom_token()` with Basic Auth
   - Added `_refresh_zoom_token()`
   - Added `_validate_zoom_token()`

3. `api/routers/oauth.py`
   - Added Zoom credentials save logic
   - Added `/zoom/authorize` endpoint
   - Added `/zoom/callback` endpoint

4. `api/schemas/credentials/platform_credentials.py`
   - Updated `ZoomCredentialsManual` to support OAuth format
   - Added validation for both OAuth and Server-to-Server

5. `docs/CREDENTIALS_GUIDE.md`
   - Added Zoom OAuth 2.0 section
   - Added comparison table (OAuth vs Server-to-Server)
   - Added Zoom troubleshooting section

---

## Comparison: OAuth vs Server-to-Server

| Feature | OAuth 2.0 | Server-to-Server |
|---------|-----------|------------------|
| **Multi-user** | ✅ Yes | ❌ No (single account) |
| **Refresh Token** | ✅ Yes | N/A (JWT-based) |
| **User-specific permissions** | ✅ Yes | ❌ No |
| **Authorization** | Web-based | Config-based |
| **Use Case** | **Production multi-user** | Legacy / Single-tenant |
| **Recommendation** | ⭐ **Recommended** | Not recommended for new projects |

---

## Security Features

1. **CSRF Protection** - State token хранится в Redis с TTL
2. **Encrypted Storage** - Credentials зашифрованы в БД (Fernet)
3. **Basic Auth** - Client credentials передаются через Authorization header
4. **Token Rotation** - Automatic refresh при истечении
5. **Multi-tenancy** - Изоляция credentials по пользователям

---

## Troubleshooting

### "Invalid access token"

**Problem:** Access token expired or revoked

**Solution:**
1. System automatically uses refresh_token
2. If refresh fails, get new token via `/api/v1/oauth/zoom/authorize`
3. Check app scopes in Zoom Developer Console

### "User does not have recording permission"

**Problem:** Insufficient permissions

**Solution:**
1. Verify OAuth app has required scopes:
   - `cloud_recording:read:list_user_recordings`
   - `cloud_recording:read:recording`
   - `recording:write:recording`
   - `user:read:user`
2. Re-authorize via OAuth flow to update scopes

### "Invalid redirect_uri"

**Problem:** Mismatch between config and Zoom app settings

**Solution:**
1. Check `oauth_zoom.json` redirect_uri matches Zoom app
2. For production, use HTTPS redirect URI
3. Update `OAUTH_REDIRECT_BASE_URL` environment variable

---

## Production Deployment

### 1. HTTPS Required

Zoom requires HTTPS for production redirect URIs:

```json
{
  "redirect_uri": "https://yourdomain.com/api/v1/oauth/zoom/callback"
}
```

### 2. Environment Variables

```bash
export OAUTH_REDIRECT_BASE_URL="https://yourdomain.com"
export ZOOM_OAUTH_CONFIG="/app/config/oauth_zoom.json"
```

### 3. Scopes Review

Review and request only necessary scopes (User-level):
- `cloud_recording:read:list_user_recordings` - List user's recordings
- `cloud_recording:read:recording` - Read recording details
- `recording:write:recording` - Delete recordings
- `user:read:user` - User info

---

## Next Steps

1. ✅ **OAuth Implementation** - Complete
2. ✅ **Testing** - All tests passed
3. ✅ **Documentation** - Complete
4. ⏳ **Production Deployment** - Ready for deployment
5. ⏳ **Frontend Integration** - Implement OAuth flow in UI

---

## Metrics

- **Endpoints Added:** 2 (`/zoom/authorize`, `/zoom/callback`)
- **Methods Added:** 3 (`_exchange_zoom_token`, `_refresh_zoom_token`, `_validate_zoom_token`)
- **Tests:** 5/5 passed ✅
- **Linter Errors:** 0 ✅
- **Documentation:** Complete ✅

---

## Conclusion

✅ Zoom OAuth 2.0 реализован полностью и готов к production использованию.

**Key Benefits:**
- Multi-user support с изоляцией credentials
- Automatic token refresh
- Secure encrypted storage
- Unified OAuth pattern (YouTube, VK, Zoom)

**Status:** 🎉 **Production-Ready!**

