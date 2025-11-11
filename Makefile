.PHONY: clean-pycache

clean-pycache:
	@find . -type d -name "__pycache__" -prune -exec rm -rf {} +
	@find . -type f \( -name "*.pyc" -o -name "*.pyo" \) -delete

.PHONY: help
help:
	@echo "📦 Установка и обновление:"
	@echo "  make install        - Установка зависимостей (uv sync)"
	@echo "  make uv-update      - Обновить lock и синхронизировать"
	@echo ""
	@echo "🔍 Проверка и форматирование:"
	@echo "  make lint           - Проверка кода ruff"
	@echo "  make lint-fix       - Авто-исправления ruff"
	@echo "  make format         - Форматирование ruff"
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
	@echo "  make upload-youtube - Загрузить на YouTube"
	@echo "  make upload-vk      - Загрузить на VK"
	@echo "  make upload-all     - Загрузить на все платформы"
	@echo ""
	@echo "🚀 Полный пайплайн:"
	@echo "  make full-process   - Полный пайплайн (скачать + обработать)"
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

.PHONY: install uv-install uv-update uv-run
install: uv-install

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
.PHONY: download process upload-youtube upload-vk upload-all
download:
	@uv run python main.py download --all

process:
	@uv run python main.py process --all

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


