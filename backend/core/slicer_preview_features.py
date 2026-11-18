"""Engine-neutral prioritisation for a bounded whole-print G-code overview.

Only affects visual preview; complete G-code and single-layer inspection retain
every native extrusion move. Priority follows visual shell significance.
"""

def is_prime_tower_feature(feature):
    """Recognise explicit native tower labels without guessing G-code geometry."""
    name = str(feature or "").lower().replace("_", " ").replace("-", " ")
    return any(marker in name for marker in (
        "prime tower", "wipe tower", "purge tower", "prime pillar",
        "wipe pillar", "purge pillar",
    ))


def is_support_feature(feature):
    name = str(feature or "").lower().strip()
    return "support" in name and not is_prime_tower_feature(name)


def overview_priority(feature):
    name = str(feature or "").lower().strip()
    if is_prime_tower_feature(name):
        return 0
    if any(value in name for value in ("outer wall", "external perimeter", "external wall", "outer perimeter")):
        return 0
    if any(value in name for value in ("top surface", "top solid", "top skin", "top fill", "bridge", "overhang")):
        return 1
    if "support" in name and any(value in name for value in ("interface", "roof", "contact", "floor")):
        return 2
    if "support" in name:
        return 3
    if any(value in name for value in ("inner wall", "internal perimeter", "wall", "perimeter")):
        return 4
    if any(value in name for value in ("brim", "skirt", "prime tower", "wipe tower")):
        return 5
    if any(value in name for value in ("solid infill", "bottom solid", "bottom surface")):
        return 6
    if any(value in name for value in ("infill", "fill", "sparse")):
        return 7
    return 8


def overview_family(feature):
    """Coarse display groups; no model region can monopolise the preview.

    A categorical label is never used to infer missing geometry. This only
    distributes the bounded preview allowance among real G-code paths.
    """
    if is_prime_tower_feature(feature):
        return "tower"
    if is_support_feature(feature):
        return "support"
    name = str(feature or "").lower().strip()
    if any(part in name for part in ("outer wall", "external perimeter",
                                    "external wall", "outer perimeter")):
        return "shell"
    if any(part in name for part in ("top surface", "top solid", "top skin",
                                    "bottom surface", "bottom solid", "bridge")):
        return "skin"
    if any(part in name for part in ("inner wall", "internal perimeter",
                                    "inner perimeter", "internal wall")):
        return "inner"
    return "body"


def balanced_overview_indices(grouped, budget):
    """Choose diverse, order-preserving original moves within a per-layer budget.

    Keep every present structural group represented and distribute remaining
    capacity fairly. Handles prints with few or no supports/tower.
    """
    if budget <= 0:
        return []
    target_weights = {
        "tower": 0.18, "support": 0.20, "shell": 0.26,
        "skin": 0.16, "inner": 0.12, "body": 0.08,
    }
    present = {name: list(indices) for name, indices in grouped.items() if indices}
    if not present:
        return []
    # A minimum allocation stops small but important sections from vanishing.
    allocations = {
        name: min(len(indices), max(1, int(budget * target_weights[name])))
        for name, indices in present.items()
    }
    unused = budget - sum(allocations.values())
    while unused > 0:
        candidates = [name for name in present if allocations[name] < len(present[name])]
        if not candidates:
            break
        # Give space where the current sample density is lowest; do not
        # prioritise one type so strongly that other surfaces disappear.
        name = max(candidates, key=lambda n: (len(present[n]) /
                    max(1, allocations[n]), target_weights[n]))
        allocations[name] += 1
        unused -= 1
    selected = []
    for name, values in present.items():
        count = allocations[name]
        if len(values) <= count:
            selected.extend(values)
        else:
            selected.extend(values[min(len(values) - 1, (i * len(values)) // count)]
                            for i in range(count))
    return sorted(selected)
