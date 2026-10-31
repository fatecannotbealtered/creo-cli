"""Controlled keep-alive expiry and lost replies, never a native-CAD qualification."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from creo_cli.core import Error
from creo_cli.transport import Client


@pytest.fixture
def peer(tmp_path, monkeypatch):
    state = {"mode": "reply", "posts": [], "health_closed": threading.Event()}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def reply(self, value):
            raw = json.dumps(value).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
            self.wfile.flush()

        def do_GET(self):
            self.reply({"ok": True, "service": "creo-cli", "protocol": 2})
            # Simulate the server expiring an idle keep-alive socket without a
            # Connection:close header. No sleep, network fault or actual CAD call.
            self.close_connection = True
            state["health_closed"].set()

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["posts"].append(body)
            if state["mode"] == "lost_reply":
                self.close_connection = True
                return
            self.reply({"ok": True, "data": {"models": []}})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    token = tmp_path / "service-token"
    token.write_text("0" * 64)
    monkeypatch.setenv("CREO_CLI_SERVICE_URL", f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("CREO_CLI_SERVICE_TOKEN_FILE", str(token))
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_expired_health_connection_is_not_reused_for_the_single_cad_read(peer):
    with Client(timeout=5) as client:
        client.health()
        assert peer["health_closed"].wait(2)
        assert client.op("model.list") == {"models": []}
    assert len(peer["posts"]) == 1


@pytest.mark.parametrize(
    "write,code", [(False, "E_NATIVE_READ_PENDING"), (True, "E_OUTCOME_UNKNOWN")]
)
def test_new_connection_never_retries_a_lost_native_reply(peer, write, code):
    peer["mode"] = "lost_reply"
    with Client(timeout=5) as client:
        with pytest.raises(Error) as caught:
            client.op("model.save" if write else "model.list", write=write)
        assert caught.value.code == code
        assert caught.value.details["request_sent"] is True
        if not write:
            with pytest.raises(Error) as stopped:
                client.op("model.list")
            assert stopped.value.code == "E_NATIVE_READ_PENDING"
    assert len(peer["posts"]) == 1
