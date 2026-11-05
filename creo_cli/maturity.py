"""How far each command is proven (DVER-040), with the evidence behind it (DVER-041).

Verified: every behavior-matrix row that applies passed on Creo Parametric 13.4.1.0 with the
real adapter; each command cites its normal row, and its dialog and read_back_mismatch rows
where they apply. Update this table after live runs or an evaluation.
"""
from __future__ import annotations

from typing import Any

DOMAIN: dict[str, dict[str, Any]] = {
    "component list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-121046-component-list.json#normal",
        "live:docs/evidence/2026-11-05-121940-component-list.json#dialog",
    ]},
    "dimension list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-120902-dimension-list.json#normal",
        "live:docs/evidence/2026-11-05-121947-dimension-list.json#dialog",
    ]},
    "dimension update": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-121334-dimension-update.json#normal",
        "live:docs/evidence/2026-11-05-122005-dimension-update.json#dialog",
        "live:docs/evidence/2026-11-05-121758-dimension-update.json#read_back_mismatch",
    ]},
    "distance get": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-120946-distance-get.json#normal",
        "live:docs/evidence/2026-11-05-122020-distance-get.json#dialog",
    ]},
    "feature get": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-120939-feature-get.json#normal",
        "live:docs/evidence/2026-11-05-122119-feature-get.json#dialog",
    ]},
    "feature list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-120833-feature-list.json#normal",
        "live:docs/evidence/2026-11-05-122133-feature-list.json#dialog",
    ]},
    "feature update": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-121412-feature-update.json#normal",
        "live:docs/evidence/2026-11-05-122153-feature-update.json#dialog",
    ]},
    "geometry list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-120844-geometry-list.json#normal",
        "live:docs/evidence/2026-11-05-122210-geometry-list.json#dialog",
    ]},
    "material list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-120926-material-list.json#normal",
        "live:docs/evidence/2026-11-05-122227-material-list.json#dialog",
    ]},
    "model export": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-121236-model-export.json#normal",
        "live:docs/evidence/2026-11-05-122245-model-export.json#dialog",
    ]},
    "model get": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-120824-model-get.json#normal",
        "live:docs/evidence/2026-11-05-122302-model-get.json#dialog",
    ]},
    "model render": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-121253-model-render.json#normal",
        "live:docs/evidence/2026-11-05-122321-model-render.json#dialog",
    ]},
    "parameter list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-120914-parameter-list.json#normal",
        "live:docs/evidence/2026-11-05-122339-parameter-list.json#dialog",
    ]},
    "parameter update": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-121357-parameter-update.json#normal",
        "live:docs/evidence/2026-11-05-122357-parameter-update.json#dialog",
    ]},
    "relation list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-120953-relation-list.json#normal",
        "live:docs/evidence/2026-11-05-122416-relation-list.json#dialog",
    ]},
}

STANDARD: dict[str, dict[str, Any]] = {
    "doc close": {"maturity": "draft", "evidence": []},
    "doc get": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-121133-doc-get.json#normal",
    ]},
    "doc list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-121126-doc-list.json#normal",
    ]},
    "doc open": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-120805-doc-open.json#normal",
        "live:docs/evidence/2026-11-05-122050-doc-open.json#dialog",
        "live:docs/evidence/2026-11-05-121011-doc-open.json#read_back_mismatch",
    ]},
    "doc save": {"maturity": "draft", "evidence": []},
    "plugin get": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-121140-plugin-get.json#normal",
    ]},
    "plugin install": {"maturity": "draft", "evidence": []},
    "plugin remove": {"maturity": "draft", "evidence": []},
    "session get": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-121117-session-get.json#normal",
    ]},
    "session list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-121111-session-list.json#normal",
    ]},
}
