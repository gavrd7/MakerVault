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


def _pin_hints(node_type, obj):
    if node_type == "board":
        pinout = obj.pinout or {}
        if isinstance(pinout, dict):
            pins = pinout.get("pins") if isinstance(pinout.get("pins"), list) else None
            if pins:
                values = []
                for item in pins:
                    if isinstance(item, dict):
                        label = item.get("name") or item.get("label") or item.get("pin")
                    else:
                        label = item
                    if label:
                        values.append(str(label))
                return values[:100]
            return [str(key) for key in list(pinout)[:100] if key not in {"notes", "source"}]
    if node_type == "component":
        specs = obj.specifications or {}
        pins = specs.get("pins") or specs.get("pinout") or []
        if isinstance(pins, dict):
            return [str(key) for key in list(pins)[:100]]
        if isinstance(pins, list):
            values = []
            for item in pins[:100]:
                if isinstance(item, dict):
                    value = item.get("name") or item.get("label") or item.get("pin")
                else:
                    value = item
                if value:
                    values.append(str(value))
            return values
    if node_type == "inventory":
        if obj.board_id:
            return _pin_hints("board", obj.board)
        if obj.component_id:
            return _pin_hints("component", obj.component)
    return []


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
    clean_canvas = {
        "zoom": max(0.25, min(float(clean_canvas.get("zoom", 1) or 1), 3.0)),
        "show_grid": bool(clean_canvas.get("show_grid", True)),
    }
    return clean_nodes, clean_connections, clean_canvas


def wiring_warnings(nodes, connections):
    labels = {node["id"]: node.get("label") or node["id"] for node in nodes}
    endpoints = Counter()
    has_ground = False
    for edge in connections:
        for node_key, pin_key in (("from_node", "from_pin"), ("to_node", "to_pin")):
            endpoint = (edge[node_key], edge[pin_key].casefold())
            endpoints[endpoint] += 1
            if any(token in edge[pin_key].casefold() for token in ("gnd", "ground", "0v")):
                has_ground = True

    warnings = []
    for (node_id, pin), count in endpoints.items():
        if count > 1:
            warnings.append({
                "code": "shared-endpoint",
                "message": f"{labels.get(node_id, node_id)} pin {pin} is used by {count} connections; confirm the fan-out is intentional.",
            })
    if connections and not has_ground:
        warnings.append({
            "code": "no-common-ground",
            "message": "No ground/common connection is shown. Verify whether the devices in this circuit require a shared ground.",
        })
    return warnings[:30]


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
                }
            else:
                enriched["reference"] = None
        nodes.append(enriched)

    payload = {
        "id": str(diagram.id),
        "project_id": str(diagram.project_id),
        "name": diagram.name,
        "description": diagram.description,
        "node_count": len(diagram.nodes or []),
        "connection_count": len(diagram.connections or []),
        "revision": diagram.revision,
        "created_at": diagram.created_at.isoformat(),
        "updated_at": diagram.updated_at.isoformat(),
    }
    if detailed:
        payload.update({
            "nodes": nodes,
            "connections": diagram.connections or [],
            "canvas": diagram.canvas or {},
            "warnings": wiring_warnings(diagram.nodes or [], diagram.connections or []),
            "node_types": [{"value": value, "label": label} for value, label in NODE_TYPES.items()],
        })
    return payload
