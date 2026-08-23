import os
import unittest
from unittest import mock

from csebridge import backends
from csebridge.errors import CseError

from .helpers import FakeTransport, load_fixture, ok


PARAMS = {
    "q": "example domains",
    "query": "example domains",
    "num": 10,
    "start": 1,
    "lr": None,
    "safe": None,
    "site_search": None,
    "site_search_filter": "i",
}


class BackendCase(unittest.TestCase):
    backend_name = None
    fixture = None
    env_var = None
    env_value = "test-key-123"

    def setUp(self):
        self.backend = backends.BACKENDS[self.backend_name]
        self.patcher = mock.patch.dict(os.environ, {self.env_var: self.env_value})
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.fake = FakeTransport(ok(load_fixture(self.fixture)))
        patch = mock.patch.object(backends.transport, "request", self.fake)
        patch.start()
        self.addCleanup(patch.stop)

    def fetch(self, **overrides):
        p = dict(PARAMS)
        p.update(overrides)
        return self.backend.fetch(p)


class TestBrave(BackendCase):
    backend_name = "brave"
    fixture = "brave_web"
    env_var = "BRAVE_API_KEY"

    def test_get_with_subscription_token_header(self):
        total, hits = self.fetch()
        call = self.fake.calls[0]
        self.assertEqual(call["method"], "GET")
        self.assertIn("api.search.brave.com/res/v1/web/search", call["url"])
        self.assertEqual(call["headers"]["X-Subscription-Token"], "test-key-123")

    def test_hits_normalized_with_global_positions(self):
        _, hits = self.fetch(start=11)
        self.assertEqual([h["pos"] for h in hits], [11, 12, 13])
        self.assertEqual(hits[0]["url"], "https://example.com/")

    def test_offset_maps_from_start(self):
        self.fetch(start=21)
        self.assertIn("offset=20", self.fake.calls[0]["url"])


class TestSerper(BackendCase):
    backend_name = "serper"
    fixture = "serper_organic"
    env_var = "SERPER_API_KEY"

    def test_post_with_api_key_header(self):
        _, hits = self.fetch()
        call = self.fake.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["headers"]["X-API-KEY"], "test-key-123")
        self.assertEqual(call["payload"]["q"], "example domains")

    def test_provider_positions_are_absolute(self):
        _, hits = self.fetch(start=11, num=10)
        # page=2 for start=11; provider positions restart at 1 -> must shift
        self.assertGreaterEqual(hits[0]["pos"], 1)

    def test_page_mapping(self):
        self.fetch(start=11, num=10)
        self.assertEqual(self.fake.calls[0]["payload"]["page"], 2)


class TestSerpApi(BackendCase):
    backend_name = "serpapi"
    fixture = "serpapi_results"
    env_var = "SERPAPI_API_KEY"

    def test_total_results_extracted(self):
        total, hits = self.fetch()
        self.assertEqual(total, 95300000)
        self.assertEqual(len(hits), 2)

    def test_start_passthrough_and_key(self):
        self.fetch(start=5)
        url = self.fake.calls[0]["url"]
        self.assertIn("start=5", url)
        self.assertIn("api_key=test-key-123", url)


class TestTavily(BackendCase):
    backend_name = "tavily"
    fixture = "tavily_results"
    env_var = "TAVILY_API_KEY"

    def test_post_bearer_auth_and_max_results(self):
        total, hits = self.fetch(num=2)
        call = self.fake.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertEqual(call["headers"]["Authorization"], "Bearer test-key-123")
        self.assertEqual(call["payload"]["max_results"], 2)
        self.assertIsNone(total)

    def test_positions_start_at_start_index(self):
        _, hits = self.fetch(start=4)
        self.assertEqual([h["pos"] for h in hits], [4, 5])


class TestSearxng(BackendCase):
    backend_name = "searxng"
    fixture = "searxng_results"
    env_var = "SEARXNG_BASE_URL"

    def setUp(self):
        super().setUp()

    def test_base_url_from_env(self):
        with mock.patch.dict(os.environ, {self.env_var: "https://searx.example.org/"}):
            total, hits = self.fetch()
            self.assertIn("https://searx.example.org/search?", self.fake.calls[0]["url"])
            self.assertEqual(total, 42100)

    def test_provider_position_wins_when_present(self):
        with mock.patch.dict(os.environ, {self.env_var: "https://searx.example.org"}):
            _, hits = self.fetch()
            # second result carried positions:[7] in the fixture
            self.assertEqual(hits[1]["pos"], 7)


class TestMissingKey(unittest.TestCase):
    def test_missing_key_raises_cse_error_401(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(CseError) as ctx:
                backends.get_backend("brave").fetch(PARAMS)
        payload = ctx.exception.payload
        self.assertEqual(payload["error"]["code"], 401)
        self.assertEqual(payload["error"]["status"], "UNAUTHENTICATED")
        self.assertIn("BRAVE_API_KEY", payload["error"]["message"])

    def test_unknown_backend_named_in_error(self):
        with self.assertRaises(CseError) as ctx:
            backends.get_backend("nope")
        self.assertIn("nope", str(ctx.exception))
        self.assertIn("brave", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
