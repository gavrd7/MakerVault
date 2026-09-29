from django.core.management.base import BaseCommand, CommandError
from django.db.models import F, Q

from core.models import (
    FileAsset,
    InventoryItem,
    Model3D,
    PrintJob,
    Printer,
    PrintingIntegrationSetting,
    PrintingLocation,
    Project,
    Spool,
)


PRIVATE_MODELS = (
    Project,
    InventoryItem,
    FileAsset,
    PrintingLocation,
    PrintingIntegrationSetting,
    Spool,
    Printer,
    Model3D,
    PrintJob,
)


class Command(BaseCommand):
    help = "Audit v0.7 private-data ownership without exposing private record contents."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fail-on-issues",
            action="store_true",
            help="Exit non-zero when unowned records or cross-owner relationships are found.",
        )

    def handle(self, *args, **options):
        issues = 0
        self.stdout.write("MakerVault private ownership audit")

        for model in PRIVATE_MODELS:
            total = model.objects.count()
            unowned = model.objects.filter(owner__isnull=True).count()
            issues += unowned
            self.stdout.write(
                f"  {model.__name__}: total={total}, unowned={unowned}"
            )

        checks = {
            "inventory/project owner mismatch": InventoryItem.objects.filter(
                project__isnull=False
            ).exclude(owner_id=F("project__owner_id")).count(),
            "file/project owner mismatch": FileAsset.objects.filter(
                project__isnull=False
            ).exclude(owner_id=F("project__owner_id")).count(),
            "model/project owner mismatch": Model3D.objects.filter(
                project__isnull=False
            ).exclude(owner_id=F("project__owner_id")).count(),
            "printer/location owner mismatch": Printer.objects.filter(
                printing_location__isnull=False
            ).exclude(owner_id=F("printing_location__owner_id")).count(),
            "spool/location owner mismatch": Spool.objects.filter(
                storage_location__isnull=False
            ).exclude(owner_id=F("storage_location__owner_id")).count(),
            "spool/printer owner mismatch": Spool.objects.filter(
                assigned_printer__isnull=False
            ).exclude(owner_id=F("assigned_printer__owner_id")).count(),
            "print/printer owner mismatch": PrintJob.objects.exclude(
                owner_id=F("printer__owner_id")
            ).count(),
            "print/project owner mismatch": PrintJob.objects.filter(
                project__isnull=False
            ).exclude(owner_id=F("project__owner_id")).count(),
            "print/model owner mismatch": PrintJob.objects.filter(
                model_revision__isnull=False
            ).exclude(owner_id=F("model_revision__model__owner_id")).count(),
        }

        for label, count in checks.items():
            issues += count
            self.stdout.write(f"  {label}: {count}")

        if issues:
            message = f"Ownership audit found {issues} issue(s)."
            if options["fail_on_issues"]:
                raise CommandError(message)
            self.stdout.write(self.style.WARNING(message))
        else:
            self.stdout.write(self.style.SUCCESS("Ownership audit passed: no issues found."))
