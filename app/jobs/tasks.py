from uuid import UUID

from app.db.session import SessionLocal
from app.jobs.celery_app import celery_app
from app.services.job_dispatcher import dispatch_background_job


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
