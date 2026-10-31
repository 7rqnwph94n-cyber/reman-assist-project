from __future__ import annotations

from models import db, Job, JobReportRevisionLog


def bump_revision(job: Job, reason: str, user=None) -> None:
    """
    Increment job report revision and store a revision log entry.
    Caller is responsible for committing the session.
    """
    if not job:
        return
    job.report_revision = (job.report_revision or 0) + 1
    db.session.add(
        JobReportRevisionLog(
            job_id=job.id,
            revision=job.report_revision,
            reason=reason[:255],
            user_id=user.id if user else None,
        )
    )
