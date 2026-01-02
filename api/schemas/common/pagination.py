"""Схемы для пагинации."""

from pydantic import BaseModel, Field


class PaginationParams(BaseModel):
    """Параметры пагинации."""

    page: int = Field(1, ge=1, description="Номер страницы")
    per_page: int = Field(20, ge=1, le=100, description="Записей на страницу")


class PaginatedResponse(BaseModel):
    """Ответ с пагинацией."""

    page: int
    per_page: int
    total: int
    total_pages: int

    @property
    def has_next(self) -> bool:
        """Есть ли следующая страница."""
        return self.page < self.total_pages

    @property
    def has_prev(self) -> bool:
        """Есть ли предыдущая страница."""
        return self.page > 1
