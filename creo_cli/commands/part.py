"""part create (and assembly create, which shares it): a new model from a template, as File >
New does. Units are never implied."""

from __future__ import annotations

from dataclasses import dataclass

from .. import engine, paths
from ..core import Error
from ..registry import Command, Param
from ..schemas import NB, NS, UNITS, WRITTEN, B, S, array, shape, written
from ..transport import Client

SHIPPED = {"mmns": "mm", "inlbs": "in"}


@dataclass(frozen=True)
class Kind:
    word: str  # part, assembly
    extension: str  # prt, asm
    op: str
    shipped: str  # the template file name pattern, {units}
    session_option: str
    datum_planes: tuple

    @property
    def templates(self) -> dict:
        return {
            "mmns": "Creo's shipped " + self.shipped.format(units="mmns"),
            "inlbs": "Creo's shipped " + self.shipped.format(units="inlbs"),
            "session_default": f"the session's {self.session_option} setting",
        }


PART = Kind(
    "part",
    "prt",
    "part.create",
    "{units}_part_solid_abs.prt",
    "template_solidpart",
    ("RIGHT", "TOP", "FRONT"),
)
ASSEMBLY = Kind(
    "assembly",
    "asm",
    "assembly.create",
    "{units}_asm_design_abs.asm",
    "template_designasm",
    ("ASM_RIGHT", "ASM_TOP", "ASM_FRONT"),
)


def creator(kind: Kind):
    command = kind.word + " create"

    def prepare(opts: dict) -> dict:
        name = engine.model_name(opts["name"], (kind.extension,), "name")
        units, template = opts.get("units"), opts.get("template")
        if (units is None) == (template is None):
            raise Error(
                "E_VALIDATION",
                f"give exactly one of --units (mmns, inlbs, session_default) or --template; a "
                f"{kind.word}'s units are never implied",
                {"path": "units"},
            )
        source = None
        if template is not None:
            file = paths.contained(template, directory=False)
            m = paths.MODEL_FILE.fullmatch(file.name)
            if not m or m[2].lower() != kind.extension:
                raise Error(
                    "E_VALIDATION",
                    f"a template must be a {kind.word} file (*.{kind.extension} or "
                    f"*.{kind.extension}.<n>)",
                    {"path": "template"},
                )
            source = paths.artifact(file)
        return {"name": name, "units": units, "template": source}

    def plan(client: Client, opts: dict, pre: dict) -> engine.Plan:
        name, units, source = pre["name"], pre["units"], pre["template"]
        s = engine.session(client)
        cwd = engine.working_directory(s)
        if name in s["models"]:
            raise Error(
                "E_CONFLICT",
                "a model of that name is already in session",
                {"model": name, "_untrusted": ["model"]},
            )
        existing = paths.model_files(cwd, name)
        if existing:
            raise Error(
                "E_CONFLICT",
                f"the working directory already holds files of that name; a new {kind.word} would "
                "be mixed up with them",
                {
                    "files": [f["path"] for f in existing],
                    "fix": "choose another name",
                    "_untrusted": ["files"],
                },
            )
        request = {"name": name, "display": True} | (
            {"units": units} if units else {"template": source["path"]}
        )

        def observe(c: Client):
            models = engine.session(c)["models"]
            return {
                "models": models,
                "files": paths.model_files(cwd, name),
                "model": engine.show(c, name) if name in models else None,
            }

        def verify(c: Client, data: dict):
            written_files = paths.model_files(cwd, name, identity=True)
            actual = engine.show(c, name)
            checks = [
                engine.check(kind.word + "_in_session", name in engine.session(c)["models"]),
                engine.check(kind.word + "_name_as_requested", actual.get("model") == name),
                engine.check("created_model_type", actual.get("type") == kind.word),
                engine.check(
                    "created_model_saved_state_readable",
                    type(actual.get("modified")) is bool,
                    observed_modified=actual.get("modified"),
                ),
                engine.check(
                    "first_version_on_disk",
                    len(written_files) == 1,
                    files=[f["path"] for f in written_files],
                ),
            ]
            if units in SHIPPED:
                length = str(actual["units"].get("length", ""))
                checks += [
                    engine.check(
                        "length_unit_as_requested",
                        length.lower() == SHIPPED[units],
                        expected=SHIPPED[units],
                        actual=length,
                    ),
                    engine.check(
                        "default_datum_planes_present",
                        all(engine.by_name(actual["datum_planes"], p) for p in kind.datum_planes),
                    ),
                ]
            current_files = paths.model_files(cwd, name, identity=True)
            stable = written_files == current_files
            checks.append(
                engine.check(
                    "first_version_stable_during_readback",
                    stable,
                    before=written_files,
                    after=current_files,
                )
            )
            p.persisted = (
                actual["modified"] is False and len(current_files) == 1
                if stable and type(actual.get("modified")) is bool
                else None
            )
            result = data | {
                k: actual.get(k) for k in ("model", "units", "datum_planes", "origin", "modified")
            }
            return result | {
                "artifact": current_files[0] if stable and len(current_files) == 1 else None
            }, {
                "level": "selected_postconditions_verified",
                "checks": checks,
                "observations": [
                    {
                        "observation": "created_model_read_back",
                        "model": actual,
                        "saved_files": current_files if stable else [],
                        "file_evidence_stable": stable,
                    }
                ],
                "not_checked": ["template_contents_beyond_units_and_datums"],
            }

        p = engine.Plan(
            op=kind.op,
            request=request,
            target=name,
            binding={
                "models": s["models"],
                "working_directory": s["working_directory"],
                "template": source or units,
            },
            preview={
                "command": command,
                "creates": name,
                "units": units or "as the template defines",
                "template": source["path"] if source else kind.templates[units],
                "working_directory": str(cwd),
                "writes": f"{name}.1 in the working directory, at once: Creo writes a new "
                f"{kind.word} to disk when it creates it; current memory may subsequently "
                "be modified, in which case a separate explicit save is needed",
                "displayed": True,
            },
            verify=verify,
            observe=observe,
            before=observe(client),
            persisted=None,
            arguments={"name": opts["name"], "units": units, "template": opts.get("template")},
        )
        return p

    def run(opts: dict) -> dict:
        return engine.write(command, opts, prepare, plan)

    return run


def declaration(kind: Kind, description: str, example: str) -> Command:
    return Command(
        kind.word + " create",
        description,
        creator(kind),
        written(CREATED),
        (
            Param("name", required=True, description=f"the new {kind.word}'s name, e.g. {example}"),
            Param(
                "units",
                choices=tuple(kind.templates),
                description="copy Creo's shipped template for these units",
            ),
            Param("template", description=f"or copy this {kind.word} file from the workspace"),
        ),
        write=True,
        untrusted=WRITTEN,
        example=f"--name {example} --units mmns",
        service_ops=(kind.op,),
    )


create = creator(PART)
CREATED = shape(
    {
        "model": S,
        "template": S,
        "units": UNITS,
        "datum_planes": array(S),
        "displayed": B,
        "working_directory": S,
        "origin": NS,
        "modified": NB,
    },
    ("model", "template", "units", "datum_planes", "working_directory"),
)
COMMANDS = [
    declaration(
        PART, "Create a part from a template, as File > New does; units are never implied", "block"
    ),
]
