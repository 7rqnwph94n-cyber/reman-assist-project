"""
Backfill missing job_pack_id values by copying job_number.
Run once after deployments that changed job_pack_id to non-null.

Usage:
    PYTHONPATH=. python3 scripts/backfill_job_pack_id.py
"""
from app import app
from models import db, Job


def main():
    with app.app_context():
        missing = Job.query.filter((Job.job_pack_id.is_(None)) | (Job.job_pack_id == "")).all()
        for j in missing:
            j.job_pack_id = j.job_number
        db.session.commit()
        print(f"Backfilled {len(missing)} job(s).")


if __name__ == "__main__":
    main()
