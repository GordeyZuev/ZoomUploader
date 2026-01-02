"""Repositories для работы с аутентификацией и пользователями."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.schemas.auth import (
    RefreshTokenCreate,
    RefreshTokenInDB,
    UserCreate,
    UserCredentialCreate,
    UserCredentialInDB,
    UserCredentialUpdate,
    UserInDB,
    UserQuotaCreate,
    UserQuotaInDB,
    UserQuotaUpdate,
    UserUpdate,
)
from database.auth_models import RefreshTokenModel, UserCredentialModel, UserModel, UserQuotaModel


class UserRepository:
    """Repository для работы с пользователями."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, user_id: int) -> UserInDB | None:
        """Получить пользователя по ID."""
        result = await self.session.execute(select(UserModel).where(UserModel.id == user_id))
        db_user = result.scalars().first()
        if not db_user:
            return None
        return UserInDB.model_validate(db_user)

    async def get_by_email(self, email: str) -> UserInDB | None:
        """Получить пользователя по email."""
        result = await self.session.execute(select(UserModel).where(UserModel.email == email))
        db_user = result.scalars().first()
        if not db_user:
            return None
        return UserInDB.model_validate(db_user)

    async def create(self, user_data: UserCreate, hashed_password: str) -> UserInDB:
        """Создать нового пользователя."""
        user = UserModel(
            email=user_data.email,
            hashed_password=hashed_password,
            full_name=user_data.full_name,
        )
        self.session.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        return UserInDB.model_validate(user)

    async def update(self, user_id: int, user_data: UserUpdate) -> UserInDB | None:
        """Обновить пользователя."""
        result = await self.session.execute(select(UserModel).where(UserModel.id == user_id))
        db_user = result.scalars().first()
        if not db_user:
            return None

        update_dict = user_data.model_dump(exclude_unset=True)
        for key, value in update_dict.items():
            setattr(db_user, key, value)

        await self.session.commit()
        await self.session.refresh(db_user)
        return UserInDB.model_validate(db_user)


class RefreshTokenRepository:
    """Repository для работы с refresh токенами."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, token_data: RefreshTokenCreate) -> RefreshTokenInDB:
        """Создать refresh токен."""
        refresh_token = RefreshTokenModel(
            user_id=token_data.user_id,
            token=token_data.token,
            expires_at=token_data.expires_at,
        )
        self.session.add(refresh_token)
        await self.session.commit()
        await self.session.refresh(refresh_token)
        return RefreshTokenInDB.model_validate(refresh_token)

    async def get_by_token(self, token: str) -> RefreshTokenInDB | None:
        """Получить refresh токен."""
        result = await self.session.execute(select(RefreshTokenModel).where(RefreshTokenModel.token == token))
        db_token = result.scalars().first()
        if not db_token:
            return None
        return RefreshTokenInDB.model_validate(db_token)

    async def revoke(self, token: str) -> RefreshTokenInDB | None:
        """Отозвать refresh токен."""
        result = await self.session.execute(select(RefreshTokenModel).where(RefreshTokenModel.token == token))
        db_token = result.scalars().first()
        if db_token:
            db_token.is_revoked = True
            await self.session.commit()
            await self.session.refresh(db_token)
            return RefreshTokenInDB.model_validate(db_token)
        return None


class UserQuotaRepository:
    """Repository для работы с квотами пользователей."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, quota_data: UserQuotaCreate) -> UserQuotaInDB:
        """Создать квоты для пользователя."""
        from datetime import timedelta

        quota = UserQuotaModel(
            user_id=quota_data.user_id,
            max_recordings_per_month=quota_data.max_recordings_per_month,
            max_storage_gb=quota_data.max_storage_gb,
            max_concurrent_tasks=quota_data.max_concurrent_tasks,
            quota_reset_at=datetime.utcnow() + timedelta(days=30),
        )
        self.session.add(quota)
        await self.session.commit()
        await self.session.refresh(quota)
        return UserQuotaInDB.model_validate(quota)

    async def get_by_user_id(self, user_id: int) -> UserQuotaInDB | None:
        """Получить квоты пользователя."""
        result = await self.session.execute(select(UserQuotaModel).where(UserQuotaModel.user_id == user_id))
        db_quota = result.scalars().first()
        if not db_quota:
            return None
        return UserQuotaInDB.model_validate(db_quota)

    async def update(self, user_id: int, quota_data: UserQuotaUpdate) -> UserQuotaInDB | None:
        """Обновить квоты пользователя."""
        result = await self.session.execute(select(UserQuotaModel).where(UserQuotaModel.user_id == user_id))
        db_quota = result.scalars().first()
        if not db_quota:
            return None

        update_dict = quota_data.model_dump(exclude_unset=True)
        for key, value in update_dict.items():
            setattr(db_quota, key, value)

        await self.session.commit()
        await self.session.refresh(db_quota)
        return UserQuotaInDB.model_validate(db_quota)


class UserCredentialRepository:
    """Repository для работы с учетными данными пользователей."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, credential_data: UserCredentialCreate) -> UserCredentialInDB:
        """Создать учетные данные пользователя."""
        credential = UserCredentialModel(
            user_id=credential_data.user_id,
            platform=credential_data.platform,
            account_name=credential_data.account_name,
            encrypted_data=credential_data.encrypted_data,
        )
        self.session.add(credential)
        await self.session.commit()
        await self.session.refresh(credential)
        return UserCredentialInDB.model_validate(credential)

    async def get_by_platform(
        self, user_id: int, platform: str, account_name: str | None = None
    ) -> UserCredentialInDB | None:
        """
        Получить учетные данные пользователя для платформы.

        Args:
            user_id: ID пользователя
            platform: Платформа
            account_name: Имя аккаунта (опционально, для множественных аккаунтов)

        Returns:
            Учетные данные или None
        """
        query = select(UserCredentialModel).where(
            UserCredentialModel.user_id == user_id,
            UserCredentialModel.platform == platform,
            UserCredentialModel.is_active,
        )

        if account_name is not None:
            query = query.where(UserCredentialModel.account_name == account_name)
        else:
            # Если account_name не указан, берем первый найденный
            query = query.where(UserCredentialModel.account_name.is_(None))

        result = await self.session.execute(query)
        db_credential = result.scalars().first()
        if not db_credential:
            return None
        return UserCredentialInDB.model_validate(db_credential)

    async def get_by_id(self, credential_id: int) -> UserCredentialInDB | None:
        """Получить учетные данные по ID."""
        result = await self.session.execute(select(UserCredentialModel).where(UserCredentialModel.id == credential_id))
        db_credential = result.scalars().first()
        if not db_credential:
            return None
        return UserCredentialInDB.model_validate(db_credential)

    async def list_by_platform(self, user_id: int, platform: str) -> list[UserCredentialInDB]:
        """Получить все учетные данные пользователя для платформы."""
        result = await self.session.execute(
            select(UserCredentialModel).where(
                UserCredentialModel.user_id == user_id,
                UserCredentialModel.platform == platform,
                UserCredentialModel.is_active,
            )
        )
        db_credentials = result.scalars().all()
        return [UserCredentialInDB.model_validate(cred) for cred in db_credentials]

    async def update(self, credential_id: int, credential_data: UserCredentialUpdate) -> UserCredentialInDB | None:
        """Обновить учетные данные пользователя."""
        result = await self.session.execute(select(UserCredentialModel).where(UserCredentialModel.id == credential_id))
        db_credential = result.scalars().first()
        if not db_credential:
            return None

        update_dict = credential_data.model_dump(exclude_unset=True)
        for key, value in update_dict.items():
            setattr(db_credential, key, value)

        db_credential.last_used_at = datetime.utcnow()
        await self.session.commit()
        await self.session.refresh(db_credential)
        return UserCredentialInDB.model_validate(db_credential)

    async def delete(self, credential_id: int) -> bool:
        """Удалить учетные данные пользователя."""
        result = await self.session.execute(select(UserCredentialModel).where(UserCredentialModel.id == credential_id))
        db_credential = result.scalars().first()
        if db_credential:
            await self.session.delete(db_credential)
            await self.session.commit()
            return True
        return False

    async def find_by_user(self, user_id: int) -> list[UserCredentialInDB]:
        """Получить все учетные данные пользователя."""
        result = await self.session.execute(select(UserCredentialModel).where(UserCredentialModel.user_id == user_id))
        db_credentials = result.scalars().all()
        return [UserCredentialInDB.model_validate(cred) for cred in db_credentials]

    async def update_last_used(self, credential_id: int) -> None:
        """Обновить время последнего использования."""
        result = await self.session.execute(select(UserCredentialModel).where(UserCredentialModel.id == credential_id))
        db_credential = result.scalars().first()
        if db_credential:
            db_credential.last_used_at = datetime.utcnow()
            await self.session.commit()

