from __future__ import annotations

import math
import re
from collections import Counter
from uuid import UUID

from django.core.exceptions import ValidationError

from .models import BoardModel, ComponentModel, InventoryItem, WiringDiagram


NODE_TYPES = {
    "board": "Board catalogue",
    "component": "Component catalogue",
    "inventory": "Inventory item",
    "custom": "Custom node",
}

POWER_NAMES = {"VCC", "VDD", "VIN", "VBUS", "V+", "+V", "3V3", "3.3V", "5V", "12V", "24V"}
GROUND_NAMES = {"GND", "GROUND", "AGND", "DGND", "PGND", "0V", "VSS"}
INPUT_WORDS = {"IN", "INPUT", "RX", "MISO"}
OUTPUT_WORDS = {"OUT", "OUTPUT", "TX", "MOSI"}
POWER_ROLES = {"power", "power_input", "power_output"}
GROUND_ROLES = {"ground"}
INPUT_ROLES = {"input", "digital_input", "analog_input", "power_input", "uart_rx", "spi_miso"}
OUTPUT_ROLES = {"output", "digital_output", "analog_output", "power_output", "uart_tx", "spi_mosi"}


def _clean_text(value, max_length):
    return re.sub(r"\s+", " ", str(value or "").strip())[:max_length]


def _node_id(value):
    value = _clean_text(value, 80)
    if not value or not re.fullmatch(r"[A-Za-z0-9._:-]+", value):
        raise ValidationError({"nodes": "Each wiring node needs a stable alphanumeric ID."})
    return value


def _connection_id(value):
    value = _clean_text(value, 80)
    if not value or not re.fullmatch(r"[A-Za-z0-9._:-]+", value):
        raise ValidationError({"connections": "Each wiring connection needs a stable alphanumeric ID."})
    return value


def _coordinate(value, field):
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({"nodes": f"Node {field} must be numeric."}) from exc
    if not math.isfinite(number) or number < -10000 or number > 10000:
        raise ValidationError({"nodes": f"Node {field} is outside the supported canvas range."})
    return round(number, 2)


def _uuid(value, field):
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValidationError({field: "Referenced catalogue/inventory ID is invalid."}) from exc


def _resolve_reference(owner, node_type, reference_id):
    if node_type == "board":
        obj = BoardModel.objects.select_related("manufacturer").filter(pk=reference_id).first()
        if not obj:
            raise ValidationError({"nodes": "A referenced board no longer exists."})
        return obj
    if node_type == "component":
        obj = ComponentModel.objects.select_related("category").filter(pk=reference_id).first()
        if not obj:
            raise ValidationError({"nodes": "A referenced component no longer exists."})
        return obj
    if node_type == "inventory":
        obj = InventoryItem.objects.filter(owner=owner, pk=reference_id).select_related(
            "board__manufacturer", "component"
        ).first()
        if not obj:
            raise ValidationError({"nodes": "A referenced inventory item was not found for this user."})
        return obj
    return None


def _reference_label(node_type, obj):
    if node_type == "board":
        return str(obj)
    if node_type == "component":
        return obj.name
    if node_type == "inventory":
        return obj.display_name
    return ""


def _reference_subtitle(node_type, obj):
    if node_type == "board":
        return " · ".join(filter(None, [obj.family, obj.mcu]))
    if node_type == "component":
        return obj.category.name if obj.category else "Component"
    if node_type == "inventory":
        return f"{obj.inventory_id} · {obj.get_status_display()}"
    return ""


def _raw_pin_entries(node_type, obj):
    if node_type == "inventory":
        if obj.board_id:
            return _raw_pin_entries("board", obj.board)
        if obj.component_id:
            return _raw_pin_entries("component", obj.component)
        return []
    data = obj.pinout if node_type == "board" else (obj.specifications or {}).get("pins") or (obj.specifications or {}).get("pinout")
    if not data:
        return []
    if isinstance(data, dict):
        nested = data.get("pins")
        if isinstance(nested, list):
            return nested
        entries = []
        for name, value in data.items():
            if name in {"notes", "source"}:
                continue
            if isinstance(value, dict):
                entries.append({"name": name, **value})
            else:
                entries.append({"name": name, "description": str(value or "")})
        return entries
    return data if isinstance(data, list) else []


def _normalise_role(value):
    text = _clean_text(value, 60).lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "gnd": "ground", "vss": "ground", "supply_ground": "ground",
        "vcc": "power", "vdd": "power", "supply": "power",
        "power_in": "power_input", "supply_input": "power_input",
        "power_out": "power_output", "supply_output": "power_output",
        "gpio": "gpio", "io": "gpio",
        "adc": "analog_input", "dac": "analog_output",
        "rx": "uart_rx", "tx": "uart_tx",
        "sda": "i2c_sda", "scl": "i2c_scl",
        "mosi": "spi_mosi", "miso": "spi_miso", "sck": "spi_clock", "clk": "clock",
    }
    return aliases.get(text, text)


def _float_or_none(value):
    if value is None or value == "":
        return None
    try:
        number = float(str(value).lower().replace("v", "").strip())
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _voltage_from_name(name):
    upper = str(name or "").upper().replace(" ", "")
    match = re.fullmatch(r"(\d+(?:\.\d+)?)V", upper)
    if match:
        return float(match.group(1))
    match = re.fullmatch(r"(\d+)V(\d+)", upper)
    if match:
        return float(f"{match.group(1)}.{match.group(2)}")
    return None


def _infer_role(name):
    upper = re.sub(r"[^A-Z0-9.+-]", "", str(name or "").upper())
    if upper in GROUND_NAMES or upper.endswith("GND"):
        return "ground", "name"
    if upper in POWER_NAMES or _voltage_from_name(upper) is not None or re.fullmatch(r"(VCC|VDD|VIN|VBUS)[0-9.]*", upper):
        return "power", "name"
    if upper in {"SDA", "I2CSDA"} or upper.endswith("SDA"):
        return "i2c_sda", "name"
    if upper in {"SCL", "I2CSCL"} or upper.endswith("SCL"):
        return "i2c_scl", "name"
    if upper in {"TX", "TXD", "UARTTX"} or upper.endswith("_TX"):
        return "uart_tx", "name"
    if upper in {"RX", "RXD", "UARTRX"} or upper.endswith("_RX"):
        return "uart_rx", "name"
    if upper in {"MOSI", "COPI"}:
        return "spi_mosi", "name"
    if upper in {"MISO", "CIPO"}:
        return "spi_miso", "name"
    if upper in {"SCK", "SCLK", "SPI_CLK", "SPICLK"}:
        return "spi_clock", "name"
    if re.fullmatch(r"(GPIO|IO|D)\d+", upper):
        return "gpio", "name"
    if re.fullmatch(r"(ADC|A)\d+", upper):
        return "analog_input", "name"
    if upper in INPUT_WORDS:
        return "input", "name"
    if upper in OUTPUT_WORDS:
        return "output", "name"
    return "unknown", "unknown"


def _pin_metadata_from_entry(entry):
    if isinstance(entry, dict):
        name = entry.get("name") or entry.get("label") or entry.get("pin") or ""
        role_value = entry.get("role") or entry.get("type") or entry.get("electrical_role") or entry.get("function")
        role = _normalise_role(role_value) if role_value else ""
        source = "catalogue" if role else "unknown"
        if not role:
            role, source = _infer_role(name)
        voltage = _float_or_none(entry.get("voltage") or entry.get("voltage_v") or entry.get("logic_voltage"))
        min_voltage = _float_or_none(entry.get("min_voltage") or entry.get("voltage_min") or entry.get("min_voltage_v"))
        max_voltage = _float_or_none(entry.get("max_voltage") or entry.get("voltage_max") or entry.get("max_voltage_v"))
        if voltage is None:
            voltage = _voltage_from_name(name)
            if voltage is not None and source == "unknown":
                source = "name"
        return {
            "name": str(name),
            "role": role or "unknown",
            "voltage": voltage,
            "min_voltage": min_voltage,
            "max_voltage": max_voltage,
            "source": source,
        }
    name = str(entry or "")
    role, source = _infer_role(name)
    return {"name": name, "role": role, "voltage": _voltage_from_name(name), "min_voltage": None, "max_voltage": None, "source": source}


def _pin_metadata(node_type, obj):
    return [_pin_metadata_from_entry(entry) for entry in _raw_pin_entries(node_type, obj) if (entry if not isinstance(entry, dict) else entry.get("name") or entry.get("label") or entry.get("pin"))]


def _pin_hints(node_type, obj):
    return [pin["name"] for pin in _pin_metadata(node_type, obj)][:100]


def _node_pin_profiles(owner, nodes):
    profiles = {}
    for node in nodes:
        if node.get("type") == "custom" or not node.get("reference_id"):
            profiles[node["id"]] = {}
            continue
        try:
            obj = _resolve_reference(owner, node["type"], node["reference_id"])
        except ValidationError:
            profiles[node["id"]] = {}
            continue
        profiles[node["id"]] = {pin["name"].casefold(): pin for pin in _pin_metadata(node["type"], obj)}
    return profiles


def normalise_wiring(owner, nodes, connections, canvas=None):
    if not isinstance(nodes, list):
        raise ValidationError({"nodes": "Wiring nodes must be a list."})
    if not isinstance(connections, list):
        raise ValidationError({"connections": "Wiring connections must be a list."})
    if len(nodes) > 250:
        raise ValidationError({"nodes": "A wiring diagram can contain at most 250 nodes."})
    if len(connections) > 1000:
        raise ValidationError({"connections": "A wiring diagram can contain at most 1000 connections."})

    clean_nodes = []
    seen_nodes = set()
    for raw in nodes:
        if not isinstance(raw, dict):
            raise ValidationError({"nodes": "Each wiring node must be an object."})
        node_id = _node_id(raw.get("id"))
        if node_id in seen_nodes:
            raise ValidationError({"nodes": f"Duplicate node ID: {node_id}."})
        seen_nodes.add(node_id)
        node_type = _clean_text(raw.get("type"), 24).lower()
        if node_type not in NODE_TYPES:
            raise ValidationError({"nodes": f"Unsupported wiring node type: {node_type or 'blank'}."})

        reference_id = ""
        reference = None
        if node_type != "custom":
            reference_id = _uuid(raw.get("reference_id"), "nodes")
            reference = _resolve_reference(owner, node_type, reference_id)

        label = _clean_text(raw.get("label"), 180) or _reference_label(node_type, reference)
        if not label:
            raise ValidationError({"nodes": "Custom wiring nodes require a label."})

        clean_nodes.append({
            "id": node_id,
            "type": node_type,
            "reference_id": reference_id,
            "label": label,
            "x": _coordinate(raw.get("x", 24), "x"),
            "y": _coordinate(raw.get("y", 24), "y"),
            "notes": str(raw.get("notes") or "").strip()[:2000],
        })

    clean_connections = []
    seen_connections = set()
    seen_edges = set()
    for raw in connections:
        if not isinstance(raw, dict):
            raise ValidationError({"connections": "Each wiring connection must be an object."})
        connection_id = _connection_id(raw.get("id"))
        if connection_id in seen_connections:
            raise ValidationError({"connections": f"Duplicate connection ID: {connection_id}."})
        seen_connections.add(connection_id)

        from_node = _node_id(raw.get("from_node"))
        to_node = _node_id(raw.get("to_node"))
        if from_node not in seen_nodes or to_node not in seen_nodes:
            raise ValidationError({"connections": "Connection endpoints must reference nodes in this diagram."})
        from_pin = _clean_text(raw.get("from_pin"), 120)
        to_pin = _clean_text(raw.get("to_pin"), 120)
        if not from_pin or not to_pin:
            raise ValidationError({"connections": "Both ends of a connection require a pin/terminal label."})
        if from_node == to_node and from_pin.casefold() == to_pin.casefold():
            raise ValidationError({"connections": "A connection cannot join a pin to itself."})

        canonical = tuple(sorted([
            f"{from_node}:{from_pin.casefold()}",
            f"{to_node}:{to_pin.casefold()}",
        ]))
        if canonical in seen_edges:
            raise ValidationError({"connections": "The same pin-to-pin connection is already present."})
        seen_edges.add(canonical)

        colour = _clean_text(raw.get("color"), 20)
        if colour and not re.fullmatch(r"#[0-9A-Fa-f]{6}", colour):
            colour = ""

        clean_connections.append({
            "id": connection_id,
            "from_node": from_node,
            "from_pin": from_pin,
            "to_node": to_node,
            "to_pin": to_pin,
            "label": _clean_text(raw.get("label"), 180),
            "color": colour,
            "notes": str(raw.get("notes") or "").strip()[:2000],
        })

    clean_canvas = canvas if isinstance(canvas, dict) else {}
    try:
        zoom = float(clean_canvas.get("zoom", 1) or 1)
    except (TypeError, ValueError):
        zoom = 1.0
    if not math.isfinite(zoom):
        zoom = 1.0
    clean_canvas = {
        "zoom": max(0.25, min(zoom, 3.0)),
        "show_grid": bool(clean_canvas.get("show_grid", True)),
    }
    return clean_nodes, clean_connections, clean_canvas


def _diagnostic(severity, code, message, edge=None):
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "connection_id": edge.get("id") if edge else "",
    }


def _endpoint_text(label, pin):
    return f"{label} · {pin}"


def _voltage_range(pin):
    if pin.get("voltage") is not None:
        return pin["voltage"], pin["voltage"]
    return pin.get("min_voltage"), pin.get("max_voltage")


def _connection_diagnostics(edge, labels, profiles):
    # Always fall back to conservative label inference when the catalogue does not
    # contain this exact pin. Users may legitimately type a pin that is missing
    # from an incomplete catalogue entry; obvious names such as GND/VCC/5V are
    # still high-confidence enough to sanity-check.
    a = profiles.get(edge["from_node"], {}).get(edge["from_pin"].casefold()) or _pin_metadata_from_entry(edge["from_pin"])
    b = profiles.get(edge["to_node"], {}).get(edge["to_pin"].casefold()) or _pin_metadata_from_entry(edge["to_pin"])
    a_text = _endpoint_text(labels.get(edge["from_node"], edge["from_node"]), edge["from_pin"])
    b_text = _endpoint_text(labels.get(edge["to_node"], edge["to_node"]), edge["to_pin"])
    ar, br = a["role"], b["role"]
    diagnostics = []

    if (ar in GROUND_ROLES and br in POWER_ROLES) or (br in GROUND_ROLES and ar in POWER_ROLES):
        diagnostics.append(_diagnostic("error", "ground-power-conflict", f"Ground is connected to a power pin: {a_text} ↔ {b_text}.", edge))
        return diagnostics

    if ar == "i2c_sda" and br == "i2c_scl" or ar == "i2c_scl" and br == "i2c_sda":
        diagnostics.append(_diagnostic("warning", "i2c-line-mismatch", f"I²C SDA is connected to SCL: {a_text} ↔ {b_text}.", edge))
    if ar == "uart_tx" and br == "uart_tx":
        diagnostics.append(_diagnostic("warning", "uart-tx-tx", f"Two UART TX pins are connected: {a_text} ↔ {b_text}. Usually TX should connect to RX.", edge))
    if ar == "uart_rx" and br == "uart_rx":
        diagnostics.append(_diagnostic("warning", "uart-rx-rx", f"Two UART RX pins are connected: {a_text} ↔ {b_text}. Usually RX should connect to TX.", edge))
    if ar == "spi_mosi" and br == "spi_miso" or ar == "spi_miso" and br == "spi_mosi":
        diagnostics.append(_diagnostic("warning", "spi-data-mismatch", f"SPI MOSI/COPI is connected to MISO/CIPO: {a_text} ↔ {b_text}. Verify the intended bus wiring.", edge))

    if ar in OUTPUT_ROLES and br in OUTPUT_ROLES:
        diagnostics.append(_diagnostic("warning", "output-output", f"Two output pins are connected: {a_text} ↔ {b_text}. Verify neither side is driving against the other.", edge))

    for source, target, source_text, target_text in ((a, b, a_text, b_text), (b, a, b_text, a_text)):
        source_v = source.get("voltage")
        target_min, target_max = _voltage_range(target)
        if source_v is None or source["role"] not in {"power", "power_output"}:
            continue
        if target_max is not None and source_v > target_max + 0.05:
            diagnostics.append(_diagnostic("error", "overvoltage", f"{source_text} supplies {source_v:g} V but {target_text} is rated to a maximum of {target_max:g} V.", edge))
        elif target_min is not None and source_v < target_min - 0.05:
            diagnostics.append(_diagnostic("warning", "undervoltage", f"{source_text} supplies {source_v:g} V but {target_text} expects at least {target_min:g} V.", edge))

    known = ar != "unknown" and br != "unknown"
    if not diagnostics and known:
        compatible = (
            ar == br
            or {ar, br} <= {"gpio", "input", "output", "digital_input", "digital_output"}
            or {ar, br} == {"uart_tx", "uart_rx"}
            or ar == br == "i2c_sda"
            or ar == br == "i2c_scl"
            or ar == br == "spi_clock"
            or (ar in POWER_ROLES and br in POWER_ROLES)
            or (ar in GROUND_ROLES and br in GROUND_ROLES)
        )
        if compatible:
            diagnostics.append(_diagnostic("valid", "compatible", f"Compatible connection: {a_text} ↔ {b_text}.", edge))
    return diagnostics


def wiring_diagnostics(owner, nodes, connections):
    labels = {node["id"]: node.get("label") or node["id"] for node in nodes}
    profiles = _node_pin_profiles(owner, nodes)
    endpoints = Counter()
    diagnostics = []
    has_ground = False

    for edge in connections:
        diagnostics.extend(_connection_diagnostics(edge, labels, profiles))
        for node_key, pin_key in (("from_node", "from_pin"), ("to_node", "to_pin")):
            endpoint = (edge[node_key], edge[pin_key].casefold())
            endpoints[endpoint] += 1
            pin = profiles.get(edge[node_key], {}).get(edge[pin_key].casefold()) or _pin_metadata_from_entry(edge[pin_key])
            if pin["role"] == "ground":
                has_ground = True

    for (node_id, pin), count in endpoints.items():
        if count > 1:
            diagnostics.append(_diagnostic(
                "advisory",
                "shared-endpoint",
                f"{labels.get(node_id, node_id)} pin {pin} is used by {count} connections; confirm the fan-out is intentional.",
            ))
    if connections and not has_ground:
        diagnostics.append(_diagnostic(
            "advisory",
            "no-common-ground",
            "No ground/common connection is shown. Verify whether the devices in this circuit require a shared ground.",
        ))

    rank = {"error": 0, "warning": 1, "advisory": 2, "valid": 3, "unknown": 4}
    diagnostics.sort(key=lambda item: (rank.get(item["severity"], 9), item["message"]))
    return diagnostics[:100]


def _diagnostic_summary(diagnostics, connection_ids):
    counts = Counter(item["severity"] for item in diagnostics)
    by_connection = {}
    for connection_id in connection_ids:
        relevant = [item for item in diagnostics if item.get("connection_id") == connection_id]
        if not relevant:
            by_connection[connection_id] = "unknown"
            continue
        severity_order = {"error": 0, "warning": 1, "advisory": 2, "valid": 3, "unknown": 4}
        by_connection[connection_id] = min(relevant, key=lambda item: severity_order.get(item["severity"], 9))["severity"]
    return {
        "counts": {key: counts.get(key, 0) for key in ("error", "warning", "advisory", "valid")},
        "connections": by_connection,
    }


def serialise_wiring_diagram(diagram: WiringDiagram, *, detailed=False):
    nodes = []
    for node in diagram.nodes or []:
        enriched = dict(node)
        if node.get("type") != "custom" and node.get("reference_id"):
            try:
                ref = _resolve_reference(diagram.owner, node["type"], node["reference_id"])
            except ValidationError:
                ref = None
            if ref is not None:
                enriched["reference"] = {
                    "label": _reference_label(node["type"], ref),
                    "subtitle": _reference_subtitle(node["type"], ref),
                    "pin_hints": _pin_hints(node["type"], ref),
                    "pins": _pin_metadata(node["type"], ref),
                }
            else:
                enriched["reference"] = None
        nodes.append(enriched)

    payload = {
        "id": str(diagram.id),
        "project_id": str(diagram.project_id) if diagram.project_id else "",
        "project_name": diagram.project.name if diagram.project_id else "",
        "name": diagram.name,
        "description": diagram.description,
        "node_count": len(diagram.nodes or []),
        "connection_count": len(diagram.connections or []),
        "revision": diagram.revision,
        "created_at": diagram.created_at.isoformat(),
        "updated_at": diagram.updated_at.isoformat(),
    }
    if detailed:
        diagnostics = wiring_diagnostics(diagram.owner, diagram.nodes or [], diagram.connections or [])
        payload.update({
            "nodes": nodes,
            "connections": diagram.connections or [],
            "canvas": diagram.canvas or {},
            "diagnostics": diagnostics,
            "diagnostic_summary": _diagnostic_summary(diagnostics, [edge["id"] for edge in diagram.connections or []]),
            "warnings": [item for item in diagnostics if item["severity"] in {"error", "warning", "advisory"}],
            "node_types": [{"value": value, "label": label} for value, label in NODE_TYPES.items()],
        })
    return payload
