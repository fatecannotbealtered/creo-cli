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
                "models": ["bracket.prt"], "drawing_views": [{"name": "FRONT_MAIN", "sheet": 1, "location": {"x": 10, "y": 10, "z": 0}, "view_model": "bracket.prt"}], "sheets": 1}

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
        if cmd == "creo":
            if fn == "pwd": return {"dirname": str(self.root)}
            if fn == "set_creo_version": self.major = q["version"]; return None
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
            if self.skip_mutation: return {}
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
            row = next(x for x in m["features"] if x["name"] == q["name"])
            if not self.skip_mutation:
                if fn == "rename": row["name"] = q["new_name"]
                elif fn == "suppress": row["status"] = "SUPPRESSED"
                elif fn == "resume": row["status"] = "ACTIVE"
                else: raise ValueError((cmd, fn))
            return None
        if cmd == "view":
            if fn == "list": return {"viewlist": m["views"]}
            if fn == "activate": return None
            if fn == "save":
                if not self.skip_mutation: m["views"].append(q["name"])
                return None
        if cmd == "bom" and fn == "get_paths":
            return {"file": name, "generic": name, "children": [{"file": "bracket.prt", "path": [39], "seq_path": "root.1"}], "has_simprep": False}
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
