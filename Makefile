.PHONY: clean-pycache

clean-pycache:
	@find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	@find . -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete

# ==================== Production-Ready API Commands ====================

# Setup: Установка всех зависимостей
.PHONY: install
install:
	@echo "📦 Установка зависимостей..."
	@uv pip install -r requirements.txt
	@echo "✅ Готово!"

# API: Запуск FastAPI сервера
.PHONY: api
api:
	uv run uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# API: Production запуск (без reload)
.PHONY: api-prod
api-prod:
	uv run uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 4

# Celery: Запуск worker (все очереди)
.PHONY: celery
celery:
	PYTHONPATH=$$PWD:$$PYTHONPATH uv run celery -A api.celery_app worker --loglevel=info --queues=processing,upload --concurrency=4

# Celery: Запуск worker только для processing
.PHONY: celery-processing
celery-processing:
	PYTHONPATH=$$PWD:$$PYTHONPATH uv run celery -A api.celery_app worker --loglevel=info -Q processing --concurrency=2

# Celery: Запуск worker только для upload
.PHONY: celery-upload
celery-upload:
	PYTHONPATH=$$PWD:$$PYTHONPATH uv run celery -A api.celery_app worker --loglevel=info -Q upload --concurrency=2

# Celery: Запуск Flower (мониторинг)
.PHONY: flower
flower:
	PYTHONPATH=$$PWD:$$PYTHONPATH uv run celery -A api.celery_app flower --port=5555

# Celery Beat: Запуск scheduler (для automation jobs)
.PHONY: celery-beat
celery-beat:
	PYTHONPATH=$$PWD:$$PYTHONPATH uv run celery -A api.celery_app beat --loglevel=info --scheduler celery_sqlalchemy_scheduler.schedulers:DatabaseScheduler

# Celery: Запуск worker + beat вместе (dev mode)
.PHONY: celery-dev
celery-dev:
	PYTHONPATH=$$PWD:$$PYTHONPATH uv run celery -A api.celery_app worker --beat --loglevel=info --queues=processing,upload,automation --concurrency=4

# Celery: Проверить активные tasks
.PHONY: celery-status
celery-status:
	@echo "📊 Active workers:"
	@PYTHONPATH=$$PWD:$$PYTHONPATH uv run celery -A api.celery_app inspect active
	@echo "\n📋 Registered tasks:"
	@PYTHONPATH=$$PWD:$$PYTHONPATH uv run celery -A api.celery_app inspect registered
	@echo "\n📈 Stats:"
	@PYTHONPATH=$$PWD:$$PYTHONPATH uv run celery -A api.celery_app inspect stats

# Celery: Очистить все задачи из очередей
.PHONY: celery-purge
celery-purge:
	@echo "⚠️  Удаление всех задач из очередей..."
	@PYTHONPATH=$$PWD:$$PYTHONPATH uv run celery -A api.celery_app purge -f
	@echo "✅ Очереди очищены!"

# Docker: Запуск PostgreSQL и Redis
.PHONY: docker-up
docker-up:
	docker-compose up -d postgres redis

# Docker: Остановка всех сервисов
.PHONY: docker-down
docker-down:
	docker-compose down

# Docker: Полная сборка и запуск
.PHONY: docker-full
docker-full:
	docker-compose up --build -d

# Database: Инициализация (создание БД + миграции)
.PHONY: init-db
init-db:
	@echo "🚀 Инициализация базы данных..."
	@uv run python -c "\
import asyncio; \
from database.config import DatabaseConfig; \
from database.manager import DatabaseManager; \
async def init(): \
    db = DatabaseManager(DatabaseConfig.from_env()); \
    await db.create_database_if_not_exists(); \
    await db.close(); \
asyncio.run(init())" 2>/dev/null || true
	@echo "✅ База данных создана"
	@echo "🔄 Применение миграций..."
	@uv run alembic upgrade head
	@echo "✅ Миграции применены!"

# Database: Применить миграции
.PHONY: migrate
migrate:
	uv run alembic upgrade head

# Database: Откатить последнюю миграцию
.PHONY: migrate-down
migrate-down:
	uv run alembic downgrade -1

# Database: Создать новую миграцию
.PHONY: migration
migration:
	@read -p "Enter migration name: " name; \
	uv run alembic revision --autogenerate -m "$$name"

# Database: Проверить текущую версию БД
.PHONY: db-version
db-version:
	@uv run alembic current

# Database: Показать историю миграций
.PHONY: db-history
db-history:
	@uv run alembic history

# Tests: Запуск всех тестов
.PHONY: test
test:
	uv run pytest tests/ -v

.PHONY: help
help:
	@echo "📦 Установка и обновление:"
	@echo "  make install        - Установка зависимостей из requirements.txt"
	@echo "  make uv-install     - Установка через uv sync"
	@echo "  make uv-update      - Обновить lock и синхронизировать"
	@echo ""
	@echo "🔍 Проверка и форматирование:"
	@echo "  make lint           - Проверка кода (ruff check)"
	@echo "  make lint-fix       - Авто-исправления (ruff check --fix)"
	@echo "  make format         - Форматирование (ruff format)"
	@echo ""
	@echo "🚀 Production API:"
	@echo "  make api            - Запуск FastAPI (dev режим)"
	@echo "  make api-prod       - Запуск FastAPI (production)"
	@echo "  make celery         - Запуск Celery worker"
	@echo "  make celery-beat    - Запуск Celery Beat (automation scheduler)"
	@echo "  make celery-dev     - Запуск worker + beat вместе (dev)"
	@echo "  make flower         - Запуск Flower (мониторинг)"
	@echo "  make docker-up      - Запуск PostgreSQL + Redis"
	@echo "  make docker-down    - Остановка сервисов"
	@echo ""
	@echo "🗄️ База данных:"
	@echo "  make init-db        - Инициализация БД (создание + миграции)"
	@echo "  make migrate        - Применить миграции БД"
	@echo "  make migrate-down   - Откатить последнюю миграцию"
	@echo "  make db-version     - Показать текущую версию БД"
	@echo "  make db-history     - Показать историю миграций"
	@echo ""
	@echo "📋 Работа с записями:"
	@echo "  make list           - Показать записи за сегодня"
	@echo "  make list-week      - Показать записи за неделю"
	@echo "  make sync           - Синхронизировать с Zoom"
	@echo "  make sync-week      - Синхронизировать за неделю"
	@echo ""
	@echo "⬇️ Загрузка и обработка:"
	@echo "  make download       - Скачать записи со статусом INITIALIZED"
	@echo "  make process        - Обработать скачанные записи"
	@echo "  make transcribe     - Транскрибировать обработанные записи"
	@echo "  make upload-youtube - Загрузить на YouTube"
	@echo "  make upload-vk      - Загрузить на VK"
	@echo "  make upload-all     - Загрузить на все платформы"
	@echo ""
	@echo "🚀 Полный пайплайн:"
	@echo "  make full-process   - Полный пайплайн (скачать + обработать + транскрибировать)"
	@echo "  make full-youtube   - Полный пайплайн с YouTube"
	@echo "  make full-all       - Полный пайплайн со всеми платформами"
	@echo ""
	@echo "🧹 Очистка:"
	@echo "  make clean-old      - Очистить записи старше 7 дней"
	@echo "  make clean-pycache  - Очистить __pycache__ и *.pyc/*.pyo"
	@echo "  make clean-logs     - Очистить логи"
	@echo "  make clean          - Очистить кэши и логи"
	@echo "  make reset          - Сбросить статусы записей"
	@echo "  make recreate-db    - Полностью пересоздать БД (УДАЛИТ ВСЕ ДАННЫЕ!)"
	@echo ""
	@echo "ℹ️ Справка:"
	@echo "  make run-help       - Показать help приложения"

.PHONY: uv-install uv-update uv-run
uv-install:
	@uv sync

uv-update:
	@uv lock --upgrade && uv sync

.PHONY: lint
lint:
	@ruff check .

.PHONY: lint-fix
lint-fix:
	@ruff check . --fix

.PHONY: format
format:
	@ruff format .

.PHONY: clean-logs
clean-logs:
	@rm -rf logs/*

.PHONY: clean
clean: clean-pycache clean-logs

.PHONY: run-help
run-help:
	@uv run python main.py --help || true

# Команды для работы с записями
.PHONY: list list-week sync sync-week
list:
	@uv run python main.py list --last 0

list-week:
	@uv run python main.py list --last 7

sync:
	@uv run python main.py sync

sync-week:
	@uv run python main.py sync --last 7

# Команды загрузки и обработки
.PHONY: download process transcribe upload-youtube upload-vk upload-all
download:
	@uv run python main.py download --all

process:
	@uv run python main.py process --all

transcribe:
	@uv run python main.py transcribe --all

upload-youtube:
	@uv run python main.py upload --youtube --all

upload-vk:
	@uv run python main.py upload --vk --all

upload-all:
	@uv run python main.py upload --all-platforms --all

# Полный пайплайн
.PHONY: full-process full-youtube full-all
full-process:
	@uv run python main.py full-process --all

full-youtube:
	@uv run python main.py full-process --youtube --all

full-all:
	@uv run python main.py full-process --all-platforms --all

# Очистка и сброс
.PHONY: clean-old reset recreate-db
clean-old:
	@uv run python main.py clean

reset:
	@uv run python main.py reset

recreate-db:
	@uv run python main.py recreate-db


