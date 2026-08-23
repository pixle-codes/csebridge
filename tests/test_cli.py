import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from csebridge import cli
from csebridge import transport as transport_module

from .helpers import FakeTransport, load_fixture, ok


def run_cli(argv, env=None, responder=None):
    env = env or {"BRAVE_API_KEY": "k-test"}
    fake = FakeTransport(responder or ok(load_fixture("brave_web")))
    with mock.patch.dict(os.environ, env):
        with mock.patch("csebridge.transport.request", fake):
            out, err = io.StringIO(), io.StringIO()
            code = None
            try:
                with redirect_stdout(out), redirect_stderr(err):
                    cli.main(argv)
            except SystemExit as exc:
                code = exc.code
    return code, out.getvalue(), err.getvalue(), fake


class TestCliHuman(unittest.TestCase):
    def test_human_output_lists_results(self):
        code, out, err, _ = run_cli(["example domains"])
        self.assertEqual(code, 0)
        self.assertIn("About 3 results", out)
        self.assertIn("1. Example Domain", out)
        self.assertIn("https://example.com/", out)

    def test_json_output_is_full_payload(self):
        code, out, _, _ = run_cli(["--json", "example domains"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual(payload["kind"], "customsearch#search")
        self.assertIn("queries", payload)

    def test_start_numbering_follows_start_arg(self):
        code, out, _, _ = run_cli(["--start", "11", "q"])
        self.assertIn("11. Example Domain", out)


class TestCliErrors(unittest.TestCase):
    def test_backend_error_exit_1_with_hint(self):
        def boom(method, url, headers=None, payload=None):
            raise transport_module.TransportError("HTTP 401 from api.search.brave.com", status=401)

        code, out, err, _ = run_cli(["q"], responder=boom)
        self.assertEqual(code, 1)
        self.assertIn("error", err)
        self.assertIn("BRAVE_API_KEY", err)

    def test_json_mode_prints_error_payload_with_code_1(self):
        def boom(method, url, headers=None, payload=None):
            raise transport_module.TransportError("HTTP 429", status=429)

        code, out, err, _ = run_cli(["--json", "q"], responder=boom)
        self.assertEqual(code, 1)
        payload = json.loads(out)
        self.assertEqual(payload["error"]["code"], 429)

    def test_usage_error_exit_2(self):
        code, out, err, fake = run_cli(["   "])
        self.assertEqual(code, 2)
        self.assertIn("non-empty", err)
        self.assertEqual(fake.calls, [])

    def test_unknown_flag_is_usage_exit_2(self):
        # argparse errors exit with code 2 via SystemExit
        code, out, err, _ = run_cli(["--frobnicate"])
        self.assertEqual(code, 2)


class TestCliBackendSelection(unittest.TestCase):
    def test_explicit_backend_used(self):
        env = {"SERPER_API_KEY": "sk"}

        def serper_ok(method, url, headers, payload):
            self.assertEqual(method, "POST")
            return 200, load_fixture("serper_organic")

        code, out, _, fake = run_cli(["--backend", "serper", "q"], env=env, responder=serper_ok)
        self.assertEqual(code, 0)
        self.assertIn("Example Domain", out)


if __name__ == "__main__":
    unittest.main()
