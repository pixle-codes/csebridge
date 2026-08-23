import os
import unittest
import urllib.parse
from unittest import mock

from csebridge import api
from csebridge.errors import CseError

from .helpers import FakeTransport


def brave_page_responder(short_at=None):
    """Returns `count` unique hits per call; optional short page at an offset."""

    def respond(method, url, headers, payload):
        qs = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        offset = int(qs["offset"][0])
        count = int(qs["count"][0])
        if short_at is not None and offset >= short_at:
            return 200, {"web": {"results": [
                _brave_hit(offset + i) for i in range(2)
            ]}}
        return 200, {"web": {"results": [
            _brave_hit(offset + i) for i in range(count)
        ]}}

    return respond


def _brave_hit(n):
    return {
        "title": f"t{n}",
        "url": f"https://r.example/{n}",
        "description": "s",
        "position": n + 1,
    }


class TestFanOut(unittest.TestCase):
    def run_brave(self, responder, **kw):
        with mock.patch.dict(os.environ, {"BRAVE_API_KEY": "k"}):
            fake = FakeTransport(responder)
            with mock.patch("csebridge.transport.request", fake):
                resp = api.search("example domains", backend="brave", **kw)
        return resp, fake

    def test_num_over_ten_fans_out_and_merges(self):
        resp, fake = self.run_brave(brave_page_responder(), num=25)
        self.assertEqual(len(fake.calls), 3)
        starts = [urllib.parse.parse_qs(urllib.parse.urlsplit(c["url"]).query)["offset"][0]
                  for c in fake.calls]
        self.assertEqual(starts, ["0", "10", "20"])
        counts = [urllib.parse.parse_qs(urllib.parse.urlsplit(c["url"]).query)["count"][0]
                  for c in fake.calls]
        self.assertEqual(counts, ["10", "10", "5"])
        self.assertEqual(len(resp["items"]), 25)

    def test_request_block_echoes_caller_intent(self):
        resp, _ = self.run_brave(brave_page_responder(), num=25)
        req = resp["queries"]["request"][0]
        self.assertEqual(req["count"], 25)
        self.assertEqual(req["startIndex"], 1)
        nxt = resp["queries"]["nextPage"][0]
        self.assertEqual(nxt["startIndex"], 26)

    def test_positions_are_continuous_across_pages(self):
        resp, _ = self.run_brave(brave_page_responder(), start=7, num=15)
        items = resp["items"]
        # provider positions are absolute and stitched without gap or overlap
        links = [int(item["link"].rsplit("/", 1)[1]) for item in items]
        self.assertEqual(links, list(range(6, 21)))
        req = resp["queries"]["request"][0]
        nxt = resp["queries"]["nextPage"][0]
        self.assertEqual(req["startIndex"], 7)
        self.assertEqual(nxt["startIndex"], 22)
        self.assertEqual(items[0]["displayLink"], "r.example")

    def test_short_page_stops_fan_out(self):
        resp, fake = self.run_brave(brave_page_responder(short_at=10), num=30)
        self.assertEqual(len(fake.calls), 2)
        self.assertLess(len(resp["items"]), 30)
        self.assertNotIn("nextPage", resp["queries"])

    def test_duplicate_results_stop_fan_out(self):
        def full_pages_of_dupes(method, url, headers, payload):
            results = [
                {"title": "a", "url": "https://same.example/1", "description": ""},
                {"title": "b", "url": "https://same.example/2", "description": ""},
            ] * 5
            return 200, {"web": {"results": results}}

        resp, fake = self.run_brave(full_pages_of_dupes, num=30)
        self.assertEqual(len(fake.calls), 2)
        self.assertEqual(len(resp["items"]), 2)

    def test_small_requests_make_one_call(self):
        _, fake = self.run_brave(brave_page_responder(), num=10)
        self.assertEqual(len(fake.calls), 1)

    def test_window_beyond_100_is_rejected(self):
        with self.assertRaises(CseError) as ctx:
            self.run_brave(brave_page_responder(), start=95, num=10)
        payload = ctx.exception.payload
        self.assertEqual(payload["error"]["code"], 400)
        self.assertIn("100", payload["error"]["message"])

    def test_image_search_fans_out_too(self):
        def images_responder(method, url, headers, payload):
            qs = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            offset = int(qs["offset"][0])
            count = int(qs["count"][0])
            results = [
                {
                    "title": f"img {offset + i}",
                    "url": f"https://page.example/{offset + i}",
                    "image": {"url": f"https://img.example/{offset + i}.jpg"},
                }
                for i in range(count)
            ]
            return 200, {"results": results}

        resp, fake = self.run_brave(images_responder, num=15, search_type="image")
        self.assertEqual(len(fake.calls), 2)
        self.assertTrue(all("/res/v1/images/search" in c["url"] for c in fake.calls))
        self.assertEqual(len(resp["items"]), 15)


if __name__ == "__main__":
    unittest.main()
