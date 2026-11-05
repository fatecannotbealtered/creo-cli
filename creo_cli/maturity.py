"""How far each command is proven (DVER-040), with the evidence behind it (DVER-041).

Verified: every behavior-matrix row that applies passed on Creo Parametric 13.4.1.0 with the
real adapter; each command cites its normal row, and its dialog and read_back_mismatch rows
where they apply. Stable: also run by the Agent in the evaluation report it cites. Draft: doc
save, plugin install and plugin remove, whose read_back_mismatch row the matrix runner cannot
reach: it stops two-step commands at their preview. Update this table after live runs or an
evaluation.
"""
from __future__ import annotations

from typing import Any

DOMAIN: dict[str, dict[str, Any]] = {
    "component list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-131149-component-list.json#normal",
        "live:docs/evidence/2026-11-05-131356-component-list.json#dialog",
    ]},
    "dimension list": {"maturity": "stable", "evidence": [
        "live:docs/evidence/2026-11-05-131128-dimension-list.json#normal",
        "live:docs/evidence/2026-11-05-131357-dimension-list.json#dialog",
        "eval:docs/evidence/eval-2026-11-05.json",
    ]},
    "dimension update": {"maturity": "stable", "evidence": [
        "live:docs/evidence/2026-11-05-131225-dimension-update.json#normal",
        "live:docs/evidence/2026-11-05-131358-dimension-update.json#dialog",
        "live:docs/evidence/2026-11-05-131328-dimension-update.json#read_back_mismatch",
        "eval:docs/evidence/eval-2026-11-05.json",
    ]},
    "distance get": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-131138-distance-get.json#normal",
        "live:docs/evidence/2026-11-05-131359-distance-get.json#dialog",
    ]},
    "feature get": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-131136-feature-get.json#normal",
        "live:docs/evidence/2026-11-05-131404-feature-get.json#dialog",
    ]},
    "feature list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-131123-feature-list.json#normal",
        "live:docs/evidence/2026-11-05-131405-feature-list.json#dialog",
    ]},
    "feature update": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-131234-feature-update.json#normal",
        "live:docs/evidence/2026-11-05-131407-feature-update.json#dialog",
    ]},
    "geometry list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-131125-geometry-list.json#normal",
        "live:docs/evidence/2026-11-05-131408-geometry-list.json#dialog",
    ]},
    "material list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-131133-material-list.json#normal",
        "live:docs/evidence/2026-11-05-131409-material-list.json#dialog",
    ]},
    "model export": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-131211-model-export.json#normal",
        "live:docs/evidence/2026-11-05-131410-model-export.json#dialog",
    ]},
    "model get": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-131120-model-get.json#normal",
        "live:docs/evidence/2026-11-05-131411-model-get.json#dialog",
    ]},
    "model render": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-131214-model-render.json#normal",
        "live:docs/evidence/2026-11-05-131412-model-render.json#dialog",
    ]},
    "parameter list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-131131-parameter-list.json#normal",
        "live:docs/evidence/2026-11-05-131414-parameter-list.json#dialog",
    ]},
    "parameter update": {"maturity": "stable", "evidence": [
        "live:docs/evidence/2026-11-05-131230-parameter-update.json#normal",
        "live:docs/evidence/2026-11-05-131415-parameter-update.json#dialog",
        "eval:docs/evidence/eval-2026-11-05.json",
    ]},
    "relation list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-131141-relation-list.json#normal",
        "live:docs/evidence/2026-11-05-131416-relation-list.json#dialog",
    ]},
}

STANDARD: dict[str, dict[str, Any]] = {
    "doc close": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-131219-doc-close.json#normal",
        "live:docs/evidence/2026-11-05-131401-doc-close.json#dialog",
    ]},
    "doc get": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-131200-doc-get.json#normal",
    ]},
    "doc list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-131158-doc-list.json#normal",
    ]},
    "doc open": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-131118-doc-open.json#normal",
        "live:docs/evidence/2026-11-05-131402-doc-open.json#dialog",
        "live:docs/evidence/2026-11-05-131144-doc-open.json#read_back_mismatch",
    ]},
    "doc save": {"maturity": "draft", "evidence": [
    ]},
    "plugin get": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-131202-plugin-get.json#normal",
    ]},
    "plugin install": {"maturity": "draft", "evidence": [
    ]},
    "plugin remove": {"maturity": "draft", "evidence": [
    ]},
    "session get": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-131156-session-get.json#normal",
    ]},
    "session list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-05-131155-session-list.json#normal",
    ]},
}
