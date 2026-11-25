"""Authenticated native Prusa 3MF acceptance through actual isolated worker."""
import base64
import hashlib
import json
from pathlib import Path
import threading
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from slicer_worker import service
from slicer_worker.prusa_vendor_profiles import flatten_prusa_vendor_preset
from slicer_worker.prusa_gcode_audit import audit_prusa_positive_e

TOKEN = "0123456789012345678901234567890123456789"


def main(vendor_path, project_paths):
    vendor = Path(vendor_path).read_bytes()
    digest = hashlib.sha256(vendor).hexdigest()
    profiles = {}
    for kind, name, field in (
        ("printer", "Original Prusa i3 MK2S", "printer_profile"),
        ("filament", "Generic PLA", "filament_profile"),
        ("print", "0.20mm NORMAL", "process_profile"),
    ):
        profiles[field] = base64.b64encode(flatten_prusa_vendor_preset(
            vendor, kind=kind, name=name, expected_sha256=digest)).decode("ascii")
    worker = service.BoundedWorkerHTTPServer(("127.0.0.1", 0), service.Handler)
    thread = threading.Thread(target=worker.serve_forever, daemon=True)
    thread.start()
    base = "http://127.0.0.1:" + str(worker.server_address[1])
    try:
        for label, path in project_paths:
            project = Path(path).read_bytes()
            payload = {
                "job_id": str(uuid.uuid4()), "engine": "prusaslicer",
                "engine_version": "2.9.7", "model_format": "3mf",
                "model": base64.b64encode(project).decode("ascii"), **profiles,
            }
            if label in ("support-enforced", "support-blocked"):
                # Fixture only: the application adds this through the exact
                # Prusa process adapter; never alter the stored upstream preset.
                native = base64.b64decode(payload["process_profile"])
                opts = {key: val for key, val in (
                    line.split("=", 1) for line in native.decode().splitlines()
                    if "=" in line and not line.lstrip().startswith(("#", ";"))
                )}
                opts = {key.strip(): val.strip() for key, val in opts.items()}
                opts["support_material"] = "1"
                opts["support_material_auto"] = (
                    "0" if label == "support-enforced" else "1")
                safe = "".join("%s = %s\n" % entry for entry in sorted(opts.items()))
                payload["process_profile"] = base64.b64encode(
                    safe.encode("utf-8")).decode("ascii")
            data = json.dumps(payload, separators=(",", ":")).encode()
            unauthenticated = Request(base + "/v1/slice", data=data, headers={
                "Content-Type": "application/json"})
            try:
                urlopen(unauthenticated, timeout=15)
                raise AssertionError("Unauthenticated Prusa project was accepted")
            except HTTPError as exc:
                assert exc.code == 403, exc.code
            request = Request(base + "/v1/slice", data=data, headers={
                "Content-Type": "application/json", "Authorization": "Bearer " + TOKEN})
            with urlopen(request, timeout=180) as response:
                assert response.status == 200
                result = json.load(response)
            gcode = base64.b64decode(result["gcode"], validate=True)
            assert result["bytes"] == len(gcode)
            assert result["sha256"] == hashlib.sha256(gcode).hexdigest()
            audited = audit_prusa_positive_e(gcode)
            assert audited["positive_e_moves"] >= 40, (label, audited)
            if label == "support-enforced":
                # Authentic HTTP G-code must demonstrate more than successful
                # XML loading. Manual support enforcers generate support paths.
                assert b";TYPE:Support material" in gcode, label
            print("PASS: authenticated Prusa native 3MF", label, audited)
    finally:
        worker.shutdown()
        worker.server_close()


if __name__ == "__main__":
    import sys
    pairs = [value.split("=", 1) for value in sys.argv[2:]]
    if any(len(p) != 2 for p in pairs):
        raise SystemExit("Pass label=/absolute/path.3mf")
    main(sys.argv[1], pairs)
