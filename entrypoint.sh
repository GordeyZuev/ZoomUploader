#!/bin/bash
set -e

echo "🚀 Starting LEAP..."

# Ждем, пока PostgreSQL будет готов
echo "⏳ Waiting for PostgreSQL..."
while ! pg_isready -h ${DATABASE_HOST:-localhost} -p ${DATABASE_PORT:-5432} -U ${DATABASE_USERNAME:-postgres} > /dev/null 2>&1; do
    echo "   PostgreSQL is unavailable - sleeping"
    sleep 2
done
echo "✅ PostgreSQL is ready!"

# Создаем БД, если её нет, и применяем миграции
echo "🔄 Creating database and applying migrations..."
python <<EOF
import asyncio
from database.config import DatabaseConfig
from database.manager import DatabaseManager

async def init_db():
    db_config = DatabaseConfig.from_env()
    db_manager = DatabaseManager(db_config)
    await db_manager.create_database_if_not_exists()
    await db_manager.close()
    print("✅ Database ready")

asyncio.run(init_db())
EOF

# Применяем миграции Alembic
echo "🔄 Applying Alembic migrations..."
alembic upgrade head
echo "✅ Migrations applied!"

# Запускаем команду, переданную в CMD
echo "🎉 Starting application: $@"
exec "$@"

