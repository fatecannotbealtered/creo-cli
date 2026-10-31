"""Files produced from models. File identity is distinct from geometry/consumer proof."""

from __future__ import annotations

import os
import uuid
from dataclasses import replace

from .. import engine, paths, render_record
from ..core import Error
from ..registry import MODEL, Command, Param
from ..schemas import NS, B, S, array, shape, written
from ..transport import Client
from . import model


def _prepare_render(opts):
    name = engine.model_name(opts["model"], ("prt", "asm"))
    output = paths.contained(opts["output"], exists=False)
    if output.suffix.lower() not in (".jpg", ".jpeg"):
        raise Error("E_VALIDATION", "render output must be .jpg or .jpeg")
    if output.exists():
        raise Error("E_CONFLICT", "render never overwrites an existing artifact")
    if not output.parent.is_dir():
        raise Error("E_NOT_FOUND", "render output directory must exist in the workspace")
    if not all(64 <= opts[k] <= 4000 for k in ("width", "height")):
        raise Error("E_VALIDATION", "render dimensions must be 64..4000 pixels")
    return {"model": name, "file": output}


def _plan_render(client: Client, opts, pre):
    from .. import presentation

    name, output = pre["model"], pre["file"]
    s = engine.session(client)
    engine.require_in_session(s, name)
    if (s.get("active_model") or "").lower() != name:
        raise Error(
            "E_UNSUPPORTED",
            "render requires the target to be the active graphics model",
            {
                "target": name,
                "active_model": s.get("active_model"),
                "reason": "native inactive-window presentation getters are unavailable",
                "next_action": "preview and confirm public display activate --model "
                + name
                + "; then prepare a new render preview",
            },
        )
    before = engine.show(client, name)
    engine.store_directory(before, s)
    context = presentation.render_state(client, name)

    def coherent(view, physical):
        if type(physical.get("modified")) is not bool or view["modified"] != physical["modified"]:
            raise Error(
                "E_VERIFY_INCOMPLETE",
                "render context and independent model readback disagree on modified state",
                {"context_modified": view["modified"], "model_modified": physical.get("modified")},
            )

    coherent(context, before)
    selected = "FRONT" if opts["view"] == "isometric" else opts["view"].upper()
    if opts["view"] != "current" and selected not in context.get("named_views", []):
        raise Error(
            "E_NOT_FOUND",
            "requested standard orientation is not available",
            {"requested": selected, "available": context.get("named_views")},
        )
    staging = paths.workspace() / ".creo-cli" / "staging" / uuid.uuid4().hex
    staged = staging / "render.jpg"
    published = False
    active_run = None

    def prepare_dispatch(run):
        nonlocal active_run
        active_run = run
        render_record.prepare(run, staged, output, binding, request)

    def files():
        return render_record.inspect(active_run)["artifacts"] if active_run else []

    def observe(c):
        current, physical = presentation.settled_render_state(c, name)[0], engine.show(c, name)
        coherent(current, physical)
        return {
            "presentation": current,
            "physical": physical,
            "artifacts": files(),
        }

    def verify(c, data):
        nonlocal published
        actual, samples = presentation.settled_render_state(c, name)
        restored = presentation.equivalent(context, actual)
        actual_model = engine.show(c, name)
        coherent(actual, actual_model)
        physical_unchanged = presentation.equivalent(before, actual_model)
        try:
            decoded = c.op("artifact.jpeg-inspect", {"file": str(staged)})
        except Error as exc:
            decoded = {"decoded": False, "error": {"code": exc.code, "message": str(exc)}}
        raw = staged.read_bytes() if staged.is_file() else b""
        jpeg = raw.startswith(b"\xff\xd8") and raw.endswith(b"\xff\xd9")
        valid = (
            jpeg
            and decoded.get("decoded") is True
            and (
                decoded.get("width"),
                decoded.get("height"),
            )
            == (opts["width"], opts["height"])
        )
        nonempty = bool(decoded.get("sampled_rgb_range", 0) >= 2)
        if restored and physical_unchanged and valid and nonempty:
            # Keep the exact verified file identity before exclusive publication. A new
            # CLI can prove ownership across the link/checkpoint interruption window.
            render_record.checkpoint(
                active_run,
                phase="verified",
                verified_file=render_record.file_identity(staged),
                readback={"presentation": actual, "physical": actual_model},
                decoded=decoded,
            )
            # Link creation is exclusive on both Windows and POSIX; no overwrite race.
            os.link(staged, output)
            published = True
            render_record.checkpoint(active_run, phase="published")
            staged.unlink()
            staging.rmdir()
        known = files()
        identity = next(iter(known), None)
        result = {
            "model": name,
            "file": identity["path"] if identity else None,
            "bytes": identity["size_bytes"] if identity else None,
            "sha256": identity["sha256"] if identity else None,
            "format": "jpeg",
            "view": opts["view"],
            "window_opened": False,
            "published": published,
            "requested_output": str(output),
            "presentation": actual,
            "presentation_observations": samples,
            "physical": actual_model,
            "decoded": decoded,
        }
        return result, {
            "level": "selected_postconditions_verified",
            "checks": [
                engine.check("jpeg_fully_decoded", decoded.get("decoded") is True),
                engine.check("encoded_dimensions_as_requested", valid),
                engine.check("nonuniform_image_content", nonempty),
                engine.check("presentation_restored", restored, expected=context, observed=actual),
                engine.check("physical_model_unchanged", physical_unchanged),
                engine.check("published_without_overwriting", published),
            ],
            "observations": [
                {
                    "observation": "artifact_identity",
                    "observed": known,
                    "source": "independent file bytes and ImageIO reader",
                    "independent": True,
                }
            ],
            "not_checked": [
                "all components visible",
                "cropping and visual overlap",
                "manufacturing quality",
            ],
        }

    def send():
        return {
            "model": name,
            "file": str(staged),
            "view": opts["view"],
            "width": opts["width"],
            "height": opts["height"],
        }

    request = {
        "model": name,
        "output": str(output),
        "view": opts["view"],
        "width": opts["width"],
        "height": opts["height"],
    }
    binding = {"model": before, "output": str(output), "presentation": context}
    return engine.Plan(
        op="model.render",
        request=request,
        target=name,
        send=send,
        prepare_dispatch=prepare_dispatch,
        artifacts_after=files,
        binding=binding,
        preview={
            "command": "artifact render",
            "model": name,
            "output": str(output),
            "model_footprint": sorted(
                {name, "session:presentation", context["active_model"].lower()}
            ),
            "view": opts["view"],
            "pixels": [opts["width"], opts["height"]],
            "presentation_before": context,
            "effect": "temporarily orient and hide datums, export JPEG, then restore "
            "view, screen transform, active window and datum display; retain selected explosion",
            "limits": [
                "existing displayed part/assembly window required",
                "use public display activate for the target, then display fit "
                "--view <orientation> --margin <fraction> and render --view current",
                "no drawing-mode context",
                "caller framing is retained; no automatic refit",
                "image visibility/cropping need independent visual inspection",
            ],
            "staging": "private workspace staging; publish only after decode and restoration",
        },
        verify=verify,
        observe=observe,
        before={"presentation": context, "physical": before, "artifacts": []},
        arguments={k: opts[k] for k in ("model", "output", "view", "width", "height")},
    )


def render(opts):
    return engine.write("artifact render", opts, _prepare_render, _plan_render)


def inspect(opts):
    output = paths.contained(opts["file"], directory=False)
    identity = paths.artifact(output)
    with output.open("rb") as stream:
        prefix = stream.read(256)
    signatures = (("jpeg", b"\xff\xd8"), ("pdf", b"%PDF-"), ("step", b"ISO-10303-21"))
    detected = next((kind for kind, magic in signatures if magic in prefix[:80]), "unknown")
    return {
        "artifact": identity,
        "detected_header": detected,
        "inspection": {
            "completed": True,
            "source": "actual_file_bytes",
            "version": 1,
            "scope": "file_identity_and_header_only",
            "consumer_semantics_verified": False,
        },
        "not_checked": [
            "full_decode",
            "geometry",
            "units",
            "native_editability",
            "pdf_page_layout",
        ],
        "_untrusted": ["artifact"],
    }


EXPORT = next(command for command in model.COMMANDS if command.path == "model export")
COMMANDS = [
    replace(
        EXPORT,
        path="artifact export",
        description=EXPORT.description
        + "; file/header readback does not prove consumer geometry or page layout",
    ),
    Command(
        "artifact render",
        (
            "Create a new JPEG of the active part/assembly, retaining framing and explosion; "
            "verify full decode and view/config restoration; visibility still needs visual review"
        ),
        render,
        written(
            shape(
                {
                    "model": S,
                    "file": NS,
                    "bytes": {"type": ["integer", "null"]},
                    "sha256": NS,
                    "format": S,
                    "view": S,
                    "published": B,
                    "requested_output": S,
                    "window_opened": B,
                    "decoded": shape({}),
                    "physical": shape({}),
                    "presentation": shape({}),
                    "presentation_observations": array(shape({})),
                }
            )
        ),
        params=(
            MODEL,
            Param("output", required=True, description="new .jpg/.jpeg in the workspace"),
            Param(
                "view",
                default="isometric",
                choices=("isometric", "front", "back", "top", "bottom", "left", "right", "current"),
            ),
            Param("width", "integer", default=1024),
            Param("height", "integer", default=768),
        ),
        write=True,
        untrusted=("result", "verification"),
        service_ops=(
            "model.render",
            "model.render-state",
            "artifact.jpeg-inspect",
            "session.status",
            "model.show",
        ),
        example="--model block --output block.jpg",
    ),
    Command(
        "artifact inspect",
        (
            "Read actual file identity/header; explicitly does not "
            "validate geometry, editable features or full PDF pages"
        ),
        inspect,
        shape({"artifact": shape({}), "detected_header": S, "inspection": shape({"completed": B})}),
        params=(Param("file", required=True, description="existing workspace artifact"),),
        untrusted=("artifact",),
        example="--file block.stp",
    ),
]
