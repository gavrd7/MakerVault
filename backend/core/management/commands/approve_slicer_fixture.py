"""Explicit administrative review of an Orca fixture receipt and native presets.

Dry-run by default. The command NEVER generates a test receipt, downloads a
binary, changes execution flags or sends commands to printers.
"""
import hashlib
import json
import os
import uuid
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from core.models import SlicerProfile
from core.slicer_profiles import SlicerProfileError, inspect_native_profile


MAX_RECEIPT_BYTES = 16384
KINDS = ("printer", "filament", "process")


def _hex_sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _load_receipt(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_RECEIPT_BYTES:
        raise CommandError("Provide a bounded, regular fixture receipt JSON file.")
    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
    except (OSError, UnicodeDecodeError, ValueError):
        raise CommandError("Fixture receipt could not be read as JSON.") from None
    required = (
        "engine", "engine_version", "engine_binary_sha256",
        "fixture_sha256", "printer_profile_sha256",
        "filament_profile_sha256", "process_profile_sha256",
        "gcode_sha256", "gcode_bytes", "cli_invocation",
        "approved_for_production",
    )
    if not isinstance(payload, dict) or any(key not in payload for key in required):
        raise CommandError("Fixture receipt is missing required evidence.")
    if payload["engine"] != "orcaslicer" or payload["cli_invocation"] != "verified":
        raise CommandError("A successful Orca real-engine fixture is required.")
    if payload["approved_for_production"] is not False:
        raise CommandError("Fixture receipt must not self-approve production deployment.")
    if not isinstance(payload["engine_version"], str) or not payload["engine_version"] or len(payload["engine_version"]) > 80:
        raise CommandError("Fixture lacks an exact engine version.")
    for key in ("engine_binary_sha256", "fixture_sha256", "printer_profile_sha256",
                "filament_profile_sha256", "process_profile_sha256", "gcode_sha256"):
        if not _hex_sha(payload.get(key)):
            raise CommandError("Fixture includes an invalid SHA-256 digest.")
    if type(payload["gcode_bytes"]) is not int or not 0 < payload["gcode_bytes"] <= 64 * 1024 * 1024:
        raise CommandError("Fixture G-code size is invalid.")
    return payload, hashlib.sha256(raw).hexdigest()


def _inspect_profiles(profile_ids, receipt):
    if set(profile_ids) != set(KINDS):
        raise CommandError("Specify printer, filament and process profile IDs.")
    profiles = {}
    owner_id = None
    for kind in KINDS:
        try:
            profile_id = uuid.UUID(str(profile_ids[kind]))
        except (TypeError, ValueError):
            raise CommandError("Invalid native profile ID.") from None
        record = SlicerProfile.objects.select_for_update(of=("self",)).select_related(
            "file_asset"
        ).filter(pk=profile_id, engine="orcaslicer",
                 engine_version=receipt["engine_version"], kind=kind).first()
        if record is None or (owner_id is not None and record.owner_id != owner_id):
            raise CommandError("Profile is missing or does not belong to this engine/version and owner.")
        owner_id = record.owner_id
        if record.file_asset.owner_id != owner_id:
            raise CommandError("Profile source ownership does not match.")
        try:
            inspected = inspect_native_profile(record.file_asset, "orcaslicer")
        except (ValueError, SlicerProfileError) as exc:
            raise CommandError("Imported native profile is no longer valid.") from exc
        if inspected["sha256"] != record.content_sha256 or inspected["sha256"] != receipt[kind + "_profile_sha256"]:
            raise CommandError("Native profile content does not match the reviewed fixture.")
        if inspected.get("requires_parent_bundle"):
            raise CommandError("Inherited Orca profiles require verified native parent-bundle execution support.")
        profiles[kind] = record
    if len({record.pk for record in profiles.values()}) != 3:
        raise CommandError("Each native preset must have a distinct identity.")
    return profiles


class Command(BaseCommand):
    help = "Review an Orca real-CLI fixture receipt; profile approval is explicit and never automatic."

    def add_arguments(self, parser):
        parser.add_argument("--receipt", required=True)
        for kind in KINDS:
            parser.add_argument("--" + kind + "-profile", required=True)
        parser.add_argument("--approve", action="store_true")
        parser.add_argument("--acknowledge-image-reviewed", action="store_true")
        parser.add_argument("--acknowledge-gcode-reviewed", action="store_true")
        parser.add_argument("--expected-gcode-sha256", default="")

    def handle(self, *args, **options):
        receipt, receipt_sha = _load_receipt(options["receipt"])
        if options["approve"]:
            if not options["acknowledge_image_reviewed"] or not options["acknowledge_gcode_reviewed"]:
                raise CommandError("Approval requires separate image and generated-G-code review acknowledgements.")
            if options["expected_gcode_sha256"] != receipt["gcode_sha256"]:
                raise CommandError("Manually reviewed output G-code checksum does not match the receipt.")
            # Only a digest-pinned, explicitly enabled service is eligible.
            image_ref = os.environ.get("MAKERVAULT_SLICER_WORKER_IMAGE", "")
            image_sha = os.environ.get("MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST", "")
            engine_sha = os.environ.get("MAKERVAULT_SLICER_ENGINE_BINARY_SHA256", "")
            version = os.environ.get("MAKERVAULT_SLICER_ENGINE_VERSION", "")
            if (
                os.environ.get("MAKERVAULT_SLICER_ENGINE") != "orcaslicer"
                or os.environ.get("MAKERVAULT_SLICER_EXECUTION_ENABLED") != "1"
                or not _hex_sha(image_sha[7:]) or not image_sha.startswith("sha256:")
                or not image_ref.endswith("@" + image_sha)
                or not _hex_sha(engine_sha) or engine_sha != receipt["engine_binary_sha256"]
                or version != receipt["engine_version"]
            ):
                raise CommandError("A matching explicitly enabled, digest-pinned Orca worker is required.")
        ids = {kind: options[kind + "_profile"] for kind in KINDS}
        with transaction.atomic():
            profiles = _inspect_profiles(ids, receipt)
            if options["approve"]:
                evidence = {
                    "receipt_sha256": receipt_sha,
                    "engine_binary_sha256": receipt["engine_binary_sha256"],
                    "engine_version": receipt["engine_version"],
                    "gcode_sha256": receipt["gcode_sha256"],
                    "image_digest": image_sha,
                }
                for profile in profiles.values():
                    profile.status = "verified"
                    profile.verified_at = timezone.now()
                    profile.verification_evidence = evidence
                    profile.save(update_fields=["status", "verified_at", "verification_evidence", "updated_at"])
        mode = "APPROVED" if options["approve"] else "DRY RUN ONLY"
        self.stdout.write(
            self.style.SUCCESS(f"{mode}: Orca fixture and three exact native profiles matched.")
        )
        if not options["approve"]:
            self.stdout.write("No profile was approved. Use explicit review flags after validating the real engine.")
