"""Inspect saved Creality model slots against fresh native CFS telemetry; never print."""
import json

from django.core.management.base import BaseCommand, CommandError

from core.models import SliceJob, PrinterConnection, PrinterFilamentSlot
from core.printer_gcode_submission import creality_cfs_context, _is_k2
from core.slicer_creality_cfs_audit import (
    CrealityCfsAuditError, audit_creality_cfs_assignments,
)


class Command(BaseCommand):
    help = "Read-only audit of a saved two-model Creality slice's CFS selections"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--job-id")
        group.add_argument("--latest", action="store_true",
                           help="Audit the most recent saved Creality two-material job")

    def handle(self, *args, **options):
        if options["latest"]:
            job = next((
                candidate for candidate in
                SliceJob.objects.select_related("printer").filter(
                    engine="crealityprint"
                ).order_by("-created_at")[:25]
                if (candidate.settings or {}).get("multi_material_test") is True
                and len((candidate.settings or {}).get("plate_objects") or []) == 2
            ), None)
            if job is None:
                raise CommandError("No recent two-material Creality job found.")
        else:
            try:
                job = SliceJob.objects.select_related("printer").get(pk=options["job_id"])
            except (SliceJob.DoesNotExist, ValueError, TypeError):
                raise CommandError("Saved Creality job not found.") from None
        if job.engine != "crealityprint" or (job.settings or {}).get("multi_material_test") is not True:
            raise CommandError("Select a two-material Creality Print slice.")
        objects = (job.settings or {}).get("plate_objects") or []
        sources = list(PrinterConnection.objects.filter(
            printer_id=job.printer_id, adapter="creality_local", enabled=True
        ).order_by("-last_seen_at")[:2])
        if len(sources) != 1:
            raise CommandError("Exactly one enabled native Creality connection is required.")
        if not _is_k2(sources[0]):
            raise CommandError("This CFS identity audit currently supports K2 printers only.")
        slot_ids = [
            obj.get("material_slot", {}).get("slot_id")
            for obj in objects if isinstance(obj, dict)
        ]
        if len(slot_ids) != 2 or any(not isinstance(slot, str) for slot in slot_ids):
            raise CommandError("This job has no complete saved CFS slot assignments.")
        rows = list(PrinterFilamentSlot.objects.filter(
            printer_id=job.printer_id, pk__in=slot_ids, system="creality_cfs"
        ))
        try:
            report = audit_creality_cfs_assignments(
                objects, rows, creality_cfs_context(sources[0]),
                printer_id=job.printer_id,
            )
        except CrealityCfsAuditError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(report, indent=2))
