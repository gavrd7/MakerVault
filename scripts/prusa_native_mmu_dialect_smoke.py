"""Determine real PrusaSlicer 2.9.7 MMU object-tool metadata semantics.

Offline G-code test under the immutable upstream vendor profile and binary.
All variants are *candidate research inputs*: do not enable the worker or UI.
"""
import hashlib
from pathlib import Path
import re
import subprocess
import sys
from tempfile import TemporaryDirectory

from slicer_worker.prusa_vendor_profiles import (
    flatten_prusa_vendor_preset, validate_flat_prusa_preset,
)
from slicer_worker.prusa_gcode_audit import WORD, audit_prusa_positive_e



def _spatial_tool_audit(gcode):
    """Separate model deposition from native MMU toolchange/tower extrusion."""
    tool = None
    x = y = None
    e = 0.
    relative = False
    counts = {0: {"left": 0, "right": 0, "outside": 0},
              1: {"left": 0, "right": 0, "outside": 0}}
    tower_labels = 0
    for line in gcode.decode("utf-8").splitlines():
        if "wipe tower" in line.lower() or "prime tower" in line.lower():
            tower_labels += 1
        cmd = line.split(";", 1)[0].strip()
        if not cmd:
            continue
        op = cmd.split(None, 1)[0].upper()
        if op in ("T0", "T1"):
            tool = int(op[1:])
        words = {k.upper(): float(v) for k, v in WORD.findall(cmd)}
        if op == "M82":
            relative = False
        elif op == "M83":
            relative = True
        elif op == "G92":
            e = words.get("E", e)
        elif op in ("G0", "G00", "G1", "G01"):
            x = words.get("X", x)
            y = words.get("Y", y)
            if "E" in words:
                delta = words["E"] if relative else words["E"] - e
                e = e + words["E"] if relative else words["E"]
                if (delta > 1e-6 and tool in counts and
                        x is not None and y is not None):
                    zone = ("left" if 79 <= x <= 101 and 94 <= y <= 116 else
                            "right" if 149 <= x <= 171 and 94 <= y <= 116 else
                            "outside")
                    counts[tool][zone] += 1
    return {"by_tool": counts, "tower_comment_lines": tower_labels}



def _research_xl_two_tool(binary, vendor, source_digest, directory, work):
    """Independently investigate XL *physical* T0/T1, not MMU changer slots.

    Research only: we never permit an actual printer upload or guess an XL
    machine's tool offsets/start G-code from its name.
    """
    label = "Original Prusa XL - 2T 0.4 nozzle"
    try:
        raw = flatten_prusa_vendor_preset(vendor, kind="printer", name=label,
                                          expected_sha256=source_digest)
        converted = []
        for line in raw.decode("utf-8").splitlines():
            converted.append("binary_gcode = 0" if line.split("=", 1)[0].strip()
                             == "binary_gcode" else line)
        native = ("\n".join(converted) + "\n").encode()
        identity = validate_flat_prusa_preset(native, kind="printer")
        tools = identity["nozzle_diameter"].split(",")
        assert len(tools) == 2 and identity.get(
            "single_extruder_multi_material", "0") in ("", "0", "false")
    except (ValueError, AssertionError) as error:
        print("XL native dual-head source profile unavailable:", str(error))
        return
    machine = work / "xl-printer.ini"
    machine.write_bytes(native)
    flags = ["--load", str(machine),
             "--load", str(work / "filament.ini"),
             "--load", str(work / "print.ini")]
    model = str(Path(directory)/"object.3mf")
    output = work / "xl-object.gcode"
    result = subprocess.run([binary, *flags, "--export-gcode", "--dont-arrange",
                             "--output", str(output), model],
                            cwd=work, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=300)
    if result.returncode or not output.is_file():
        print("XL native physical T0/T1 feasibility blocked, exit", result.returncode)
        return
    payload = output.read_bytes()
    audited = audit_prusa_positive_e(payload)
    spatial = _spatial_tool_audit(payload)["by_tool"]
    correct = (
        spatial[0]["left"] > 100 and spatial[1]["right"] > 100 and
        spatial[0]["right"] < 5 and spatial[1]["left"] < 5)
    print("XL REAL CLI physical two-head model deposition",
          "positive_e_moves", audited["positive_e_moves"], spatial,
          "correct_tools", correct)
    if correct:
        print("PASS: pinned Prusa 2.9.7 native XL 2-head T0/T1 toolpath "
              "assignment. This is not physical tool-change or upload approval.")



def main(binary, source, directory):
    raw = Path(source).read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    printer_name = "Original Prusa i3 MK3S & MK3S+ MMU3"
    vendor_profiles = (
        ("printer", printer_name),
        ("filament", "Generic PLA"),
        ("print", "0.20mm NORMAL"),
    )
    with TemporaryDirectory(prefix="prusa-mmu-dialect-") as tmp:
        root = Path(tmp)
        native = []
        for kind,name in vendor_profiles:
            data = flatten_prusa_vendor_preset(raw, kind=kind,
                                               name=name, expected_sha256=digest)
            parsed = validate_flat_prusa_preset(data, kind=kind)
            if kind == "printer":
                assert parsed.get("single_extruder_multi_material") == "1"
                assert len(parsed["nozzle_diameter"].split(",")) == 5
                print("PINNED", printer_name, "5 virtual nozzles and MMU changer")
            file = root / (kind + ".ini")
            file.write_bytes(data)
            native.extend(["--load", str(file)])
        # Deliberately different per-tool temperatures exercise native vector
        # routing rather than merely repeating one filament preset for all tools.
        # Keep this an offline fixture; production owner-scoped routing is separate.
        filament = root / "filament.ini"
        original = filament.read_bytes()
        settings = validate_flat_prusa_preset(original, kind="filament")
        for key in ("temperature", "first_layer_temperature"):
            assert key in settings, "Pinned Generic PLA missing " + key
        # Import the exact application compiler from the read-only backend
        # mount in the native acceptance container.
        from core.slicer_prusa_filament_palette import compile_prusa_filament_palette
        profiles = []
        for temperature in (205,220,205,205,205):
            values = dict(settings)
            for key in ("temperature", "first_layer_temperature"):
                values[key] = str(temperature)
            profiles.append("".join(f"{k} = {v}\n" for k,v in values.items()).encode())
        filament.write_bytes(compile_prusa_filament_palette(
            (root / "printer.ini").read_bytes(), profiles))
        try:
            output = root / "distinct-material-temperatures.gcode"
            subprocess.run([binary, *native, "--export-gcode", "--dont-arrange",
                            "--output", str(output), str(Path(directory)/"trusted.3mf")],
                           cwd=root, check=True, timeout=300)
            data = output.read_bytes()
            assert audit_prusa_positive_e(data)["positive_e_moves"] > 100
            spatial = _spatial_tool_audit(data)["by_tool"]
            assert spatial[0]["left"] > 100 and spatial[1]["right"] > 100, spatial
            # Require actual executable heater commands, not a config footer.
            temperatures = set()
            for line in data.decode("utf-8").splitlines():
                command = line.split(";", 1)[0].strip()
                if re.match(r"^M10[49](?:\\s|$)", command):
                    match = re.search(r"(?:^|\\s)S(\\d+)(?:\\s|$)", command)
                    if match:
                        temperatures.add(int(match.group(1)))
            assert {205, 220}.issubset(temperatures), temperatures
            print("PASS: native MMU distinct filament temperature vector",
                  sorted(temperatures), spatial)
        finally:
            filament.write_bytes(original)
        winners = []
        for dialect in ("object", "volume", "both", "trusted"):
            model = str(Path(directory) / (dialect + ".3mf"))
            dest = root / (dialect + ".gcode")
            command = [binary, *native, "--export-gcode", "--dont-arrange",
                       "--output", str(dest), model]
            result = subprocess.run(command, cwd=root, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, timeout=300)
            if result.returncode != 0 or not dest.exists():
                print("CANDIDATE", dialect, "native CLI did not slice",
                      "code", result.returncode)
                continue
            data = dest.read_bytes()
            audited = audit_prusa_positive_e(data)
            tools = {int(v): len(re.findall(rb"(?m)^T"+v+rb"(?:[ ;\r\n]|$)", data))
                     for v in (b"0",b"1",b"2",b"3",b"4")}
            meaningful = tools[0] > 0 and tools[1] > 0
            print("CANDIDATE", dialect, "extrusion", audited["positive_e_moves"],
                  "selected_tools", tools, "two_tool_selection", meaningful,
                  "gcode_bytes", len(data))
            spatial = _spatial_tool_audit(data)
            print("MMU native spatial tool deposition", dialect, spatial)
            correct = (
                spatial["by_tool"][0]["left"] > 100 and
                spatial["by_tool"][1]["right"] > 100 and
                spatial["by_tool"][0]["right"] < 5 and
                spatial["by_tool"][1]["left"] < 5)
            if meaningful and correct:
                winners.append(dialect)
        if not winners:
            raise RuntimeError("No native Prusa MMU3 project variant proved distinct correct tool deposition.")
        print("PASS: native upstream Prusa 2.9.7 MMU3 selected and deposited the correct tools in distinct model regions for", winners)
        print("NOTE: dual tool selection is NOT sufficient to approve purge, hardware, colours or worker admission.")
        _research_xl_two_tool(binary, raw, digest, directory, root)


if __name__ == "__main__":
    main(*sys.argv[1:])
