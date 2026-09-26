from celery import shared_task

from .catalogue_image_sources import run_catalogue_image_seed


@shared_task
def ping_worker():
    return {"status": "ok", "worker": "makervault"}


@shared_task(bind=True, acks_late=True)
def seed_catalogue_images_task(self, limit=None, force_retry=False):
    return run_catalogue_image_seed(limit=limit, force_retry=force_retry)
