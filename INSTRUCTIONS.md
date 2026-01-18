# Development Guidelines

## Core Principles
- **KISS** (Keep It Simple, Stupid) - простота превыше всего
- **DRY** (Don't Repeat Yourself) - избегай дублирования
- **YAGNI** (You Aren't Gonna Need It) - не создавай лишнюю функциональность
- Заложить возможность для масштабируемости и поддержки
- Приоритет: читаемость и понятность кода

## Code Style & Quality
- **PEP8** - строго следуй стандарту Python
- **Linter**: используй `ruff` для проверки кода перед коммитом
- **Type hints**: используй там, где это улучшает понимание кода
- Тщательно проверяй себя перед отправкой изменений

### Docstrings
- Пиши на **английском языке**
- Должны быть **емкими и полезными** - не очевидные факты
- Используй для: публичных API, сложной логики, неочевидного поведения
- Формат: краткое описание + Args/Returns/Raises при необходимости
- НЕ дублируй информацию из сигнатуры функции

### Comments
- Пиши **только при максимальной необходимости**
- Объясняй "почему", а не "что" делает код
- Используй для: бизнес-логики, workarounds, неочевидных решений
- Избегай: описания очевидного кода, дублирования docstrings
- Код должен быть self-explanatory

## Project Structure
- **Package manager**: используй `uv run` для запуска команд
- **Database name**: `zoom_manager`
- **API**: FastAPI приложение в `api/`
- **Database**: модели SQLAlchemy в `database/`
- **Services**: бизнес-логика в отдельных модулях
- **Tasks**: Celery задачи в `api/tasks/`
- **Multi-tenancy**: все операции должны учитывать `user_id`

## Security Requirements
- Проверяй доступ к ресурсам через `ResourceAccessValidator`
- Используй `TaskAccessService` для доступа к задачам
- Все запросы к БД должны фильтроваться по `user_id`
- OAuth токены хранятся encrypted в БД

## Documentation
- НЕ создавай лишние MD файлы
- Обновляй `WHAT_WAS_DONE.md` только важными изменениями
- Формат записи: краткое описание + файлы/модули

## Testing & Validation
- Проверяй через линтер: `uv run ruff check .`
- Убедись, что миграции БД проходят корректно
- Проверь мультитенантность в изменениях

## Common Patterns
- Используй dependency injection в FastAPI роутерах
- Async/await для всех I/O операций
- Context managers для работы с БД сессиями
- Enum для статусов и платформ