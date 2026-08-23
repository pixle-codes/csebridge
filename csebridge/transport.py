"""Injectable HTTP transport (stdlib urllib; tests swap `request`)."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 30


class TransportError(Exception):
    def __init__(self, message, status=0, body=None):
        super().__init__(message)
        self.status = status
        self.body = body


def request(method, url, headers=None, payload=None):
    """Return (status, parsed_json_or_text). Raises TransportError on failure.

    Elapsed wall-clock seconds are attached as `.elapsed` on success so the
    CSE layer can fill searchInformation.searchTime.
    """
    data = None
    headers = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", "replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 - best-effort body read
            pass
        raise TransportError(
            f"HTTP {exc.code} from {urllib.parse.urlsplit(url).netloc}",
            status=exc.code,
            body=body,
        ) from exc
    except urllib.error.URLError as exc:
        raise TransportError(f"connection failed: {exc.reason}") from exc
    except OSError as exc:
        raise TransportError(f"network error: {exc}") from exc
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = raw
    request.last_elapsed = time.monotonic() - started  # type: ignore[attr-defined]
    return status, parsed
