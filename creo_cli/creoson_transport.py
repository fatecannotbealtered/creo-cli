"""Bounded, loopback-only CREOSON JSON transport. No retries or raw CLI passthrough.

Protocol reference: SimplifiedLogic/creoson and Zepmanbc/creopyson connection.py.
This implementation is original; it deliberately does not depend on requests.
"""
from __future__ import annotations

import hashlib
import http.client
import os
import socket
import time
from pathlib import Path
from urllib.parse import urlsplit

from . import safety
from .core import Error, MAX_INPUT, atomic_write, canonical, decode, read_json

DEFAULT_ENDPOINT = "http://127.0.0.1:9056/creoson"


def endpoint() -> str:
    value = os.environ.get("CREO_CLI_CREOSON_URL", DEFAULT_ENDPOINT)
    try:
        u = urlsplit(value)
        port = u.port or 9056
        if (u.scheme != "http" or u.hostname not in ("127.0.0.1", "localhost", "::1")
                or u.username or u.password or u.query or u.fragment
                or u.path.rstrip("/") != "/creoson" or not 1 <= port <= 65535):
            raise ValueError()
    except ValueError as exc:
        raise Error("E_CONFIG", "CREOSON must use a loopback HTTP URL ending in /creoson; credentials, redirects and remote hosts are forbidden") from exc
    # Canonicalize aliases so localhost/127.0.0.1 cannot obtain separate locks.
    host = "[::1]" if u.hostname == "::1" else "127.0.0.1"
    return f"http://{host}:{port}/creoson"


def endpoint_key(url: str | None = None) -> str:
    # One lock for ALL loopback servers: they may connect to the same Creo process.
    # Identity binding still uses the exact endpoint and session below.
    return hashlib.sha256((url or endpoint()).encode()).hexdigest()


def cache_path(url: str | None = None) -> Path:
    return safety.directory() / ("creoson-session-" + endpoint_key(url) + ".json")


def configuration() -> dict:
    url = endpoint()
    return {"endpoint": url, "session_cached": cache_path(url).is_file(),
            "workspace_configured": bool(os.environ.get("CREO_CLI_WORKSPACE")),
            "live_verified": False, "transport": "loopback_http", "automatic_retries": False}


def load_session(url: str) -> dict:
    env_id = os.environ.get("CREO_CLI_CREOSON_SESSION")
    if env_id:
        raw_major = os.environ.get("CREO_CLI_CREO_MAJOR")
        try:
            major = int(raw_major) if raw_major else None
        except ValueError as exc:
            raise Error("E_CONFIG", "CREO_CLI_CREO_MAJOR must be an integer") from exc
        value = {"endpoint": url, "session_id": env_id, "creo_major": major,
                 "version_configured": False, "source": "env"}
    else:
        p = cache_path(url)
        if p.is_symlink():
            raise Error("E_FORBIDDEN", "session cache must not be a symbolic link")
        if not p.exists():
            raise Error("E_CONFIG", "no CREOSON session; run creoson connect first")
        value = read_json(p)
    if (not isinstance(value, dict) or value.get("endpoint") != url
            or not isinstance(value.get("session_id"), str)
            or not 1 <= len(value["session_id"]) <= 512
            or any(ord(c) < 32 for c in value["session_id"])):
        raise Error("E_CONFIG", "invalid CREOSON session cache or environment")
    return value


class Client:
    """Reuse one HTTP connection under a single wall-clock deadline per command.

    No requests are retried, including reads: a caller explicitly decides when
    another request is appropriate. HTTP proxies and redirects are never used.
    """

    def __init__(self, timeout: float = 30, *, connected: bool = True):
        self.url = endpoint()
        self.deadline = time.monotonic() + timeout
        self.session = load_session(self.url) if connected else {"session_id": "", "endpoint": self.url}
        u = urlsplit(self.url)
        self.conn = http.client.HTTPConnection(u.hostname, u.port, timeout=timeout)
        self.calls = 0
        self.timings: list[dict] = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.conn.close()

    @property
    def identity(self) -> dict:
        return {"endpoint": self.url,
                "session_sha256": hashlib.sha256(self.session["session_id"].encode()).hexdigest(),
                "creo_major": self.session.get("creo_major"),
                "version_configured": self.session.get("version_configured", False)}

    def remaining(self) -> float:
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise Error("E_TIMEOUT", "operation deadline exceeded", {"request_sent": False})
        return left

    def request(self, command: str, function: str, data: dict | None = None, *, write: bool = False) -> dict:
        request = {"sessionId": self.session["session_id"], "command": command,
                   "function": function, "data": data or {}}
        raw = canonical(request)
        if len(raw) > MAX_INPUT:
            raise Error("E_VALIDATION", "CREOSON request exceeds 8 MiB")
        started, sent = time.monotonic(), False
        try:
            self.conn.timeout = self.remaining()
            if self.conn.sock:
                self.conn.sock.settimeout(self.conn.timeout)
            sent = True  # conservative even if the OS fails before it transmits
            self.calls += 1
            self.conn.request("POST", "/creoson", body=raw,
                              headers={"Content-Type": "application/json; charset=utf-8", "Accept": "application/json"})
            if self.conn.sock:
                self.conn.sock.settimeout(self.remaining())
            response = self.conn.getresponse()
            code = response.status
            if code != 200:
                mapping = {401: "E_AUTH", 403: "E_FORBIDDEN", 404: "E_NOT_FOUND",
                           408: "E_TIMEOUT", 409: "E_CONFLICT", 429: "E_RATE_LIMITED"}
                error = mapping.get(code, "E_SERVER" if code >= 500 else "E_PROTOCOL")
                raise Error(error, "CREOSON HTTP request rejected", {"http_status": code})
            length = response.getheader("Content-Length")
            if length is not None and (not length.isdecimal() or int(length) > MAX_INPUT):
                raise Error("E_PROTOCOL", "invalid or oversized CREOSON response length")
            chunks, size = [], 0
            while True:
                left = self.remaining()
                if self.conn.sock:
                    self.conn.sock.settimeout(left)
                part = response.read1(min(65536, MAX_INPUT + 1 - size))
                if not part:
                    break
                size += len(part)
                if size > MAX_INPUT:
                    raise Error("E_PROTOCOL", "CREOSON response exceeds 8 MiB")
                chunks.append(part)
            try:
                reply = decode(b"".join(chunks).decode("utf-8", "strict"))
            except (Error, UnicodeError) as exc:
                raise Error("E_PROTOCOL", "CREOSON did not return strict UTF-8 JSON") from exc
            if (not isinstance(reply, dict) or not isinstance(reply.get("status"), dict)
                    or type(reply["status"].get("error")) is not bool):
                raise Error("E_PROTOCOL", "invalid CREOSON status envelope")
            if reply["status"]["error"]:
                # Never parse localized error text to infer safe retry or subtype.
                raise Error("E_NATIVE_FAILURE", "CREOSON reported a business error",
                            {"upstream_message": str(reply["status"].get("message", "")).replace(self.session["session_id"], "[redacted]")[:1000] if self.session["session_id"] else "upstream error (message withheld)",
                             "_untrusted": ["upstream_message"]})
            if command == "connection" and function == "connect":
                sid = reply.get("sessionId")
                if not isinstance(sid, str) or not 1 <= len(sid) <= 512:
                    raise Error("E_PROTOCOL", "CREOSON connect returned no valid session ID")
                return {"session_id": sid}
            result = reply.get("data")
            if result is None:
                return {}
            if not isinstance(result, dict):
                raise Error("E_PROTOCOL", "CREOSON data must be an object or null")
            return result
        except (socket.timeout, TimeoutError) as exc:
            raise self._error("E_TIMEOUT", "CREOSON request timed out", sent, write) from exc
        except (OSError, http.client.HTTPException) as exc:
            raise self._error("E_NETWORK", "CREOSON transport failed", sent, write) from exc
        except Error as exc:
            if sent and write:
                raise Error("E_OUTCOME_UNKNOWN", "write outcome is uncertain; inspect the receipt and actual Creo state before any new write",
                            {"cause_code": exc.code, "request_sent": True, "state_unknown": True,
                             "automatic_retry": False}) from exc
            raise
        finally:
            self.timings.append({"command": command, "function": function,
                                 "duration_ms": round((time.monotonic() - started) * 1000)})

    @staticmethod
    def _error(code: str, message: str, sent: bool, write: bool) -> Error:
        if write and sent:
            return Error("E_OUTCOME_UNKNOWN", "write transport failed; the server may still be executing",
                         {"cause_code": code, "state_unknown": True, "automatic_retry": False})
        return Error(code, message, {"request_sent": sent})

    def connect(self, creo_major: int) -> dict:
        response = self.request("connection", "connect", write=True)
        self.session = {"endpoint": self.url, "session_id": response["session_id"],
                        "creo_major": creo_major, "version_configured": False, "source": "cache"}
        self.request("creo", "set_creo_version", {"version": creo_major}, write=True)
        self.session["version_configured"] = True
        safety.directory(True)
        atomic_write(cache_path(self.url), canonical(self.session) + b"\n")
        return {"connected": True, "creo_major_declared": creo_major,
                "creo_major_detected": None, "session_stored": True, "live_verified": False}
