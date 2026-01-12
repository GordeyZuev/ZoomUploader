# 🔒 Security Quick Start

**Время на настройку:** 15 минут  
**Перед запуском в production:** ОБЯЗАТЕЛЬНО

---

## 🚨 Критичные настройки (15 мин)

### 1. Секретные ключи (5 мин)

```bash
# Генерация
openssl rand -hex 32  # Скопировать результат
openssl rand -hex 32  # Скопировать результат

# Создать .env файл
cat > .env << EOF
# JWT Secret (для токенов)
API_JWT_SECRET_KEY=<первый результат>

# Encryption Key (для credentials)
API_ENCRYPTION_KEY=<второй результат>

# Database (если не дефолтные)
DB_HOST=localhost
DB_PORT=5432
DB_USERNAME=postgres
DB_PASSWORD=<strong_password>
DB_DATABASE=zoom_publishing

# CORS (только ваши домены!)
API_CORS_ORIGINS=https://app.yourdomain.com,https://admin.yourdomain.com
EOF
```

### 2. HTTPS (5 мин)

**Вариант А: Let's Encrypt + Caddy (самый простой)**
```bash
# Caddyfile
app.yourdomain.com {
    reverse_proxy localhost:8000
}
```

**Вариант Б: Let's Encrypt + nginx**
```bash
# Установка certbot
sudo apt install certbot python3-certbot-nginx

# Получение сертификата
sudo certbot --nginx -d app.yourdomain.com
```

### 3. Backup БД (5 мин)

```bash
# Автоматический backup (добавить в crontab)
0 3 * * * pg_dump zoom_publishing | gzip > /backups/db_$(date +\%Y\%m\%d).sql.gz

# Хранить 30 дней
find /backups -name "db_*.sql.gz" -mtime +30 -delete

# ⚠️ ОБЯЗАТЕЛЬНО протестировать восстановление!
gunzip -c /backups/db_20260107.sql.gz | psql zoom_publishing_test
```

---

## ✅ Проверка перед запуском

```bash
# 1. Проверить что секреты установлены
grep "API_JWT_SECRET_KEY" .env
grep "API_ENCRYPTION_KEY" .env

# 2. Проверить CORS
grep "API_CORS_ORIGINS" .env
# Должно быть: https://yourdomain.com (НЕ *)

# 3. Применить миграции
uv run alembic upgrade head

# 4. Проверить версию
uv run alembic current
# Должно быть: 015 (head)

# 5. Запустить API
make api

# 6. Запустить Celery + Beat
make celery-beat
```

---

## 🔐 Что уже работает

✅ **JWT Authentication**
- Access token: 30 мин
- Refresh token: 7 дней
- Token rotation при каждом refresh
- Проверка в БД перед refresh

✅ **Logout Management**
- `POST /auth/logout` - выход с устройства
- `POST /auth/logout-all` - выход со всех устройств
- Автоматическая очистка expired токенов (daily)

✅ **Multi-tenancy**
- Полная изоляция данных по `user_id`
- Credentials зашифрованы (Fernet)
- Cascading deletes

✅ **OAuth 2.0**
- YouTube + VK
- CSRF protection (Redis state)
- Automatic token refresh

---

## 📊 Production Checklist

```
Критично (перед запуском):
[ ] JWT_SECRET_KEY установлен (не дефолтный)
[ ] ENCRYPTION_KEY установлен (отдельный от JWT)
[ ] DATABASE_PASSWORD сильный
[ ] CORS origins = конкретные домены (не *)
[ ] HTTPS настроен
[ ] Backup БД автоматизирован
[ ] .env в .gitignore

Важно (первая неделя):
[ ] Rate limiting на Redis
[ ] Security logging настроен
[ ] Alerts настроены (Sentry/DataDog)

Желательно (первый месяц):
[ ] Security headers добавлены
[ ] Load testing выполнен
[ ] OWASP ZAP scan пройден
```

---

## 🆘 Troubleshooting

**Проблема:** `Invalid JWT secret key`
```bash
# Решение: Проверить что секрет установлен
echo $API_JWT_SECRET_KEY
# Если пусто - добавить в .env
```

**Проблема:** `CORS error in browser`
```bash
# Решение: Добавить домен в CORS origins
API_CORS_ORIGINS=https://yourdomain.com
```

**Проблема:** `Token expired`
```bash
# Это нормально! Используйте /auth/refresh
curl -X POST /api/v1/auth/refresh \
  -d '{"refresh_token": "..."}'
```

---

## 📚 Полная документация

- **Security Audit:** `docs/SECURITY_AUDIT.md`
- **What Was Done:** `docs/WHAT_WAS_DONE.md`
- **API Docs:** http://localhost:8000/docs

---

**Готово!** Система готова к production после выполнения критичных настроек. 🚀

