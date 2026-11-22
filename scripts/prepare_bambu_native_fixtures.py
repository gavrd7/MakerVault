"""Resolve an offline Bambu X1C smoke fixture from the pinned AppImage resources.

No downloads, printer connections, slicer admission or host profile mutation.
Fail closed if an upstream profile moves, is ambiguous, or has unknown ancestry.
This is **not** a general-purpose profile import pathway.
"""
import argparse
import hashlib
import json
from pathlib import Path

PROFILE_NAMES = {
    "machine": "Bambu Lab X1 Carbon 0.4 nozzle",
    "process": "0.20mm Standard @BBL X1C",
    "filament": "Bambu PLA Basic @BBL X1C",
}
MAX_FILE = 1024 * 1024
MAX_DEPTH = 32


def find_vendor_bundle(appdir: Path) -> Path:
    root = Path(appdir).resolve(strict=True)
    found = []
    for directory in root.rglob("cli_config.json"):
        if directory.parent.name != "BBL" or directory.is_symlink():
            continue
        candidate = directory.parent
        if all((candidate / kind).is_dir() for kind in PROFILE_NAMES):
            found.append(candidate)
    if len(found) != 1:
        raise ValueError("Expected exactly one bundled BBL native profile directory.")
    return found[0]


def _profile_path(bundle: Path, kind: str, name: str) -> Path:
    directory = bundle / kind
    if not name or "/" in name or "\\\\" in name or name in {".", ".."}:
        raise ValueError("Invalid native profile reference.")
    direct = directory / (name + ".json")
    if direct.is_file() and not direct.is_symlink():
        return direct
    matches = [p for p in directory.rglob("*.json")
               if p.stem == name and not p.is_symlink()]
    if len(matches) != 1:
        raise ValueError("Native Bambu profile is missing or ambiguous: " + kind + "/" + name)
    return matches[0]


def _document(path: Path) -> dict:
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= MAX_FILE:
        raise ValueError("Native Bambu profile file is unsafe or exceeds its size limit.")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Native Bambu profile must be an object.")
    return data


def resolve(bundle: Path, kind: str, name: str) -> dict:
    if kind not in PROFILE_NAMES:
        raise ValueError("Unapproved native Bambu profile category.")
    cache = {}

    def visit(current: str, stack: tuple[str, ...], *, included=False) -> dict:
        if current in stack or len(stack) >= MAX_DEPTH:
            raise ValueError("Native Bambu profile inheritance cycle or excess depth.")
        # Bambu's explicitly included G-code fragments are intentionally
        # type-less template JSON. Actual presets and inherited parents are
        # required to carry the exact native machine/process/filament type.
        key = (current, included)
        if key in cache:
            return dict(cache[key])
        doc = _document(_profile_path(bundle, kind, current))
        observed_type = doc.get("type")
        if (doc.get("name") != current or
                (observed_type != kind and not (included and observed_type is None))):
            raise ValueError("Native Bambu profile identity mismatch at " + kind + "/" + current
                             + " (type_ok=" + str(observed_type == kind or (included and observed_type is None))
                             + ", name_ok=" + str(doc.get("name") == current) + ").")
        parent = doc.get("inherits", "")
        if not isinstance(parent, str):
            raise ValueError("Invalid Bambu inheritance reference.")
        includes = doc.get("include", [])
        if not isinstance(includes, list) or any(not isinstance(x, str) for x in includes):
            raise ValueError("Invalid Bambu include references.")
        merged = visit(parent, stack + (current,)) if parent else {}
        for name_included in includes:
            merged.update(visit(name_included, stack + (current,), included=True))
        merged.update({field: value for field, value in doc.items()
                       if field not in {"inherits", "include"}})
        cache[key] = dict(merged)
        return merged

    result = visit(name, ())
    if "inherits" in result or "include" in result:
        raise ValueError("Unresolved Bambu profile lineage.")
    return result


def prepare(appdir: Path, output: Path):
    bundle = find_vendor_bundle(appdir)
    output = Path(output)
    if output.is_symlink() or (output.exists() and (
            not output.is_dir() or any(output.iterdir()))):
        raise ValueError("Refusing to overwrite native fixture output.")
    compiled = {}
    # Resolve everything before creating any output files.
    for kind, name in PROFILE_NAMES.items():
        compiled[kind] = resolve(bundle, kind, name)
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    hashes = {}
    for kind, value in compiled.items():
        raw = (json.dumps(value, separators=(",", ":"), ensure_ascii=False) + "\n").encode()
        if len(raw) > MAX_FILE:
            raise ValueError("Resolved native Bambu profile exceeds worker limits.")
        (output / (("printer" if kind == "machine" else kind) + ".json")).write_bytes(raw)
        hashes[kind] = hashlib.sha256(raw).hexdigest()
    return hashes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--appdir", type=Path, required=True,
                        help="Extracted, SHA-verified official Bambu AppImage root")
    parser.add_argument("--output", type=Path, required=True,
                        help="Fresh output directory for offline acceptance fixtures")
    args = parser.parse_args(argv)
    try:
        hashes = prepare(args.appdir, args.output)
    except (OSError, ValueError, UnicodeError, json.JSONDecodeError) as exc:
        parser.exit(1, "Bambu native fixture refused: " + str(exc) + "\n")
    print(json.dumps({"engine": "bambustudio",
                      "source": "bundled-official-profile-resources",
                      "profiles_sha256": hashes}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
