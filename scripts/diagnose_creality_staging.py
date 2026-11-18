#!/usr/bin/env python3
"""Run Creality native 3MF diagnostic matrix against the EXISTING staging worker.

Usage:
  sudo python3 scripts/diagnose_creality_staging.py
  sudo python3 scripts/diagnose_creality_staging.py --job-id UUID
  sudo python3 scripts/diagnose_creality_staging.py --reference /path/Creality.3mf

Requires the staging app and slicer worker containers, the installed verified
Creality 7.3.x engine, and a previously failed two-material Creality draft.
Does not start a printer, change profile records, or create extra containers.
Private 3MF is ephemeral; only sanitised JSON diagnostics are retained.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid


APP = "makervault"
WORKER = "makervault-slicer-worker-1"
ROOT = Path(__file__).resolve().parent.parent


def _cmd(args, *, input_bytes=None, timeout=120, check=True):
    proc = subprocess.run(args, input=input_bytes, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, timeout=timeout, check=False)
    if check and proc.returncode:
        # Avoid accidentally printing engine output or private profile content.
        raise RuntimeError("A staging diagnostic step failed: " + str(args[:3]))
    return proc


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", help="Optional Creality failed job UUID")
    refs = parser.add_mutually_exclusive_group()
    refs.add_argument("--reference", help="Local genuine Creality-exported 3MF")
    refs.add_argument("--reference-inventory", metavar="FILENAME",
                      help="Select genuine 3MF from failed job owner's MakerVault files")
    refs.add_argument("--reference-asset-id", metavar="UUID",
                      help="Select specific owned FileAsset UUID")
    parser.add_argument("--timeout", type=int, default=90,
                        help="Seconds per native test (10–180)")
    parser.add_argument("--output", type=Path,
                        default=ROOT / "creality-diagnostic-report.json")
    args = parser.parse_args(argv)
    if os.geteuid() != 0:
        parser.error("Run with sudo for Docker access.")
    if not 10 <= args.timeout <= 180:
        parser.error("Timeout must be between 10 and 180 seconds.")
    if args.job_id:
        try:
            uuid.UUID(args.job_id)
        except ValueError:
            parser.error("Invalid job UUID.")
    if args.output.exists() or args.output.is_symlink():
        parser.error("Report already exists; specify another --output path.")
    if args.reference_asset_id:
        try:
            uuid.UUID(args.reference_asset_id)
        except ValueError:
            parser.error("Invalid FileAsset UUID.")
    if args.reference:
        path = Path(args.reference)
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
            parser.error("Reference must be a regular 3MF up to 32 MiB.")
    suffix = uuid.uuid4().hex
    app_candidate = "/tmp/makervault-creality-" + suffix + ".3mf"
    worker_candidate = app_candidate
    worker_report = "/tmp/makervault-creality-report-" + suffix + ".json"
    worker_reference = "/tmp/makervault-creality-ref-" + suffix + ".3mf"
    with tempfile.TemporaryDirectory(prefix="makervault-creality-") as temporary:
        local_candidate = Path(temporary) / "candidate.3mf"
        try:
            export = [
                "docker", "exec", APP, "python3", "/app/backend/manage.py",
                "diagnose_creality_candidate", "--output", app_candidate,
            ]
            if args.job_id:
                export += ["--job-id", args.job_id]
            _cmd(export, timeout=90)
            _cmd(["docker", "cp", APP + ":" + app_candidate, str(local_candidate)])
            project = local_candidate.read_bytes()
            if not 0 < len(project) <= 32 * 1024 * 1024:
                raise RuntimeError("Generated candidate is empty or oversized.")
            # Worker writes file under its own unprivileged account. Do not
            # copy files with root-only permissions into its read-only FS.
            _cmd([
                "docker", "exec", "-i", WORKER, "sh", "-c",
                'umask 077; cat > "$1"', "sh", worker_candidate,
            ], input_bytes=project)
            runner = [
                "docker", "exec", WORKER, "python3", "-m",
                "slicer_worker.creality_diagnostics",
                "--project", worker_candidate, "--output", worker_report,
                "--timeout", str(args.timeout),
            ]
            if args.reference or args.reference_inventory or args.reference_asset_id:
                if args.reference:
                    refdata = Path(args.reference).read_bytes()
                else:
                    app_reference = "/tmp/makervault-creality-ref-" + suffix + ".3mf"
                    reference_export = [
                        "docker", "exec", APP, "python3",
                        "/app/backend/manage.py", "diagnose_creality_reference",
                        "--output", app_reference,
                    ]
                    if args.job_id:
                        reference_export += ["--job-id", args.job_id]
                    if args.reference_asset_id:
                        reference_export += ["--asset-id", args.reference_asset_id]
                    else:
                        reference_export += ["--name", args.reference_inventory]
                    try:
                        reference_lookup = _cmd(reference_export, timeout=90,
                                                check=False)
                        if reference_lookup.returncode:
                            raise RuntimeError(
                                "Inventory reference was not found, ambiguous, or "
                                "not a valid native 3MF. Use --reference-asset-id "
                                "with the exact FileAsset UUID if needed.")
                        local_reference = Path(temporary) / "reference.3mf"
                        _cmd(["docker", "cp", APP + ":" + app_reference,
                              str(local_reference)], timeout=90)
                        refdata = local_reference.read_bytes()
                    finally:
                        _cmd(["docker", "exec", APP, "rm", "-f", "--",
                              app_reference], check=False, timeout=15)
                if not 0 < len(refdata) <= 32 * 1024 * 1024:
                    raise RuntimeError("Reference 3MF is empty or exceeds the limit.")
                _cmd([
                    "docker", "exec", "-i", WORKER, "sh", "-c",
                    'umask 077; cat > "$1"', "sh", worker_reference,
                ], input_bytes=refdata)
                runner += ["--reference", worker_reference]
            execution = _cmd(runner, timeout=7 * args.timeout + 60, check=False)
            # 2 means none of the CLI cases passed; the JSON is still useful.
            if execution.returncode not in (0, 2):
                raise RuntimeError(
                    "Diagnostic execution failed before writing a report; "
                    "check worker health and native engine availability.")
            result = _cmd(["docker", "exec", WORKER, "cat", worker_report],
                          timeout=30)
            report = json.loads(result.stdout)
            if (report.get("schema") != 1 or
                    not isinstance(report.get("test_results"), list) or
                    len(report["test_results"]) != 7):
                raise RuntimeError("Worker returned malformed diagnostic report.")
            # Always create a new report, never overwrite earlier runs.
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as handle:
                json.dump(report, handle, indent=2)
                handle.write("\n")
            # sudo creates root-owned files otherwise, preventing the actual
            # staging user from reading a report containing only safe fields.
            uid_text = os.environ.get("SUDO_UID", "")
            gid_text = os.environ.get("SUDO_GID", "")
            if uid_text.isdecimal() and gid_text.isdecimal():
                os.chown(args.output, int(uid_text), int(gid_text))
            os.chmod(args.output, 0o600)
            print("Creality diagnostic report: " + str(args.output))
            for case in report["test_results"]:
                print(" - {case}: {status} (exit={exit_code}, category={validation_category}, reason={known_validation_reason})".format(
                    case=case["case"], status=case["status"],
                    exit_code=case.get("exit_code", "none"),
                    validation_category=case.get("validation_category", "none"),
                    known_validation_reason=case.get("known_validation_reason", "unclassified")))
            if report.get("reference"):
                comparison = report["reference"]
                print(" Structural reference comparison: missing settings={missing}, shape differences={shapes}, candidate models={candidate}, reference models={reference}".format(
                    missing=comparison["missing_setting_count"],
                    shapes=comparison["different_value_shape_count"],
                    candidate=comparison["candidate_structure_counts"]["resource_objects"],
                    reference=comparison["reference_structure_counts"]["resource_objects"]))
            return 0 if any(x["status"] == "passed" for x in report["test_results"]) else 2
        finally:
            # Deliberately erase all private model/config copies, including on
            # failure. Only the safe non-sensitive report persists.
            for container, names in (
                (APP, [app_candidate]),
                (WORKER, [worker_candidate, worker_report, worker_reference]),
            ):
                for name in names:
                    _cmd(["docker", "exec", container, "rm", "-f", "--", name],
                         check=False, timeout=15)


if __name__ == "__main__":
    sys.exit(main())
