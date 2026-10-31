"""Loopback transport to the service that runs inside Creo (service/). No retries.

The service listens on 127.0.0.1:9057 by default and answers every request except
/health only when it carries the token that copy of the service wrote to
~/.creo-cli/service-token when Creo loaded it. See docs/SERVICE.md.

Replies the service gives are definitive: a refusal or a Creo failure is reported as
such. A lost write reply leaves its outcome unknown. A lost native-read reply may leave
a call running in Creo, so this client must not dispatch another CAD request. Neither
case may be retried automatically; process-only /health remains available.
"""

from __future__ import annotations

import http.client
import os
import re
import time
import uuid
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit

from . import execution_budgets, native_diagnostic_recovery, timing
from .core import MAX_INPUT, Error, canonical, decode

OBSERVATION_GETTERS = frozenset(
    (
        "session.status",
        "model.show",
        "model.definition-state",
        "dimension.list",
        "feature.list",
        "feature.show",
        "geometry.list",
        "parameter.list",
        "relation.list",
        "assembly.components",
        "appearance.get",
        "display.state",
    )
)
OBSERVATION_FRESH_GETTERS = frozenset({"drawing.bom-template"})

DEFAULT_ENDPOINT = "http://127.0.0.1:9057"
PROTOCOL = 2
TOKEN_HEADER = "X-Creo-Cli-Token"
WAIT_HEADER = "X-Creo-Cli-Wait-Ms"
INVOCATION_HEADER = "X-Creo-Cli-Invocation-Id"
# Correlate all RPCs in this CLI process without accepting an external identity override.
INVOCATION_ID = uuid.uuid4().hex
# The service withdraws an operation Creo has not started once the caller's wait budget
# runs out. Asking it to give up this much before our own deadline means a job stuck
# behind an open dialog is reported as "not started" rather than left queued.
MARGIN_SECONDS = 1.0
SETUP = (
    "install the bound service (creo-cli service install --from <bundle>), then use "
    "examples/engineering/start-owned-creo.ps1 in new private startup/runtime directories "
    "to auto-load protk.dat and check readiness; preserve existing instances and external "
    "trust/license requirements; creo-cli doctor says what is missing"
)

# Service codes that mean "refused before anything was changed": every one is raised by
# a check the service makes before it touches the model.
REFUSALS = ("E_VALIDATION", "E_NOT_FOUND", "E_CONFLICT", "E_CONFIG", "E_UNSUPPORTED")


def endpoint() -> str:
    value = os.environ.get("CREO_CLI_SERVICE_URL", DEFAULT_ENDPOINT)
    try:
        u = urlsplit(value)
        port = u.port or 9057
        if (
            u.scheme != "http"
            or u.hostname not in ("127.0.0.1", "localhost", "::1")
            or u.username
            or u.password
            or u.query
            or u.fragment
            or u.path.rstrip("/") != ""
            or not 1 <= port <= 65535
        ):
            raise ValueError()
    except ValueError as exc:
        raise Error(
            "E_CONFIG",
            "CREO_CLI_SERVICE_URL must be a loopback http://host:port with no path; "
            "credentials, redirects and remote hosts are forbidden",
        ) from exc
    host = "[::1]" if u.hostname == "::1" else "127.0.0.1"
    return f"http://{host}:{port}"


def token_path() -> Path:
    raw = os.environ.get("CREO_CLI_SERVICE_TOKEN_FILE")
    return Path(raw).expanduser() if raw else Path.home() / ".creo-cli" / "service-token"


def read_token() -> str:
    p = token_path()
    details = {
        "token_file": str(p),
        "fix": SETUP,
        "request_sent": False,
        "_untrusted": ["token_file"],
    }
    if p.is_symlink():
        raise Error("E_FORBIDDEN", "the service token file must not be a symbolic link", details)
    try:
        fd = os.open(p, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as f:
            raw = f.read(257)
    except FileNotFoundError as exc:
        raise Error(
            "E_BACKEND_UNAVAILABLE",
            "no service token: the service writes one each time Creo loads it",
            details,
        ) from exc
    except OSError as exc:
        raise Error(
            "E_BACKEND_UNAVAILABLE", "the service token file cannot be read", details
        ) from exc
    text = raw.decode("ascii", "replace").strip()
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise Error(
            "E_BACKEND_UNAVAILABLE",
            "the service token file is malformed; restarting Creo makes the service rewrite it",
            details,
        )
    return text


def configuration() -> dict:
    return {
        "endpoint": endpoint(),
        "token_file_present": token_path().is_file(),
        "protocol": PROTOCOL,
        "transport": "loopback_http",
        "automatic_retries": False,
    }


class Client:
    """Fresh socket per request, one command deadline, and no automatic retries."""

    def __init__(self, timeout: float = 30):
        self.url = endpoint()
        self.deadline = timing.deadline(timeout)
        u = urlsplit(self.url)
        self.conn = http.client.HTTPConnection(u.hostname, u.port, timeout=timeout)
        self._token: str | None = None
        self._health: dict | None = None
        self._observation: dict | None = None
        self._observation_fresh: frozenset[str] = frozenset()
        self._native_read_pending: Error | None = None
        self._native_diagnostic_stop: Error | None = None
        self._execution_profile = timing.execution_profile()
        self._budget_admitted = False

    @contextmanager
    def observation(self, *, enabled=True, fresh_operations=()):
        """One read-only observation boundary; never retained across a dispatched write."""
        if not enabled:
            yield
            return
        fresh = frozenset(fresh_operations)
        if not fresh <= OBSERVATION_FRESH_GETTERS:
            raise Error("E_FORBIDDEN", "unsupported fresh operation in read-only observation")
        previous = self._observation
        previous_fresh = self._observation_fresh
        self._observation = {}
        self._observation_fresh = fresh
        try:
            yield
        finally:
            self._observation = previous
            self._observation_fresh = previous_fresh
            if previous is not None:
                previous.clear()  # A nested fresh reading invalidates older outer samples.

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.conn.close()

    def remaining(self) -> float:
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise Error("E_TIMEOUT", "command deadline exceeded", {"request_sent": False})
        return left

    def probe(self) -> dict:
        """Whatever /health says, unchecked. Touches no Creo API."""
        with timing.rpc("/health", False):
            return self._exchange("GET", "/health", auth=False)

    def health(self) -> dict:
        """Is the service there, and does it speak this CLI's protocol?"""
        reply = self.probe()
        if reply.get("ok") is not True or reply.get("service") != "creo-cli":
            raise Error(
                "E_PROTOCOL", "the endpoint is not the creo-cli service", {"endpoint": self.url}
            )
        if reply.get("protocol") != PROTOCOL:
            raise Error(
                "E_BACKEND_UNAVAILABLE",
                "the service in Creo speaks a different protocol than this CLI",
                {
                    "service_protocol": reply.get("protocol"),
                    "cli_protocol": PROTOCOL,
                    "fix": "install the service that ships with this CLI and restart Creo",
                },
            )
        self._health = reply
        return reply

    def require_capability(self, name: str, version: int) -> dict:
        """Read the process-only health declaration; this never calls a Creo API."""
        self._guard_pending_read("capability:" + name)
        reply = self._health if self._health is not None else self.health()
        if self._execution_profile is not None:
            self._guard_health_diagnostic(reply, "capability:" + name)
        offered = reply.get("capabilities")
        actual = offered.get(name) if isinstance(offered, dict) else None
        if type(actual) is not int or actual != version:
            raise Error(
                "E_BACKEND_UNAVAILABLE",
                "this write requires a matching service capability",
                {
                    "dispatch_state": "not_started",
                    "request_sent": False,
                    "required_capability": {"name": name, "version": version},
                    "observed_capability_version": actual,
                    "service_revision": reply.get("revision"),
                    "identity_scope": "process_only_capability_declaration_not_loaded_hash",
                    "next_action": "protect existing models and coordinate a matching service "
                    "upgrade; no write was dispatched",
                    "automatic_retry": False,
                    "_untrusted": ["observed_capability_version", "service_revision"],
                },
            )
        return reply

    def op(self, name: str, request: dict | None = None, *, write: bool = False) -> dict:
        self._guard_pending_read(name)
        self._admit_execution_budget(name)
        cache = self._observation
        key = None
        if cache is not None:
            if (
                write
                or "op" in (request or {})
                or name not in OBSERVATION_GETTERS | {"material.list"} | self._observation_fresh
            ):
                raise Error(
                    "E_FORBIDDEN",
                    "a read-only observation cannot dispatch this operation",
                    {"dispatch_state": "not_started", "request_sent": False, "operation": name},
                )
            key = canonical([name, request or {}])
            if name == "material.list":
                cache.clear()  # Configuration/material observations are always fresh.
            elif key in cache:
                self.remaining()
                return deepcopy(cache[key])
        body = {"op": name, **(request or {})}
        correlation = {"operation": body["op"], "cli_invocation_id": INVOCATION_ID}
        with timing.rpc(name, write):
            reply = self._exchange("POST", "/op", body, write=write)
        if isinstance(reply.get("diagnostic_request_id"), str) and reply["diagnostic_request_id"]:
            correlation["diagnostic_request_id"] = reply["diagnostic_request_id"]
        if reply.get("ok") is True:
            if not isinstance(reply.get("data"), dict):
                raise self._lost(
                    "E_PROTOCOL",
                    "the service's reply carries no data object",
                    write,
                    correlation,
                    native_read=not write,
                )
            if cache is not None and name in OBSERVATION_GETTERS:
                cache[key] = deepcopy(reply["data"])
            return reply["data"]
        if reply.get("ok") is False:
            raise self._service_error(reply.get("error"), write=write, correlation=correlation)
        raise self._lost(
            "E_PROTOCOL",
            "invalid service reply envelope",
            write,
            correlation,
            native_read=not write,
        )

    def _admit_execution_budget(self, name):
        self._guard_pending_read(name)
        if self._execution_profile is None:
            return
        if self._health is not None:
            self._guard_health_diagnostic(self._health, name)
        if self._budget_admitted:
            return
        reply = self._health if self._health is not None else self.health()
        self._guard_health_diagnostic(reply, name)
        self.require_capability(execution_budgets.CAPABILITY, 1)
        self.remaining()  # Capability checking consumes this same invocation deadline.
        self._budget_admitted = True

    def _guard_health_diagnostic(self, reply, name):
        diagnostic = reply.get("native_diagnostic")
        if isinstance(diagnostic, dict) and diagnostic.get("stopped") is True:
            # This is a process-only observation, not a newly dispatched native call.
            details = {
                "native_diagnostic": deepcopy(diagnostic),
                "request_sent": False,
                "dispatch_state": "not_started",
                "operation": name,
                "automatic_retry": False,
                "next_action": native_diagnostic_recovery.STOP_ACTION,
                "fix": native_diagnostic_recovery.STOP_ACTION,
                "diagnostic_source": "process_only_health",
            }
            self._native_diagnostic_stop = Error(
                "E_NATIVE_DIAGNOSTIC", "the service reports a diagnostic stop", details
            )
            raise self._native_diagnostic_stop

    def _guard_pending_read(self, name: str) -> None:
        if self._native_diagnostic_stop is not None:
            original = self._native_diagnostic_stop
            raise Error(
                original.code,
                original.message,
                deepcopy(original.details)
                | {
                    "request_sent": False,
                    "blocked_requested_operation": name,
                    "blocked_request_dispatch_state": "not_started",
                    "diagnostic_original_request_sent": original.details.get("request_sent"),
                },
            )
        if self._native_read_pending is not None:
            pending = self._native_read_pending
            raise Error(
                pending.code,
                pending.message,
                pending.details
                | {
                    "request_sent": False,
                    "blocked_requested_operation": name,
                    "blocked_request_dispatch_state": "not_started",
                    "pending_original_read": True,
                    "pending_original_request_sent": True,
                },
            )

    def _service_error(self, error, *, write: bool, correlation: dict | None = None) -> Error:
        if not isinstance(error, dict) or type(error.get("code")) is not str:
            return self._lost(
                "E_PROTOCOL",
                "the service reported a failure without a code",
                write,
                correlation,
                native_read=not write,
            )
        code = error["code"]
        extra = {k: v for k, v in error.items() if k not in ("code", "message", "retryable")}
        details = {
            **(correlation or {}),
            "service_code": code,
            "service_message": str(error.get("message", ""))[:2000],
            **({"service_details": extra} if extra else {}),
            "_untrusted": ["service_message"] + (["service_details"] if extra else []),
        }
        if isinstance(error.get("diagnostic_request_id"), str) and error["diagnostic_request_id"]:
            details["diagnostic_request_id"] = error["diagnostic_request_id"]
        if code == "E_NATIVE_DIAGNOSTIC":
            # A definite diagnostic stop is distinct from a getter whose return is unknown.
            # Keep the service's evidence verbatim; do not invent started/pending or effects.
            if isinstance(error.get("native_diagnostic"), dict):
                details["native_diagnostic"] = deepcopy(error["native_diagnostic"])
            stopped = Error(
                code,
                "the service stopped CAD dispatch after a native diagnostic or journal failure",
                details
                | {
                    "request_sent": True,
                    "dispatch_state": "dispatched",
                    "automatic_retry": False,
                    "next_action": native_diagnostic_recovery.STOP_ACTION,
                    "fix": native_diagnostic_recovery.STOP_ACTION,
                },
            )
            # Parent receipt code may enrich the raised error; the guard keeps the first
            # service error independently so later refusals retain its original identity.
            self._native_diagnostic_stop = Error(code, stopped.message, deepcopy(stopped.details))
            self.conn.close()
            return stopped
        if code in REFUSALS:
            if write:
                return Error(
                    code,
                    "the service refused the request before changing anything",
                    details | {"request_sent": True, "model_changed": False},
                )
            return Error(code, "the service refused the request", details | {"request_sent": True})
        if code == "E_CREO":
            return Error(
                "E_NATIVE_FAILURE", "Creo rejected the operation", details | {"request_sent": True}
            )
        if code == "E_VERIFY_INCOMPLETE":
            return Error(
                code,
                "the required native readback could not be completed",
                details | {"request_sent": True, "automatic_retry": False},
            )
        if code == "E_BUSY":
            if error.get("started") is False:
                return Error(
                    "E_TIMEOUT",
                    "Creo stayed busy -- with another operation, or waiting for input in a dialog "
                    "-- and "
                    "the operation was withdrawn before it started, so nothing was done",
                    details | {"request_sent": True, "started": False},
                )
            if write:
                return Error(
                    "E_OUTCOME_UNKNOWN",
                    "the operation started in Creo but did not finish in time; inspect Creo before "
                    "any "
                    "further write",
                    details | {"started": True, "state_unknown": True, "automatic_retry": False},
                )
            return self._pending_read(
                code,
                details["service_message"],
                details,
                started=error.get("started") is True,
            )
        if code == "E_UNAVAILABLE":
            if not write and error.get("started") is not False:
                return self._pending_read(
                    code,
                    details["service_message"],
                    details,
                    started=error.get("started") is True,
                )
            return Error(
                "E_BACKEND_UNAVAILABLE",
                "the service cannot reach Creo's thread",
                details
                | ({"started": error["started"]} if "started" in error else {})
                | {"fix": SETUP},
            )
        if code == "E_AUTH":
            return Error("E_AUTH", "the service rejected the token", details)
        return self._lost(
            "E_PROTOCOL",
            "the service reported an unknown error code",
            write,
            details,
            native_read=not write,
        )

    def _exchange(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        auth: bool = True,
        write: bool = False,
    ) -> dict:
        cad_request = method == "POST" and path == "/op" and isinstance(body, dict)
        native_read = cad_request and not write and isinstance(body.get("op"), str)
        correlation = (
            {"operation": body.get("op"), "cli_invocation_id": INVOCATION_ID} if cad_request else {}
        )
        if cad_request:
            self._guard_pending_read(body.get("op"))
            self._admit_execution_budget(body.get("op"))
        headers = {"Accept": "application/json", INVOCATION_HEADER: INVOCATION_ID}
        if cad_request and self._execution_profile is not None:
            headers[execution_budgets.HEADER] = self._execution_profile["profile"]
        raw = None
        if body is not None:
            raw = canonical(body)
            if len(raw) > 1024 * 1024:
                raise Error(
                    "E_VALIDATION",
                    "request exceeds the service's 1 MiB limit",
                    {"request_sent": False},
                )
            headers["Content-Type"] = "application/json; charset=utf-8"
        if auth:
            if self._token is None:
                self._token = read_token()
            headers[TOKEN_HEADER] = self._token
        sent = False
        try:
            left = self.remaining()
            headers[WAIT_HEADER] = str(max(100, int((left - MARGIN_SECONDS) * 1000)))
            self.conn.timeout = left
            # Local history/proof work can outlive the server's keep-alive socket.
            # Reads need the same fresh-connection protection as writes: otherwise
            # the first read after local computation becomes spuriously unknown.
            # This opens a socket before one request; it never retries a sent call.
            self.conn.close()
            if self.conn.sock is None:
                try:
                    self.conn.connect()
                except ConnectionRefusedError as exc:
                    raise Error(
                        "E_BACKEND_UNAVAILABLE",
                        "the service in Creo is not answering",
                        {"endpoint": self.url, "request_sent": False, "fix": SETUP},
                    ) from exc
            self.conn.sock.settimeout(self.remaining())
            sent = True  # conservative: the OS may accept bytes that never reach the service
            self.conn.request(method, path, body=raw, headers=headers)
            self.conn.sock.settimeout(self.remaining())
            response = self.conn.getresponse()
            status = response.status
            diagnostic_id = response.getheader("X-Creo-Cli-Diagnostic-Request-Id")
            if diagnostic_id:
                correlation["diagnostic_request_id"] = diagnostic_id
            if status == 401:
                self.conn.close()
                raise Error(
                    "E_AUTH",
                    "the service rejected the token: it belongs to a different Creo session",
                    {
                        **correlation,
                        "token_file": str(token_path()),
                        "request_sent": True,
                        "fix": "restart Creo so the service writes a fresh token, or check which "
                        "Creo answers on the endpoint",
                        "_untrusted": ["token_file"],
                    },
                )
            length = response.getheader("Content-Length")
            if length is not None and (not length.isdecimal() or int(length) > MAX_INPUT):
                raise Error("E_PROTOCOL", "invalid or oversized service reply length")
            chunks, size = [], 0
            while True:
                if self.conn.sock:
                    self.conn.sock.settimeout(self.remaining())
                part = response.read1(min(65536, MAX_INPUT + 1 - size))
                if not part:
                    break
                size += len(part)
                if size > MAX_INPUT:
                    raise Error("E_PROTOCOL", "service reply exceeds 8 MiB")
                chunks.append(part)
            if length is not None and size != int(length):
                raise Error("E_PROTOCOL", "the service reply ended before its declared length")
            try:
                reply = decode(b"".join(chunks).decode("utf-8", "strict"))
            except (Error, UnicodeError) as exc:
                raise Error(
                    "E_PROTOCOL",
                    "the service did not return strict UTF-8 JSON",
                    {"http_status": status},
                ) from exc
            if not isinstance(reply, dict):
                raise Error(
                    "E_PROTOCOL", "the service reply is not a JSON object", {"http_status": status}
                )
            if status != 200:
                raise Error(
                    "E_PROTOCOL",
                    "the service answered with an unexpected HTTP status",
                    {"http_status": status},
                )
            if diagnostic_id and (
                not isinstance(reply.get("diagnostic_request_id"), str)
                or not reply["diagnostic_request_id"]
            ):
                reply["diagnostic_request_id"] = diagnostic_id
            return reply
        except Error as exc:
            if sent and (write or native_read) and exc.code in ("E_PROTOCOL", "E_TIMEOUT"):
                raise self._lost(
                    exc.code,
                    exc.message,
                    write,
                    exc.details | correlation,
                    native_read=native_read,
                ) from exc
            raise
        except TimeoutError as exc:
            if sent and (write or native_read):
                raise self._lost(
                    "E_TIMEOUT",
                    "the service did not reply in time",
                    write,
                    correlation,
                    native_read=native_read,
                ) from exc
            raise Error(
                "E_TIMEOUT", "the service did not reply in time", {"request_sent": sent}
            ) from exc
        except (OSError, http.client.HTTPException) as exc:
            if sent and (write or native_read):
                raise self._lost(
                    "E_NETWORK",
                    "the connection to the service failed",
                    write,
                    correlation,
                    native_read=native_read,
                ) from exc
            raise Error(
                "E_NETWORK", "the connection to the service failed", {"request_sent": sent}
            ) from exc

    def _pending_read(self, code: str, message: str, details: dict, *, started=False) -> Error:
        """Retain a safety guard without claiming an unobserved native-call start."""
        if "service_message" in details:
            details = details | {"_untrusted": [*details.get("_untrusted", []), "cause"]}
        pending = Error(
            "E_NATIVE_READ_PENDING",
            (
                "the native read started and has not returned; ending the client wait did not "
                "cancel it"
                if started
                else "a native read was sent but its start or completion cannot be established; "
                "it may still be running in Creo and ending the client wait does not cancel it"
            ),
            details
            | {
                "cause_code": code,
                "cause": message,
                "request_sent": True,
                "dispatch_state": "started" if started else "unknown",
                "read_only": True,
                "automatic_retry": False,
                **(
                    {"started": True, "native_call_pending": True}
                    if started
                    else {
                        "native_call_may_be_pending": True,
                        "state_unknown": True,
                    }
                ),
                "next_action": "preserve the diagnostic journal and inspect this Creo "
                "instance; use process-only health or OS observations and do not issue "
                "another CAD request until the pending call is resolved",
            },
        )
        self._native_read_pending = pending
        self.conn.close()  # A partial response cannot be reused even for process-only health.
        return pending

    def _lost(
        self,
        code: str,
        message: str,
        write: bool,
        details: dict | None = None,
        *,
        native_read: bool = False,
    ) -> Error:
        """A reply that cannot be read. After a write, the operation may still have run."""
        if write:
            return Error(
                "E_OUTCOME_UNKNOWN",
                "a write was sent but its reply was lost or unreadable; the operation may have run "
                "-- "
                "inspect Creo before any further write",
                (details or {})
                | {
                    "cause_code": code,
                    "cause": message,
                    "request_sent": True,
                    "state_unknown": True,
                    "automatic_retry": False,
                },
            )
        if native_read:
            return self._pending_read(code, message, details or {})
        return Error(code, message, details or {})
