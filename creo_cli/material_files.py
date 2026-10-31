"""Bound a concrete modern MTL source without loading it into the CAD model."""

import hashlib
import math
import re
from pathlib import Path

from . import paths
from .core import Error

FACTORS = {"tonne/mm^3": 1.0, "kg/m^3": 1e-12, "g/cm^3": 1e-9}


def read_source(path):
    path = Path(path).absolute()
    paths.no_links(path)
    if path.suffix.lower() != ".mtl":
        raise Error("E_UNSUPPORTED", "this material profile requires a modern .mtl file")
    try:
        before = path.stat()
        artifact = paths.artifact(path)
        raw = path.read_bytes()
        after = path.stat()
    except FileNotFoundError as exc:
        raise Error("E_NOT_FOUND", "material source is unavailable") from exc
    except OSError as exc:
        raise Error("E_IO", "material source cannot be reliably read") from exc
    if artifact["size_bytes"] > 1024 * 1024:
        raise Error("E_VALIDATION", "material source exceeds 1 MiB")

    def stamp(s):
        return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)

    if stamp(before) != stamp(after) or hashlib.sha256(raw).hexdigest() != artifact["sha256"]:
        raise Error("E_CONFLICT", "material source changed during inspection")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise Error("E_UNSUPPORTED", "material source encoding is outside this profile") from exc
    blocks = re.findall(r"\{\s*Name\s*=\s*PTC_MASS_DENSITY\b([^{}]*)\}", text, re.I)
    if len(blocks) != 1:
        raise Error("E_VERIFY_INCOMPLETE", "material source has no unique readable mass density")
    matched = re.search(r"Default\s*=\s*([+-]?[0-9.]+(?:[Ee][+-]?[0-9]+)?)\s+([^\r\n]+)", blocks[0])
    if not matched:
        raise Error("E_VERIFY_INCOMPLETE", "material source density or units cannot be read")
    try:
        value = float(matched[1])
    except ValueError as exc:
        raise Error("E_VERIFY_INCOMPLETE", "material density is not a readable number") from exc
    units = re.sub(r"\s+", "", matched[2]).lower()
    if units not in FACTORS:
        raise Error(
            "E_UNSUPPORTED",
            "material density units are outside the bounded profile",
            {"units": units, "supported": sorted(FACTORS)},
        )
    if not math.isfinite(value) or value <= 0:
        raise Error("E_VALIDATION", "material density must be finite and positive")
    return artifact | {
        "file_identity": list(stamp(after)),
        "density": {"value": value, "units": units},
        "model_density_tonne_per_mm3": value * FACTORS[units],
    }
