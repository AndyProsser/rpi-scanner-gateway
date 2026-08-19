"""
Deletes local archive copies older than RETENTION_DAYS.
Run daily via systemd timer (see systemd/retention-cleanup.timer).

Only touches the local archive backup — never touches OneDrive or email,
those are the durable copies.
"""
import logging
import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import config
from app import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("retention")


def main():
    config.ensure_dirs()
    cutoff = time.time() - (config.RETENTION_DAYS * 86400)
    old_jobs = db.jobs_older_than(cutoff)

    deleted = 0
    for job in old_jobs:
        archive_path = Path(job["archive_path"])
        if archive_path.exists():
            archive_path.unlink()
            deleted += 1
            logger.info("Deleted expired local backup: %s (job %d, %d days old)",
                        archive_path.name, job["id"], config.RETENTION_DAYS)
        db.update_job(job["id"], archive_path=None)

    logger.info("Retention cleanup complete: %d file(s) deleted", deleted)


if __name__ == "__main__":
    main()
