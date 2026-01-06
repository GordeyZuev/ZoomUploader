"""API endpoints для работы с thumbnails пользователей."""

from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from api.auth.dependencies import get_current_user
from api.schemas.thumbnail import (
    ThumbnailInfo,
    ThumbnailListResponse,
    ThumbnailUploadResponse,
)
from database.auth_models import UserModel
from logger import get_logger
from utils.thumbnail_manager import get_thumbnail_manager

logger = get_logger()
router = APIRouter(prefix="/api/v1/thumbnails", tags=["Thumbnails"])


@router.get("", response_model=ThumbnailListResponse)
async def list_user_thumbnails(
    current_user: Annotated[UserModel, Depends(get_current_user)],
    include_templates: bool = True,
) -> ThumbnailListResponse:
    """
    Получить список thumbnails пользователя.

    Args:
        include_templates: Включить ли глобальные templates в список
    """
    thumbnail_manager = get_thumbnail_manager()

    # Получить пользовательские thumbnails
    user_thumbnails = thumbnail_manager.list_user_thumbnails(current_user.id)
    user_items = [
        ThumbnailInfo(
            name=thumb.name,
            path=str(thumb),
            is_template=False,
            **thumbnail_manager.get_thumbnail_info(thumb),
        )
        for thumb in user_thumbnails
    ]

    # Добавить templates если нужно
    template_items = []
    if include_templates:
        template_thumbnails = thumbnail_manager.list_template_thumbnails()
        template_items = [
            ThumbnailInfo(
                name=thumb.name,
                path=str(thumb),
                is_template=True,
                **thumbnail_manager.get_thumbnail_info(thumb),
            )
            for thumb in template_thumbnails
        ]

    return ThumbnailListResponse(
        user_thumbnails=user_items,
        template_thumbnails=template_items,
    )


@router.post("", response_model=ThumbnailUploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_thumbnail(
    current_user: Annotated[UserModel, Depends(get_current_user)],
    file: UploadFile = File(...),
) -> ThumbnailUploadResponse:
    """
    Загрузить пользовательский thumbnail.

    Поддерживаемые форматы: PNG, JPG, JPEG
    Максимальный размер: 2MB (рекомендация YouTube)
    """
    # Проверить формат
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is required",
        )

    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in [".png", ".jpg", ".jpeg"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported format: {file_ext}. Supported: .png, .jpg, .jpeg",
        )

    # Проверить размер (2MB)
    max_size = 2 * 1024 * 1024
    content = await file.read()
    if len(content) > max_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large: {len(content) / 1024 / 1024:.1f}MB > 2MB",
        )

    # Сохранить во временный файл
    thumbnail_manager = get_thumbnail_manager()
    temp_path = Path(f"/tmp/{file.filename}")

    try:
        with open(temp_path, "wb") as f:
            f.write(content)

        # Загрузить через менеджер
        saved_path = thumbnail_manager.upload_user_thumbnail(
            user_id=current_user.id,
            source_path=temp_path,
            thumbnail_name=file.filename,
        )

        logger.info(f"User {current_user.id} uploaded thumbnail: {file.filename}")

        return ThumbnailUploadResponse(
            message="Thumbnail uploaded successfully",
            thumbnail=ThumbnailInfo(
                name=saved_path.name,
                path=str(saved_path),
                is_template=False,
                **thumbnail_manager.get_thumbnail_info(saved_path),
            ),
        )

    except Exception as e:
        logger.error(f"Failed to upload thumbnail for user {current_user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to upload thumbnail: {str(e)}",
        )
    finally:
        # Удалить временный файл
        if temp_path.exists():
            temp_path.unlink()


@router.get("/{thumbnail_name}")
async def get_thumbnail_file(
    thumbnail_name: str,
    current_user: Annotated[UserModel, Depends(get_current_user)],
    use_template: bool = True,
) -> FileResponse:
    """
    Получить файл thumbnail (для просмотра или скачивания).

    Args:
        thumbnail_name: Имя файла thumbnail
        use_template: Искать ли в templates если не найдено у пользователя
    """
    thumbnail_manager = get_thumbnail_manager()

    thumbnail_path = thumbnail_manager.get_thumbnail_path(
        user_id=current_user.id,
        thumbnail_name=thumbnail_name,
        fallback_to_template=use_template,
    )

    if not thumbnail_path or not thumbnail_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thumbnail not found: {thumbnail_name}",
        )

    return FileResponse(
        path=thumbnail_path,
        media_type="image/png",
        filename=thumbnail_path.name,
    )


@router.delete("/{thumbnail_name}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_thumbnail(
    thumbnail_name: str,
    current_user: Annotated[UserModel, Depends(get_current_user)],
) -> None:
    """
    Удалить пользовательский thumbnail.

    Нельзя удалить глобальные templates.
    """
    thumbnail_manager = get_thumbnail_manager()

    success = thumbnail_manager.delete_user_thumbnail(
        user_id=current_user.id,
        thumbnail_name=thumbnail_name,
    )

    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Thumbnail not found: {thumbnail_name}",
        )

    logger.info(f"User {current_user.id} deleted thumbnail: {thumbnail_name}")
