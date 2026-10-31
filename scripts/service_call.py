"""Send one operation to the Creo-side service and print its reply.

A development tool, not the product surface: the CLI commands that wrap these
operations add the preview/confirm flow and the permission gate this bypasses. Use it
against a disposable part in a disposable working directory.

  python scripts/service_call.py '{"op": "model.show", "model": "slice_part.prt"}'
  python scripts/service_call.py --file request.json

The token is read from the file the service writes when Creo loads it; without it the
service answers 401 to everything except /health.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_ENDPOINT = "http://127.0.0.1:9057"
TOKEN_FILE = Path.home() / ".creo-cli" / "service-token"


def call(payload: dict, *, endpoint: str = DEFAULT_ENDPOINT, timeout: float = 150.0) -> dict:
    token = TOKEN_FILE.read_text(encoding="ascii").strip()
    request = urllib.request.Request(
        endpoint + "/op",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Creo-Cli-Token": token},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            return json.loads(answer.read().decode("utf-8"))
    except urllib.error.HTTPError as refused:
        return json.loads(refused.read().decode("utf-8"))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("request", nargs="?", help="the operation as a JSON object")
    p.add_argument("--file", help="read the operation from a JSON file instead")
    p.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    a = p.parse_args()
    if bool(a.request) == bool(a.file):
        p.error("give the request inline or with --file, not both")
    try:
        payload = json.loads(Path(a.file).read_text(encoding="utf-8") if a.file else a.request)
        reply = call(payload, endpoint=a.endpoint)
    except FileNotFoundError:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": f"no token at {TOKEN_FILE}; is Creo running with the service?",
                }
            )
        )
        return 1
    except (OSError, ValueError) as failure:
        print(json.dumps({"ok": False, "error": str(failure)}))
        return 1
    print(json.dumps(reply, indent=2, ensure_ascii=False))
    return 0 if reply.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
