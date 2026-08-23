import unittest

from csebridge import cse, params


def make(params_kwargs=None):
    p = params.normalize("example domains", **(params_kwargs or {}))
    hits = [
        {"title": "Example Domain", "url": "https://example.com/", "snippet": "This domain is for use in illustrative examples.", "pos": 1},
        {"title": "Reserved Domains - IANA", "url": "https://www.iana.org/domains/reserved", "snippet": "Certain domains are set aside.", "pos": 2},
    ]
    return cse.build_response(p, None, hits, elapsed=0.26), p, hits


class TestGoldenShape(unittest.TestCase):
    def test_top_level_kind_and_url(self):
        resp, _, _ = make()
        self.assertEqual(resp["kind"], "customsearch#search")
        self.assertEqual(resp["url"]["type"], "application/json")
        self.assertTrue(resp["url"]["template"].startswith("https://www.googleapis.com/customsearch/v1?q="))

    def test_search_information_fields(self):
        resp, _, _ = make()
        info = resp["searchInformation"]
        self.assertEqual(info["searchTime"], 0.26)
        self.assertEqual(info["formattedSearchTime"], "0.26")
        # no backend total -> visible estimate
        self.assertEqual(info["totalResults"], "2")
        self.assertEqual(info["formattedTotalResults"], "2")

    def test_backend_total_wins_and_formats(self):
        p = params.normalize("q")
        resp = cse.build_response(
            p,
            95300000,
            [{"title": "t", "url": "https://a.io", "snippet": "", "pos": 1}],
            elapsed=0.0,
        )
        self.assertEqual(resp["searchInformation"]["totalResults"], "95300000")
        self.assertEqual(resp["searchInformation"]["formattedTotalResults"], "95,300,000")

    def test_context_present(self):
        resp, _, _ = make()
        self.assertIn("title", resp["context"])

    def test_item_field_set_matches_cse(self):
        resp, _, _ = make()
        item = resp["items"][0]
        for key in (
            "title",
            "htmlTitle",
            "link",
            "displayLink",
            "snippet",
            "htmlSnippet",
            "formattedUrl",
            "htmlFormattedUrl",
        ):
            self.assertIn(key, item)
        self.assertEqual(item["displayLink"], "example.com")

    def test_html_fields_bold_matched_terms(self):
        resp, _, _ = make()
        item = resp["items"][0]
        self.assertIn("<b>Example</b>", item["htmlTitle"])
        # second item's title carries the word "Domains"
        self.assertIn("<b>Domains</b>", resp["items"][1]["htmlTitle"])
        # snippet itself must stay plain text
        self.assertNotIn("<b>", item["snippet"])


class TestQueriesBlock(unittest.TestCase):
    def test_request_echoes_caller_params(self):
        resp, p, _ = make({"num": 2})
        req = resp["queries"]["request"][0]
        self.assertEqual(req["searchTerms"], "example domains")
        self.assertEqual(req["count"], 2)
        self.assertEqual(req["startIndex"], 1)
        self.assertEqual(req["inputEncoding"], "utf8")
        self.assertEqual(req["outputEncoding"], "utf8")
        self.assertEqual(req["safe"], "false")
        self.assertIn("Google Custom Search - example domains", req["title"])

    def test_no_next_page_when_fewer_results_than_num(self):
        resp, _, _ = make()
        self.assertNotIn("nextPage", resp["queries"])

    def test_next_page_when_page_is_full(self):
        p = params.normalize("q", num=2)
        hits = [
            {"title": f"r{i}", "url": f"https://e{i}.io", "snippet": "", "pos": i}
            for i in range(1, 3)
        ]
        resp = cse.build_response(p, None, hits, elapsed=0.1)
        nxt = resp["queries"]["nextPage"][0]
        self.assertEqual(nxt["startIndex"], 3)

    def test_previous_page_when_past_first(self):
        resp, _, _ = make({"start": 11, "num": 10})
        prev = resp["queries"]["previousPage"][0]
        self.assertEqual(prev["startIndex"], 1)
        self.assertEqual(resp["queries"]["request"][0]["startIndex"], 11)

    def test_both_directions_mid_stream(self):
        p = params.normalize("q", start=21, num=2)
        hits = [
            {"title": f"r{i}", "url": f"https://e{i}.io", "snippet": "", "pos": i}
            for i in range(21, 23)
        ]
        resp = cse.build_response(p, None, hits, elapsed=0.1)
        self.assertEqual(resp["queries"]["nextPage"][0]["startIndex"], 23)
        self.assertEqual(resp["queries"]["previousPage"][0]["startIndex"], 19)


class TestPagemap(unittest.TestCase):
    def hit(self, **extras):
        base = {"title": "t", "url": "https://a.example/", "snippet": "s", "pos": 1}
        base.update(extras)
        return base

    def test_no_pagemap_without_extras(self):
        p = params.normalize("q")
        resp = cse.build_response(p, None, [self.hit()], elapsed=0.0)
        self.assertNotIn("pagemap", resp["items"][0])

    def test_image_and_thumbnail_populate_cse_keys(self):
        p = params.normalize("q")
        hit = self.hit(
            image_url="https://img.example/pic.jpg",
            thumbnail_url="https://img.example/pic_s.jpg",
            width=640,
            height=480,
            metatags={"og:title": "The Title"},
        )
        resp = cse.build_response(p, None, [hit], elapsed=0.0)
        pm = resp["items"][0]["pagemap"]
        self.assertEqual(pm["cse_image"], [{"src": "https://img.example/pic.jpg"}])
        self.assertEqual(
            pm["cse_thumbnail"],
            [{"src": "https://img.example/pic_s.jpg", "width": "640", "height": "480"}],
        )
        self.assertEqual(pm["metatags"], [{"og:title": "The Title"}])

    def test_image_item_omits_context_when_missing(self):
        from csebridge.backends import _image_hit

        h = _image_hit(title="x", image_url="https://img.example/a.png", width="10")
        item = cse._image_item(h, "q")
        # no context page known -> image url doubles as link and context
        self.assertEqual(item["link"], "https://img.example/a.png")
        self.assertEqual(item["image"]["contextLink"], "https://img.example/a.png")
        self.assertNotIn("byteSize", item["image"])
        self.assertEqual(item["mime"], "image/png")


if __name__ == "__main__":
    unittest.main()
