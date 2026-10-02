from datetime import timedelta

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .backup_bundle import BackupBundleError, create_prepared_bundle
from .backups import backup_in_progress
from .catalogue_image_sources import run_catalogue_image_seed
from .catalogue_enrichment import run_board_catalogue_enrichment
from .models import CatalogueMaintenanceSettings, PrinterConnection, PrintingIntegrationSetting
from .orcaslicer_catalogue import OrcaCatalogueError, sync_orcaslicer_printer_catalogue
from .printing_sync import PrintingSyncError, sync_printing_integration
from .printer_connectivity import POLLERS, PrinterConnectionError, poll_connection


@shared_task
def ping_worker():
    return {"status": "ok", "worker": "makervault"}


@shared_task(bind=True, acks_late=True, reject_on_worker_lost=True)
def create_managed_backup_task(self, backup_id):
    """Create a prepared recovery bundle inside the existing MakerVault worker."""
    try:
        return create_prepared_bundle(str(backup_id))
    except BackupBundleError as exc:
        return {"status": "failed", "backup_id": str(backup_id), "error": str(exc)}


@shared_task(bind=True, acks_late=True)
def seed_catalogue_images_task(self, limit=None, force_retry=False, kinds=None):
    if backup_in_progress():
        return {"status": "backup-in-progress"}
    result = run_catalogue_image_seed(limit=limit, force_retry=force_retry, kinds=kinds)
    if result.get("status") == "limit-reached":
        self.apply_async(
            kwargs={"limit": limit, "force_retry": False, "kinds": kinds},
            countdown=5,
        )
    return result


@shared_task(bind=True, acks_late=True)
def enrich_board_catalogue_task(self, limit=None, force_retry=False):
    if backup_in_progress():
        return {"status": "backup-in-progress"}
    return run_board_catalogue_enrichment(limit=limit, force_retry=force_retry)


@shared_task(bind=True, acks_late=True)
def sync_orcaslicer_printer_catalogue_task(self):
    if backup_in_progress():
        return {"status": "backup-in-progress"}
    try:
        return sync_orcaslicer_printer_catalogue()
    except OrcaCatalogueError as exc:
        return {"status": "error", "error": str(exc)}


def _queue_catalogue_maintenance(config):
    if backup_in_progress():
        return []
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
    if backup_in_progress():
        return {"status": "backup-in-progress", "queued": []}
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
    if backup_in_progress():
        config = CatalogueMaintenanceSettings.objects.filter(singleton_key=1).first()
        return (config or CatalogueMaintenanceSettings(singleton_key=1)), []
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
    if backup_in_progress():
        return {"status": "backup-in-progress", "setting_id": str(setting_id)}
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
    if backup_in_progress():
        return {"status": "backup-in-progress", "queued": []}
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

@shared_task
def live_printer_connection_poll_task(connection_id):
    """Poll one configured live source and persist its normalised snapshot."""
    if backup_in_progress():
        return {"status": "backup-in-progress", "connection_id": str(connection_id)}
    item = PrinterConnection.objects.select_related("printer").filter(pk=connection_id).first()
    if not item:
        return {"status": "missing", "connection_id": str(connection_id)}
    if not item.enabled or not item.printer.is_active:
        return {"status": "disabled", "connection_id": str(connection_id)}
    try:
        snapshot = poll_connection(item)
        return {
            "status": "connected",
            "connection_id": str(item.id),
            "printer_id": str(item.printer_id),
            "adapter": item.adapter,
            "state": snapshot.get("state", "unknown"),
        }
    except PrinterConnectionError as exc:
        return {
            "status": "disconnected",
            "connection_id": str(item.id),
            "printer_id": str(item.printer_id),
            "adapter": item.adapter,
            "error": str(exc),
        }


@shared_task
def live_printer_connections_tick():
    """Queue live printer polls when each connection's own interval is due."""
    if backup_in_progress():
        return {"status": "backup-in-progress", "queued": [], "count": 0}
    now = timezone.now()
    due = []
    supported = set(POLLERS)

    with transaction.atomic():
        rows = list(
            PrinterConnection.objects.select_for_update()
            .select_related("printer")
            .filter(
                enabled=True,
                printer__is_active=True,
                adapter__in=supported,
            )
            .exclude(endpoint_url="")
            .order_by("printer__name", "adapter")
        )
        for item in rows:
            if item.last_checked_at:
                if item.status == "connecting":
                    # Treat an in-flight poll as leased. The lease is longer
                    # than normal HTTP adapter timeouts but eventually expires
                    # so a crashed worker cannot leave a source stuck forever.
                    lease_seconds = max(60, item.poll_interval_seconds * 2)
                    if item.last_checked_at + timedelta(seconds=lease_seconds) > now:
                        continue
                next_due = item.last_checked_at + timedelta(seconds=item.poll_interval_seconds)
                if next_due > now:
                    continue
            # Reserve the poll window before queueing so a 10-second beat does
            # not enqueue the same printer repeatedly while a request is slow.
            item.status = "connecting"
            item.last_checked_at = now
            item.save(update_fields=["status", "last_checked_at", "updated_at"])
            due.append((item.pk, item.adapter))

    for connection_id, _adapter in due:
        live_printer_connection_poll_task.delay(connection_id)

    return {
        "status": "queued" if due else "not-due",
        "queued": [adapter for _, adapter in due],
        "count": len(due),
    }

