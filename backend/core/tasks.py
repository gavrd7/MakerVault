from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .catalogue_image_sources import run_catalogue_image_seed
from .catalogue_enrichment import run_board_catalogue_enrichment
from .models import CatalogueMaintenanceSettings


@shared_task
def ping_worker():
    return {"status": "ok", "worker": "makervault"}


@shared_task(bind=True, acks_late=True)
def seed_catalogue_images_task(self, limit=None, force_retry=False):
    result = run_catalogue_image_seed(limit=limit, force_retry=force_retry)
    if result.get("status") == "limit-reached":
        self.apply_async(kwargs={"limit": limit, "force_retry": False}, countdown=5)
    return result


@shared_task(bind=True, acks_late=True)
def enrich_board_catalogue_task(self, limit=None):
    return run_board_catalogue_enrichment(limit=limit)


def _queue_catalogue_maintenance(config):
    queued = []
    if config.check_board_data and getattr(settings, "ENRICH_BOARD_CATALOGUE", True):
        enrich_board_catalogue_task.delay()
        queued.append("board-data")
    if config.check_images and getattr(settings, "SEED_CATALOGUE_IMAGES", True):
        seed_catalogue_images_task.delay()
        queued.append("images")
    return queued


@shared_task
def catalogue_maintenance_tick():
    """Lightweight periodic scheduler; the persistent interval lives in PostgreSQL."""
    now = timezone.now()
    with transaction.atomic():
        config, _ = CatalogueMaintenanceSettings.objects.select_for_update().get_or_create(singleton_key=1)
        if not config.enabled:
            return {"status": "disabled", "queued": []}
        if config.next_run_at and config.next_run_at > now:
            return {
                "status": "not-due",
                "next_run_at": config.next_run_at.isoformat(),
                "queued": [],
            }

        config.last_run_at = now
        config.next_run_at = now + timedelta(hours=config.interval_hours)
        config.last_triggered_by = "schedule"
        config.save(update_fields=["last_run_at", "next_run_at", "last_triggered_by", "updated_at"])

    queued = _queue_catalogue_maintenance(config)
    return {
        "status": "queued",
        "queued": queued,
        "next_run_at": config.next_run_at.isoformat(),
    }


def queue_catalogue_maintenance_now(triggered_by="manual"):
    now = timezone.now()
    with transaction.atomic():
        config, _ = CatalogueMaintenanceSettings.objects.select_for_update().get_or_create(singleton_key=1)
        config.last_run_at = now
        config.next_run_at = now + timedelta(hours=config.interval_hours) if config.enabled else None
        config.last_triggered_by = str(triggered_by or "manual")[:120]
        config.save(update_fields=["last_run_at", "next_run_at", "last_triggered_by", "updated_at"])
    queued = _queue_catalogue_maintenance(config)
    return config, queued
