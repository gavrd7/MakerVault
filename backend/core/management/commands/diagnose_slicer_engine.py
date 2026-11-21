"""Read-only, credential-safe staging diagnosis for slicer worker approvals.

Run: docker exec makervault python manage.py diagnose_slicer_engine
This never prints worker URLs, tokens, engine hashes, image IDs, or env values.
"""
import json
import os

from django.core.management.base import BaseCommand

from core.slicer_execution import verified_installation
from core.slicer_worker_client import health, SlicerWorkerError


def inspect_slicer_worker(environ=None, probe=health, approvals=verified_installation):
    env = os.environ if environ is None else environ
    if env.get("MAKERVAULT_SLICER_EXECUTION_ENABLED") != "1":
        return {"status": "disabled", "detail": "Slicer execution is disabled in the MakerVault container."}
    digest = env.get("MAKERVAULT_SLICER_ENGINE_IMAGE_DIGEST", "")
    image = env.get("MAKERVAULT_SLICER_WORKER_IMAGE", "")
    if (not digest.startswith("sha256:") or len(digest) != 71
            or any(ch not in "0123456789abcdef" for ch in digest[7:])
            or not (image == digest or image.endswith("@" + digest))):
        return {"status": "image_mismatch", "detail": "The worker image is not pinned to its approved digest."}
    config = env.get("MAKERVAULT_SLICER_ENGINES_JSON", "")
    if config:
        try:
            parsed = json.loads(config)
        except (ValueError, TypeError):
            parsed = None
        if not isinstance(parsed, dict) or not parsed:
            return {"status": "approval_missing", "detail": "The approved engine registry is missing or invalid."}
    else:
        if not env.get("MAKERVAULT_SLICER_ENGINE_VERSION") or not env.get("MAKERVAULT_SLICER_ENGINE_BINARY_SHA256"):
            return {"status": "approval_missing", "detail": "The approved engine version and binary identity are not configured."}
    try:
        response = probe()
    except (ValueError, SlicerWorkerError):
        return {"status": "unreachable", "detail": "The isolated worker could not be contacted or authenticated."}
    if not isinstance(response, dict) or response.get("ready") is not True:
        return {"status": "worker_unready", "detail": "The worker answered but is not ready."}
    approved = approvals()
    if not approved:
        return {"status": "identity_mismatch", "detail": "The worker is healthy, but its approved version or binary identity does not match."}
    return {"status": "ready", "detail": "Verified slicer engine(s) are available.", "engines": sorted(approved)}


class Command(BaseCommand):
    help = "Read-only slicer engine diagnosis, without exposing credentials or hashes."

    def handle(self, *args, **options):
        state = inspect_slicer_worker()
        self.stdout.write("Slicer engine status: " + state["status"])
        self.stdout.write(state["detail"])
        if state.get("engines"):
            self.stdout.write("Approved engine names: " + ", ".join(state["engines"]))
        self.stdout.write("No configuration was changed.")
