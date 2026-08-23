import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from csebridge import transport as transport_module

from .helpers import load_fixture


class FakeOnce:
    """Stands in for transport._request_once; scripted (status, body) sequence."""

    def __init__(self, script, final=None):
        self.script = list(script)
        self.final = final if final is not None else (200, {"ok": True})
        self.calls = []

    def __call__(self, method, url, headers, payload, timeout):
        self.calls.append({"method": method, "url": url, "timeout": timeout})
        if self.script:
            item = self.script.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return self.final


class TestRetryPolicy(unittest.TestCase):
    def setUp(self):
        self.sleeps = []
        sleep_patch = mock.patch("time.sleep", side_effect=self.sleeps.append)
        sleep_patch.start()
        self.addCleanup(sleep_patch.stop)

    def run_request(self, fake, env=None, **kwargs):
        env = env or {}
        with mock.patch.dict(os.environ, env):
            with mock.patch.object(transport_module, "_request_once", fake):
                return transport_module.request("GET", "https://x.example/v1", **kwargs)

    def test_429_retried_then_success(self):
        fake = FakeOnce([transport_module.TransportError("HTTP 429", status=429)])
        status, body = self.run_request(fake, env={"CSEBRIDGE_RETRIES": "1"})
        self.assertEqual(status, 200)
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(self.sleeps, [transport_module.BACKOFF_BASE])

    def test_500_and_network_errors_retried(self):
        fake = FakeOnce([
            transport_module.TransportError("HTTP 503", status=503),
            transport_module.TransportError("connection failed: boom", status=0),
        ])
        status, _ = self.run_request(fake, env={"CSEBRIDGE_RETRIES": "2"})
        self.assertEqual(status, 200)
        self.assertEqual(len(fake.calls), 3)

    def test_retries_exhausted_reraises_last(self):
        err = transport_module.TransportError("HTTP 429", status=429)
        fake = FakeOnce([err] * 3)
        with self.assertRaises(transport_module.TransportError) as ctx:
            self.run_request(fake, env={"CSEBRIDGE_RETRIES": "2"})
        self.assertIs(ctx.exception, err)
        self.assertEqual(len(fake.calls), 3)  # 1 initial + 2 retries

    def test_client_errors_never_retried(self):
        for code in (400, 401, 403, 404):
            fake = FakeOnce([
                transport_module.TransportError(f"HTTP {code}", status=code)
            ])
            with self.assertRaises(transport_module.TransportError):
                self.run_request(fake, env={"CSEBRIDGE_RETRIES": "3"})
            self.assertEqual(len(fake.calls), 1)

    def test_backoff_doubles_and_caps(self):
        fake = FakeOnce([transport_module.TransportError("HTTP 500", status=500)] * 5)
        with self.assertRaises(transport_module.TransportError):
            self.run_request(fake, env={"CSEBRIDGE_RETRIES": "4"})
        base, cap = transport_module.BACKOFF_BASE, transport_module.BACKOFF_CAP
        expected = []
        delay = base
        for _ in range(4):
            expected.append(delay)
            delay = min(delay * 2, cap)
        self.assertEqual(self.sleeps, expected)
        self.assertTrue(all(s <= cap for s in self.sleeps))

    def test_default_is_zero_retries(self):
        fake = FakeOnce([transport_module.TransportError("HTTP 429", status=429)])
        with self.assertRaises(transport_module.TransportError):
            self.run_request(fake)
        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(self.sleeps, [])

    def test_bad_env_values_fall_back_to_defaults(self):
        fake = FakeOnce([], final=(200, {"ok": 1}))
        status, body = self.run_request(
            fake, env={"CSEBRIDGE_TIMEOUT": "nope", "CSEBRIDGE_RETRIES": "-3"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(fake.calls[0]["timeout"], transport_module.TIMEOUT)

    def test_explicit_kwargs_override_env(self):
        fake = FakeOnce([transport_module.TransportError("HTTP 429", status=429)])
        status, _ = self.run_request(
            fake,
            env={"CSEBRIDGE_RETRIES": "0"},
            timeout=1.25,
            retries=1,
        )
        self.assertEqual(status, 200)
        self.assertEqual(fake.calls[0]["timeout"], 1.25)


class TestRateLimitHint(unittest.TestCase):
    def test_wrap_transport_appends_hint_on_429(self):
        from csebridge.backends import _wrap_transport

        exc = _wrap_transport(
            transport_module.TransportError("HTTP 429", status=429, body="slow down")
        )
        self.assertEqual(exc.code, 429)
        self.assertIn("--retries 2", str(exc))

    def test_no_hint_on_other_statuses(self):
        from csebridge.backends import _wrap_transport

        exc = _wrap_transport(transport_module.TransportError("HTTP 403", status=403))
        self.assertNotIn("--retries", str(exc))


class TestCliPolicyFlags(unittest.TestCase):
    def run_cli(self, argv, responder):
        from csebridge import cli

        seen = {}
        captured = responder(seen)
        out, err = io.StringIO(), io.StringIO()
        code = None
        try:
            with mock.patch.dict(os.environ, {"BRAVE_API_KEY": "k-test"}):
                with mock.patch("csebridge.transport.request", captured):
                    with redirect_stdout(out), redirect_stderr(err):
                        cli.main(argv)
        except SystemExit as exc:
            code = exc.code
        return code, seen, out.getvalue(), err.getvalue()

    def test_retries_flag_sets_env_for_search(self):
        def responder(seen):
            def fake(method, url, headers=None, payload=None):
                seen["retries"] = os.environ.get("CSEBRIDGE_RETRIES")
                seen["timeout"] = os.environ.get("CSEBRIDGE_TIMEOUT")
                return 200, load_fixture("brave_web")

            return fake

        code, seen, out, _ = self.run_cli(["q=x", "--json", "--retries", "3"], responder)
        self.assertEqual(code, 0)
        self.assertEqual(seen["retries"], "3")
        json.loads(out)  # still emits the CSE payload

    def test_timeout_flag_sets_env_for_search(self):
        def responder(seen):
            def fake(method, url, headers=None, payload=None):
                seen["timeout"] = os.environ.get("CSEBRIDGE_TIMEOUT")
                return 200, load_fixture("brave_web")

            return fake

        code, seen, _, _ = self.run_cli(["q=x", "--json", "--timeout", "7.5"], responder)
        self.assertEqual(code, 0)
        self.assertEqual(seen["timeout"], "7.5")

    def test_flags_absent_leave_env_alone(self):
        def responder(seen):
            def fake(method, url, headers=None, payload=None):
                seen["retries"] = os.environ.get("CSEBRIDGE_RETRIES")
                return 200, load_fixture("brave_web")

            return fake

        code, seen, _, _ = self.run_cli(["q=x", "--json"], responder)
        self.assertEqual(code, 0)
        self.assertIsNone(seen["retries"])
