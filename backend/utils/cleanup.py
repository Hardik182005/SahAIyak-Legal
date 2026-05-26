"""APScheduler job: delete cases older than DATA_RETENTION_DAYS daily at 2 AM IST."""
import logging
from datetime import datetime, timezone, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
_scheduler = AsyncIOScheduler(timezone="Asia/Kolkata")


def start_cleanup_scheduler(session_factory, retention_days: int):
    _scheduler.add_job(
        _cleanup_job,
        "cron",
        hour=2,
        minute=0,
        args=[session_factory, retention_days],
        id="case_cleanup",
        replace_existing=True,
    )
    _scheduler.start()
    logger.info("Cleanup scheduler started — runs daily at 2 AM IST, retention=%d days", retention_days)


def stop_cleanup_scheduler():
    if _scheduler.running:
        _scheduler.shutdown(wait=False)


async def _cleanup_job(session_factory, retention_days: int):
    from ..models import Case
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    async with session_factory() as session:
        result = await session.execute(
            delete(Case).where(Case.created_at < cutoff).returning(Case.id)
        )
        deleted = result.rowcount
        await session.commit()
    logger.info("Cleanup: deleted %d cases older than %d days", deleted, retention_days)
