"""Non-disruptive real HTTP and Orca G-code test for the published worker.

Use on a Docker-enabled test/staging host:
    python3 scripts/test_published_slicer_worker.py

Requires outbound access to fetch pinned Orca 2.5.0 Creality reference
profiles. The published immutable image runs in one temporary container,
without any Docker network, port publication or access to MakerVault data.
Does not modify Compose, installed worker, printer, or database.
"""
import argparse
import base64
import hashlib
import json
import re
import secrets
import subprocess
import sys
import tempfile
import textwrap
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.build_orca_reference_fixture import generate

IMAGE = ("ghcr.io/gavrd7/makervault-slicer-orca@sha256:"
         "7f12df990d059d6a5e889c3cff6ebacd3a7c627fee28ff75e8696bee9c3423f4")
ENGINE_SHA256 = "b30b0ae933e653692cf85a493287a949215ae4c14d547a00203d16dfcadb8054"
ENGINE_REGISTRY = json.dumps({"orcaslicer": {
    "binary": "/opt/engines/orcaslicer.AppImage",
    "version": "2.5.0", "binary_sha256": ENGINE_SHA256,
}}, separators=(",", ":"))

# Executed INSIDE the disposable worker container (no host network). Do not
# log the bearer token or full native profile payloads / G-code.
RUNTIME_PROBE = textwrap.dedent("""
import base64, hashlib, json, os, re, uuid
from pathlib import Path
from urllib.request import Request, urlopen
from slicer_worker.probe import fixture_stl

base = "http://127.0.0.1:8088"
with urlopen(base + "/health", timeout=15) as response:
    health = json.load(response)
assert health.get("ready") is True, health
installed = health["engines"]["orcaslicer"]
assert installed["version"] == "2.5.0"
assert installed["binary_sha256"] == os.environ["EXPECTED_ENGINE_SHA256"]
print("PASS: HTTP health and pinned Orca identity", flush=True)

def encoded(name):
    return base64.b64encode(Path("/fixtures/" + name + ".json").read_bytes()).decode("ascii")

payload = {
    "job_id": str(uuid.uuid4()), "engine": "orcaslicer",
    "engine_version": "2.5.0",
    "model": base64.b64encode(fixture_stl()).decode("ascii"),
    "printer_profile": encoded("printer"),
    "filament_profile": encoded("filament"),
    "process_profile": encoded("process"),
}
req = Request(base + "/v1/slice", data=json.dumps(payload).encode("utf-8"),
              method="POST", headers={
                  "Authorization": "Bearer " + os.environ["SLICER_WORKER_TOKEN"],
                  "Content-Type": "application/json",
              })
with urlopen(req, timeout=240) as response:
    result = json.load(response)
assert result["status"] == "completed"
gcode = base64.b64decode(result["gcode"], validate=True)
assert gcode and len(gcode) == result["bytes"]
assert hashlib.sha256(gcode).hexdigest() == result["sha256"]
assert re.search(rb"(?m)^G0?1[^\\r\\n]*\\bE[-+]?\\d", gcode), "No G-code extrusion"
print("PASS: authenticated worker slice with real Orca CLI", flush=True)
print("G-code bytes:", len(gcode), "SHA-256:", result["sha256"], flush=True)
print("PASS: temporary container can be removed safely", flush=True)
""").strip()


def run(command, *, timeout=300, capture=False):
    return subprocess.run(command, check=True, timeout=timeout, text=True,
                          capture_output=capture)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--printer", choices=("k1", "k2"), default="k2",
                        help="Pinned official Orca v2.5.0 Creality fixture (default: k2)")
    args = parser.parse_args()
    token = secrets.token_hex(32)
    name = "makervault-worker-smoke-" + uuid.uuid4().hex[:12]
    launched = False
    try:
        print("Pulling immutable published worker image...", flush=True)
        run(["docker", "pull", IMAGE], timeout=600)
        with tempfile.TemporaryDirectory(prefix="makervault-worker-smoke-") as temporary:
            fixture_dir = Path(temporary) / "fixtures"
            generate(fixture_dir, args.printer, preserve_official_values=True)
            fixture_dir.chmod(0o755)
            for file in fixture_dir.iterdir():
                file.chmod(0o444)
            cmd = [
                "docker", "run", "-d", "--rm", "--name", name,
                "--network", "none", "--read-only",
                "--user", "10001:10001", "--init", "--cap-drop", "ALL",
                "--security-opt", "no-new-privileges:true",
                "--pids-limit", "96", "--memory", "3g", "--cpus", "2",
                "--tmpfs", "/tmp:rw,exec,nosuid,nodev,size=1g,mode=1777",
                "--mount", f"type=bind,src={fixture_dir},dst=/fixtures,readonly",
                "--env", "SLICER_WORKER_ENABLED=1",
                "--env", "SLICER_WORKER_TOKEN=" + token,
                "--env", "SLICER_ENGINES_JSON=" + ENGINE_REGISTRY,
                "--env", "EXPECTED_ENGINE_SHA256=" + ENGINE_SHA256,
                IMAGE,
            ]
            run(cmd, timeout=90, capture=True)
            launched = True
            print("Running isolated health and authenticated K1/K2 slicing checks...", flush=True)
            # The HTTP server starts almost immediately; bounded retries avoid
            # spurious failures on slower staging hosts.
            health_code = ('import time,urllib.request; '
                           'url="http://127.0.0.1:8088/health"; '
                           '[(time.sleep(1) if i else None) for i in range(4)]; '
                           'assert urllib.request.urlopen(url,timeout=5).status==200')
            run(["docker", "exec", name, "python3", "-c", health_code], timeout=40)
            run(["docker", "exec", name, "python3", "-c", RUNTIME_PROBE], timeout=300)
        print("SUCCESS: published worker passed isolated runtime smoke test.", flush=True)
        return 0
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError,
            ValueError, AssertionError) as exc:
        print("FAILED: " + str(exc), file=sys.stderr)
        return 1
    finally:
        if launched:
            subprocess.run(["docker", "rm", "-f", name], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL, check=False, timeout=30)


if __name__ == "__main__":
    sys.exit(main())
