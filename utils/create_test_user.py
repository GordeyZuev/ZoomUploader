"""Создание тестового пользователя с credentials."""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path

from api.auth.encryption import get_encryption
from api.auth.security import PasswordHelper
from database.auth_models import UserCredentialModel, UserModel, UserQuotaModel
from database.config import DatabaseConfig
from database.config_models import UserConfigModel
from database.manager import DatabaseManager
from database.template_models import InputSourceModel


async def create_test_user():
    """Создать тестового пользователя с credentials из zoom_creds.json."""

    # Zoom credentials из config/zoom_creds.json
    # ВАЖНО: Замените на свои реальные credentials из config/zoom_creds.json
    zoom_accounts = [
        {
            "account_name": "account1",
            "credentials": {
                "account": "user1@example.com",
                "account_id": "YOUR_ACCOUNT_ID_1",
                "client_id": "YOUR_CLIENT_ID_1",
                "client_secret": "YOUR_CLIENT_SECRET_1",
            },
        },
        {
            "account_name": "account2",
            "credentials": {
                "account": "user2@example.com",
                "account_id": "YOUR_ACCOUNT_ID_2",
                "client_id": "YOUR_CLIENT_ID_2",
                "client_secret": "YOUR_CLIENT_SECRET_2",
            },
        },
        {
            "account_name": "account3",
            "credentials": {
                "account": "user3@example.com",
                "account_id": "YOUR_ACCOUNT_ID_3",
                "client_id": "YOUR_CLIENT_ID_3",
                "client_secret": "YOUR_CLIENT_SECRET_3",
            },
        },
    ]

    config = DatabaseConfig.from_env()
    db_manager = DatabaseManager(config)
    encryption = get_encryption()

    async with db_manager.async_session() as session:
        # Проверяем, существует ли уже пользователь
        user = await db_manager.get_user_by_email("test@test.com")

        if user:
            print(f"✅ Пользователь test@test.com уже существует (id={user.id})")
        else:
            # Создаем пользователя
            user = UserModel(
                email="test@test.com",
                hashed_password=PasswordHelper.hash_password("testpassword"),
                full_name="Test User",
                is_active=True,
                is_verified=True,
                is_superuser=False,
                role="user",
            )
            session.add(user)
            await session.flush()

            # Создаем квоты
            quota = UserQuotaModel(
                user_id=user.id,
                max_recordings_per_month=1000,
                max_storage_gb=500,
                max_concurrent_tasks=10,
                quota_reset_at=datetime.utcnow() + timedelta(days=30),
            )
            session.add(quota)
            await session.flush()

            # Создаем config
            config_path = Path(__file__).parent.parent / "config" / "default_user_config.json"
            with open(config_path, "r", encoding="utf-8") as f:
                default_config = json.load(f)

            user_config = UserConfigModel(
                user_id=user.id,
                config_data=default_config,
            )
            session.add(user_config)
            await session.flush()

            print(f"✅ Создан пользователь: test@test.com (id={user.id})")
            print("   Пароль: testpassword")

        # Создаем Zoom credentials
        for zoom_account in zoom_accounts:
            # Проверяем, существует ли credential
            from sqlalchemy import select

            result = await session.execute(
                select(UserCredentialModel).where(
                    UserCredentialModel.user_id == user.id,
                    UserCredentialModel.platform == "zoom",
                    UserCredentialModel.account_name == zoom_account["account_name"],
                )
            )
            existing_cred = result.scalar_one_or_none()

            if existing_cred:
                print(f"   ⚠️  Credential для {zoom_account['account_name']} уже существует")
                continue

            # Шифруем credentials
            encrypted_data = encryption.encrypt_credentials(zoom_account["credentials"])

            # Создаем credential
            credential = UserCredentialModel(
                user_id=user.id,
                platform="zoom",
                account_name=zoom_account["account_name"],
                encrypted_data=encrypted_data,
                is_active=True,
            )
            session.add(credential)
            await session.flush()

            print(f"   ✅ Создан credential: zoom/{zoom_account['account_name']} (id={credential.id})")

            # Создаем input source
            source = InputSourceModel(
                user_id=user.id,
                name=f"Zoom {zoom_account['account_name'].title()}",
                description=f"Zoom account: {zoom_account['credentials']['account']}",
                source_type="ZOOM",
                credential_id=credential.id,
                config={
                    "sync_automatically": False,
                    "sync_schedule": None,
                },
                is_active=True,
            )
            session.add(source)
            await session.flush()

            print(f"      ✅ Создан source: {source.name} (id={source.id})")

        await session.commit()

        print("\n" + "=" * 60)
        print("✅ Тестовый пользователь создан успешно!")
        print("=" * 60)
        print("Email: test@test.com")
        print("Password: testpassword")
        print(f"User ID: {user.id}")
        print("\nДля получения токена:")
        print('curl -X POST "http://127.0.0.1:8000/api/v1/auth/login" \\')
        print('  -H "Content-Type: application/x-www-form-urlencoded" \\')
        print('  -d "username=test@test.com&password=testpassword"')

    await db_manager.close()


if __name__ == "__main__":
    asyncio.run(create_test_user())

