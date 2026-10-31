"""Native presentation commands; no desktop automation fallback."""

from .. import display
from ..registry import MODEL, Command, Param
from ..schemas import WRITTEN, B, S, shape, written

RESULT = shape({"model": S, "after": shape({})}, ("model",))


def _command(action, params=()):
    public = {"visibility": "component-visibility"}.get(action, action)
    return Command(
        "display " + public,
        "Activate the exact bound model through a registered native command and verify "
        "current-model/window context after control returns to Creo"
        if action == "activate"
        else "Native "
        + public
        + " for the explicit owned model; protected state and independent readback",
        lambda opts: display.execute(opts, action),
        written(RESULT),
        (MODEL, *params),
        write=True,
        untrusted=WRITTEN,
        example="--model phone_demo.asm"
        + (
            " --component 40 --state hidden"
            if action == "visibility"
            else " --margin 0.1"
            if action == "fit"
            else ""
        ),
        service_ops=(
            "session.status",
            "model.show",
            "appearance.get",
            "display.state",
            "display." + action,
        ),
    )


COMMANDS = [
    Command(
        "display show",
        "Read target context, direct component hide flags, "
        "current native framing and explosion display",
        display.query,
        shape(
            {"model": S, "target_active": B, "component_visibility": {"type": "array"}},
            ("model", "target_active", "component_visibility"),
        ),
        (MODEL,),
        untrusted=("component_visibility", "active_model"),
        example="--model phone_demo.asm",
        service_ops=("display.state",),
    ),
    _command("activate"),
    _command(
        "fit",
        (
            Param(
                "margin",
                type="number",
                default=0.1,
                description="0..0.4 fraction on each edge after native refit; "
                "visual pixel margin is checked separately",
            ),
            Param(
                "view",
                default="current",
                choices=("current", "isometric", "front", "back", "top", "bottom", "left", "right"),
                description="orientation retained by fit; "
                "render --view current preserves this framing",
            ),
        ),
    ),
    _command(
        "visibility",
        (
            Param("component", required=True, description="exact direct occurrence feature ID"),
            Param("state", required=True, choices=("visible", "hidden")),
        ),
    ),
    _command("unexplode"),
]
