"""Conservative catalogue narrowing to a user's selected printer model.

Name-based matches are discovery hints only, never compatibility approval.
"""
import re

_GENERIC_WORDS = {
    "creality", "bambu", "bambulab", "prusa", "anycubic", "elegoo",
    "printer", "machine", "series", "combo", "3d", "fdm",
}
_VARIANTS = {"max", "plus", "pro", "mini", "se", "neo", "v2", "v3", "ultra"}


def _words(value):
    return re.findall(r"[a-z0-9]+", str(value or "").casefold())


def _model_words(model):
    tokens = [w for w in _words(model) if w not in _GENERIC_WORDS]
    # Avoid guessing when the printer has no useful model identifier.
    return tokens if tokens else []


def profile_matches_printer(name, kind, model):
    """Narrow explicit machine variants; retain unqualified generic presets."""
    expected = _model_words(model)
    if not expected:
        return True
    raw = str(name or "")
    words = _words(raw)
    match = all(w in words for w in expected)

    if kind == "printer":
        if not match:
            return False
        # K1 is not K1 Max, K2 is not K2 Plus, etc.
        first = words.index(expected[0])
        tail = words[first + 1:first + 3]
        return not any(w in _VARIANTS and w not in expected for w in tail)

    if "@" in raw:
        qualifier = _words(raw.rsplit("@", 1)[1])
        if qualifier == ["base"]:
            return True  # Native generic filament root; not a K2-only claim.
        if not all(w in qualifier for w in expected):
            return False
        # Preserve exact model variants: K1 is not K1 SE/Max/Plus or
        # K1_CFS-C. The selected model may itself include those variants.
        first = qualifier.index(expected[0])
        tail = qualifier[first + 1:first + 4]
        return not any(w in _VARIANTS | {"cfs", "c"} and w not in expected for w in tail)

    # Model-coded presets without an @ suffix may be machine-specific.
    # These conventional identifiers should not leak into a different
    # machine's suggested results. Other unqualified presets remain visible
    # as candidates, not as verified compatible profiles.
    identifiers = [w for w in words if re.fullmatch(
        r"(?:k[12](?:c)?|mk[234]|x1c?|p1[ps]|a1|ender\d+)", w
    )]
    if identifiers and not any(w in expected for w in identifiers):
        return False
    return True


def narrow_catalogue(entries, kind, model):
    return [(name, path) for name, path in entries
            if profile_matches_printer(name, kind, model)]

def models_from_machines(entries):
    """Unique catalogue model labels, stripping only nozzle-size suffixes."""
    models = set()
    for name, _path in entries:
        model = re.sub(r"\s*\(?\d+(?:[.]\d+)?\s*(?:mm\s*)?nozzle\)?\s*$", "", name, flags=re.I).strip()
        if model:
            models.add(model)
    return sorted(models, key=str.casefold)


def fuzzy_name_match(name, query):
    """All search tokens may appear anywhere, irrespective of their order."""
    # A decimal layer height in official preset names is commonly followed
    # immediately by "mm" (e.g. "0.20mm Standard"). Tokenise the unit
    # separately so searches for "0.20", "0.20mm" and "0.20 mm" agree.
    # Keep whole-token model matching unchanged (K1 must not match K10).
    separate_units = lambda text: re.sub(r"(?<=\\d)mm\\b", " mm", str(text or ""), flags=re.I)
    terms = _words(separate_units(query))
    words = _words(separate_units(name))
    if not terms:
        return False
    # Exact token matching avoids treating K1 as K10 or K1 Max as K1.
    return all(term in words or (len(term) >= 4 and any(
        word.startswith(term) for word in words)) for term in terms)


def slot_filament_catalogue(entries, printer_model, product="", material="", manufacturer="", catalogue_vendor=""):
    """Rank user-selected printer filament candidates BEFORE truncating results.

    This is discovery only. Do not misrepresent a similarly named preset as
    compatible for printing. Internal @base/@BBL variants and other printer
    families must never appear as direct slot import choices.
    """
    expected = _model_words(printer_model)
    model = expected[0] if expected else ""
    variant = set(expected[1:])
    vendor = _words(manufacturer)
    product_words = _words(product)
    material_words = _words(material)
    ranked = []
    for name, path in entries:
        raw = str(name or "")
        if "@" not in raw:
            continue  # A machine-unspecified root is not a direct filament preset.
        title, qualifier = raw.rsplit("@", 1)
        q = _words(qualifier)
        if not q or q == ["base"] or path.split("/")[1:2] == ["base"]:
            continue
        if catalogue_vendor == "OrcaFilamentLibrary":
            folder = _words(path.split("/")[1] if len(path.split("/")) > 2 else "")
            # Filament-library manufacturer folders are authoritative about
            # which brand published this preset; do not recommend Bambu/BETA
            # for an unknown-brand Creality spool simply because both say PLA.
            printer_brand = "creality" if "creality" in _words(printer_model) else (
                "bambu" if "bambu" in _words(printer_model) else "")
            acceptable = {"generic", "system", printer_brand}
            acceptable.update(vendor)
            if folder and not (set(folder) & acceptable):
                continue
        # @System is a generic candidate; printer-specific profiles must
        # reference the selected model and not an unrelated model variant.
        if q != ["system"]:
            if not model or model not in q:
                continue
            if model == "k2" and any(word in q for word in ("plus", "pro", "max")) and not variant.intersection({"plus", "pro", "max"}):
                continue
            if model == "k1" and any(word in q for word in ("plus", "max", "se", "cfs")) and not variant.intersection({"plus", "max", "se", "cfs"}):
                continue
        title_words = _words(title)
        if material_words and not all(x in title_words for x in material_words):
            continue
        # Match an actual product name where possible, not merely PLA/ABS;
        # generic same-family results remain lower-ranked suggestions.
        matching_product = bool(product_words) and all(
            word in title_words for word in product_words)
        generic = "generic" in title_words
        if vendor and any(word not in {"generic", "system"} for word in vendor):
            manufacturer_match = all(word in title_words for word in vendor)
        else:
            manufacturer_match = False
        # Exclude other branded materials unless the brand is identified in
        # the user's own inventory. Don't recommend Bambu to a Creality slot.
        prefix = title_words[:1]
        if not matching_product and not generic and not manufacturer_match:
            continue
        rank = (
            0 if matching_product and manufacturer_match and q != ["system"] else
            1 if matching_product and manufacturer_match else
            2 if matching_product and q != ["system"] else
            3 if matching_product else
            4 if generic and q != ["system"] else
            5
        )
        ranked.append((rank, raw.casefold(), name, path))
    ranked.sort()
    return [(name, path) for _, _, name, path in ranked]
