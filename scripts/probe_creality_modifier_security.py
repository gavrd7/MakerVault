"""Security negatives for exact native Creality modifier project admission.

The same immutable public synthetic fixture is tested against the production
worker validator. No personal model, printer or network is accessed.
"""
import argparse
import io
import json
from pathlib import Path
import zipfile
from defusedxml import ElementTree as SafeET
from xml.etree import ElementTree as ET

from slicer_worker.creality_modifier_validation import validate_creality_modifier_project
from slicer_worker.three_mf_validation import validate_worker_3mf
from slicer_worker.runner import WorkerError


def repack(items):
    with io.BytesIO() as output:
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED,
                             allowZip64=False) as archive:
            for name, blob in items:
                archive.writestr(name, blob)
        return output.getvalue()


def probe(path):
    with zipfile.ZipFile(path) as archive:
        original = [(item.filename, archive.read(item)) for item in archive.infolist()]
    native = repack(original)
    assert validate_creality_modifier_project(native)
    try:
        validate_worker_3mf(native)
    except WorkerError:
        pass
    else:
        raise AssertionError("Native project bypassed generic 3MF admission.")
    cases = []
    cases.append(("extra-archive-member",
                  original + [("3D/foreign-script.bin", b"not permitted")]))
    cases.append(("duplicate-member",
                  original + [original[0]]))
    for field in ("3D/_rels/3dmodel.model.rels",
                  "Metadata/model_settings.config",
                  "Metadata/project_settings.config"):
        edited = dict(original)
        if field.endswith("3dmodel.model.rels"):
            edited[field] = edited[field].replace(
                b"/3D/Objects/object_1.model", b"/3D/Objects/evil.model")
        elif field.endswith("model_settings.config"):
            root = SafeET.fromstring(edited[field])
            parts = root.findall("./object/part")
            assert len(parts) >= 2
            parts[-1].set("subtype", "normal_part")
            edited[field] = ET.tostring(root)
        else:
            settings = json.loads(edited[field])
            settings["post_process_scripts"] = ["sh -c 'unsafe'"]
            edited[field] = json.dumps(settings).encode()
        cases.append((field, list(edited.items())))
    for description, changed in cases:
        try:
            validate_creality_modifier_project(repack(changed))
        except WorkerError:
            continue
        raise AssertionError("Creality modifier validator accepted " + description)
    print("Pinned Creality modifier archive security negatives: PASSED", len(cases))
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args()
    probe(args.project)


if __name__ == "__main__":
    main()
