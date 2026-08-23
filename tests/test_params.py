import unittest

from csebridge import params
from csebridge.params import UsageError


class TestNormalize(unittest.TestCase):
    def test_defaults(self):
        p = params.normalize("hello world")
        self.assertEqual(p["q"], "hello world")
        self.assertEqual(p["num"], 10)
        self.assertEqual(p["start"], 1)
        self.assertIsNone(p["lr"])
        self.assertIsNone(p["safe"])

    def test_empty_q_raises_usage(self):
        with self.assertRaises(UsageError):
            params.normalize("   ")

    def test_non_string_q_raises_usage(self):
        with self.assertRaises(UsageError):
            params.normalize(123)

    def test_num_clamped_to_window(self):
        # num>10 is allowed since v0.2 (api fans out); hard ceiling = 100
        self.assertEqual(params.normalize("q", num=50)["num"], 50)
        self.assertEqual(params.normalize("q", num=250)["num"], 100)
        self.assertEqual(params.normalize("q", num=0)["num"], 1)

    def test_search_type_validation(self):
        self.assertIsNone(params.normalize("q")["search_type"])
        self.assertEqual(params.normalize("q", search_type="image")["search_type"], "image")
        self.assertEqual(params.normalize("q", search_type="IMAGE")["search_type"], "image")
        with self.assertRaises(UsageError):
            params.normalize("q", search_type="video")
        with self.assertRaises(UsageError):
            params.normalize("q", search_type="news")

    def test_start_below_one_raises(self):
        with self.assertRaises(UsageError):
            params.normalize("q", start=0)

    def test_safe_aliases(self):
        self.assertEqual(params.normalize("q", safe="true")["safe"], "active")
        self.assertEqual(params.normalize("q", safe="false")["safe"], "off")
        self.assertEqual(params.normalize("q", safe="ACTIVE")["safe"], "active")
        with self.assertRaises(UsageError):
            params.normalize("q", safe="moderate")

    def test_lr_forms(self):
        self.assertEqual(params.normalize("q", lr="lang_en")["lr"], "lang_en")
        self.assertEqual(params.normalize("q", lr="en")["lr"], "lang_en")
        self.assertEqual(params.normalize("q", lr="EN-us")["lr"], "lang_en")
        self.assertIsNone(params.normalize("q", lr="")["lr"])
        with self.assertRaises(UsageError):
            params.normalize("q", lr="english")

    def test_site_search_include_rewrites_query(self):
        p = params.normalize("docs", site_search="python.org")
        self.assertIn("+site:python.org", p["query"])

    def test_site_search_exclude_rewrites_query(self):
        p = params.normalize("docs", site_search="pinterest.com", site_search_filter="e")
        self.assertIn("-site:pinterest.com", p["query"])

    def test_bad_ints_raise_usage(self):
        with self.assertRaises(UsageError):
            params.normalize("q", num="ten")


if __name__ == "__main__":
    unittest.main()
