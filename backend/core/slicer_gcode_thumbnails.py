"""Safe, shared PNG G-code thumbnail fallback for all slicer engines.

Never changes motion commands. Native slicer thumbnails are left untouched.
The fallback visualises deposited G-code paths (not the editable STL mesh).
"""
import base64
from io import BytesIO
import math
import re

from PIL import Image, ImageDraw

THUMBNAIL = re.compile(rb"(?im)^;\s*(?:thumbnail(?:_[A-Z]+)?|png|jpg)\s+begin\b")
FILAMENT_COLOURS = re.compile(r"^;\s*filament_colou?r\s*[:=]\s*(.+)$", re.I)
NUMBER = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)"
AXIS = re.compile(r"([XYZE])\s*(" + NUMBER + r")", re.I)
TOOL = re.compile(r"^T(\d{1,2})\s*(?:;.*)?$", re.I)
HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
MAX_LINES = 1_000_000
MAX_SEGMENTS = 180_000
MAX_RENDER_SEGMENTS = 48_000
SIZES = (96, 300)


def _rgb(colour):
    if not HEX.fullmatch(colour):
        return (115, 182, 226)
    return tuple(int(colour[pos:pos + 2], 16) for pos in (1, 3, 5))


def _paths(gcode):
    """Sample positive planar extrusion, excluding tagged prime/purge towers.

    Only explicit movement commands are interpreted. Relative XY/Z motion and
    ambiguous extrusion state are ignored, rather than fabricating geometry.
    """
    x = y = z = e = 0.0
    absolute_xy = True
    absolute_e = True
    current_tool = 0
    colours = []
    tagged_objects = "EXCLUDE_OBJECT_START" in gcode
    in_object = False
    segments = []
    observed = 0
    stride = 1
    for number, raw in enumerate(gcode.splitlines()):
        if number >= MAX_LINES:
            break
        line = raw.strip()
        if not line:
            continue
        if line.startswith(";"):
            match = FILAMENT_COLOURS.match(line)
            if match and not colours:
                colours = [value.strip().strip('"') for value in match.group(1).split(";")][:16]
            continue
        command = line.split(";", 1)[0].strip()
        upper = command.upper()
        if upper.startswith("EXCLUDE_OBJECT_START "):
            in_object = True
            continue
        if upper.startswith("EXCLUDE_OBJECT_END "):
            in_object = False
            continue
        selection = TOOL.fullmatch(command)
        if selection:
            current_tool = int(selection.group(1))
            continue
        code = upper.split(None, 1)[0]
        if code == "G90":
            absolute_xy = True
        elif code == "G91":
            absolute_xy = False
        elif code == "M82":
            absolute_e = True
        elif code == "M83":
            absolute_e = False
        elif code == "G92":
            params = dict((name.upper(), float(value)) for name, value in AXIS.findall(upper[3:]))
            x, y, z, e = (params.get("X", x), params.get("Y", y),
                          params.get("Z", z), params.get("E", e))
        elif code in {"G0", "G00", "G1", "G01"}:
            params = dict((name.upper(), float(value)) for name, value in AXIS.findall(upper[len(code):]))
            nx = params.get("X", x)
            ny = params.get("Y", y)
            nz = params.get("Z", z)
            if not absolute_xy:
                nx, ny, nz = (x + params.get("X", 0), y + params.get("Y", 0),
                              z + params.get("Z", 0))
            ne = params.get("E", e)
            extruded = (ne - e) if absolute_e else params.get("E", 0)
            if all(math.isfinite(val) for val in (x, y, z, nx, ny, nz, extruded)):
                if (absolute_xy and 0.000001 < extruded < 10000 and
                        all(abs(value) <= 10000 for value in (x, y, z, nx, ny, nz)) and
                        ("X" in params or "Y" in params) and
                        (not tagged_objects or in_object) and
                        abs(nx - x) + abs(ny - y) > 0.001):
                    observed += 1
                    if observed % stride == 0:
                        segments.append((x, y, nx, ny, nz, current_tool))
                    if len(segments) >= MAX_SEGMENTS:
                        # Re-sample the accumulated history and continue
                        # collecting across later layers. A hard first-N cap
                        # otherwise produces thumbnails missing their tops.
                        segments = segments[::2]
                        stride *= 2
            x, y, z = nx, ny, nz
            if "E" in params and absolute_e:
                e = ne
    if not segments:
        return [], []
    # Stable, deterministic overview of the complete toolpath.
    render_stride = max(1, math.ceil(len(segments) / MAX_RENDER_SEGMENTS))
    return segments[::render_stride], colours


def _render_png(segments, colours, size):
    """Render a transparent, supersampled isometric preview of deposited paths.

    The printer gets the original requested pixel dimensions. Drawing at a
    higher resolution first improves curved edges and thin mechanical details,
    especially on the 96-pixel file-browser preview. No bed/background pixels
    are baked in: the printer UI supplies its own background.
    """
    projected = []
    for x1, y1, x2, y2, z, tool in segments:
        projected.append(((x1 - y1) * 0.866, (x1 + y1) * 0.44 - z * 1.4,
                          (x2 - y2) * 0.866, (x2 + y2) * 0.44 - z * 1.4,
                          tool, z))
    minx = min(min(p[0], p[2]) for p in projected)
    maxx = max(max(p[0], p[2]) for p in projected)
    miny = min(min(p[1], p[3]) for p in projected)
    maxy = max(max(p[1], p[3]) for p in projected)
    # Size-independent framing avoids clipping tall or very flat parts.
    scale = (size * 0.84) / max(maxx - minx, maxy - miny, 0.01)
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2

    supersample = 3 if size <= 96 else 2
    canvas_size = size * supersample
    im = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    line_width = max(2, round(size / 130 * supersample))
    # A narrow dark keyline separates pale filament from a light printer UI.
    edge_width = line_width + max(1, supersample // 2)
    low_z = min(p[5] for p in projected)
    high_z = max(p[5] for p in projected)
    z_span = max(high_z - low_z, 0.01)
    # Render bottom first, top last; preserve distinct native tool colours.
    for x1, y1, x2, y2, tool, z in sorted(projected, key=lambda p: p[5]):
        points = (
            (size / 2 + (x1 - cx) * scale) * supersample,
            (size / 2 + (y1 - cy) * scale) * supersample,
            (size / 2 + (x2 - cx) * scale) * supersample,
            (size / 2 + (y2 - cy) * scale) * supersample,
        )
        colour = _rgb(colours[tool]) if tool < len(colours) else _rgb("")
        # Subtle height shading adds form without washing out the filament
        # palette or changing the model's assigned tool colours.
        light = 0.83 + 0.17 * ((z - low_z) / z_span)
        colour = tuple(max(0, min(255, round(component * light))) for component in colour)
        draw.line(points, fill=(39, 46, 53, 225), width=edge_width)
        draw.line(points, fill=(*colour, 255), width=line_width)
    im = im.resize((size, size), Image.Resampling.LANCZOS)
    output = BytesIO()
    im.save(output, format="PNG", optimize=True)
    return output.getvalue()

def add_gcode_thumbnails(raw):
    """Return (updated_bytes, sizes), preserving all printer commands exactly.

    Refuse binary/invalid text, unsupported G-code, already-thumbnailed files,
    and inputs for which no deposition could be visualised.
    """
    if not isinstance(raw, bytes) or not raw or b"\x00" in raw or THUMBNAIL.search(raw):
        return raw, ()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw, ()
    segments, colours = _paths(text)
    if not segments:
        return raw, ()
    blocks = []
    for size in SIZES:
        data = base64.b64encode(_render_png(segments, colours, size)).decode("ascii")
        lines = [data[index:index + 76] for index in range(0, len(data), 76)]
        blocks.append(("; thumbnail begin %dx%d %d\n" % (size, size, len(data))
                       + "".join("; " + line + "\n" for line in lines)
                       + "; thumbnail end\n").encode("ascii"))
    payload = b"\n" + b"\n".join(blocks) + b"\n"
    # Preserve the Creality HEAD_BLOCK_START at the beginning of the file,
    # inserting *after* its header instead of before it.
    match = re.search(rb"(?m)^; HEADER_BLOCK_END\r?\n", raw[:16_384])
    if match:
        return raw[:match.end()] + payload + raw[match.end():], SIZES
    return payload + raw, SIZES
