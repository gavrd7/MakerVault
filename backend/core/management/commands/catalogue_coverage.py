import json

from django.core.management.base import BaseCommand

from core.catalogue_coverage import catalogue_coverage_summary


class Command(BaseCommand):
    help = "Report image/specification completeness across MakerVault shared catalogues."

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", help="Emit the complete audit as JSON.")

    def handle(self, *args, **options):
        summary = catalogue_coverage_summary()
        if options["json"]:
            self.stdout.write(json.dumps(summary, indent=2, sort_keys=True))
            return

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"MakerVault catalogue coverage — {summary['records']} shared records"
        ))
        for catalogue in summary["catalogues"]:
            self.stdout.write("")
            self.stdout.write(self.style.HTTP_INFO(
                f"{catalogue['label']} ({catalogue['total']} records)"
            ))
            for metric in catalogue["metrics"]:
                self.stdout.write(
                    f"  {metric['label']}: {metric['percent']:.1f}% "
                    f"({metric['complete']} complete / {metric['missing']} missing)"
                )
            if catalogue["missing_samples"]:
                self.stdout.write("  Examples needing attention:")
                for item in catalogue["missing_samples"][:5]:
                    missing = list(item.get("missing") or [])
                    if item.get("missing_image"):
                        missing.append("image")
                    missing.extend((item.get("unresolved_fields") or [])[:4])
                    self.stdout.write(f"    - {item['name']}: {', '.join(missing)}")
