"""Bounded numeric family-table leaves on owned saved part generics; no hidden replay."""

import math
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from . import driver, engine, machining, model_management, operations, paths, safety
from .core import Error, canonical, digest, read_request, request_path

PROFILE = "dimension-only-v1"
MAX_ROWS = 4
MAX_COLUMNS = 4


def request_source(value):
    if not isinstance(value, str) or value == "-":
        raise Error("E_UNSUPPORTED", "bounded family apply requires an explicit JSON request file")
    path = request_path(value).absolute()
    driver.scope().require(effects=["observe"], paths=[(str(path), "observe")])
    paths.no_links(path)
    before = paths.artifact(path, identity=True)
    data = read_request(str(path))
    if before != paths.artifact(path, identity=True):
        raise Error("E_CONFLICT", "family request changed while being read")
    return data, before


def table(client, name):
    data = engine.normalize(client.op("family.show", {"model": name}))
    validate_table(data)
    if data.get("model") != name:
        raise Error("E_VERIFY_INCOMPLETE", "family table belongs to another model")
    return data


def validate_table(data):
    if not isinstance(data, dict):
        raise Error("E_VERIFY_INCOMPLETE", "native family table is not readable")
    columns, rows = data.get("columns"), data.get("instances")
    if (
        data.get("complete") is not True
        or not isinstance(columns, list)
        or not isinstance(rows, list)
    ):
        raise Error("E_VERIFY_INCOMPLETE", "complete native family table is unavailable")
    if len(rows) > MAX_ROWS or len(columns) > MAX_COLUMNS:
        raise Error("E_UNSUPPORTED", "bounded family table permits at most four rows/four columns")
    if data.get("generic") is not None:
        raise Error("E_UNSUPPORTED", "nested family tables and editing an instance are unsupported")
    symbols, names, dimensions = set(), set(), set()
    for column in columns:
        if not isinstance(column, dict):
            raise Error("E_VERIFY_INCOMPLETE", "native family column is not readable")
        if column.get("kind") != "dimension":
            raise Error("E_UNSUPPORTED", "only numeric dimension columns are supported")
        symbol = column.get("symbol")
        dimension = str(column.get("name") or "").lower()
        if (
            not isinstance(symbol, str)
            or not symbol
            or not isinstance(column.get("name"), str)
            or symbol.lower() in symbols
            or not dimension
            or dimension in dimensions
            or column.get("error")
            or type(column.get("generic_value")) not in (int, float)
            or not math.isfinite(column["generic_value"])
        ):
            raise Error("E_VERIFY_INCOMPLETE", "family column identity is incomplete or repeated")
        symbols.add(symbol.lower())
        dimensions.add(dimension)
    actual_symbols = {c["symbol"] for c in columns}
    for row in rows:
        if not isinstance(row, dict):
            raise Error("E_VERIFY_INCOMPLETE", "native family row is not readable")
        if not isinstance(row.get("name"), str):
            raise Error("E_VERIFY_INCOMPLETE", "native family row identity is unreadable")
        name = row["name"].lower()
        cells = row.get("cells")
        if not name or name in names or not isinstance(cells, dict) or set(cells) != actual_symbols:
            raise Error("E_VERIFY_INCOMPLETE", "family rows/cells are incomplete or contradictory")
        names.add(name)
        for cell in cells.values():
            if not isinstance(cell, dict):
                raise Error("E_VERIFY_INCOMPLETE", "native family cell is not readable")
            value = cell.get("value")
            if (
                cell.get("error")
                or type(cell.get("generic")) is not bool
                or type(value) not in (int, float)
                or not math.isfinite(value)
            ):
                raise Error(
                    "E_VERIFY_INCOMPLETE", "numeric cell value/default readback is incomplete"
                )


def _part(client, name):
    result = machining.snapshot(client, name)
    if (result["model"].get("common_name_readback") or {}).get("readable") is not True:
        raise Error("E_VERIFY_INCOMPLETE", "protected native common name is unreadable")
    for op, key in (("parameter.list", "parameters"), ("relation.list", "relations")):
        value = engine.normalize(client.op(op, {"model": name}))
        if not isinstance(value.get(key), list) or value.get("reading_failures"):
            raise Error("E_VERIFY_INCOMPLETE", "protected part parameters/relations are unreadable")
        result[key] = value[key]
    return result


def snapshot(client, generic, prospective=()):
    client.require_capability("family_dimension_runtime", 1)
    state = model_management.session_state(client)
    rows = {r["model"]: r for r in state["models"]}
    if generic not in rows:
        raise Error("E_NOT_FOUND", "family generic is not loaded")
    selected = model_management.family_identity(rows[generic])
    if selected["kind"] == "instance":
        raise Error(
            "E_UNSUPPORTED",
            "edit the owning generic's table, not an instance",
            {"generic": selected["generic"]},
        )
    root = model_management.saved_origin(rows[generic])
    directory = paths.contained(str(root.parent), directory=True)
    driver.scope().require(effects=["observe"], paths=[(str(directory), "observe")])
    tab = table(client, generic)
    instances = {r["name"].lower() + ".prt" for r in tab["instances"]} | set(prospective)
    parts, files = {}, {}
    for name, row in rows.items():
        if row["type"] != "part":
            raise Error(
                "E_UNSUPPORTED",
                "family writes require a part-only session; "
                "assembly/drawing references are not ignored",
            )
        identity = model_management.family_identity(row)
        member = (
            name in instances
            and identity["kind"] == "instance"
            and identity["generic"].lower() == generic
        )
        if member and (identity["row_count"] or identity["column_count"]):
            raise Error("E_UNSUPPORTED", "nested family members are outside this profile")
        if name != generic and not member and identity["kind"] != "standalone":
            raise Error("E_UNSUPPORTED", "other family/nested models are outside this bounded task")
        allowed = [generic] if member else []
        if any(dep not in allowed for dep in row["dependencies"]):
            raise Error(
                "E_CONFLICT", "part has dependencies outside the selected family", {"model": name}
            )
        origin = row.get("origin_readback") or {}
        if origin.get("complete") is not True or origin.get("value") != row.get("origin"):
            raise Error("E_VERIFY_INCOMPLETE", "family member origin getter is incomplete")
        if member and row["origin"]:
            actual = paths.contained(row["origin"], directory=False)
            driver.scope().require(effects=["observe"], paths=[(str(actual), "observe")])
            if actual.parent != directory:
                raise Error(
                    "E_UNSUPPORTED", "family instance source is outside the bound generic directory"
                )
            paths.artifact(actual, identity=True)
        own_dir = (
            directory
            if member
            else paths.contained(str(model_management.saved_origin(row).parent), directory=True)
        )
        driver.scope().require(effects=["observe"], paths=[(str(own_dir), "observe")])
        detail = _part(client, name)
        if (
            detail["model"].get("origin_readback") != origin
            or detail["model"].get("family") != identity
        ):
            raise Error("E_VERIFY_INCOMPLETE", "independent family/source readers disagree")
        if len(detail["features"]) > 128 or len(detail["geometry"]["items"]) > 4096:
            raise Error("E_UNSUPPORTED", "part exceeds bounded family geometry inventory")
        parts[name] = detail
        files[name] = paths.model_files(own_dir, name, identity=True)
        if not member and not any(engine.same_path(f["path"], row["origin"]) for f in files[name]):
            raise Error("E_VERIFY_INCOMPLETE", "actual source file identity is unavailable")
    for name in instances:
        if name not in files:
            files[name] = paths.model_files(directory, name, identity=True)
    project = []
    for index, p in enumerate(sorted(directory.iterdir())):
        if index >= 4096:
            raise Error("E_UNSUPPORTED", "family project directory inventory exceeds 4096 entries")
        match = paths.MODEL_FILE.fullmatch(p.name)
        if match and match[2].lower() in ("asm", "drw"):
            project.append(paths.artifact(p, identity=True))
    value = {
        "generic": generic,
        "directory": str(directory),
        "session": state,
        "parts": parts,
        "files": files,
        "table": tab,
        "project_references": project,
    }
    if len(canonical(value)) > 768 * 1024:
        raise Error("E_UNSUPPORTED", "family snapshot exceeds 768 KiB")
    return value


def _generic_geometry(state):
    value = deepcopy(state["parts"][state["generic"]])
    for key in ("family", "modified"):
        value["model"].pop(key, None)
    return value


def _table_cells(value):
    return {
        r["name"].lower(): {
            symbol: {"value": cell["value"], "generic": cell["generic"]}
            for symbol, cell in r["cells"].items()
        }
        for r in value["instances"]
    }


def _dimensions(before):
    result = {}
    for row in before["parts"][before["generic"]]["dimensions"]["dimensions"]:
        name = str(row.get("name") or "").lower()
        if not name or name in result:
            raise Error("E_VERIFY_INCOMPLETE", "generic dimension identities are ambiguous")
        result[name] = row
    return result


def _table_contract(table):
    """Semantic columns/rows/cells, not native verification labels or presentation order."""
    validate_table(table)
    return {
        "model": table["model"],
        "units": table["units"],
        "columns": {
            c["symbol"]: {key: c[key] for key in ("symbol", "kind", "name", "generic_value")}
            for c in table["columns"]
        },
        "rows": {
            r["name"].lower(): {
                symbol: {"value": cell["value"], "generic": cell["generic"]}
                for symbol, cell in r["cells"].items()
            }
            for r in table["instances"]
        },
    }


def expected_table(before, values):
    """Derive the complete authorized table only from pre-write native state and intent."""
    expected = _table_contract(before["table"])
    if (
        expected["model"] != before["generic"]
        or expected["units"] != before["parts"][before["generic"]]["model"]["units"]
    ):
        raise Error("E_VERIFY_INCOMPLETE", "frozen table model/units contradict its generic")
    dimensions = _dimensions(before)
    columns = expected["columns"]
    by_name = {c["name"].lower(): c["symbol"] for c in columns.values()}
    for column in columns.values():
        dimension = dimensions.get(column["name"].lower(), {})
        if dimension.get("value") != column["generic_value"]:
            raise Error(
                "E_VERIFY_INCOMPLETE", "column generic value disagrees with native dimension"
            )
    for name in sorted({d for row in values.values() for d in row}):
        dimension = dimensions.get(name)
        if (
            not dimension
            or not dimension.get("name")
            or not dimension.get("type")
            or dimension.get("reference")
        ):
            raise Error("E_VERIFY_INCOMPLETE", "retained intent lacks a driving generic dimension")
        if name not in by_name:
            # Native FamColDimension identity is the referenced dimension's symbol.
            symbol = dimension["name"]
            if symbol in columns:
                raise Error("E_VERIFY_INCOMPLETE", "dimension and column identities contradict")
            columns[symbol] = {
                "symbol": symbol,
                "kind": "dimension",
                "name": dimension["name"],
                "generic_value": dimension["value"],
            }
            by_name[name] = symbol
    for name in sorted(set(expected["rows"]) | set(values)):
        row = expected["rows"].setdefault(name, {})
        for symbol, column in columns.items():
            if symbol not in row:
                row[symbol] = {"value": column["generic_value"], "generic": True}
            if row[symbol]["generic"] and row[symbol]["value"] != column["generic_value"]:
                raise Error("E_VERIFY_INCOMPLETE", "inherited cell contradicts its frozen generic")
        for dimension, value in values.get(name, {}).items():
            row[by_name[dimension]] = {"value": value, "generic": False}
    return expected


def verify(before, intent, after):
    validate_table(before["table"])
    validate_table(after["table"])
    name = before["generic"]
    checks = [
        engine.check(
            "generic_complete_geometry_properties_unchanged",
            digest(_generic_geometry(before)) == digest(_generic_geometry(after)),
        ),
        engine.check("saved_versions_unchanged", before["files"] == after["files"]),
        engine.check(
            "project_reference_files_unchanged",
            before["project_references"] == after["project_references"],
        ),
        engine.check(
            "existing_windows_and_active_context_unchanged",
            {k: v for k, v in before["session"].items() if k != "models"}
            == {k: v for k, v in after["session"].items() if k != "models"},
        ),
    ]
    for other in before["parts"]:
        if other != name:
            checks.append(
                engine.check(
                    "protected_part_unchanged:" + other,
                    before["parts"][other] == after["parts"].get(other),
                )
            )
    old_models = {r["model"]: r for r in before["session"]["models"]}
    new_models = {r["model"]: r for r in after["session"]["models"]}
    for key, row in old_models.items():
        actual = new_models.get(key, {})
        ignored = {"modified", "version_stamp", "family"} if key == name else set()
        checks.append(
            engine.check(
                "native_model_identity_dependencies:" + key,
                {k: v for k, v in row.items() if k not in ignored}
                == {k: v for k, v in actual.items() if k not in ignored},
            )
        )
    old, new = _table_cells(before["table"]), _table_cells(after["table"])
    if intent["kind"] == "remove":
        removed = intent["instance"]
        checks.extend(
            [
                engine.check(
                    "exact_row_removed", new == {k: v for k, v in old.items() if k != removed}
                ),
                engine.check(
                    "columns_unchanged", before["table"]["columns"] == after["table"]["columns"]
                ),
                engine.check(
                    "session_models_unchanged", set(before["parts"]) == set(after["parts"])
                ),
            ]
        )
        return checks
    expected = expected_table(before, intent["values"])
    if "expected_table" in intent and intent["expected_table"] != expected:
        raise Error("E_VERIFY_INCOMPLETE", "retained table intent contradicts its frozen inputs")
    actual_table = _table_contract(after["table"])
    columns = {c["name"].lower(): c["symbol"] for c in expected["columns"].values()}
    expected_names = set(expected["rows"])
    checks.extend(
        [
            engine.check(
                "complete_expected_family_columns",
                actual_table["columns"] == expected["columns"],
                expected=expected["columns"],
                observed=actual_table["columns"],
            ),
            engine.check(
                "complete_expected_family_cells_and_defaults",
                actual_table["rows"] == expected["rows"],
                expected=expected["rows"],
                observed=actual_table["rows"],
            ),
            engine.check(
                "family_model_and_units",
                actual_table["model"] == expected["model"]
                and actual_table["units"] == expected["units"],
            ),
        ]
    )
    checks.append(engine.check("exact_family_rows", set(new) == expected_names))
    checks.append(
        engine.check(
            "planned_instances_only_in_session",
            set(after["parts"]) == set(before["parts"]) | {n + ".prt" for n in expected_names},
        )
    )
    for instance, values in intent["values"].items():
        for dimension, wanted in values.items():
            cell = new.get(instance, {}).get(columns.get(dimension), {})
            checks.append(
                engine.check(
                    "cell:" + instance + ":" + dimension,
                    cell.get("value") == wanted and cell.get("generic") is False,
                    expected=wanted,
                    observed=cell.get("value"),
                )
            )
    changed = {n: set(v) for n, v in intent["values"].items()}
    old_columns = {c["symbol"]: c for c in before["table"]["columns"]}
    for instance, cells in old.items():
        for symbol, cell in cells.items():
            if old_columns[symbol]["name"].lower() not in changed.get(instance, set()):
                checks.append(
                    engine.check(
                        "unselected_cell:" + instance + ":" + symbol,
                        new.get(instance, {}).get(symbol) == cell,
                    )
                )
    by_name = _dimensions(before)
    for instance in sorted(expected_names):
        part = after["parts"].get(instance + ".prt")
        if part is None:
            checks.append(engine.check("instance_readable:" + instance, False))
            continue
        identity = model_management.family_identity(part["model"])
        native_identity = new_models.get(instance + ".prt", {}).get("family")
        checks.append(
            engine.check(
                "instance_belongs_to_generic:" + instance,
                identity["kind"] == "instance"
                and str(identity["generic"]).lower() == name
                and identity["row_count"] == 0
                and identity["column_count"] == 0
                and identity == native_identity,
                expected={"kind": "instance", "generic": name},
                observed=identity,
            )
        )
        dimensions = {d["name"].lower(): d for d in part["dimensions"]["dimensions"]}
        for dimension, base in by_name.items():
            cell = expected["rows"][instance].get(columns.get(dimension))
            wanted = cell["value"] if cell else base["value"]
            actual = dimensions.get(dimension, {})
            checks.append(
                engine.check(
                    "instance_dimension:" + instance + ":" + dimension,
                    actual.get("units") == base.get("units") and actual.get("value") == wanted,
                    expected=wanted,
                    observed=actual.get("value"),
                )
            )
        actual = part["model"]
        mass = actual.get("mass_properties") or {}
        checks.append(
            engine.check(
                "instance_native_solid_and_features:" + instance,
                actual.get("units") == before["parts"][name]["model"]["units"]
                and type(mass.get("volume")) in (int, float)
                and mass["volume"] > 0
                and bool(part["geometry"]["items"])
                and all(
                    f.get("status") == "FEAT_ACTIVE"
                    for f in part["features"]
                    if f.get("visible") is True
                ),
            )
        )
    return checks


def removal_basis(client, before, instance):
    """Only same-generation owned rows with an explicit saved generic baseline."""
    name = before["generic"]
    saved = model_management.saved_baseline(
        client, name, {"files": before["files"], "model": before["parts"][name]["model"]}
    )
    saved_run = operations.get(saved["save_operation_id"])
    writers = []
    creator = None
    for run in operations.all_runs():
        if run.get("command") not in ("family-table apply", "family-table remove-instance"):
            continue
        plan = run.get("driver_plan") or {}
        target = plan.get("target") or {}
        if (
            target.get("instance_id") != client.health()["service_instance_id"]
            or target.get("object_id") != name
        ):
            continue
        if run.get("status") not in ("completed", "resolved_manual"):
            continue
        if run.get("status") == "resolved_manual" and not driver.resolution_evidence_trusted(run):
            continue
        retained = (
            plan["base_snapshot"].get("extensions", {}).get("creo", {}).get("observation", {})
        )
        old = retained.get("family_before") or {}
        if not engine.same_path(old.get("directory", ""), before["directory"]):
            continue
        at = run.get("finished_at") or (run.get("driver_resolution") or {}).get("resolved_at")
        if not at:
            continue
        writers.append((at, run))
        intended = retained.get("family_intent") or {}
        outcome = (run.get("driver_receipt") or {}).get("outcome") or {}
        applied = (
            outcome.get("change") == "applied"
            and outcome.get("verification", {}).get("status") == "passed"
        ) or (run.get("driver_family_table_resolution") or {}).get(
            "registered_outcome"
        ) == "applied"
        if (
            applied
            and instance in intended.get("values", {})
            and instance not in _table_cells(old["table"])
        ):
            proof_state = run.get("driver_effect_readback")
            if not proof_state and run.get("driver_family_table_resolution"):
                proof_state = operations.load_query(
                    run["driver_family_table_resolution"]["evidence_id"]
                )["observation"]["family_table_verification"]["current"]
            if not proof_state or not all(c["passed"] for c in verify(old, intended, proof_state)):
                raise Error(
                    "E_VERIFY_INCOMPLETE",
                    "historical row creation does not prove the complete authorized table",
                    {"operation_id": run["operation_id"]},
                )
            creator = run["operation_id"]
    if creator is None or not writers:
        raise Error(
            "E_UNSUPPORTED",
            "remove-instance requires a row created by a verified public apply "
            "in this instance and owned directory",
        )
    require_no_known_external_use(client, instance, operations.get(creator))
    at, latest = max(writers, key=lambda item: item[0])
    if not saved_run.get("finished_at") or saved_run["finished_at"] < at:
        raise Error(
            "E_CONFLICT",
            "save and verify the generic after the last family write before removing a row",
        )
    observed = latest.get("driver_effect_readback")
    if not observed and latest.get("driver_family_table_resolution"):
        proof = operations.load_query(latest["driver_family_table_resolution"]["evidence_id"])
        observed = proof["observation"]["family_table_verification"]["current"]
    if (
        not observed
        or _table_cells(observed["table"]) != _table_cells(before["table"])
        or observed["table"]["columns"] != before["table"]["columns"]
    ):
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "current table differs from the independently verified owned family baseline",
        )
    return {
        "created_by_operation": creator,
        "latest_family_operation": latest["operation_id"],
        "saved_baseline": saved,
        "dependency_scope": "complete current part-only session and owned generic directory; "
        "no dispatched external reference since row creation; no global disk reference claim",
    }


def require_no_known_external_use(client, instance, creator):
    """Closing an assembly/drawing does not erase its retained reference evidence."""
    generation = client.health()["service_instance_id"]
    created_at = creator.get("started_at") or creator["at"]
    member = instance.lower() + ".prt"
    for run in operations.all_runs():
        if not run.get("started_at") or run["started_at"] < created_at:
            continue
        plan = run.get("driver_plan") or {}
        target = plan.get("target") or {}
        if target.get("instance_id") != generation or not str(
            target.get("object_id", "")
        ).lower().endswith((".asm", ".drw")):
            continue
        outcome = (run.get("driver_receipt") or {}).get("outcome") or {}
        if (
            run.get("status") in ("failed_before_write", "failed_unchanged")
            or outcome.get("change") == "not_applied"
        ):
            continue
        dependencies = plan.get("base_snapshot", {}).get("dependencies", [])
        if any(str(row.get("identity", "")).lower() == member for row in dependencies):
            raise Error(
                "E_CONFLICT",
                "instance has a retained external reference; closing the referencing model "
                "does not prove the row unused. External reference removal is outside this profile",
                {
                    "instance": member,
                    "reference_model": target["object_id"],
                    "operation_id": run["operation_id"],
                },
            )


def _plan(client, opts, pre, kind):
    name = pre["name"]
    q = pre.get("request", {})
    prospective = {r["name"].lower() + ".prt" for r in q.get("instances", [])}
    before = snapshot(client, name, prospective)
    if opts.get("confirm"):
        previous = operations.get(safety.token_operation(opts["confirm"]))
        retained = (
            previous["driver_plan"]["base_snapshot"]
            .get("extensions", {})
            .get("creo", {})
            .get("observation", {})
        )
        if digest(retained.get("family_before")) != digest(before):
            raise Error(
                "E_CONFLICT",
                "family model/table/window/file state changed after preview",
                {"conflict": "state_drift", "dispatch_state": "not_started"},
            )
    family = model_management.family_identity(before["parts"][name]["model"])
    if family["kind"] == "instance" or before["parts"][name]["relations"]:
        raise Error(
            "E_UNSUPPORTED",
            "nested/related generics and model relations are outside the numeric family profile",
        )
    volume = (before["parts"][name]["model"].get("mass_properties") or {}).get("volume")
    if type(volume) not in (int, float) or not math.isfinite(volume) or volume <= 0:
        raise Error("E_UNSUPPORTED", "bounded family editing requires a readable nonempty solid")
    existing = {r["name"].lower() for r in before["table"]["instances"]}
    all_names = existing | {n[:-4] for n in prospective}
    if len(all_names) > MAX_ROWS:
        raise Error("E_UNSUPPORTED", "bounded family tasks permit at most four instance rows")
    if any(n + ".prt" in before["parts"] for n in all_names):
        raise Error(
            "E_CONFLICT",
            "family instances must be explicitly saved and closed before this write; "
            "no implicit erase",
        )
    if before["project_references"]:
        raise Error(
            "E_UNSUPPORTED",
            "owned family directory contains assembly/drawing files; "
            "dependency absence is not proven",
        )
    intent = {"kind": kind, "model": name}
    if kind == "apply":
        from .commands.family import _items

        # Do not inspect closed arbitrary/nested legacy rows by instantiating them in preview.
        # Editing retained rows is limited to this generation's verified owned flat family.
        if existing:
            intent["existing_row_basis"] = {
                n: removal_basis(client, before, n) for n in sorted(existing)
            }

        found = _items(client, name, q, before["parts"][name]["model"])
        if any(v["kind"] != "dimension" or v.get("units") != q["units"] for v in found.values()):
            raise Error("E_UNSUPPORTED", "family profile permits explicit length dimensions only")
        if any(
            len(row["values"]) != len({found[key]["name"].lower() for key in row["values"]})
            for row in q["instances"]
        ):
            raise Error("E_VALIDATION", "each actual dimension may be assigned only once per row")
        values = {
            r["name"].lower(): {found[k]["name"].lower(): v for k, v in r["values"].items()}
            for r in q["instances"]
        }
        requested_columns = {d for v in values.values() for d in v} | {
            c["name"].lower() for c in before["table"]["columns"]
        }
        if len(requested_columns) > MAX_COLUMNS:
            raise Error("E_UNSUPPORTED", "family task permits at most four dimension columns")
        if name[:-4] in all_names:
            raise Error("E_CONFLICT", "an instance cannot use its generic's model name")
        if any(before["files"].get(n + ".prt") for n in all_names - existing):
            raise Error("E_CONFLICT", "new instance name conflicts with an existing model file")
        intent.update(values=values, requested_columns=sorted(requested_columns))
        intent["expected_table"] = expected_table(before, values)
        request = {
            "model": name,
            "instances": q["instances"],
            "profile": PROFILE,
            "inspect_instances": sorted(all_names),
        }
        command, op = "family-table apply", "family.set"
    else:
        instance = pre["instance"].lower()
        if instance not in existing:
            raise Error("E_NOT_FOUND", "family table has no exact selected instance")
        if before["parts"][name]["model"].get("modified") is not False:
            raise Error("E_CONFLICT", "save and verify the generic baseline before removing a row")
        intent["instance"] = instance
        intent["removal_basis"] = removal_basis(client, before, instance)
        request = {"model": name, "instance": instance, "profile": PROFILE}
        command, op = "family-table remove-instance", "family.remove"
    footprint = sorted(set(before["parts"]) | {n + ".prt" for n in all_names})
    driver.require_clear(
        driver.target(
            client,
            SimpleNamespace(
                target=name, op=op, request=request, preview={"model_footprint": footprint}
            ),
        ),
        footprint,
    )
    bound = {"family_profile": PROFILE, "family_before": before, "family_intent": intent}
    if "source" in pre:
        bound["request_file"] = pre["source"]

    def observe(c):
        return snapshot(c, name, {n + ".prt" for n in all_names})

    def check(c, data):
        after = observe(c)
        checks = verify(before, intent, after)
        if all(t["passed"] for t in checks):
            p.verified_observation = deepcopy(after)
        return data | {"readback": after}, {
            "level": "selected_postconditions_verified",
            "checks": checks,
            "not_checked": [
                "save/reopen; separate explicit steps",
                "global disk references outside the owned directory and current session",
                "independent B-rep consumer/task design-intent acceptance",
            ],
        }

    scope_paths = [
        (str(Path(v[0]["path"]).parent), "change" if n == name else "observe")
        for n, v in before["files"].items()
        if v
    ]
    if "source" in pre:
        scope_paths.append((pre["source"]["path"], "observe"))
    p = engine.Plan(
        op=op,
        target=name,
        request=request,
        binding=bound,
        preview={
            "command": command,
            "model": name,
            "table_now": before["table"],
            "intent": intent,
            "model_footprint": footprint,
            "scope_paths": scope_paths,
            "effect": (
                "edit only declared numeric cells; instantiate inspected rows for "
                "independent native readback and retain them in session; "
                "explicit generic save and clean closes follow"
            )
            if kind == "apply"
            else "remove only the exact unused row; no implicit close, cascade or disk deletion",
            "instance_count": len(all_names),
            "limits": [
                "one saved generic; four rows/four numeric length columns",
                "no open instances at dispatch, nested tables, expressions, feature columns "
                "or assembly/drawing dependencies",
                "no automatic continuation or rollback claim",
            ],
        },
        verify=check,
        observe=observe,
        before=before,
        arguments={k: opts[k] for k in ("model", "request", "instance") if k in opts},
    )
    return p


def plan_apply(client, opts, pre):
    return _plan(client, opts, pre, "apply")


def plan_remove(client, opts, pre):
    return _plan(client, opts, pre, "remove")


def recovery(client, run):
    plan = run["driver_plan"]
    retained = plan["base_snapshot"].get("extensions", {}).get("creo", {}).get("observation", {})
    before, intent = retained.get("family_before"), retained.get("family_intent")
    if not before or not intent:
        raise Error("E_VERIFY_INCOMPLETE", "retained family baseline/intent unavailable")
    if client.health()["service_instance_id"] != plan["target"]["instance_id"]:
        raise Error(
            "E_VERIFY_INCOMPLETE", "another instance cannot establish the old family outcome"
        )
    prospective = {r["name"].lower() + ".prt" for r in before["table"]["instances"]} | {
        n + ".prt" for n in intent.get("values", {})
    }
    after = snapshot(client, before["generic"], prospective)
    second = snapshot(client, before["generic"], prospective)
    if intent["kind"] == "apply" and digest(before) != digest(after):
        if not prospective.issubset(after["parts"]):
            raise Error(
                "E_VERIFY_INCOMPLETE",
                "instance geometry needed for family recovery is absent; "
                "queries do not instantiate or replay rows",
            )
    checks = verify(before, intent, after)
    stable = digest(after) == digest(second)
    checks.append(engine.check("independent_observation_stable", stable))
    accepted = all(c["passed"] for c in checks)
    return {
        "accepted": accepted,
        "checks": checks,
        "current": after,
        "intent": intent,
        "can_register": []
        if not stable
        else ["not_applied"]
        if digest(before) == digest(after)
        else ["applied"]
        if accepted
        else ["partial"],
        "coverage": "complete bounded table, native instance dimensions/solid inventories, "
        "generic/protected states and saved files; no replay",
    }


def retained_evidence_sufficient(run, proof):
    retained = (
        run["driver_plan"]["base_snapshot"]
        .get("extensions", {})
        .get("creo", {})
        .get("observation", {})
    )
    if retained.get("family_profile") != PROFILE or proof.get("intent") != retained.get(
        "family_intent"
    ):
        raise Error("E_VERIFY_INCOMPLETE", "retained bounded family profile/intent unavailable")
    before = retained["family_before"]
    after = proof.get("current")
    checks = verify(before, retained["family_intent"], after)
    if proof.get("accepted") is not all(c["passed"] for c in checks):
        raise Error(
            "E_VERIFY_INCOMPLETE", "recorded family conclusion lacks complete current proof"
        )
