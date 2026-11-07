"""Administrator-controlled fixture approval for three engine-native profiles.

A successful fixture is evidence for this exact engine/binary/image/profile trio.
It never starts a print or approves another engine/version. This does not claim
the resulting G-code is safe for every model or physical printer.
"""
import hashlib
import uuid

from django.db import transaction
from django.utils import timezone

from .models import SlicerProfile
from .slicer_execution import MAX_PROFILE, SlicerExecutionError, verified_installation, _read_owned_file
from .slicer_worker_client import run_remote_job
from .slicer_native_resolution import resolved_native_profile
from .slicer_native_compatibility import check_native_compatibility


def fixture_stl():
    """A simple valid ASCII tetrahedron with non-coplanar triangular faces."""
    triangles = (
        ((0, 0, 0), (10, 0, 0), (0, 10, 0)),
        ((0, 0, 0), (0, 0, 10), (10, 0, 0)),
        ((0, 0, 0), (0, 10, 0), (0, 0, 10)),
        ((10, 0, 0), (0, 0, 10), (0, 10, 0)),
    )
    lines = ["solid makervault_fixture"]
    for face in triangles:
        lines += ["facet normal 0 0 1", "outer loop"]
        lines += ["vertex %s %s %s" % point for point in face]
        lines += ["endloop", "endfacet"]
    lines += ["endsolid makervault_fixture"]
    return ("\n".join(lines) + "\n").encode("ascii")


def _approved_gcode(data):
    if not isinstance(data, bytes) or len(data) < 40 or len(data) > 64 * 1024 * 1024:
        raise SlicerExecutionError("Fixture did not produce a bounded G-code file.")
    if b"\x00" in data[:4096]:
        raise SlicerExecutionError("Fixture produced binary output.")
    # The fixture must contain extrusion motion; a comment-only output is not
    # evidence that a real slice has occurred.
    import re
    if not re.search(rb"(?m)^\s*G0?1\s+[^\r\n]*\bE[-+\d.]+", data[:32 * 1024 * 1024], re.I):
        raise SlicerExecutionError("Fixture returned no extrusion moves.")
    return hashlib.sha256(data).hexdigest()


def approve_profiles_for_worker(*, owner, engine, version, profile_ids):
    """Verify one owned native trio via actual worker output, then approve.

    Requires a healthy worker authenticated by server configuration. Must only be
    called from an administrator-only API; never from ordinary import.
    """
    if not isinstance(profile_ids, dict) or set(profile_ids) != {"printer", "filament", "process"}:
        raise SlicerExecutionError("Choose all three native profile kinds.")
    installed = verified_installation()
    selected = installed.get(engine)
    if not selected or selected.get("version") != version:
        raise SlicerExecutionError("Requested engine/version has no approved worker.")
    ids = {}
    try:
        for kind in ("printer", "filament", "process"):
            ids[kind] = uuid.UUID(str(profile_ids[kind]))
    except (TypeError, ValueError, KeyError):
        raise SlicerExecutionError("Invalid native profile identity.") from None
    if len(set(ids.values())) != 3:
        raise SlicerExecutionError("Choose three separate native profiles.")
    profiles = {}
    inputs = {}
    for kind, pk in ids.items():
        profile = SlicerProfile.objects.select_related("file_asset").filter(
            pk=pk, owner=owner, kind=kind, engine=engine, engine_version=version,
        ).first()
        if not profile:
            raise SlicerExecutionError("A selected native profile is unavailable or belongs to another engine.")
        data = _read_owned_file(profile.file_asset, owner.pk, MAX_PROFILE, "Native profile")
        if hashlib.sha256(data).hexdigest() != profile.content_sha256:
            raise SlicerExecutionError("A native profile has changed since import.")
        profiles[kind] = profile
        inputs[kind] = resolved_native_profile(profile) if engine in {"orcaslicer", "crealityprint"} else data
        check_native_compatibility(engine, version, kind, inputs[kind])

    output = run_remote_job(
        uuid.uuid4(), engine, version, fixture_stl(),
        inputs["printer"], inputs["filament"], inputs["process"],
        timeout_seconds=95,
    )
    gcode_hash = _approved_gcode(output)
    # Check worker and binary identity a second time after running the fixture;
    # losing approval must fail closed.
    new_worker = verified_installation().get(engine)
    if not new_worker or new_worker != selected:
        raise SlicerExecutionError("Engine identity changed during the test slice.")
    receipt = hashlib.sha256(
        (engine + "|" + version + "|" + selected["image_digest"] + "|" +
         selected["binary_sha256"] + "|" + "|".join(profiles[k].content_sha256
         for k in ("printer", "filament", "process")) + "|" + gcode_hash).encode()
    ).hexdigest()
    evidence = {
        "engine_version": version,
        "image_digest": selected["image_digest"],
        "engine_binary_sha256": selected["binary_sha256"],
        "receipt_sha256": receipt,
        "gcode_sha256": gcode_hash,
        "fixture": "makervault-tetrahedron-v1",
    }
    with transaction.atomic():
        locked = list(SlicerProfile.objects.select_for_update().filter(
            pk__in=ids.values(), owner=owner
        ))
        if len(locked) != 3 or any(row.content_sha256 != profiles[row.kind].content_sha256
                                   or row.engine != engine or row.engine_version != version
                                   for row in locked):
            raise SlicerExecutionError("Native profiles changed during fixture approval.")
        now = timezone.now()
        for row in locked:
            row.status = "verified"
            row.verification_evidence = evidence
            row.verified_at = now
            row.save(update_fields=["status", "verification_evidence", "verified_at", "updated_at"])
    return {"engine": engine, "engine_version": version,
            "receipt_sha256": receipt, "gcode_sha256": gcode_hash,
            "verified_profile_ids": {kind: str(pk) for kind, pk in ids.items()}}
