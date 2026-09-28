from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .catalogue_image_sources import run_catalogue_image_seed
from .catalogue_enrichment import run_board_catalogue_enrichment
from .models import CatalogueMaintenanceSettings, PrintingIntegrationSetting
from .orcaslicer_catalogue import OrcaCatalogueError, sync_orcaslicer_printer_catalogue
from .printing_sync import PrintingSyncError, sync_printing_integration


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
def enrich_board_catalogue_task(self, limit=None, force_retry=False):
    return run_board_catalogue_enrichment(limit=limit, force_retry=force_retry)


@shared_task(bind=True, acks_late=True)
def sync_orcaslicer_printer_catalogue_task(self):
    try:
        return sync_orcaslicer_printer_catalogue()
    except OrcaCatalogueError as exc:
        return {"status": "error", "error": str(exc)}


def _queue_catalogue_maintenance(config):
    queued = []
    if config.check_board_data and getattr(settings, "ENRICH_BOARD_CATALOGUE", True):
        enrich_board_catalogue_task.delay(force_retry=True)
        queued.append("board-data")
    if config.check_printer_data and getattr(settings, "SYNC_ORCASLICER_PRINTER_CATALOGUE", True):
        sync_orcaslicer_printer_catalogue_task.delay()
        queued.append("printer-data")
    if config.check_images and getattr(settings, "SEED_CATALOGUE_IMAGES", True):
        seed_catalogue_images_task.delay(force_retry=True)
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



@shared_task
def printing_integration_sync_task(setting_id, triggered_by="schedule"):
    try:
        setting = PrintingIntegrationSetting.objects.filter(pk=setting_id).first()
        if not setting:
            return {"status": "missing", "setting_id": str(setting_id)}
        provider = setting.provider
        setting, result = sync_printing_integration(
            provider,
            triggered_by=triggered_by,
            setting_id=setting_id,
        )
        return {
            "status": setting.status,
            "provider": provider,
            "result": result,
        }
    except PrintingSyncError as exc:
        return {
            "status": "error",
            "provider": provider,
            "error": str(exc),
        }


@shared_task
def printing_integrations_tick():
    """Queue due user-enabled printing integrations; schedule lives in PostgreSQL."""
    now = timezone.now()
    due = []
    with transaction.atomic():
        rows = list(
            PrintingIntegrationSetting.objects.select_for_update()
            .filter(enabled=True, auto_sync=True)
            .order_by("provider")
        )
        for item in rows:
            if item.next_sync_at and item.next_sync_at > now:
                continue
            item.next_sync_at = now + timedelta(minutes=item.sync_interval_minutes)
            item.save(update_fields=["next_sync_at", "updated_at"])
            due.append((item.pk, item.provider))

    for setting_id, provider in due:
        printing_integration_sync_task.delay(setting_id, triggered_by="schedule")

    return {"status": "queued" if due else "not-due", "queued": [provider for _, provider in due]}
