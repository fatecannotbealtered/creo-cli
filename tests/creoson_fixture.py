"""Stateful HTTP protocol substitute. No Creo, PTC SDK, or valid CAD files.

This fixture is intentionally independent of the CLI's dispatcher and catalog;
API names and response shapes are spelled out from the published interfaces.
It tests transport/control behavior, never real CAD geometry or SDK compatibility.
"""
from __future__ import annotations

import copy
import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

# Upper bound for World.block. A test releases its event as soon as the CLI call
# returns, so this ceiling is never reached in a passing run; it exists so a broken
# test fails instead of hanging the suite. Chosen well above the largest client
# deadline any test sets (seconds), not tuned to a machine's speed.
BLOCK_CEILING_SECONDS = 30.0


class World:
    def __init__(self, root: Path):
        self.root = root
        (root / "exports").mkdir()
        (root / "templates").mkdir()
        (root / "templates" / "a4.drw").write_bytes(b"TEST FIXTURE NOT A REAL CREO DRAWING")
        self.sid = "fixture-session-private-12345"
        self.loaded = ["bracket.prt", "device.asm", "bracket.drw"]
        self.active = "bracket.prt"
        self.major = None
        self.events = []
        self.fail = None
        self.drop = None
        self.delay = None
        self.block = None
        # Creo's working directory is session state that `creo cd` moves; the server's
        # own directory is deliberately a different value so tests can tell them apart.
        self.cwd = root
        self.server_dir = root / "server-home"
        self.server_dir.mkdir(exist_ok=True)
        self.config = {"pro_unit_length": ["unit_mm"], "regen_failure_handling": ["resolve_mode"]}
        self.bad_json = False
        self.http_status = None
        self.skip_mutation = False
        self.models = {}
        for name in self.loaded:
            (root / name).write_bytes(b"NOT A REAL CREO MODEL: " + name.encode())
            self.models[name] = {"parameters": [{"name": "PART_NO", "type": "STRING", "value": "OLD", "encoded": False}],
                "dimensions": [{"name": "d1", "value": 40.0, "text": ["{0:@D}\n"], "dim_type": "linear", "dwg_dim": False, "encoded": False},
                               {"name": "d2", "value": 5.0, "dim_type": "diameter", "dwg_dim": False, "encoded": False}],
                "features": [{"name": "HOLE_1", "feat_id": 10, "feat_number": 1, "type": "HOLE", "status": "ACTIVE"},
                             {"name": "PRT_CSYS_DEF", "feat_id": 11, "feat_number": 2, "type": "COORDINATE SYSTEM", "status": "ACTIVE"},
                             {"name": "ASM_DEF_CSYS", "feat_id": 12, "feat_number": 3, "type": "COORDINATE SYSTEM", "status": "ACTIVE"}],
                "relations": [], "postregen_relations": [], "length_units": "mm", "mass_units": "kg",
                "materials": ["ALUMINUM", "STEEL"], "material": "STEEL", "views": ["FRONT", "TOP", "RIGHT"],
                "models": ["bracket.prt"], "drawing_views": [{"name": "FRONT_MAIN", "sheet": 1, "location": {"x": 10, "y": 10, "z": 0}, "view_model": "bracket.prt"}], "sheets": 1,
                "layers": {"DATUMS": "HIDDEN", "PART_GEOM": "SHOWN"},
                "notes": {"NOTE_1": "BREAK SHARP EDGES"},
                "feature_params": {"HOLE_1": {"DEPTH": "THRU"}},
                "exploded_views": ["EXPLODE_1"], "simp_reps": ["MASTER"], "instances": ["bracket_s.prt"],
                "family": {"bracket_s": {"d1": 30.0}, "bracket_l": {"d1": 60.0}},
                "family_columns": {"d1": "DOUBLE"}, "family_parents": [],
                "cur_sheet": 1, "cur_model": "bracket.prt", "sheet_scale": 1.0,
                "symbols": ["note.sym"], "symbol_defs": ["note.sym"]}

    def handle(self, body):
        cmd, fn, q = body["command"], body["function"], body.get("data") or {}
        self.events.append((cmd, fn, copy.deepcopy(q)))
        if self.delay and self.delay[:2] == (cmd, fn):
            time.sleep(self.delay[2])
        if self.block and self.block[:2] == (cmd, fn):
            # Withhold this one response until the test releases it. A client deadline
            # then always expires with the request already sent, instead of depending on
            # a fixed sleep outlasting however long the preliminary reads took.
            self.block[2].wait(BLOCK_CEILING_SECONDS)
        if self.fail == (cmd, fn):
            return {"status": {"error": True, "message": "fixture error with " + self.sid}}
        if cmd == "connection" and fn == "connect":
            return {"status": {"error": False}, "sessionId": self.sid}
        if cmd == "connection" and fn == "is_creo_running":
            return {"status": {"error": False}, "data": {"running": True}}
        if body.get("sessionId") != self.sid:
            return {"status": {"error": True, "message": "unknown session"}}
        result = self.operation(cmd, fn, q)
        if self.drop == (cmd, fn):
            return None  # request may have completed; intentionally lose reply
        return {"status": {"error": False}, "data": result}

    def operation(self, cmd, fn, q):
        name = q.get("file") or q.get("drawing") or q.get("asm") or self.active
        m = self.models.get(name, {})
        if cmd == "server":
            if fn == "pwd": return {"dirname": str(self.server_dir)}
        if cmd == "geometry":
            if fn == "bound_box": return {"xmin": -10.0, "xmax": 90.0, "ymin": -5.0, "ymax": 45.0, "zmin": 0.0, "zmax": 12.0}
            if fn == "get_surfaces":
                return {"surflist": [{"surface_id": 1, "area": 4050.0,
                                      "min_extent": {"x": -10.0, "y": -5.0, "z": 0.0},
                                      "max_extent": {"x": 90.0, "y": 45.0, "z": 0.0}}]}
            if fn == "get_edges":
                return {"contourlist": [{"surface_id": sid, "traversal": "external",
                                         "edgelist": [{"edge_id": 11, "length": 100.0, "edge_type": "LINE",
                                                       "start": {"x": -10.0, "y": -5.0, "z": 0.0},
                                                       "end": {"x": 90.0, "y": -5.0, "z": 0.0}}]}
                                        for sid in q["surface_ids"]]}
        if cmd == "familytable":
            table = m.setdefault("family", {})
            if fn == "list":
                rows = sorted(table)
                return {"instances": [r for r in rows if r == q["instance"]] if q.get("instance") else rows}
            if fn == "exists": return {"exists": q["instance"] in table}
            if fn == "get_header":
                return {"columns": [{"colid": c, "datatype": d, "coltype": "DIMENSION"}
                                    for c, d in m.get("family_columns", {}).items()]}
            if fn == "get_row":
                row = table.get(q["instance"], {})
                return {"instance": q["instance"],
                        "columns": [{"colid": c, "value": v, "datatype": m.get("family_columns", {}).get(c, "STRING"),
                                     "coltype": "DIMENSION"} for c, v in row.items()]}
            if fn == "get_cell":
                row = table.get(q["instance"], {})
                return {"instance": q["instance"], "colid": q["colid"], "value": row.get(q["colid"]),
                        "datatype": m.get("family_columns", {}).get(q["colid"], "STRING"), "coltype": "DIMENSION"}
            if fn == "get_parents": return {"parents": list(m.get("family_parents", []))}
            if fn == "list_tree":
                return {"total": len(table), "children": [{"name": n, "total": 0, "children": []} for n in sorted(table)]}
            if self.skip_mutation: return {}
            if fn == "create_inst":
                made = q["instance"] + ".prt"
                if made not in self.loaded: self.loaded.append(made)
                self.models.setdefault(made, copy.deepcopy(m))
                return {"name": made}
            if fn == "add_inst": table.setdefault(q["instance"], {}); return None
            if fn == "delete_inst": table.pop(q["instance"], None); return None
            if fn == "delete": m["family"] = {}; m["instances"] = []; return None
            if fn == "set_cell": table.setdefault(q["instance"], {})[q["colid"]] = q["value"]; return None
            if fn == "replace": return None
        if cmd == "layer":
            if fn == "list":
                rows = [{"name": n, "status": s, "id": i} for i, (n, s) in enumerate(m.get("layers", {}).items(), start=1)]
                return {"layers": [r for r in rows if r["name"] == q["name"]] if q.get("name") else rows}
            if fn == "exists": return {"exists": q.get("name") in m.get("layers", {})}
        if cmd == "note":
            notes = m.get("notes", {})
            if fn == "list":
                rows = [{"name": n, "value": v, "value_expanded": v, "encoded": False} for n, v in notes.items()]
                return {"itemlist": [r for r in rows if r["name"] == q["name"]] if q.get("name") else rows}
            if fn == "exists": return {"exists": q.get("name") in notes}
            if fn == "get":
                if q["name"] not in notes: return {"status": {"error": True, "message": "no such note"}}
                return {"name": q["name"], "value": notes[q["name"]], "encoded": False,
                        "url": "", "location": {"x": 0.0, "y": 0.0, "z": 0.0}}
        if cmd == "creo":
            if fn == "pwd": return {"dirname": str(self.cwd)}
            if fn == "set_creo_version": self.major = q["version"]; return None
            if fn == "get_config": return {"values": list(self.config.get(q["name"], []))}
            if fn == "list_files":
                return {"filelist": sorted(p.name for p in self.cwd.glob(q.get("filename") or "*") if p.is_file())}
            if fn == "list_dirs":
                return {"dirlist": sorted(p.name for p in self.cwd.glob(q.get("dirname") or "*") if p.is_dir())}
            if self.skip_mutation: return {}
            if fn == "cd":
                target = Path(q["dirname"])
                if not target.is_dir(): return None
                self.cwd = target
                return {"dirname": str(self.cwd)}
            if fn == "mkdir":
                Path(q["dirname"]).mkdir(parents=True, exist_ok=True)
                return {"dirname": q["dirname"]}
            if fn == "rmdir":
                target = Path(q["dirname"])
                if target.is_dir(): target.rmdir()
                return None
            if fn == "set_config":
                self.config[q["name"]] = [q["value"]]
                return None
        if cmd == "file":
            if fn == "list": return {"files": list(self.loaded)}
            if fn == "get_active": return {"file": self.active, "dirname": str(self.root)}
            if fn == "get_fileinfo": return {"file": name, "dirname": str(self.root), "revision": 1}
            if fn == "get_length_units": return {"units": m["length_units"]}
            if fn == "get_mass_units": return {"units": m["mass_units"]}
            if fn == "relations_get": return {"relations": m["relations"]}
            if fn == "postregen_relations_get": return {"relations": m["postregen_relations"]}
            if fn == "list_instances": return {"generic": name, "dirname": str(self.root), "files": ["bracket_s.prt", "bracket_l.prt"]}
            if fn == "list_materials": return {"materials": m["materials"]}
            if fn == "get_cur_material": return {"material": m["material"]}
            if fn == "massprops": return {"mass": 0.27, "volume": 100000.0, "density": 0.0000027, "surface_area": 2200, "ctr_grav": {"x": 1, "y": 2, "z": 3}}
            if fn == "get_transform": return {"origin": {"x": 0, "y": 0, "z": 0}, "x_axis": {"x": 1, "y": 0, "z": 0}, "y_axis": {"x": 0, "y": 1, "z": 0}, "z_axis": {"x": 0, "y": 0, "z": 1}, "x_rot": 0.0, "y_rot": 0.0, "z_rot": 0.0}
            if fn == "open_errors": return {"errors": False}
            if fn == "exists": return {"exists": name in self.loaded}
            if fn == "is_active": return {"active": name == self.active}
            if fn == "get_accuracy": return {"accuracy": 0.0012, "relative": True}
            if fn == "get_unit_system": return {"name": "mmNs"}
            if fn == "has_instances": return {"exists": bool(m.get("instances"))}
            if fn == "list_simp_reps": return {"reps": list(m.get("simp_reps", []))}
            if self.skip_mutation: return {}
            if fn in ("refresh", "repaint"): return None
            if fn == "open":
                saved = self.root / (name + ".2")
                if saved.exists() and saved.read_bytes().startswith(b"SIMULATED SAVE "):
                    self.models[name] = json.loads(saved.read_bytes()[len(b"SIMULATED SAVE "):])
                self.loaded.append(name); self.active = name
                return {"files": [name], "dirname": q["dirname"], "revision": 1}
            if fn == "erase": self.loaded.remove(name); return None
            if fn == "display": self.active = name; return None
            if fn in ("regenerate", "close_window"): return None
            if fn == "save": (self.root / (name + ".2")).write_bytes(b"SIMULATED SAVE " + json.dumps(m).encode()); return None
            if fn == "backup":
                (Path(q["target_dir"]) / name).write_bytes(b"SIMULATED BACKUP ONLY"); return None
            if fn == "set_cur_material": m["material"] = q["material"]; return {"files": [name]}
            if fn == "assemble":
                asm = self.models[q["into_asm"]]
                fid = max(x["feat_id"] for x in asm["features"]) + 1
                asm["features"].append({"name": "COMPONENT_" + str(fid), "feat_id": fid, "feat_number": fid, "type": "COMPONENT", "status": "ACTIVE"})
                return {"files": [name], "dirname": str(self.root), "revision": 1, "featureid": fid}
        if cmd == "parameter":
            if fn == "list": return {"paramlist": [x for x in m["parameters"] if "name" not in q or x["name"].lower() == q["name"].lower()]}
            if fn == "exists": return {"exists": any(x["name"] == q.get("name") for x in m["parameters"])}
            if fn == "set":
                if not self.skip_mutation:
                    old = next((x for x in m["parameters"] if x["name"] == q["name"]), None)
                    if old is None:
                        if q["no_create"]: raise ValueError("not created")
                        old = {"name": q["name"], "encoded": False}; m["parameters"].append(old)
                    old.update(type=q["type"], value=q["value"])
                return None
        if cmd == "dimension":
            if fn == "list_detail": return {"dimlist": [x for x in m["dimensions"] if "name" not in q or x["name"] == q["name"]]}
            if fn == "set":
                if not self.skip_mutation: next(x for x in m["dimensions"] if x["name"] == q["name"])["value"] = q["value"]
                return None
        if cmd == "feature":
            if fn == "list": return {"featlist": m["features"]}
            if fn == "list_params":
                owned = m.get("feature_params", {})
                rows = [{"name": k, "value": v, "type": "STRING", "encoded": False, "owner_name": q.get("name", ""), "owner_type": "FEATURE"}
                        for k, v in owned.get(q.get("name"), {}).items()]
                return {"paramlist": [r for r in rows if r["name"] == q["param"]] if q.get("param") else rows}
            if fn == "param_exists":
                return {"exists": q.get("param") in m.get("feature_params", {}).get(q["name"], {})}
            row = next(x for x in m["features"] if x["name"] == q["name"])
            if not self.skip_mutation:
                if fn == "rename": row["name"] = q["new_name"]
                elif fn == "suppress": row["status"] = "SUPPRESSED"
                elif fn == "resume": row["status"] = "ACTIVE"
                else: raise ValueError((cmd, fn))
            return None
        if cmd == "view":
            if fn == "list": return {"viewlist": m["views"]}
            if fn == "list_exploded": return {"viewlist": list(m.get("exploded_views", []))}
            if fn == "activate": return None
            if fn == "save":
                if not self.skip_mutation: m["views"].append(q["name"])
                return None
        if cmd == "bom" and fn == "get_paths":
            return {"file": name, "generic": name, "children": [{"file": "bracket.prt", "path": [39], "seq_path": "root.1"}], "has_simprep": False}
        if cmd == "drawing":
            views = m.get("drawing_views", [])
            row = next((v for v in views if v["name"] == q.get("view")), {})
            if fn == "get_cur_sheet": return {"sheet": m.get("cur_sheet", 1)}
            if fn == "get_cur_model": return {"file": m.get("cur_model", "bracket.prt")}
            if fn == "get_sheet_size": return {"size": "A4"}
            if fn == "get_sheet_scale": return {"scale": m.get("sheet_scale", 1.0)}
            if fn == "get_sheet_format":
                return {"file": "a4.drw", "full_name": "a4", "common_name": "A4 FORMAT"}
            if fn == "list_views":
                names = [v["name"] for v in views]
                return {"views": [n for n in names if n == q["view"]] if q.get("view") else names}
            if fn == "get_view_loc": return dict(row.get("location", {"x": 0.0, "y": 0.0, "z": 0.0}))
            if fn == "get_view_scale": return {"scale": row.get("scale", 1.0)}
            if fn == "get_view_sheet": return {"sheet": row.get("sheet", 1)}
            if fn == "view_bound_box": return {"xmin": 0.0, "xmax": 80.0, "ymin": 0.0, "ymax": 40.0}
            if fn == "list_symbols":
                return {"symbols": [{"id": i, "symbol_name": n, "sheet": 1}
                                    for i, n in enumerate(m.get("symbols", []), start=1)]}
            if fn == "is_symbol_def_loaded": return {"loaded": q.get("symbol_file") in m.get("symbol_defs", [])}
            if self.skip_mutation: return {}
            if fn == "select_sheet": m["cur_sheet"] = q["sheet"]; return None
            if fn == "regenerate_sheet": return None
            if fn == "scale_sheet": m["sheet_scale"] = q["scale"]; return None
            if fn == "set_sheet_format": m["sheet_format"] = q["file"]; return None
            if fn == "delete_sheet": m["sheets"] = max(1, m.get("sheets", 1) - 1); return None
            if fn == "set_cur_model": m["cur_model"] = q["model"]; return None
            if fn == "delete_models":
                m["models"] = [x for x in m.get("models", []) if x != q["model"]]
                return None
            if fn == "rename_view":
                for v in views:
                    if v["name"] == q["view"]: v["name"] = q["new_view"]
                return None
            if fn == "set_view_loc":
                for v in views:
                    if v["name"] == q["view"]: v["location"] = dict(q["point"])
                return None
            if fn == "scale_view":
                hit = [v for v in views if v["name"] == q["view"]]
                for v in hit: v["scale"] = q["scale"]
                return {"success_views": [v["name"] for v in hit], "failed_views": []}
            if fn == "delete_view":
                m["drawing_views"] = [v for v in views if v["name"] != q["view"]]
                return None
            if fn == "load_symbol_def":
                m.setdefault("symbol_defs", []).append(q["symbol_file"])
                return {"id": 7, "name": q["symbol_file"]}
            if fn == "create_symbol": m.setdefault("symbols", []).append(q["symbol_file"]); return None
            if fn == "delete_symbol_def":
                m["symbol_defs"] = [x for x in m.get("symbol_defs", []) if x != q["symbol_file"]]
                return None
            if fn == "delete_symbol_inst":
                placed = m.get("symbols", [])
                index = int(q["symbol_id"]) - 1
                if 0 <= index < len(placed): placed.pop(index)
                return None
        if cmd == "drawing":
            if fn == "list_models": return {"files": m["models"]}
            if fn == "list_view_details": return {"views": m["drawing_views"]}
            if fn == "get_num_sheets": return {"num_sheets": m["sheets"]}
            if self.skip_mutation: return {}
            if fn == "create":
                self.loaded.append(q["drawing"])
                self.models[q["drawing"]] = copy.deepcopy(self.models[q["model"]])
                self.models[q["drawing"]].update(models=[q["model"]], sheets=1, drawing_views=[])
                self.active = q["drawing"]
                return {"drawing": q["drawing"]}
            if fn == "add_model": m["models"].append(q["model"]); return None
            if fn == "add_sheet": m["sheets"] += 1; return None
            if fn in ("create_gen_view", "create_proj_view"):
                m["drawing_views"].append({"name": q["view"], "sheet": q["sheet"], "location": q["point"], "view_model": q.get("model", m["models"][0])}); return None
            if fn == "regenerate": return None
        if cmd == "interface":
            out = Path(q["filename"]) if fn == "export_image" else Path(q["dirname"]) / q["filename"]
            headers = {"STEP": b"ISO-10303-21;\nSIMULATED NOT A REAL STEP;", "IGES": b" " * 72 + b"S      1\n", "DXF": b"  0\nSECTION\n  2\nHEADER\n", "JPEG": b"\xff\xd8\xffFAKE JPEG"}
            content = b"%PDF-1.7\nNOT A REAL PDF" if fn == "export_pdf" else headers[q["type"]]
            if not self.skip_mutation: out.write_bytes(content)
            return {"dirname": str(out.parent), "filename": out.name}
        raise ValueError("Fixture has no implementation for " + repr((cmd, fn, q)))


class Server:
    def __init__(self, world):
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            def setup(self):
                super().setup()
                self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            def log_message(self, *_): pass
            def handle(self):
                # A client that abandons a slow response leaves the write to fail here.
                # ConnectionError covers reset, aborted (WinError 10053) and broken pipe;
                # naming only two of the three let Windows print a handler traceback.
                try: super().handle()
                except ConnectionError: pass
            def do_POST(self):
                if self.path != "/creoson": self.send_error(404); return
                req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                try:
                    result = world.handle(req)
                    if result is None:
                        self.close_connection = True
                        self.connection.shutdown(socket.SHUT_RDWR)
                        return
                    data = b"not json" if world.bad_json else json.dumps(result).encode()
                    self.send_response(world.http_status or 200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError): pass
                except Exception as e:
                    data = json.dumps({"status": {"error": True, "message": str(e)}}).encode()
                    self.send_response(200); self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.http.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.http.server_port}/creoson"
        self.thread = threading.Thread(target=self.http.serve_forever, kwargs={"poll_interval": .02}, daemon=True)
        self.thread.start()
    def close(self):
        self.http.shutdown(); self.http.server_close(); self.thread.join(timeout=2)
