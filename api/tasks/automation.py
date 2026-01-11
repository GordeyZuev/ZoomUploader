"""Celery tasks for automation jobs."""

import asyncio
import logging

from api.celery_app import celery_app
from api.helpers.schedule_converter import get_next_run_time, schedule_to_cron
from api.repositories.automation_repos import AutomationJobRepository
from api.repositories.recording_repo import RecordingRepository
from database.manager import DatabaseManager
from models.recording import ProcessingStatus

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, name="automation.run_job")
def run_automation_job_task(self, job_id: int, user_id: int):
    """
    Execute automation job:
    1. Sync source recordings
    2. Match new recordings with templates
    3. Run full pipeline for matched recordings
    """

    async def _run():
        from database.config import DatabaseConfig
        
        db_config = DatabaseConfig.from_env()
        db_manager = DatabaseManager(db_config)
        async with db_manager.async_session() as session:
            job_repo = AutomationJobRepository(session)
            job = await job_repo.get_by_id(job_id, user_id)

            if not job or not job.is_active:
                logger.warning(f"Job {job_id} not found or inactive")
                return {"status": "skipped", "reason": "Job not found or inactive"}

            try:
                logger.info(f"Starting automation job {job_id} ({job.name})")

                sync_config = job.sync_config
                processing_config = job.processing_config

                # Step 1: Sync source via PipelineManager
                from datetime import datetime, timedelta

                # Get credentials for source
                from api.repositories.auth_repos import UserCredentialRepository
                from api.repositories.template_repos import InputSourceRepository
                from pipeline_manager import PipelineManager

                source_repo = InputSourceRepository(session)
                source = await source_repo.find_by_id(job.source_id, user_id)

                if not source or not source.credential_id:
                    logger.error(f"Job {job_id}: Invalid source configuration")
                    return {"status": "error", "error": "Invalid source configuration"}

                cred_repo = UserCredentialRepository(session)
                credential = await cred_repo.get_by_id(source.credential_id)

                if not credential:
                    logger.error(f"Job {job_id}: Credential not found")
                    return {"status": "error", "error": "Credential not found"}

                # Decrypt credentials
                from utils.encryption import decrypt_credentials
                creds_data = decrypt_credentials(credential.encrypted_data)

                # Calculate date range
                days = sync_config.get("sync_days", 2)
                to_date = datetime.now().strftime("%Y-%m-%d")
                from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

                # Sync via PipelineManager
                pipeline = PipelineManager(user_id=user_id)
                synced_count = await pipeline.sync_zoom_recordings(creds_data, from_date, to_date)

                logger.info(f"Job {job_id}: Synced {synced_count} new recordings")

                # Step 2: Get INITIALIZED recordings (newly synced)
                recording_repo = RecordingRepository(session)
                new_recordings = await recording_repo.get_by_filters(
                    user_id=user_id,
                    status=ProcessingStatus.INITIALIZED.value
                )

                # Step 3: Process recordings if auto_process is enabled
                processed_recordings = []
                processed_count = 0

                if processing_config.get("auto_process", True):
                    from api.tasks.processing import full_pipeline_task

                    # Process all INITIALIZED recordings (template-driven)
                    auto_upload = processing_config.get("auto_upload", True)
                    manual_override = {
                        "upload": {"auto_upload": auto_upload}
                    } if auto_upload else None
                    
                    for recording in new_recordings:
                        task = full_pipeline_task.delay(
                            recording_id=recording.id,
                            user_id=user_id,
                            manual_override=manual_override,
                        )

                        processed_recordings.append({
                            "recording_id": recording.id,
                            "task_id": str(task.id)
                        })
                        processed_count += 1

                logger.info(f"Job {job_id}: Processed {processed_count} recordings, started {len(processed_recordings)} pipelines")

                # Step 4: Update job stats
                cron_expr, _ = schedule_to_cron(job.schedule)
                timezone = job.schedule.get("timezone", "Europe/Moscow")
                next_run = get_next_run_time(cron_expr, timezone)
                await job_repo.mark_run(job, next_run)

                return {
                    "status": "success",
                    "job_id": job_id,
                    "synced_count": synced_count,
                    "processed_count": len(processed_recordings),
                    "processed_recordings": processed_recordings,
                    "next_run_at": next_run.isoformat()
                }

            except Exception as e:
                logger.error(f"Job {job_id} failed: {e}", exc_info=True)
                return {
                    "status": "error",
                    "job_id": job_id,
                    "error": str(e)
                }

    return asyncio.run(_run())


@celery_app.task(name="automation.dry_run")
def dry_run_automation_job_task(job_id: int, user_id: int):
    """
    Preview what the job would do without executing.
    Returns estimated counts without actually processing.
    """

    async def _run():
        from database.config import DatabaseConfig
        
        db_config = DatabaseConfig.from_env()
        db_manager = DatabaseManager(db_config)
        async with db_manager.async_session() as session:
            job_repo = AutomationJobRepository(session)
            job = await job_repo.get_by_id(job_id, user_id)

            if not job:
                return {"status": "error", "error": "Job not found"}

            try:
                # For dry-run, we estimate based on recent history
                # This is a simplified estimation without actual API calls
                estimated_new = 3  # Conservative estimate

                # Estimate current INITIALIZED recordings count
                recording_repo = RecordingRepository(session)
                current_recordings = await recording_repo.get_by_filters(
                    user_id=user_id,
                    status=ProcessingStatus.INITIALIZED.value
                )
                current_count = len(current_recordings)

                total_to_process = estimated_new + current_count
                avg_duration_minutes = 15
                estimated_duration = total_to_process * avg_duration_minutes

                return {
                    "status": "success",
                    "job_id": job_id,
                    "estimated_new_recordings": estimated_new,
                    "current_initialized_count": current_count,
                    "total_to_process": total_to_process,
                    "estimated_duration_minutes": estimated_duration
                }

            except Exception as e:
                logger.error(f"Dry run failed for job {job_id}: {e}")
                return {"status": "error", "error": str(e)}

    return asyncio.run(_run())

