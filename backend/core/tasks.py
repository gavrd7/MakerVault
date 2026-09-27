from celery import shared_task

from .catalogue_image_sources import run_catalogue_image_seed
from .catalogue_enrichment import run_board_catalogue_enrichment


@shared_task
def ping_worker():
    return {"status": "ok", "worker": "makervault"}


@shared_task(bind=True, acks_late=True)
def seed_catalogue_images_task(self, limit=None, force_retry=False):
    result = run_catalogue_image_seed(limit=limit, force_retry=force_retry)
    # Work in bounded batches so a large first-run catalogue never holds a
    # Celery worker for longer than its normal task time limit.
    if result.get("status") == "limit-reached":
        self.apply_async(kwargs={"limit": limit, "force_retry": False}, countdown=5)
    return result


@shared_task(bind=True, acks_late=True)
def enrich_board_catalogue_task(self, limit=None):
    return run_board_catalogue_enrichment(limit=limit)
