"""Helper для автоматической инициализации pipeline из конфигурации.

Создает processing_stages и output_targets на основе:
- RecordingTemplate.processing_config
- RecordingTemplate.output_config
- User config (unified_config)
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from database.models import OutputTargetModel, ProcessingStageModel, RecordingModel
from models.recording import ProcessingStageStatus, ProcessingStageType, TargetStatus, TargetType


async def initialize_processing_stages_from_config(
    session: AsyncSession,
    recording: RecordingModel,
    processing_config: dict[str, Any],
) -> list[ProcessingStageModel]:
    """
    Создать processing_stages на основе конфигурации.

    Args:
        session: DB session
        recording: Recording model
        processing_config: Конфигурация обработки из template/user_config

    Returns:
        Список созданных ProcessingStageModel

    Example processing_config:
        {
            "transcription": {
                "enable_transcription": True,
                "provider": "fireworks",
                "enable_topics": True,
                "enable_subtitles": True,
                ...
            }
        }
    """
    stages_to_create = []

    # Проверяем настройки транскрипции
    transcription_config = processing_config.get("transcription", {})

    if transcription_config.get("enable_transcription", False):
        # Создаем этап транскрипции
        stages_to_create.append(
            ProcessingStageModel(
                recording_id=recording.id,
                user_id=recording.user_id,
                stage_type=ProcessingStageType.TRANSCRIBE,
                status=ProcessingStageStatus.PENDING,
                stage_meta={"provider": transcription_config.get("provider", "fireworks")},
            )
        )

        # Если включено извлечение топиков
        if transcription_config.get("enable_topics", False):
            stages_to_create.append(
                ProcessingStageModel(
                    recording_id=recording.id,
                    user_id=recording.user_id,
                    stage_type=ProcessingStageType.EXTRACT_TOPICS,
                    status=ProcessingStageStatus.PENDING,
                    stage_meta={"mode": transcription_config.get("topic_mode", "long")},
                )
            )

        # Если включена генерация субтитров
        if transcription_config.get("enable_subtitles", False):
            stages_to_create.append(
                ProcessingStageModel(
                    recording_id=recording.id,
                    user_id=recording.user_id,
                    stage_type=ProcessingStageType.GENERATE_SUBTITLES,
                    status=ProcessingStageStatus.PENDING,
                    stage_meta={},
                )
            )

    # Добавляем stages в сессию
    for stage in stages_to_create:
        session.add(stage)

    # Flush чтобы получить ID
    await session.flush()

    return stages_to_create


async def initialize_output_targets_from_config(
    session: AsyncSession,
    recording: RecordingModel,
    output_config: dict[str, Any],
) -> list[OutputTargetModel]:
    """
    Создать output_targets на основе конфигурации.

    Args:
        session: DB session
        recording: Recording model
        output_config: Конфигурация выгрузки из template

    Returns:
        Список созданных OutputTargetModel

    Example output_config:
        {
            "preset_ids": {
                "youtube": 1,
                "vk": 2
            }
        }
    """
    targets_to_create = []

    # Получаем preset_ids
    preset_ids = output_config.get("preset_ids", {})

    if not preset_ids:
        return []

    # Создаем target для каждого preset
    for platform_str, preset_id in preset_ids.items():
        # Преобразуем строку платформы в TargetType
        try:
            target_type = TargetType[platform_str.upper()]
        except KeyError:
            # Если платформа не найдена, пропускаем
            continue

        targets_to_create.append(
            OutputTargetModel(
                recording_id=recording.id,
                user_id=recording.user_id,
                preset_id=preset_id,
                target_type=target_type,
                status=TargetStatus.NOT_UPLOADED,
                target_meta={},
            )
        )

    # Добавляем targets в сессию
    for target in targets_to_create:
        session.add(target)

    # Flush чтобы получить ID
    await session.flush()

    return targets_to_create


async def ensure_processing_stages(
    session: AsyncSession,
    recording: RecordingModel,
    processing_config: dict[str, Any],
) -> list[ProcessingStageModel]:
    """
    Убедиться, что processing_stages существуют (создать только отсутствующие).

    Args:
        session: DB session
        recording: Recording model
        processing_config: Конфигурация обработки

    Returns:
        Список всех processing_stages (существующие + созданные)
    """
    # Получаем существующие stage types
    existing_stage_types = {stage.stage_type for stage in recording.processing_stages}

    # Определяем какие stages нужны
    transcription_config = processing_config.get("transcription", {})
    required_stages = []

    if transcription_config.get("enable_transcription", False):
        required_stages.append(
            (
                ProcessingStageType.TRANSCRIBE,
                {"provider": transcription_config.get("provider", "fireworks")},
            )
        )

        if transcription_config.get("enable_topics", False):
            required_stages.append(
                (
                    ProcessingStageType.EXTRACT_TOPICS,
                    {"mode": transcription_config.get("topic_mode", "long")},
                )
            )

        if transcription_config.get("enable_subtitles", False):
            required_stages.append((ProcessingStageType.GENERATE_SUBTITLES, {}))

    # Создаем только недостающие stages
    new_stages = []
    for stage_type, meta in required_stages:
        if stage_type not in existing_stage_types:
            new_stage = ProcessingStageModel(
                recording_id=recording.id,
                user_id=recording.user_id,
                stage_type=stage_type,
                status=ProcessingStageStatus.PENDING,
                stage_meta=meta,
            )
            session.add(new_stage)
            new_stages.append(new_stage)

    if new_stages:
        await session.flush()

    return list(recording.processing_stages) + new_stages


async def ensure_output_targets(
    session: AsyncSession,
    recording: RecordingModel,
    output_config: dict[str, Any],
) -> list[OutputTargetModel]:
    """
    Убедиться, что output_targets существуют (создать только отсутствующие).

    Args:
        session: DB session
        recording: Recording model
        output_config: Конфигурация выгрузки

    Returns:
        Список всех output_targets (существующие + созданные)
    """
    # Получаем существующие target types
    existing_target_types = {target.target_type for target in recording.outputs}

    # Определяем какие targets нужны
    preset_ids = output_config.get("preset_ids", {})
    new_targets = []

    for platform_str, preset_id in preset_ids.items():
        try:
            target_type = TargetType[platform_str.upper()]
        except KeyError:
            continue

        # Проверяем, существует ли уже target
        if target_type.value not in existing_target_types:
            new_target = OutputTargetModel(
                recording_id=recording.id,
                user_id=recording.user_id,
                preset_id=preset_id,
                target_type=target_type,
                status=TargetStatus.NOT_UPLOADED,
                target_meta={},
            )
            session.add(new_target)
            new_targets.append(new_target)

    if new_targets:
        await session.flush()

    return list(recording.outputs) + new_targets

