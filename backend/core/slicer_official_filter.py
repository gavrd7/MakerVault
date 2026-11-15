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
    terms = _words(query)
    words = _words(name)
    if not terms:
        return False
    # Exact token matching avoids treating K1 as K10 or K1 Max as K1.
    return all(term in words or (len(term) >= 4 and any(
        word.startswith(term) for word in words)) for term in terms)
