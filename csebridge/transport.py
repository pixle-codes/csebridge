"""Injectable HTTP transport (stdlib urllib; tests swap `request`).

Policy knobs (read from the environment at call time):
- CSEBRIDGE_TIMEOUT  seconds per HTTP attempt (default TIMEOUT)
- CSEBRIDGE_RETRIES  extra attempts on 429/5xx/network errors (default 0)
Backoff doubles from BACKOFF_BASE, capped at BACKOFF_CAP.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

TIMEOUT = 30
RETRIES = 0
BACKOFF_BASE = 0.5
BACKOFF_CAP = 8.0


class TransportError(Exception):
    def __init__(self, message, status=0, body=None):
        super().__init__(message)
        self.status = status
        self.body = body


def request(method, url, headers=None, payload=None, timeout=None, retries=None):
    """Return (status, parsed_json_or_text); raise TransportError on failure.

    Retries transient failures (429, 5xx, connection errors) up to `retries`
    times with exponential backoff. Elapsed wall-clock seconds are attached as
    `.last_elapsed` on success so the CSE layer can fill searchTime.
    """
    if timeout is None:
        timeout = _env_float("CSEBRIDGE_TIMEOUT", TIMEOUT)
    if retries is None:
        retries = _env_int("CSEBRIDGE_RETRIES", RETRIES)
    delay = BACKOFF_BASE
    attempt = 0
    while True:
        try:
            return _request_once(method, url, headers, payload, timeout)
        except TransportError as exc:
            attempt += 1
            if not retriable(exc) or attempt > retries:
                raise
            time.sleep(delay)
            delay = min(delay * 2, BACKOFF_CAP)


def retriable(exc):
    return exc.status == 0 or exc.status == 429 or exc.status >= 500


def _request_once(method, url, headers, payload, timeout):
    data = None
    headers = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
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


def _env_float(name, default):
    try:
        value = float(os.environ[name])
        return value if value > 0 else default
    except (KeyError, ValueError):
        return default


def _env_int(name, default):
    try:
        value = int(os.environ[name])
        return value if value >= 0 else default
    except (KeyError, ValueError):
        return default

