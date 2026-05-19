from uuid import UUID

from app.db.session import SessionLocal
from app.jobs.celery_app import celery_app
from app.services.external_sources import create_sync_run, due_connections
from app.services.job_dispatcher import dispatch_background_job
from app.services.jobs import enqueue_background_job, enqueue_stale_queued_jobs


@celery_app.task(name="jobs.process_background_job")
def process_background_job(job_id: str) -> dict[str, str]:
    db = SessionLocal()
    try:
        job = dispatch_background_job(db, UUID(job_id))
        db.commit()
        if job is None:
            return {"status": "missing"}
        return {"status": job.status}
    finally:
        db.close()


@celery_app.task(name="jobs.enqueue_due_external_source_syncs")
def enqueue_due_external_source_syncs() -> dict[str, int]:
    db = SessionLocal()
    queued = 0
    try:
        for connection in due_connections(db):
            sync_run, background_job = create_sync_run(db, connection=connection, trigger="scheduled")
            db.commit()
            try:
                task = enqueue_background_job(background_job.id)
                background_job.celery_task_id = task.id or ""
                queued += 1
                db.commit()
            except Exception as exc:
                sync_run.status = "failed"
                sync_run.error_message = f"Could not enqueue external source sync: {exc}"[:1000]
                background_job.status = "failed"
                background_job.error_message = sync_run.error_message
                db.commit()
        return {"queued": queued}
    finally:
        db.close()


@celery_app.task(name="jobs.enqueue_stale_queued_jobs")
def enqueue_stale_queued_background_jobs() -> dict[str, int]:
    db = SessionLocal()
    try:
        queued = enqueue_stale_queued_jobs(db)
        db.commit()
        return {"queued": queued}
    finally:
        db.close()
