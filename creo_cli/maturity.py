"""How far each command is proven (DVER-040), with the evidence behind it (DVER-041).

Verified: every behavior-matrix row that applies passed on Creo Parametric 13.4.1.0 with the
real adapter; each command cites its normal row, and its dialog and read_back_mismatch rows
where they apply. Stable: also run by the Agent in the evaluation report it cites. Update this
table after live runs or an evaluation.
"""
from __future__ import annotations

from typing import Any

DOMAIN: dict[str, dict[str, Any]] = {
    "component list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-06-162748-component-list.json#normal",
        "live:docs/evidence/2026-11-06-163139-component-list.json#dialog",
    ]},
    "dimension list": {"maturity": "stable", "evidence": [
        "live:docs/evidence/2026-11-06-162757-dimension-list.json#normal",
        "live:docs/evidence/2026-11-06-163140-dimension-list.json#dialog",
        "eval:docs/evidence/eval-2026-11-06.json",
    ]},
    "dimension update": {"maturity": "stable", "evidence": [
        "live:docs/evidence/2026-11-06-162907-dimension-update.json#normal",
        "live:docs/evidence/2026-11-06-163141-dimension-update.json#dialog",
        "live:docs/evidence/2026-11-06-163032-dimension-update.json#read_back_mismatch",
        "eval:docs/evidence/eval-2026-11-06.json",
    ]},
    "distance get": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-06-162755-distance-get.json#normal",
        "live:docs/evidence/2026-11-06-163142-distance-get.json#dialog",
    ]},
    "feature get": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-06-162750-feature-get.json#normal",
        "live:docs/evidence/2026-11-06-163147-feature-get.json#dialog",
    ]},
    "feature list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-06-162752-feature-list.json#normal",
        "live:docs/evidence/2026-11-06-163148-feature-list.json#dialog",
    ]},
    "feature update": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-06-162919-feature-update.json#normal",
        "live:docs/evidence/2026-11-06-163150-feature-update.json#dialog",
        "live:docs/evidence/2026-11-06-163039-feature-update.json#read_back_mismatch",
    ]},
    "geometry list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-06-162753-geometry-list.json#normal",
        "live:docs/evidence/2026-11-06-163151-geometry-list.json#dialog",
    ]},
    "material list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-06-162730-material-list.json#normal",
        "live:docs/evidence/2026-11-06-163152-material-list.json#dialog",
    ]},
    "model export": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-06-162840-model-export.json#normal",
        "live:docs/evidence/2026-11-06-163153-model-export.json#dialog",
        "live:docs/evidence/2026-11-06-162847-model-export.json#read_back_mismatch",
    ]},
    "model get": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-06-162715-model-get.json#normal",
        "live:docs/evidence/2026-11-06-163154-model-get.json#dialog",
    ]},
    "model render": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-06-162843-model-render.json#normal",
        "live:docs/evidence/2026-11-06-163156-model-render.json#dialog",
        "live:docs/evidence/2026-11-06-162850-model-render.json#read_back_mismatch",
    ]},
    "parameter list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-06-162727-parameter-list.json#normal",
        "live:docs/evidence/2026-11-06-163157-parameter-list.json#dialog",
    ]},
    "parameter update": {"maturity": "stable", "evidence": [
        "live:docs/evidence/2026-11-06-162914-parameter-update.json#normal",
        "live:docs/evidence/2026-11-06-163158-parameter-update.json#dialog",
        "live:docs/evidence/2026-11-06-163036-parameter-update.json#read_back_mismatch",
        "eval:docs/evidence/eval-2026-11-06.json",
    ]},
    "relation list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-06-162738-relation-list.json#normal",
        "live:docs/evidence/2026-11-06-163159-relation-list.json#dialog",
    ]},
}

STANDARD: dict[str, dict[str, Any]] = {
    "doc close": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-06-162856-doc-close.json#normal",
        "live:docs/evidence/2026-11-06-163144-doc-close.json#dialog",
        "live:docs/evidence/2026-11-06-162902-doc-close.json#read_back_mismatch",
    ]},
    "doc get": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-06-162815-doc-get.json#normal",
    ]},
    "doc list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-06-162814-doc-list.json#normal",
    ]},
    "doc open": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-06-162713-doc-open.json#normal",
        "live:docs/evidence/2026-11-06-163145-doc-open.json#dialog",
        "live:docs/evidence/2026-11-06-162742-doc-open.json#read_back_mismatch",
    ]},
    "doc save": {"maturity": "stable", "evidence": [
        "live:docs/evidence/2026-11-06-163004-doc-save.json#normal",
        "live:docs/evidence/2026-11-06-163146-doc-save.json#dialog",
        "live:docs/evidence/2026-11-06-163047-doc-save.json#read_back_mismatch",
        "eval:docs/evidence/eval-2026-11-06.json",
    ]},
    "plugin get": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-06-162816-plugin-get.json#normal",
    ]},
    "plugin install": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-06-162822-plugin-install.json#normal",
        "live:docs/evidence/2026-11-06-162826-plugin-install.json#read_back_mismatch",
    ]},
    "plugin remove": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-06-162828-plugin-remove.json#normal",
        "live:docs/evidence/2026-11-06-162830-plugin-remove.json#read_back_mismatch",
    ]},
    "session get": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-06-162812-session-get.json#normal",
    ]},
    "session list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-06-162811-session-list.json#normal",
    ]},
}
