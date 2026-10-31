"""Real loopback failures must not turn an uncertain native read into a retry."""

from __future__ import annotations

import json
import socket
import threading
import time
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from creo_cli import transport
from creo_cli.core import Error

DIAGNOSTIC_ID = "controlled-native-read-1"


@contextmanager
def controlled_peer(fault, *, diagnostic=True, target_operation="model.show"):
    """Consume a genuine HTTP request, then fail its response in a controlled way."""
    observed = []
    release = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            pass

        def reply(self, body, status=200):
            if not diagnostic:
                body.pop("diagnostic_request_id", None)
            raw = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Connection", "close")
            if diagnostic:
                self.send_header("X-Creo-Cli-Diagnostic-Request-Id", DIAGNOSTIC_ID)
            self.end_headers()
            self.wfile.write(raw)
            self.close_connection = True

        def do_GET(self):
            observed.append({"path": self.path})
            if fault == "health_lost" and self.path == "/health":
                self.connection.shutdown(socket.SHUT_RDWR)
                self.close_connection = True
                return
            self.reply({"ok": True, "service": "creo-cli", "protocol": 2})

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            observed.append(
                {
                    "path": self.path,
                    "operation": request.get("op"),
                    "cli_invocation_id": self.headers.get(transport.INVOCATION_HEADER),
                }
            )
            if request.get("op") != target_operation and self.path == "/op":
                self.reply({"ok": True, "data": {"observed": True}})
                return
            if fault in ("reply_lost", "file_lost"):
                self.connection.shutdown(socket.SHUT_RDWR)
                self.close_connection = True
            elif fault == "timeout":
                self.send_response(200)
                self.send_header("Content-Length", "4096")
                self.send_header("X-Creo-Cli-Diagnostic-Request-Id", DIAGNOSTIC_ID)
                self.end_headers()
                self.wfile.write(b"{")
                self.wfile.flush()
                release.wait(2)
                self.close_connection = True
            elif fault in ("invalid_json", "invalid_utf8", "truncated_body", "invalid_length"):
                self.send_response(200)
                self.send_header("Connection", "close")
                raw = (
                    b'{"ok": true, "data": {}}'
                    if fault == "truncated_body"
                    else b"\xff"
                    if fault == "invalid_utf8"
                    else b"{invalid-json"
                )
                length = (
                    "not-a-length"
                    if fault == "invalid_length"
                    else str(len(raw) + (5 if fault == "truncated_body" else 0))
                )
                self.send_header("Content-Length", length)
                self.send_header("X-Creo-Cli-Diagnostic-Request-Id", DIAGNOSTIC_ID)
                self.end_headers()
                self.wfile.write(raw)
                self.close_connection = True
            elif fault == "invalid_envelope":
                self.reply({"ok": True, "data": [], "diagnostic_request_id": DIAGNOSTIC_ID})
            elif fault == "invalid_envelope_id":
                self.reply({"ok": True, "data": [], "diagnostic_request_id": None})
            elif fault == "invalid_envelope_empty_id":
                self.reply({"ok": True, "data": [], "diagnostic_request_id": ""})
            elif fault == "http_error":
                self.reply({"ok": False}, status=503)
            elif fault == "auth":
                self.reply({"ok": False, "error": {"code": "E_AUTH"}}, status=401)
            elif fault == "auth_invalid_json":
                self.send_response(401)
                self.send_header("Content-Length", "3")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(b"bad")
                self.close_connection = True
            else:
                code, started = {
                    "unavailable_started": ("E_UNAVAILABLE", True),
                    "unavailable_unsent": ("E_UNAVAILABLE", False),
                    "unavailable_unknown": ("E_UNAVAILABLE", None),
                    "unavailable_invalid_started": ("E_UNAVAILABLE", "true"),
                    "busy_started": ("E_BUSY", True),
                    "busy_withdrawn": ("E_BUSY", False),
                    "busy_unknown": ("E_BUSY", None),
                    "busy_invalid_started": ("E_BUSY", "true"),
                    "unknown_service_code": ("E_FUTURE", None),
                    "service_auth": ("E_AUTH", None),
                }[fault]
                error = {"code": code, "message": "controlled service failure"}
                if started is not None:
                    error["started"] = started
                self.reply(
                    {
                        "ok": False,
                        "error": error,
                        "diagnostic_request_id": DIAGNOSTIC_ID,
                    }
                )

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
            yield observed
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def capture_error(call):
    try:
        call()
    except Error as exc:
        return exc
    raise AssertionError("controlled peer unexpectedly returned success")


class NativeReadTransportUncertainty(unittest.TestCase):
    def assert_pending_and_blocked(self, fault, cause, *, started=None, correlation=True):
        with (
            controlled_peer(fault, diagnostic=correlation) as observed,
            transport.Client(timeout=0.15 if fault == "timeout" else 2) as client,
        ):
            original = capture_error(lambda: client.op("model.show", {"model": "owned.prt"}))
            # A real socket timeout exhausts the command deadline. Renew only this test's
            # deadline to prove that the native-read guard survives independently of it.
            if fault == "timeout":
                client.deadline = time.monotonic() + 2
                client.conn.close()
            try:
                client.op("feature.list", {"model": "owned.prt"})
            except Error as exc:
                blocked = exc
            else:
                blocked = None
            cad = [row["operation"] for row in observed if row["path"] == "/op"]
            self.assertEqual(cad, ["model.show"], f"first error={original.payload()}")
            self.assertEqual(
                (original.code, original.exit, original.retryable),
                ("E_NATIVE_READ_PENDING", 8, False),
            )
            self.assertEqual(original.details["cause_code"], cause)
            self.assertTrue(original.details["cause"])
            self.assertEqual(original.details["operation"], "model.show")
            self.assertEqual(original.details["cli_invocation_id"], transport.INVOCATION_ID)
            self.assertEqual(
                original.details["dispatch_state"], "started" if started else "unknown"
            )
            self.assertTrue(original.details["request_sent"])
            self.assertFalse(original.details["automatic_retry"])
            if started:
                self.assertIs(original.details["started"], True)
                self.assertTrue(original.details["native_call_pending"])
            else:
                self.assertNotIn("started", original.details)
                self.assertTrue(original.details["native_call_may_be_pending"])
            if correlation:
                self.assertEqual(original.details["diagnostic_request_id"], DIAGNOSTIC_ID)
            else:
                self.assertNotIn("diagnostic_request_id", original.details)
            self.assertIsNotNone(blocked)
            self.assertFalse(blocked.details["request_sent"])
            self.assertEqual(blocked.details["blocked_requested_operation"], "feature.list")
            self.assertEqual(blocked.details["operation"], "model.show")
            self.assertEqual(blocked.details["cause_code"], cause)
            self.assertTrue(client.health()["ok"])
            self.assertEqual(observed[-1]["path"], "/health")
            with self.assertRaises(Error) as after_health:
                client.op("model.save", write=True)
            self.assertEqual(after_health.exception.code, "E_NATIVE_READ_PENDING")
            with self.assertRaises(Error):
                client._exchange("POST", "/op", {"op": "feature.list"})
            self.assertEqual(
                [row["operation"] for row in observed if row["path"] == "/op"],
                ["model.show"],
            )
            self.assertNotIn("synthetic-fixture-token", str(original.payload()))

    def test_lost_response_blocks_later_cad_dispatch(self):
        self.assert_pending_and_blocked("reply_lost", "E_NETWORK", correlation=False)

    def test_real_socket_timeout_blocks_later_cad_dispatch(self):
        self.assert_pending_and_blocked("timeout", "E_TIMEOUT")

    def test_invalid_http_json_length_and_envelope_block_later_cad_dispatch(self):
        for fault in (
            "invalid_json",
            "invalid_utf8",
            "truncated_body",
            "invalid_length",
            "invalid_envelope",
            "invalid_envelope_id",
            "invalid_envelope_empty_id",
            "http_error",
        ):
            with self.subTest(fault=fault):
                self.assert_pending_and_blocked(fault, "E_PROTOCOL")

    def test_unavailable_after_confirmed_start_blocks_later_cad_dispatch(self):
        self.assert_pending_and_blocked("unavailable_started", "E_UNAVAILABLE", started=True)

    def test_busy_after_confirmed_start_blocks_later_cad_dispatch(self):
        self.assert_pending_and_blocked("busy_started", "E_BUSY", started=True)

    def test_older_formal_service_without_diagnostic_id_keeps_only_local_correlation(self):
        self.assert_pending_and_blocked("busy_started", "E_BUSY", started=True, correlation=False)
        self.assert_pending_and_blocked("invalid_envelope", "E_PROTOCOL", correlation=False)

    def test_busy_without_start_confirmation_does_not_invent_a_start(self):
        for fault in ("busy_unknown", "busy_invalid_started"):
            with self.subTest(fault=fault):
                self.assert_pending_and_blocked(fault, "E_BUSY")

    def test_unavailable_without_start_confirmation_does_not_invent_a_start(self):
        for fault in ("unavailable_unknown", "unavailable_invalid_started"):
            with self.subTest(fault=fault):
                self.assert_pending_and_blocked(fault, "E_UNAVAILABLE")

    def test_unknown_service_failure_blocks_without_inventing_a_start(self):
        self.assert_pending_and_blocked("unknown_service_code", "E_PROTOCOL")

    def test_server_confirmed_withdrawn_read_allows_next_cad_request(self):
        for fault, code in (
            ("busy_withdrawn", "E_TIMEOUT"),
            ("unavailable_unsent", "E_BACKEND_UNAVAILABLE"),
        ):
            with (
                self.subTest(fault=fault),
                controlled_peer(fault) as observed,
                transport.Client() as client,
            ):
                error = capture_error(lambda: client.op("model.show"))
                self.assertEqual(error.code, code)
                self.assertIs(error.details["started"], False)
                self.assertEqual(client.op("feature.list"), {"observed": True})
                self.assertEqual(len(observed), 2)

    def test_auth_refusal_does_not_poison_client_even_with_invalid_body(self):
        for fault in ("auth", "auth_invalid_json", "service_auth"):
            with (
                self.subTest(fault=fault),
                controlled_peer(fault) as observed,
                transport.Client() as client,
            ):
                error = capture_error(lambda: client.op("model.show"))
                self.assertEqual(error.code, "E_AUTH")
                self.assertFalse(error.retryable)
                self.assertEqual(client.op("feature.list"), {"observed": True})
                self.assertEqual(len(observed), 2)

    def test_pending_guard_is_per_client_and_new_client_does_not_clear_original(self):
        with controlled_peer("busy_started") as observed, transport.Client() as original:
            capture_error(lambda: original.op("model.show"))
            with transport.Client() as independent:
                self.assertEqual(independent.op("feature.list"), {"observed": True})
            blocked = capture_error(lambda: original.op("model.save", write=True))
            self.assertEqual(blocked.code, "E_NATIVE_READ_PENDING")
            self.assertFalse(blocked.details["request_sent"])
            self.assertEqual(
                [row["operation"] for row in observed if row["path"] == "/op"],
                ["model.show", "feature.list"],
            )

    def test_lost_write_reply_remains_outcome_unknown(self):
        with (
            controlled_peer("reply_lost", target_operation="model.save") as observed,
            transport.Client() as client,
        ):
            error = capture_error(lambda: client.op("model.save", write=True))
            self.assertEqual(
                (error.code, error.exit, error.retryable), ("E_OUTCOME_UNKNOWN", 6, False)
            )
            self.assertEqual(error.details["cause_code"], "E_NETWORK")
            self.assertTrue(error.details["request_sent"])
            self.assertIsNone(client._native_read_pending)
            self.assertEqual([row["operation"] for row in observed], ["model.save"])

    def test_preconnect_failure_does_not_poison_client(self):
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            unused_port = reserved.getsockname()[1]
        with (
            patch.object(transport, "endpoint", return_value=f"http://127.0.0.1:{unused_port}"),
            patch.object(transport, "read_token", return_value="synthetic-fixture-token"),
            transport.Client() as client,
        ):
            error = capture_error(lambda: client.op("model.show"))
            self.assertEqual(error.code, "E_BACKEND_UNAVAILABLE")
            self.assertFalse(error.details["request_sent"])
            with controlled_peer("busy_withdrawn"):
                replacement = transport.Client()
                client.conn = replacement.conn
                try:
                    self.assertEqual(client.op("feature.list"), {"observed": True})
                finally:
                    replacement.conn.close()

    def test_health_and_file_http_failures_do_not_poison_client(self):
        for fault in ("health_lost", "file_lost"):
            with self.subTest(fault=fault), controlled_peer(fault), transport.Client() as client:
                call = (
                    client.probe
                    if fault == "health_lost"
                    else lambda: client._exchange("POST", "/file", {"path": "owned.txt"})
                )
                error = capture_error(call)
                self.assertEqual(error.code, "E_NETWORK")
                self.assertTrue(error.retryable)
                client.conn.close()
                self.assertEqual(client.op("feature.list"), {"observed": True})
