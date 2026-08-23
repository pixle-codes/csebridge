import os
import unittest
from unittest import mock

from csebridge import api
from csebridge import backends
from csebridge.errors import CseError

from .helpers import FakeTransport, load_fixture, ok


class ImageBackendCase(unittest.TestCase):
    backend_name = None
    fixture = None
    env_var = None
    env_value = "test-key-123"
    endpoint = ""

    def setUp(self):
        self.backend = backends.BACKENDS[self.backend_name]
        patcher = mock.patch.dict(os.environ, {self.env_var: self.env_value})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.fake = FakeTransport(ok(load_fixture(self.fixture)))
        patch = mock.patch.object(backends.transport, "request", self.fake)
        patch.start()
        self.addCleanup(patch.stop)

    def fetch_images(self, **overrides):
        from .test_backends import PARAMS

        p = dict(PARAMS)
        p.update(overrides)
        return self.backend.fetch_images(p)


class TestBraveImages(ImageBackendCase):
    backend_name = "brave"
    fixture = "brave_images"
    env_var = "BRAVE_API_KEY"
    endpoint = "/res/v1/images/search"

    def test_endpoint_and_auth(self):
        _, hits = self.fetch_images()
        call = self.fake.calls[0]
        self.assertIn(self.endpoint, call["url"])
        self.assertEqual(call["headers"]["X-Subscription-Token"], "test-key-123")

    def test_image_fields_mapped(self):
        _, hits = self.fetch_images()
        first = hits[0]
        self.assertEqual(first["image_url"], "https://cdn.cats.example/tabby.jpg")
        self.assertEqual(first["context_url"], "https://cats.example/gallery/tabby")
        self.assertEqual(first["thumbnail_url"], "https://cdn.cats.example/tabby_thumb.jpg")
        self.assertEqual(first["width"], 1200)
        self.assertEqual(first["height"], 800)
        # second result has no width/height -> Nones
        self.assertIsNone(hits[1]["width"])


class TestSerperImages(ImageBackendCase):
    backend_name = "serper"
    fixture = "serper_images"
    env_var = "SERPER_API_KEY"
    endpoint = "google.serper.dev/images"

    def test_posts_to_images_path(self):
        _, hits = self.fetch_images()
        call = self.fake.calls[0]
        self.assertIn(self.endpoint, call["url"])
        self.assertEqual(call["method"], "POST")

    def test_dimensions_and_thumbnail(self):
        _, hits = self.fetch_images()
        self.assertEqual(hits[0]["width"], 1024)
        self.assertEqual(hits[0]["height"], 768)
        self.assertEqual(hits[0]["thumbnail_url"], "https://cdn.dogs.example/puppy_s.jpg")


class TestSerpApiImages(ImageBackendCase):
    backend_name = "serpapi"
    fixture = "serpapi_images"
    env_var = "SERPAPI_API_KEY"
    endpoint = "serpapi.com/search.json"

    def test_engine_and_original_url(self):
        _, hits = self.fetch_images()
        self.assertIn("engine=google_images", self.fake.calls[0]["url"])
        self.assertEqual(hits[0]["image_url"], "https://cdn.birds.example/bluebird.jpg")
        self.assertEqual(hits[0]["context_url"], "https://birds.example/photos/1")


class TestTavilyImages(ImageBackendCase):
    backend_name = "tavily"
    fixture = "tavily_images"
    env_var = "TAVILY_API_KEY"

    def test_include_images_payload(self):
        total, hits = self.fetch_images(num=5)
        payload = self.fake.calls[0]["payload"]
        self.assertTrue(payload["include_images"])
        self.assertEqual(payload["max_results"], 5)

    def test_descriptions_become_titles_and_plain_strings_survive(self):
        _, hits = self.fetch_images()
        self.assertEqual(len(hits), 2)
        self.assertEqual(hits[0]["title"], "A clownfish in anemone")
        self.assertEqual(hits[0]["image_url"], "https://cdn.fish.example/clownfish.webp")
        self.assertEqual(hits[1]["image_url"], "https://cdn.fish.example/tang.png")


class TestSearxngImages(ImageBackendCase):
    backend_name = "searxng"
    fixture = "searxng_images"
    env_var = "SEARXNG_BASE_URL"

    def setUp(self):
        super().setUp()

    def test_categories_images_param(self):
        with mock.patch.dict(os.environ, {self.env_var: "https://searx.example.org"}):
            total, hits = self.fetch_images()
            self.assertIn("categories=images", self.fake.calls[0]["url"])
            self.assertEqual(hits[0]["image_url"], "https://cdn.photos.example/alpine.jpg")
            self.assertEqual(hits[0]["context_url"], "https://photos.example/albums/alpine")


class TestImageContract(unittest.TestCase):
    def run_serper(self, **kw):
        with mock.patch.dict(os.environ, {"SERPER_API_KEY": "k"}):
            fake = FakeTransport(ok(load_fixture("serper_images")))
            with mock.patch("csebridge.transport.request", fake):
                return api.search("cute dog", backend="serper", search_type="image", **kw)

    def test_cse_image_item_shape(self):
        resp = self.run_serper()
        item = resp["items"][0]
        self.assertEqual(item["link"], "https://dogs.example/posts/puppy")
        self.assertEqual(item["displayLink"], "dogs.example")
        self.assertEqual(item["mime"], "image/jpeg")
        self.assertEqual(item["fileFormat"], "image/jpeg")
        image = item["image"]
        self.assertEqual(image["contextLink"], "https://dogs.example/posts/puppy")
        self.assertEqual(image["width"], 1024)
        self.assertEqual(image["height"], 768)
        self.assertEqual(image["thumbnailLink"], "https://cdn.dogs.example/puppy_s.jpg")
        self.assertEqual(item["pagemap"]["cse_image"], [{"src": "https://cdn.dogs.example/puppy.jpg"}])

    def test_unsupported_backend_names_alternatives(self):
        with self.assertRaises(CseError) as ctx:
            api.search("q", backend="ddg", search_type="image")
        payload = ctx.exception.payload
        self.assertEqual(payload["error"]["code"], 400)
        self.assertIn("ddg", payload["error"]["message"])
        self.assertIn("serper", payload["error"]["message"])

    def test_bad_search_type_is_usage_error(self):
        from csebridge.params import UsageError

        with self.assertRaises(UsageError):
            api.search("q", backend="brave", search_type="video")


if __name__ == "__main__":
    unittest.main()
