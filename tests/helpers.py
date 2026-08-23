"""Shared fake transport for offline tests."""

import json


class FakeTransport:
    """Records calls; returns canned (status, body) per backend name."""

    def __init__(self, responder):
        self.calls = []
        self._responder = responder

    def __call__(self, method, url, headers=None, payload=None):
        self.calls.append(
            {"method": method, "url": url, "headers": headers or {}, "payload": payload}
        )
        return self._responder(method, url, headers or {}, payload)


def load_fixture(name):
    import pathlib

    path = pathlib.Path(__file__).parent / "fixtures" / f"{name}.json"
    return json.loads(path.read_text())


def ok(body):
    def _respond(method, url, headers, payload):
        return 200, body

    return _respond
