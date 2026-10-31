"""A single CLI invocation can span multiple generic RPCs and client objects."""

import json
import subprocess
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from creo_cli import transport


class TransportCorrelation(unittest.TestCase):
    def test_multiple_clients_and_rpcs_keep_one_invocation_without_exposing_token(self):
        observed = []

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_):
                pass

            def reply(self, body):
                raw = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                observed.append(dict(self.headers))
                self.reply({"ok": True, "service": "creo-cli", "protocol": 2})

            def do_POST(self):
                observed.append(dict(self.headers))
                request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                self.reply({"ok": True, "op": request["op"], "data": {"complete": False}})

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with (
                patch.object(
                    transport, "endpoint", return_value=f"http://127.0.0.1:{server.server_port}"
                ),
                patch.object(transport, "read_token", return_value="synthetic-fixture-token"),
            ):
                for name in ("feature.list", "model.show"):
                    with transport.Client() as client:
                        client.health()
                        client.op(name, {"model": "owned.prt"})
            self.assertEqual(len(observed), 4)
            ids = {headers[transport.INVOCATION_HEADER] for headers in observed}
            self.assertEqual(ids, {transport.INVOCATION_ID})
            self.assertRegex(transport.INVOCATION_ID, r"^[0-9a-f]{32}$")
            self.assertNotEqual(transport.INVOCATION_ID, "synthetic-fixture-token")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    def test_new_process_has_its_own_invocation_id(self):
        observed = subprocess.check_output(
            [
                sys.executable,
                "-c",
                "from creo_cli.transport import INVOCATION_ID; print(INVOCATION_ID)",
            ],
            text=True,
        ).strip()
        self.assertRegex(observed, r"^[0-9a-f]{32}$")
        self.assertNotEqual(observed, transport.INVOCATION_ID)
