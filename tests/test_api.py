import os
import unittest
from unittest import mock

from csebridge import api
from csebridge.errors import CseError

from .helpers import FakeTransport, load_fixture, ok


class TestSearchEndToEnd(unittest.TestCase):
    def run_brave(self, **kw):
        env = {"BRAVE_API_KEY": "k-test"}
        with mock.patch.dict(os.environ, env):
            fake = FakeTransport(ok(load_fixture("brave_web")))
            with mock.patch("csebridge.transport.request", fake):
                return api.search("example domains", backend="brave", **kw), fake

    def test_returns_full_cse_payload(self):
        resp, fake = self.run_brave()
        self.assertEqual(resp["kind"], "customsearch#search")
        self.assertEqual(len(resp["items"]), 3)
        self.assertEqual(resp["items"][0]["link"], "https://example.com/")
        # searchTime measured from transport wall clock (>= 0)
        self.assertGreaterEqual(resp["searchInformation"]["searchTime"], 0)

    def test_default_backend_from_env(self):
        with mock.patch.dict(os.environ, {"BRAVE_API_KEY": "k", "CSEBRIDGE_BACKEND": "brave"}):
            fake = FakeTransport(ok(load_fixture("brave_web")))
            with mock.patch("csebridge.transport.request", fake):
                resp = api.search("example domains")
        self.assertEqual(len(resp["items"]), 3)

    def test_usage_error_is_distinct_valueerror(self):
        # library contract: caller mistakes raise UsageError (CLI -> exit 2),
        # backend/network mistakes raise CseError (CSE-shaped payload)
        from csebridge.params import UsageError

        with self.assertRaises(UsageError):
            api.search("", backend="brave")

    def test_transport_error_becomes_cse_error(self):
        from csebridge import transport as transport_module

        def boom(method, url, headers=None, payload=None):
            raise transport_module.TransportError(
                "HTTP 429 from api.search.brave.com", status=429
            )

        with mock.patch.dict(os.environ, {"BRAVE_API_KEY": "k"}):
            with mock.patch("csebridge.transport.request", boom):
                with self.assertRaises(CseError) as ctx:
                    api.search("q", backend="brave")
        payload = ctx.exception.payload
        self.assertEqual(payload["error"]["code"], 429)
        self.assertEqual(payload["error"]["status"], "RESOURCE_EXHAUSTED")

    def test_unknown_backend_is_cse_error(self):
        with self.assertRaises(CseError) as ctx:
            api.search("q", backend="altavista")
        self.assertIn("altavista", str(ctx.exception))

    def test_site_search_flows_into_backend_query(self):
        resp, fake = self.run_brave(site_search="iana.org")
        # literal '+' must arrive as %2B so backends don't read it as a space
        self.assertIn("%2Bsite%3Aiana.org", fake.calls[0]["url"])


if __name__ == "__main__":
    unittest.main()
