from django.core.management.base import BaseCommand, CommandError

from core.backup_bundle import (
    BackupBundleError,
    create_bundle,
    recover_interrupted_backups,
    register_bundle,
    restore_bundle,
    validate_backup_id,
)


class Command(BaseCommand):
    help = "Create, validate, register, restore, or recover MakerVault backup bundles."

    def add_arguments(self, parser):
        sub = parser.add_subparsers(dest="backup_command", required=True)

        create = sub.add_parser("create")
        create.add_argument("--id")
        create.add_argument("--label", default="manual")

        validate = sub.add_parser("validate")
        validate.add_argument("--id", required=True)

        register = sub.add_parser("register")
        register.add_argument("--id", required=True)
        register.add_argument("--label", default="Imported recovery bundle")

        restore = sub.add_parser("restore")
        restore.add_argument("--id", required=True)

        sub.add_parser("recover-stale")

    def handle(self, *args, **options):
        command = options["backup_command"]
        try:
            if command == "create":
                result = create_bundle(
                    backup_id=options.get("id"),
                    label=options.get("label") or "manual",
                )
            elif command == "validate":
                result = validate_backup_id(options["id"])
            elif command == "register":
                result = register_bundle(
                    options["id"],
                    label=options.get("label") or "Imported recovery bundle",
                )
            elif command == "restore":
                restore_bundle(options["id"])
                result = {"restored": True, "backup_id": options["id"]}
            elif command == "recover-stale":
                count = recover_interrupted_backups()
                result = {"recovered": count}
            else:
                raise CommandError("Unknown backup command.")
        except BackupBundleError as exc:
            raise CommandError(str(exc)) from exc

        import json
        self.stdout.write(json.dumps(result))
