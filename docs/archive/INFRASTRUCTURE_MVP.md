# 🚀 Infrastructure Setup - MVP (5-10 Users)

## Server Configuration: Hetzner CPX31

### Hardware Specs
```
Provider:   Hetzner Cloud
Model:      CPX31
vCPU:       8 (AMD EPYC shared)
RAM:        16 GB
Storage:    160 GB NVMe SSD
Bandwidth:  20 TB/month
Cost:       €26.10/month (~$28)
```

### Software Stack

#### Operating System
```bash
Ubuntu 24.04 LTS (Jammy)
# Automated security updates enabled
```

#### Container Runtime
```bash
Docker 27.x
Docker Compose 2.x
```

### Service Configuration

#### 1. PostgreSQL 15
```yaml
Container: postgres:15-alpine
RAM allocation: 4 GB
Storage: 20 GB
Connections: max 100
```

**Configuration (postgresql.conf):**
```ini
# Memory Settings
shared_buffers = 1GB              # 25% of 4GB allocation
effective_cache_size = 3GB        # 75% of 4GB allocation
work_mem = 16MB
maintenance_work_mem = 256MB

# Checkpoint Settings
checkpoint_completion_target = 0.9
wal_buffers = 16MB
max_wal_size = 2GB
min_wal_size = 1GB

# Query Performance
random_page_cost = 1.1            # SSD optimization
effective_io_concurrency = 200    # SSD optimization

# Connection Settings
max_connections = 100

# Logging
log_min_duration_statement = 1000  # Log queries > 1 second
```

#### 2. Redis 7
```yaml
Container: redis:7-alpine
RAM allocation: 512 MB
Persistence: RDB snapshots
```

**Configuration (redis.conf):**
```ini
# Memory Management
maxmemory 512mb
maxmemory-policy allkeys-lru

# Persistence
save 900 1      # Save after 900s if 1 key changed
save 300 10     # Save after 300s if 10 keys changed
save 60 10000   # Save after 60s if 10000 keys changed

# Performance
tcp-backlog 511
timeout 300
```

#### 3. FastAPI Application
```yaml
Workers: 2 (uvicorn)
RAM per worker: 512 MB
Total RAM: 1 GB
CPU: 1 vCPU
```

**Uvicorn Configuration:**
```bash
uvicorn api.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --workers 2 \
  --log-level info \
  --access-log \
  --limit-concurrency 50 \
  --timeout-keep-alive 30
```

#### 4. Celery Workers
```yaml
Workers: 3 total
- Processing queue: 2 workers (CPU intensive)
- Upload queue: 1 worker (I/O intensive)
RAM per worker: 2 GB
Total RAM: 6 GB
CPU: 4 vCPU
```

**Celery Configuration:**
```bash
# Processing Worker (FFmpeg tasks)
celery -A api.celery_app worker \
  --loglevel=info \
  --queues=processing \
  --concurrency=2 \
  --pool=prefork \
  --max-tasks-per-child=5 \
  --time-limit=7200 \
  --soft-time-limit=6900

# Upload Worker (API calls, network I/O)
celery -A api.celery_app worker \
  --loglevel=info \
  --queues=upload \
  --concurrency=4 \
  --pool=gevent \
  --max-tasks-per-child=20 \
  --time-limit=3600
```

#### 5. Celery Beat (Scheduler)
```yaml
RAM: 256 MB
CPU: 0.5 vCPU
```

#### 6. Flower (Monitoring)
```yaml
RAM: 256 MB
CPU: 0.5 vCPU
Port: 5555
```

### Resource Allocation Summary

```
Total Available:
├─ CPU: 8 vCPU
└─ RAM: 16 GB

Allocation:
├─ PostgreSQL:        4 GB RAM, 1 vCPU
├─ Redis:             512 MB RAM, 0.5 vCPU
├─ FastAPI:           1 GB RAM, 1 vCPU
├─ Celery Workers:    6 GB RAM, 4 vCPU
├─ Celery Beat:       256 MB RAM, 0.5 vCPU
├─ Flower:            256 MB RAM, 0.5 vCPU
├─ System/Overhead:   2 GB RAM, 0.5 vCPU
└─ Buffer:            2 GB RAM, 0 vCPU
────────────────────────────────────────
Total Used:          14 GB RAM, 8 vCPU
Available Buffer:    2 GB RAM
```

### Storage Configuration

#### Main Storage (160 GB NVMe)
```
/                      20 GB    (OS + packages)
/var/lib/postgresql    30 GB    (database)
/var/lib/redis          5 GB    (Redis persistence)
/var/lib/docker        10 GB    (Docker images/containers)
/app/media             85 GB    (video processing)
  ├─ temporary/        60 GB    (processing files, 0-14 days)
  └─ permanent/        25 GB    (transcriptions, metadata)
/var/log               5 GB     (application logs)
/swap                  4 GB     (swap file)
Reserve                1 GB     (emergency buffer)
```

#### Cleanup Policy
```bash
# Automated cleanup via cron
# Delete temporary files older than 7 days
0 3 * * * find /app/media/user_*/video -mtime +7 -delete
0 3 * * * find /app/media/user_*/audio -mtime +7 -delete

# Keep only last 30 days of logs
0 4 * * * find /var/log -name "*.log" -mtime +30 -delete
```

### Backup Strategy

#### Database Backups
```bash
# Daily PostgreSQL backup
0 2 * * * pg_dump -U postgres leap_platform | \
  gzip > /backups/db_$(date +\%Y\%m\%d).sql.gz

# Retention: 7 daily, 4 weekly
# Upload to Backblaze B2 or Hetzner Storage Box
```

#### Application Data Backups
```bash
# Weekly backup of permanent transcriptions
0 3 * * 0 tar -czf /backups/media_$(date +\%Y\%m\%d).tar.gz \
  /app/media/user_*/transcriptions

# Upload to object storage
```

### Monitoring

#### System Monitoring
```bash
# Install monitoring tools
apt install -y htop iotop nethogs ncdu

# Prometheus Node Exporter
docker run -d \
  --name node_exporter \
  -p 9100:9100 \
  prom/node-exporter
```

#### Application Monitoring
```python
# Already integrated:
- Flower UI: http://server:5555 (Celery monitoring)
- FastAPI metrics: /health endpoint
- PostgreSQL pg_stat_statements
```

#### Alerts
```bash
# Simple alerting via email
# Monitor disk usage
df -h | grep -E '9[0-9]%|100%' && \
  echo "Disk usage critical" | mail -s "Alert" admin@example.com

# Monitor memory
free | grep Mem | awk '{print $3/$2 * 100}' | \
  awk '{if ($1 > 90) print "Memory usage: " $1 "%"}'
```

### Security

#### Firewall (UFW)
```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp      # SSH
ufw allow 80/tcp      # HTTP
ufw allow 443/tcp     # HTTPS
ufw allow 5555/tcp    # Flower (restrict to your IP)
ufw enable
```

#### SSH Hardening
```bash
# /etc/ssh/sshd_config
PermitRootLogin no
PasswordAuthentication no
PubkeyAuthentication yes
Port 22
```

#### SSL/TLS (Certbot)
```bash
apt install -y certbot python3-certbot-nginx
certbot --nginx -d api.yourdomain.com
```

#### Fail2Ban
```bash
apt install -y fail2ban
systemctl enable fail2ban
systemctl start fail2ban
```

### Network Configuration

#### Nginx Reverse Proxy
```nginx
upstream fastapi {
    server 127.0.0.1:8000;
    keepalive 32;
}

server {
    listen 80;
    server_name api.yourdomain.com;
    
    # Redirect to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name api.yourdomain.com;
    
    ssl_certificate /etc/letsencrypt/live/api.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.yourdomain.com/privkey.pem;
    
    # Security headers
    add_header Strict-Transport-Security "max-age=31536000" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    
    # Rate limiting
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
    limit_req zone=api burst=20 nodelay;
    
    # Timeouts
    proxy_connect_timeout 60s;
    proxy_send_timeout 60s;
    proxy_read_timeout 60s;
    
    # Upload size limit
    client_max_body_size 2G;
    
    location / {
        proxy_pass http://fastapi;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_cache_bypass $http_upgrade;
    }
}
```

### Cost Breakdown

```
Hetzner CPX31:              $28.00/month
AI API (avg 500 lекций):   $60.00/month
Backblaze B2 (50GB):        $0.25/month
Domain + SSL:               $1.00/month
Monitoring (optional):      $0.00/month (self-hosted)
────────────────────────────────────────
TOTAL:                     ~$89/month
```

### Capacity

```
Comfortable capacity:
├─ Users: 10-15
├─ Lectures/week: 250-300
├─ Concurrent processing: 3-4 lectures
└─ API requests: 1000/hour

Maximum capacity (with degraded performance):
├─ Users: 20-25
├─ Lectures/week: 400-500
├─ Concurrent processing: 5-6 lectures
└─ API requests: 2000/hour
```

### Upgrade Path

When to upgrade:
```
IF (users > 15 OR lectures/week > 350 OR CPU > 80% for 24h):
    Upgrade to CPX41 (12 vCPU, 24 GB RAM, €51/month)
    OR
    Split into multi-server setup
```

### Deployment Commands

```bash
# 1. Initial server setup
ssh root@your-server-ip
apt update && apt upgrade -y
apt install -y docker.io docker-compose git ufw

# 2. Clone repository
cd /opt
git clone https://github.com/yourusername/ZoomUploader.git
cd ZoomUploader

# 3. Setup environment
cp .env.example .env
nano .env  # Configure all secrets

# 4. Start services
docker-compose up -d

# 5. Check status
docker-compose ps
docker-compose logs -f

# 6. Access services
# API: http://your-ip:8000
# Docs: http://your-ip:8000/docs
# Flower: http://your-ip:5555
```

### Daily Operations

#### Check System Health
```bash
# CPU, RAM, Disk
htop

# Disk usage
df -h
ncdu /app/media

# Docker stats
docker stats

# Service logs
docker-compose logs -f --tail=100 celery_worker
```

#### Manual Tasks
```bash
# Restart services
docker-compose restart celery_worker

# Database backup
docker exec leap_postgres pg_dump -U postgres leap_platform > backup.sql

# Clean old files
find /app/media -name "*.mp4" -mtime +7 -delete
```

