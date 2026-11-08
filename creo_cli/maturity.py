"""How far each command is proven (DVER-040), with the evidence behind it (DVER-041).

Verified: every behavior-matrix row that applies passed on Creo Parametric 13.4.1.0 with the
real adapter; each command cites its normal row, and its dialog and read_back_mismatch rows
where they apply. Stable: also run by the Agent in the evaluation report it cites. Update this
table after live runs or an evaluation.
"""
from __future__ import annotations

from typing import Any

DOMAIN: dict[str, dict[str, Any]] = {
    "axis create": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-07-213120-axis-create.json#normal",
        "live:docs/evidence/2026-11-07-191419-axis-create.json#dialog",
        "live:docs/evidence/2026-11-07-213138-axis-create.json#read_back_mismatch",
    ]},
    "chamfer create": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-07-212746-chamfer-create.json#normal",
        "live:docs/evidence/2026-11-07-191412-chamfer-create.json#dialog",
        "live:docs/evidence/2026-11-07-212805-chamfer-create.json#read_back_mismatch",
    ]},
    "component list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-07-190759-component-list.json#normal",
        "live:docs/evidence/2026-11-07-191337-component-list.json#dialog",
    ]},
    "dimension list": {"maturity": "stable", "evidence": [
        "live:docs/evidence/2026-11-07-190807-dimension-list.json#normal",
        "live:docs/evidence/2026-11-07-191339-dimension-list.json#dialog",
        "eval:docs/evidence/eval-2026-11-07-2.json",
    ]},
    "dimension update": {"maturity": "stable", "evidence": [
        "live:docs/evidence/2026-11-07-223025-dimension-update.json#normal",
        "live:docs/evidence/2026-11-07-191340-dimension-update.json#dialog",
        "live:docs/evidence/2026-11-07-191119-dimension-update.json#read_back_mismatch",
        "eval:docs/evidence/eval-2026-11-07-2.json",
    ]},
    "distance get": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-07-190806-distance-get.json#normal",
        "live:docs/evidence/2026-11-07-191342-distance-get.json#dialog",
    ]},
    "draft create": {"maturity": "stable", "evidence": [
        "live:docs/evidence/2026-11-07-212841-draft-create.json#normal",
        "live:docs/evidence/2026-11-07-191414-draft-create.json#dialog",
        "live:docs/evidence/2026-11-07-212859-draft-create.json#read_back_mismatch",
        "eval:docs/evidence/eval-2026-11-07-2.json",
    ]},
    "extrude create": {"maturity": "stable", "evidence": [
        "live:docs/evidence/2026-11-07-212350-extrude-create.json#normal",
        "live:docs/evidence/2026-11-07-191406-extrude-create.json#dialog",
        "live:docs/evidence/2026-11-07-212417-extrude-create.json#read_back_mismatch",
        "eval:docs/evidence/eval-2026-11-07-2.json",
    ]},
    "feature delete": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-07-223045-feature-delete.json#normal",
        "live:docs/evidence/2026-11-07-191426-feature-delete.json#dialog",
        "live:docs/evidence/2026-11-07-213525-feature-delete.json#read_back_mismatch",
    ]},
    "feature get": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-07-190801-feature-get.json#normal",
        "live:docs/evidence/2026-11-07-191348-feature-get.json#dialog",
    ]},
    "feature list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-07-190803-feature-list.json#normal",
        "live:docs/evidence/2026-11-07-191350-feature-list.json#dialog",
    ]},
    "feature update": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-07-223027-feature-update.json#normal",
        "live:docs/evidence/2026-11-07-191352-feature-update.json#dialog",
        "live:docs/evidence/2026-11-07-191127-feature-update.json#read_back_mismatch",
    ]},
    "geometry list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-07-190804-geometry-list.json#normal",
        "live:docs/evidence/2026-11-07-191353-geometry-list.json#dialog",
    ]},
    "material list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-07-190739-material-list.json#normal",
        "live:docs/evidence/2026-11-07-191354-material-list.json#dialog",
    ]},
    "model check": {"maturity": "stable", "evidence": [
        "live:docs/evidence/2026-11-07-213557-model-check.json#normal",
        "live:docs/evidence/2026-11-07-191427-model-check.json#dialog",
        "eval:docs/evidence/eval-2026-11-07-2.json",
    ]},
    "model export": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-07-190908-model-export.json#normal",
        "live:docs/evidence/2026-11-07-191356-model-export.json#dialog",
        "live:docs/evidence/2026-11-07-190917-model-export.json#read_back_mismatch",
    ]},
    "model get": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-07-190725-model-get.json#normal",
        "live:docs/evidence/2026-11-07-191358-model-get.json#dialog",
    ]},
    "model render": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-07-223032-model-render.json#normal",
        "live:docs/evidence/2026-11-07-191359-model-render.json#dialog",
        "live:docs/evidence/2026-11-07-190920-model-render.json#read_back_mismatch",
    ]},
    "model update": {"maturity": "stable", "evidence": [
        "live:docs/evidence/2026-11-07-213406-model-update.json#normal",
        "live:docs/evidence/2026-11-07-191424-model-update.json#dialog",
        "live:docs/evidence/2026-11-07-213426-model-update.json#read_back_mismatch",
        "eval:docs/evidence/eval-2026-11-07-2.json",
    ]},
    "parameter create": {"maturity": "stable", "evidence": [
        "live:docs/evidence/2026-11-07-213214-parameter-create.json#normal",
        "live:docs/evidence/2026-11-07-191421-parameter-create.json#dialog",
        "live:docs/evidence/2026-11-07-213231-parameter-create.json#read_back_mismatch",
        "eval:docs/evidence/eval-2026-11-07-2.json",
    ]},
    "parameter list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-07-190736-parameter-list.json#normal",
        "live:docs/evidence/2026-11-07-191401-parameter-list.json#dialog",
    ]},
    "parameter update": {"maturity": "stable", "evidence": [
        "live:docs/evidence/2026-11-07-190948-parameter-update.json#normal",
        "live:docs/evidence/2026-11-07-191402-parameter-update.json#dialog",
        "live:docs/evidence/2026-11-07-191123-parameter-update.json#read_back_mismatch",
        "eval:docs/evidence/eval-2026-11-07-2.json",
    ]},
    "pattern create": {"maturity": "stable", "evidence": [
        "live:docs/evidence/2026-11-07-212934-pattern-create.json#normal",
        "live:docs/evidence/2026-11-07-191416-pattern-create.json#dialog",
        "live:docs/evidence/2026-11-07-212952-pattern-create.json#read_back_mismatch",
        "eval:docs/evidence/eval-2026-11-07-2.json",
    ]},
    "plane create": {"maturity": "stable", "evidence": [
        "live:docs/evidence/2026-11-07-213027-plane-create.json#normal",
        "live:docs/evidence/2026-11-07-191418-plane-create.json#dialog",
        "live:docs/evidence/2026-11-07-213044-plane-create.json#read_back_mismatch",
        "eval:docs/evidence/eval-2026-11-07-2.json",
    ]},
    "relation list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-07-190746-relation-list.json#normal",
        "live:docs/evidence/2026-11-07-191404-relation-list.json#dialog",
    ]},
    "relation update": {"maturity": "stable", "evidence": [
        "live:docs/evidence/2026-11-07-213311-relation-update.json#normal",
        "live:docs/evidence/2026-11-07-191423-relation-update.json#dialog",
        "live:docs/evidence/2026-11-07-213327-relation-update.json#read_back_mismatch",
        "eval:docs/evidence/eval-2026-11-07-2.json",
    ]},
    "revolve create": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-07-212457-revolve-create.json#normal",
        "live:docs/evidence/2026-11-07-191407-revolve-create.json#dialog",
        "live:docs/evidence/2026-11-07-212516-revolve-create.json#read_back_mismatch",
    ]},
    "round create": {"maturity": "stable", "evidence": [
        "live:docs/evidence/2026-11-07-212648-round-create.json#normal",
        "live:docs/evidence/2026-11-07-191411-round-create.json#dialog",
        "live:docs/evidence/2026-11-07-212710-round-create.json#read_back_mismatch",
        "eval:docs/evidence/eval-2026-11-07-2.json",
    ]},
    "shell create": {"maturity": "stable", "evidence": [
        "live:docs/evidence/2026-11-07-212551-shell-create.json#normal",
        "live:docs/evidence/2026-11-07-191409-shell-create.json#dialog",
        "live:docs/evidence/2026-11-07-212611-shell-create.json#read_back_mismatch",
        "eval:docs/evidence/eval-2026-11-07-2.json",
    ]},
}

STANDARD: dict[str, dict[str, Any]] = {
    "doc close": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-07-190927-doc-close.json#normal",
        "live:docs/evidence/2026-11-07-191344-doc-close.json#dialog",
        "live:docs/evidence/2026-11-07-190934-doc-close.json#read_back_mismatch",
    ]},
    "doc create": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-08-083455-doc-create.json#normal",
        "live:docs/evidence/2026-11-08-085520-doc-create.json#dialog",
        "live:docs/evidence/2026-11-08-083503-doc-create.json#read_back_mismatch",
    ]},
    "doc get": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-07-190831-doc-get.json#normal",
    ]},
    "doc list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-07-190829-doc-list.json#normal",
    ]},
    "doc open": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-07-190723-doc-open.json#normal",
        "live:docs/evidence/2026-11-07-191345-doc-open.json#dialog",
        "live:docs/evidence/2026-11-07-190751-doc-open.json#read_back_mismatch",
    ]},
    "doc save-as": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-08-083557-doc-save-as.json#normal",
        "live:docs/evidence/2026-11-08-085523-doc-save-as.json#dialog",
        "live:docs/evidence/2026-11-08-083526-doc-save-as.json#read_back_mismatch",
    ]},
    "doc save": {"maturity": "stable", "evidence": [
        "live:docs/evidence/2026-11-07-191047-doc-save.json#normal",
        "live:docs/evidence/2026-11-07-191347-doc-save.json#dialog",
        "live:docs/evidence/2026-11-07-191139-doc-save.json#read_back_mismatch",
        "eval:docs/evidence/eval-2026-11-07-2.json",
    ]},
    "plugin get": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-07-190832-plugin-get.json#normal",
    ]},
    "plugin install": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-07-190846-plugin-install.json#normal",
        "live:docs/evidence/2026-11-07-190849-plugin-install.json#read_back_mismatch",
    ]},
    "plugin remove": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-07-190851-plugin-remove.json#normal",
        "live:docs/evidence/2026-11-07-190854-plugin-remove.json#read_back_mismatch",
    ]},
    "session close": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-08-083655-session-close.json#normal",
        "live:docs/evidence/2026-11-08-085525-session-close.json#dialog",
    ]},
    "session get": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-07-190827-session-get.json#normal",
    ]},
    "session list": {"maturity": "verified", "evidence": [
        "live:docs/evidence/2026-11-07-190825-session-list.json#normal",
    ]},
}
