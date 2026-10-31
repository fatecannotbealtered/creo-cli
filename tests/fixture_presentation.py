"""HTTP test substitute for cosmetic/display operations. No CAD or real image geometry."""

from __future__ import annotations

import copy
import math
from pathlib import Path

try:
    from .fixture_features import Refusal
except ImportError:
    from fixture_features import Refusal

APPEARANCE_SOURCE = (
    "pfcSelect.CreateModelSelection/WSelection.GetVisibleAppearance/"
    "WSolid.GetAllAppearancesAndTextures"
)
DISPLAY_SOURCE = (
    "Session.GetCurrentModel/GetCurrentWindow/GetModelWindow; Model.GetType; "
    "Window.GetModel/GetScreenTransform; ViewOwner.GetCurrentViewTransform/ListViews; "
    "WModelItem.IsHidden; Assembly.GetIsExploded"
)


def appearance_properties(rgb):
    return {
        "rgb": list(rgb),
        "ambient": 0.3,
        "diffuse": 0.7,
        "highlight": 0.0,
        "shininess": 0.2,
        "transparency": 0.0,
        "highlight_rgb": [1.0, 1.0, 1.0],
        "reflection": 0.0,
        "name": "creo_cli_color",
        "label": "",
        "description": "",
        "keywords": "",
    }


def identity():
    return [[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 1.0]]


class PresentationFixture:
    """Independent fake appearance/display state; not a Creo implementation."""

    def appearance_get(self, q):
        name, model = self.model(q["model"])
        if model["type"] != "part":
            raise Refusal("E_VALIDATION", "appearance requires a source part")
        current = copy.deepcopy(model.get("cosmetic_appearance"))
        assignments = copy.deepcopy(model.get("cosmetic_assignments", []))
        if current is not None and not assignments:
            assignments = [
                {
                    "item_type": "model",
                    "item_id": None,
                    "selection_model": name,
                    "selection_model_type": "part",
                    "appearance": current,
                    "texture_count": 3,
                    "texture_inventory_complete": True,
                    "textures": [
                        {"complete": True, "type": kind, "file_path": "", "placement": None}
                        for kind in ("BUMP_TEXTURE", "COLOR_TEXTURE", "DECAL_TEXTURE")
                    ],
                }
            ]
        return {
            "complete": True,
            "model": name,
            "scope": "source_part",
            "selection_model": name,
            "selection_model_type": "part",
            "appearance": current,
            "assignments": assignments,
            "modified": model["modified"],
            "source": APPEARANCE_SOURCE,
        }

    def appearance_set(self, q):
        name, model = self.model(q["model"])
        if model["type"] != "part":
            raise Refusal("E_VALIDATION", "appearance requires a source part")
        if "expected_before" not in q or "expected_source_context" not in q:
            raise Refusal("E_VALIDATION", "expected-before appearance and source context required")
        if q["expected_before"] != self.appearance_get(q) or q["expected_source_context"] != {
            "model": name,
            "origin": model.get("origin"),
        }:
            raise Refusal("E_CONFLICT", "appearance or source changed before setter")
        previous = copy.deepcopy(model.get("cosmetic_appearance"))
        replace = q.get("reference_action", "preserve") == "create_and_bind"
        if replace != q.get("reference_replacement_authorized", False):
            raise Refusal("E_FORBIDDEN", "reference creation needs explicit authorization")
        if q.get("action") == "restore":
            current = copy.deepcopy(q.get("appearance"))
        else:
            current = copy.deepcopy(previous)
            if current is None:
                current = appearance_properties(q["rgb"])
            current["rgb"] = list(q["rgb"])
        if replace:
            if previous is None or current is None:
                raise Refusal("E_UNSUPPORTED", "create_and_bind requires non-null appearances")
            # Fixture-only native allocator substitute. Product never predicts this ID.
            serial = getattr(self, "appearance_reference_serial", 0) + 1
            self.appearance_reference_serial = serial
            current["name"] = f"fixture_native_reference_{serial}"
        elif previous is not None and current is not None and previous != current:
            raise Refusal("E_UNSUPPORTED", "existing appearance changes need create_and_bind")
        model["cosmetic_appearance"] = current
        model["cosmetic_assignments"] = []
        model["presentation_owned"] = True
        model["modified"] = True
        return {
            "model": name,
            "scope": "source_part",
            "setter_returned": True,
            "reference_action": q.get("reference_action", "preserve"),
        }

    def display_state(self, q):
        name, model = self.model(q["model"])
        if model["type"] not in ("part", "assembly"):
            raise Refusal("E_VALIDATION", "display requires part or assembly")
        session_current = getattr(self, "native_current_model_override", self.active)
        window_model = self.active
        current_type = self.models.get(session_current, {}).get("type")
        window_type = self.models.get(window_model, {}).get("type")
        complete_context = (
            session_current is not None
            and session_current == window_model
            and current_type == window_type
        )
        current = complete_context and session_current == name
        view = model.get("native_display", {})
        observed = {
            "complete": True,
            "model": name,
            "window": name,
            "active_window": self.active,
            "active_model": self.active,
            "current_model": session_current,
            "current_model_type": current_type,
            "window_model": window_model,
            "window_model_type": window_type,
            "context_complete": complete_context,
            "context_reason": "matching_session_current_model_and_window"
            if current
            else "current_model_or_window_model_absent"
            if session_current is None or window_model is None
            else "target_is_inactive",
            "target_active": current,
            "screen": copy.deepcopy(view.get("screen", {"pan_x": 0, "pan_y": 0, "zoom": 1}))
            if current
            else None,
            "view_transform": copy.deepcopy(view.get("view_transform", identity()))
            if current
            else None,
            "context_readback": "observed" if current else "not_checked_inactive_target",
            "named_views": ["FRONT", "BACK", "TOP", "BOTTOM", "LEFT", "RIGHT"] if current else [],
            "named_views_complete": current,
            "component_visibility": [
                {
                    "id": str(row["id"]),
                    "model": row["model"],
                    "hidden": bool(model.get("hidden_components", {}).get(str(row["id"]), False)),
                }
                for row in model.get("components", [])
            ],
            "is_exploded": bool(model.get("is_exploded", False))
            if current and model["type"] == "assembly"
            else None,
            "modified": model["modified"],
            "persistence": "controlled substitute; session display only",
            "source": DISPLAY_SOURCE,
        }
        if self.capabilities.get("model_context_activation", 0) >= 1:
            observed["target_identity"] = self.display_target_identity(q)
        return observed

    def display_target_identity(self, q):
        """Controlled native-handle substitute; not a real SDK identity observation."""
        name, model = self.model(q["model"])
        return {
            "model": name,
            "type": model["type"],
            "origin": model["origin"],
            "version_stamp": str(id(model)),
            "relation_id": id(model) & 0x7FFFFFFF,
        }

    def display_require_current(self, q):
        if not self.display_state(q)["target_active"]:
            raise Refusal("E_VERIFY_INCOMPLETE", "complete existing target context required")

    def display_activate(self, q):
        name, model = self.model(q["model"])
        if model["type"] not in ("part", "assembly"):
            raise Refusal("E_VALIDATION", "display requires part or assembly")
        if self.display_state(q)["target_active"]:
            return {
                "model": name,
                "setter_returned": True,
                "already_active": True,
                "activation_performed": False,
            }
        if self.capabilities.get("model_context_activation", 0) < 1:
            raise Refusal(
                "E_UNSUPPORTED",
                "automatic model activation is unqualified in this synchronous service",
            )
        expected = q.get("expected_target")
        if not isinstance(expected, dict) or set(expected) != {
            "model",
            "type",
            "origin",
            "version_stamp",
            "relation_id",
        }:
            raise Refusal("E_VALIDATION", "complete expected target identity required")
        if expected != self.display_target_identity(q):
            raise Refusal("E_CONFLICT", "target identity changed before activation scheduling")

        # These are deterministic fixture phases, not a timer/SDK implementation.
        # The real deferred event-loop state machine is tested separately in Java.
        if not hasattr(self, "context_activation_trace"):
            self.context_activation_trace = []
            self.context_activation_tick = 0

        def phase(label):
            self.context_activation_tick += 1
            tick = self.context_activation_tick
            self.context_activation_trace.append({"phase": label, "tick": tick, "model": name})
            hook = getattr(self, "context_activation_hook", None)
            if hook is not None:
                hook(label, q)
            return tick

        scheduled = phase("scheduled")
        if expected != self.display_target_identity(q):
            raise Refusal("E_CONFLICT", "target identity changed before native callback")
        self.active = name
        if hasattr(self, "native_current_model_override"):
            self.native_current_model_override = name
        callback = phase("callback_returned")
        verified = phase("verified_after_return")
        observed = self.display_state(q)
        if observed["target_active"] is not True:
            raise Refusal("E_VERIFY_INCOMPLETE", "deferred callback did not restore target context")
        return {
            "model": name,
            "setter_returned": True,
            "already_active": False,
            "activation_performed": True,
            "activation_dispatch": "UICreateMaxPriorityCommand/RunMacro fixed registered command",
            "callback_returned": True,
            "verified_after_return_to_creo": True,
            "expected_target": copy.deepcopy(expected),
            "observed_target": self.display_target_identity(q),
            "scheduled_tick": scheduled,
            "callback_tick": callback,
            "verified_tick": verified,
        }

    def display_fit(self, q):
        name, model = self.model(q["model"])
        self.display_require_current(q)
        margin = q.get("margin", 0.1)
        view = q.get("view", "current")
        previous = model.get("native_display", {})
        transform = copy.deepcopy(previous.get("view_transform", identity()))
        if view != "current":
            transform = identity()
            # A controlled orientation substitute, deliberately no CAD projection proof.
            if view == "isometric":
                a, b, c = 1 / math.sqrt(2), 1 / math.sqrt(6), 1 / math.sqrt(3)
                transform[:3] = [[a, -a, 0, 0], [b, b, -2 * b, 0], [c, c, c, 0]]
            elif view in ("back", "bottom", "left"):
                transform[0][0], transform[2][2] = -1.0, -1.0
        zoom = 1.0 * (1 - 2 * margin)
        model["native_display"] = {
            "screen": {"pan_x": 0, "pan_y": 0, "zoom": zoom},
            "view_transform": transform,
        }
        orientation = [[value / math.hypot(*row[:3]) for value in row[:3]] for row in transform[:3]]
        return {
            "model": name,
            "setter_returned": True,
            "fit": {
                "margin": margin,
                "refit_zoom": 1.0,
                "requested_zoom": zoom,
                "observed_zoom": zoom,
                "observed_pan_x": 0,
                "observed_pan_y": 0,
                "source": "WWindow.Refit/Window.SetScreenTransform",
                "view": view,
                "orientation": orientation,
                "pixel_margin_verified": False,
            },
        }

    def display_visibility(self, q):
        name, model = self._assembly(q["model"])
        self.display_require_current(q)
        target = self._component_of(model, q["component"])
        model.setdefault("hidden_components", {})[str(target["id"])] = q["hidden"]
        model["modified"] = True
        model["presentation_owned"] = True
        return {"model": name, "component": str(target["id"]), "setter_returned": True}

    def display_unexplode(self, q):
        name, model = self._assembly(q["model"])
        self.display_require_current(q)
        model["is_exploded"] = False
        return {"model": name, "setter_returned": True}

    def render_state(self, q):
        context = self.display_state(q)
        if context["target_active"] is not True:
            raise Refusal(
                "E_VERIFY_INCOMPLETE", "matching Session.GetCurrentModel and target window required"
            )
        result = super().render_state(q)
        result.update(
            {
                key: context[key]
                for key in (
                    "current_model",
                    "current_model_type",
                    "window_model",
                    "window_model_type",
                    "context_complete",
                )
            }
        )
        _, model = self.model(q["model"])
        native = model.get("native_display", {})
        result.update(copy.deepcopy(native))
        result["native_part_appearances"] = {
            name: self.appearance_get({"model": name})
            for name, value in self.models.items()
            if value["type"] == "part"
        }
        return result

    def presentation_record_save(self, path, model):
        if model.get("presentation_owned"):
            if not hasattr(self, "presentation_saved"):
                self.presentation_saved = {}
            self.presentation_saved[str(path)] = copy.deepcopy(model)

    def presentation_op(self, op, q):
        dispatch = {
            "appearance.get": self.appearance_get,
            "appearance.set": self.appearance_set,
            "appearance.restore": self.appearance_set,
            "display.state": self.display_state,
            "display.activate": self.display_activate,
            "display.fit": self.display_fit,
            "display.visibility": self.display_visibility,
            "display.unexplode": self.display_unexplode,
        }
        if op in dispatch:
            return dispatch[op](q)
        if op == "model.open" and not q.get("instance"):
            saved = getattr(self, "presentation_saved", {}).get(str(Path(q["path"])))
            if saved is not None:
                name = self.name(Path(q["path"]).name)
                if name in self.models:
                    raise Refusal("E_CONFLICT", "model is already in session")
                self.models[name] = copy.deepcopy(saved)
                self.models[name]["origin"] = q["path"]
                self.models[name]["modified"] = False
                self.active = name
                return self.summary(name, self.models[name]) | {"displayed": True}
        return None
