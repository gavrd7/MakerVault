"""Read-only, bounded audit of original OrcaSlicer vendor preset inheritance.

A verified resources archive must be obtained independently. This tool does
not download, flatten, install, execute or approve any profile or engine.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath

MAX_PROFILE_BYTES = 1024 * 1024
MAX_CANDIDATES = 3000
MAX_DEPTH = 16
KINDS = ("machine", "process", "filament")


class BundleAuditError(ValueError):
    pass


def _safe_path(root, path):
    if not isinstance(path, str) or not path.startswith("resources/profiles/"):
        raise BundleAuditError("Unexpected Orca profile path.")
    rel = PurePosixPath(path)
    if any(part in (".", "..") for part in rel.parts) or rel.suffix != ".json":
        raise BundleAuditError("Unsafe native profile path.")
    candidate = root.joinpath(*rel.parts[2:])
    if any(p.is_symlink() for p in (candidate, *list(candidate.parents)[:len(rel.parts)])):
        raise BundleAuditError("Symlinks are not allowed in the audited profile bundle.")
    if not candidate.is_file() or not candidate.resolve().is_relative_to(root.resolve()):
        raise BundleAuditError("Native profile file is missing or escapes its source bundle.")
    return candidate


def _profile(root, path):
    source = _safe_path(root, path)
    if not 0 < source.stat().st_size <= MAX_PROFILE_BYTES:
        raise BundleAuditError("Native profile exceeds size limit or is empty.")
    raw = source.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeDecodeError):
        raise BundleAuditError("Native profile is not UTF-8 JSON.") from None
    if not isinstance(value, dict):
        raise BundleAuditError("Native profile must be a JSON object.")
    name = value.get("name") or source.stem
    parent = value.get("inherits") or None
    if not isinstance(name, str) or not 0 < len(name) <= 200:
        raise BundleAuditError("Native preset name is invalid.")
    if parent is not None and (not isinstance(parent, str) or not 0 < len(parent) <= 200):
        raise BundleAuditError("Native preset parent is invalid.")
    return {
        "path": path, "name": name, "inherits": parent,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def audit_bundle(resources_root, fixture_manifest):
    root = Path(resources_root).resolve(strict=True)
    if not root.is_dir():
        raise BundleAuditError("A local Orca resources/profiles directory is required.")
    fixture = json.loads(Path(fixture_manifest).read_text(encoding="utf-8"))
    if fixture.get("schema") != "makervault.orca-fixture-candidates.v1":
        raise BundleAuditError("Unsupported fixture manifest.")
    items = fixture.get("printers")
    if not isinstance(items, list) or not 1 <= len(items) <= 20:
        raise BundleAuditError("Invalid printer fixture catalogue.")
    output = []
    for printer in items:
        if not isinstance(printer, dict):
            raise BundleAuditError("Invalid printer fixture.")
        report = {"printer": printer.get("model"), "profiles": {}}
        for kind in KINDS:
            key = ("machine" if kind == "machine" else kind) + "_profile"
            start = printer.get(key)
            if not isinstance(start, str):
                raise BundleAuditError("Missing native fixture profile reference.")
            # Restrict lookup to the vendor's corresponding kind and the
            # official shared filament library, never unrelated vendors.
            base = PurePosixPath(start)
            if len(base.parts) != 5 or base.parts[:3] != ("resources", "profiles", "Creality") or base.parts[3] != kind:
                raise BundleAuditError("Unexpected fixture source location.")
            directories = [root / "Creality" / kind]
            if kind == "filament":
                directories.append(root / "OrcaFilamentLibrary" / "filament")
            candidates = {}
            scanned = 0
            for directory in directories:
                if not directory.is_dir() or directory.is_symlink():
                    continue
                for source in sorted(directory.glob("*.json")):
                    scanned += 1
                    if scanned > MAX_CANDIDATES:
                        raise BundleAuditError("Native profile candidate count exceeds limit.")
                    if source.is_symlink():
                        raise BundleAuditError("Native profile symlink found.")
                    rel = "resources/profiles/" + str(source.relative_to(root).as_posix())
                    entry = _profile(root, rel)
                    candidates.setdefault(entry["name"], []).append(entry)
            selected = _profile(root, start)
            candidates.setdefault(selected["name"], [])
            if not any(item["path"] == start for item in candidates[selected["name"]]):
                candidates[selected["name"]].append(selected)
            chain = []
            visited = set()
            current = selected
            status, missing = "complete", None
            for _ in range(MAX_DEPTH):
                if current["name"] in visited:
                    status = "cycle"
                    break
                visited.add(current["name"])
                chain.append(current)
                parent = current["inherits"]
                if not parent:
                    break
                matches = candidates.get(parent, [])
                if not matches:
                    status, missing = "missing", parent
                    break
                if len(matches) != 1:
                    status, missing = "ambiguous", parent
                    break
                current = matches[0]
            else:
                status = "too_deep"
            report["profiles"][kind] = {
                "status": status, "missing": missing, "chain": chain,
                "approved_for_execution": False,
            }
        output.append(report)
    return {
        "upstream_ref": fixture["upstream_ref"],
        "results": output,
        "approved_for_execution": False,
    }


def main():
    parser = argparse.ArgumentParser(description="Audit original, unmodified Orca parent preset files")
    parser.add_argument("--resources", required=True, type=Path,
                        help="Locally reviewed upstream resources/profiles directory")
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        result = audit_bundle(args.resources, args.manifest)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        parser.exit(1, "Orca bundle audit failed: " + str(exc) + "\n")
    rendered = json.dumps(result, sort_keys=True, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n")
    else:
        print(rendered)
    if any(profile["status"] != "complete"
           for result in result["results"] for profile in result["profiles"].values()):
        parser.exit(2, "Orca bundle has unresolved native profile dependencies.\n")


if __name__ == "__main__":
    main()
