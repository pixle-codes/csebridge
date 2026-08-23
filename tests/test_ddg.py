import os
import unittest
from unittest import mock

from csebridge import api, backends
from csebridge.errors import CseError

from .helpers import FakeTransport, load_fixture


class TestDdgBackend(unittest.TestCase):
    def setUp(self):
        self.backend = backends.BACKENDS["ddg"]
        self.fake = FakeTransport(lambda m, u, h, p: (200, load_fixture("ddg_html")))
        patch = mock.patch.object(backends.transport, "request", self.fake)
        patch.start()
        self.addCleanup(patch.stop)

    def fetch(self, **overrides):
        from .test_backends import PARAMS

        p = dict(PARAMS)
        p.update(overrides)
        with mock.patch.dict(os.environ, {}, clear=True):
            return self.backend.fetch(p)

    def test_keyless_no_env_var(self):
        self.assertIsNone(self.backend.env_var)

    def test_opt_in_only_registered(self):
        # registered so --backend ddg works, but never the default selection
        self.assertIn("ddg", backends.BACKENDS)
        with mock.patch.dict(os.environ, {}, clear=True):
            default = os.environ.get("CSEBRIDGE_BACKEND", "brave")
        self.assertEqual(default, "brave")

    def test_parses_results_and_unwraps_uddg_links(self):
        _, hits = self.fetch()
        urls = [h["url"] for h in hits]
        self.assertEqual(urls[0], "https://www.example.com/first")
        self.assertEqual(urls[-1], "https://direct.example.org/page3")
        self.assertTrue(all(u.startswith("https://") for u in urls))
        self.assertNotIn("duckduckgo.com", " ".join(urls))

    def test_ad_and_empty_title_results_skipped(self):
        _, hits = self.fetch()
        titles = [h["title"] for h in hits]
        self.assertEqual(titles[0], "The First Result — Example")
        self.assertEqual(len(titles), 2)
        self.assertFalse(any("Buy things" in t for t in titles))
        self.assertIn("example query", hits[0]["snippet"])
        self.assertNotIn("<b>", hits[0]["snippet"])

    def test_pagination_offset_params(self):
        self.fetch(start=61, num=10)
        url = self.fake.calls[0]["url"]
        self.assertIn("s=60", url)
        self.assertIn("dc=61", url)
        self.assertTrue(url.startswith("https://html.duckduckgo.com/html/"))

    def test_positions_follow_start(self):
        _, hits = self.fetch()
        self.assertEqual([h["pos"] for h in hits], [1, 2])

    def test_window_slice_for_deep_start(self):
        dummy = [
            {"url": f"https://x.example/{i}", "title": f"t{i}", "snippet": ""}
            for i in range(40)
        ]
        with mock.patch.object(backends, "_parse_ddg", return_value=dummy):
            _, hits = self.fetch(start=35, num=5)
        # start=35 -> skip=30 (s=30), local offset 4 into the fetched page
        self.assertEqual([h["pos"] for h in hits], [35, 36, 37, 38, 39])
        self.assertEqual(hits[0]["url"], "https://x.example/4")
        self.assertEqual(hits[-1]["url"], "https://x.example/8")

    def test_captcha_page_raises_429(self):
        self.fake._responder = lambda m, u, h, p: (200, load_fixture("ddg_captcha"))
        with self.assertRaises(CseError) as ctx:
            self.fetch()
        payload = ctx.exception.payload
        self.assertEqual(payload["error"]["code"], 429)
        self.assertEqual(payload["error"]["status"], "RESOURCE_EXHAUSTED")

    def test_end_to_end_default_shape(self):
        with mock.patch.dict(os.environ, {"CSEBRIDGE_BACKEND": "ddg"}):
            resp = api.search("example domains")
        self.assertEqual(resp["kind"], "customsearch#search")
        self.assertEqual(len(resp["items"]), 2)
        self.assertEqual(resp["items"][0]["link"], "https://www.example.com/first")
        self.assertEqual(resp["items"][0]["displayLink"], "www.example.com")


if __name__ == "__main__":
    unittest.main()
