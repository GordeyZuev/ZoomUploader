from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.config_models import UserConfigModel


class UserConfigRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_user_id(self, user_id: int) -> UserConfigModel | None:
        result = await self.session.execute(
            select(UserConfigModel).where(UserConfigModel.user_id == user_id)
        )
        return result.scalars().first()

    async def create(self, user_id: int, config_data: dict) -> UserConfigModel:
        config = UserConfigModel(user_id=user_id, config_data=config_data)
        self.session.add(config)
        await self.session.flush()
        await self.session.refresh(config)
        return config

    async def update(self, config: UserConfigModel, config_data: dict) -> UserConfigModel:
        config.config_data = config_data
        await self.session.flush()
        await self.session.refresh(config)
        return config

    async def delete(self, config: UserConfigModel) -> None:
        await self.session.delete(config)
        await self.session.flush()

