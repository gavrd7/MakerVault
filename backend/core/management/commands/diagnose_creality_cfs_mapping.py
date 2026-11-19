"""Inspect saved Creality model slots against fresh native CFS telemetry; never print."""
import json

from django.core.management.base import BaseCommand, CommandError

from core.models import SliceJob, PrinterConnection, PrinterFilamentSlot
from core.printer_gcode_submission import creality_cfs_context, _is_k2
from core.printer_connectivity import poll_connection, PrinterConnectionError
from core.slicer_creality_cfs_audit import (
    CrealityCfsAuditError, audit_creality_cfs_assignments, audit_creality_gcode_for_cfs,
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
                SliceJob.objects.select_related("printer", "output_asset").filter(
                    engine="crealityprint", status="completed",
                    output_asset__isnull=False,
                ).order_by("-created_at")[:25]
                if (candidate.settings or {}).get("multi_material_test") is True
                and len((candidate.settings or {}).get("plate_objects") or []) == 2
            ), None)
            if job is None:
                raise CommandError("No recent two-material Creality job found.")
        else:
            try:
                job = SliceJob.objects.select_related("printer", "output_asset").get(pk=options["job_id"])
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
        # The submission safety context intentionally rejects snapshots older
        # than 60 seconds. Refresh via the existing read-only adapter poll,
        # otherwise an otherwise healthy K2 fails when the dashboard is idle.
        # Polling updates MakerVault's stored telemetry but NEVER issues a
        # printer print/start/toolchange command.
        try:
            poll_connection(sources[0])
        except (PrinterConnectionError, OSError, ValueError) as exc:
            raise CommandError(
                "Could not refresh native K2 CFS telemetry: " + str(exc)
            ) from exc
        sources[0].refresh_from_db()
        context = creality_cfs_context(sources[0])
        if not context.get("verified"):
            raise CommandError(
                "Native K2 telemetry was refreshed but is still not verified "
                "(connection offline or no fresh online snapshot)."
            )
        if context.get("connected") is not True:
            raise CommandError(
                "Fresh K2 telemetry does not confirm an attached CFS; "
                "check that the printer reports cfs_connected and materials."
            )
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
                objects, rows, context,
                printer_id=job.printer_id,
            )
        except CrealityCfsAuditError as exc:
            raise CommandError(str(exc)) from exc
        asset = job.output_asset
        if asset is None:
            raise CommandError("Selected Creality job has no completed G-code file.")
        if asset.file.size > 64 * 1024 * 1024:
            raise CommandError("Creality G-code exceeds the supported audit size.")
        with asset.file.storage.open(asset.file.name, "rb") as handle:
            raw = handle.read(64 * 1024 * 1024 + 1)
        try:
            report = audit_creality_gcode_for_cfs(job, report, raw)
        except CrealityCfsAuditError as exc:
            raise CommandError(str(exc)) from exc
        # Read-only protocol compatibility summary, not a print command.
        # Creality/Orca use T1A for logical tool zero, T1B for tool one;
        # CFS boxId and materialId are physical bay coordinates.
        seen_bays = set()
        preview = []
        for row in report["mapping"]:
            bay = (row["box_id"], row["material_id"])
            if bay in seen_bays:
                raise CommandError("Duplicate physical CFS bay in protocol audit.")
            seen_bays.add(bay)
            preview.append({
                "logical_id": "T1" + "ABCD"[row["tool_index"]],
                "boxId": row["box_id"],
                "materialId": row["material_id"],
                "material": row["material"],
                "colour": row["colour"],
            })
        report["protocol_preflight"] = {
            "mapping_entries": preview,
            "expected_command_sequence": ["colorMatch", "multiColorPrint"],
            "commands_sent": False,
            "firmware_response_verified": False,
        }
        self.stdout.write(json.dumps(report, indent=2))
