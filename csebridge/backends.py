"""Search backends. Each adapter returns (total_or_None, hits) where a hit is
{title, url, snippet, pos} with pos being the GLOBAL 1-based position.
Image adapters return hits shaped {title, image_url, context_url, ...}."""

import html.parser as _htmlparser
import os
import urllib.parse

from .errors import CseError
from . import transport


class Backend:
    name = "?"
    env_var = None
    setup_hint = ""
    supports_images = False

    def fetch(self, p):
        raise NotImplementedError

    def fetch_images(self, p):
        raise CseError(
            f"backend {self.name!r} does not support searchType=image; "
            "try serper, serpapi, brave, searxng or tavily",
            code=400,
            reason="badRequest",
        )


def _require_env(var, hint):
    val = os.environ.get(var, "").strip()
    if not val:
        raise CseError(
            f"backend requires {var} in the environment. {hint}",
            code=401,
            reason="missingApiKey",
            status="UNAUTHENTICATED",
        )
    return val


def _lang_code(lr):
    return lr.split("_", 1)[1] if lr else None


def _pos(positions, i, start):
    for candidate in positions:
        if isinstance(candidate, int) and candidate > 0:
            return candidate
    return start + i


def _hit_from(title, url, snippet, pos):
    title = (title or "").strip()
    url = (url or "").strip()
    if not url:
        return None
    return {
        "title": title,
        "url": url,
        "snippet": (snippet or "").strip(),
        "pos": pos,
    }


def _clean(hits):
    return [h for h in hits if h]


def _image_hit(title, image_url, context_url=None, thumbnail_url=None,
               width=None, height=None, byte_size=None):
    if not image_url:
        return None
    return {
        "title": (title or "").strip(),
        "image_url": image_url.strip(),
        "context_url": (context_url or "").strip(),
        "thumbnail_url": (thumbnail_url or "").strip(),
        "width": int(width) if width else None,
        "height": int(height) if height else None,
        "byte_size": int(byte_size) if byte_size else None,
    }


class _DdgParser(_htmlparser.HTMLParser):
    """Extracts result links + snippets from html.duckduckgo.com responses."""

    def __init__(self):
        super().__init__()
        self.results = []
        self._current = None
        self._buf = None

    def handle_starttag(self, tag, attrs):
        if tag != "a":
            return
        cls = dict(attrs).get("class") or ""
        href = dict(attrs).get("href") or ""
        if "result__a" in cls:
            self._flush()
            self._current = {"href": href, "text": []}
            self._buf = self._current["text"]
        elif "result__snippet" in cls and self._current is not None:
            self._buf = self._current.setdefault("snippet", [])

    def handle_data(self, data):
        if self._buf is not None:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == "a":
            self._buf = None

    def _flush(self):
        if not self._current:
            return
        url = _unwrap_ddg_href(self._current["href"])
        title = "".join(self._current["text"]).strip()
        snippet = "".join(self._current.get("snippet") or []).strip()
        if url and title:
            self.results.append({"url": url, "title": title, "snippet": snippet})
        self._current = None

    def close(self):
        self._flush()
        super().close()


def _unwrap_ddg_href(href):
    """//duckduckgo.com/l/?uddg=<enc>&rut=.. -> real url; ads (/y.js) dropped."""
    if not href:
        return None
    if href.startswith("//"):
        href = "https:" + href
    split = urllib.parse.urlsplit(href)
    uddg = (urllib.parse.parse_qs(split.query) or {}).get("uddg", [None])[0]
    if uddg:
        return urllib.parse.unquote(uddg)
    path = split.path or ""
    if "/y.js" in path or split.netloc.endswith("duckduckgo.com"):
        return None
    return href


def _parse_ddg(html):
    parser = _DdgParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - malformed HTML must not crash the backend
        pass
    return parser.results


class Brave(Backend):
    name = "brave"
    env_var = "BRAVE_API_KEY"
    setup_hint = "Create an API key at https://api-dashboard.search.brave.com/"
    supports_images = True

    def fetch(self, p):
        key = _require_env(self.env_var, self.setup_hint)
        q = {
            "q": p["query"],
            "count": p["num"],
            "offset": p["start"] - 1,
        }
        lang = _lang_code(p["lr"])
        if lang:
            q["search_lang"] = lang
        if p["safe"]:
            q["safesearch"] = "strict" if p["safe"] == "active" else "off"
        url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(q)
        status, body = self._call(url, {"X-Subscription-Token": key, "Accept": "application/json"})
        results = (body.get("web") or {}).get("results") or []
        hits = []
        for i, r in enumerate(results):
            hits.append(
                _hit_from(
                    r.get("title"),
                    r.get("url"),
                    r.get("description"),
                    _pos([r.get("position")], i, p["start"]),
                )
            )
        return None, _clean(hits)

    def fetch_images(self, p):
        key = _require_env(self.env_var, self.setup_hint)
        q = {
            "q": p["query"],
            "count": p["num"],
            "offset": p["start"] - 1,
        }
        if p["safe"]:
            q["safesearch"] = "strict" if p["safe"] == "active" else "off"
        url = (
            "https://api.search.brave.com/res/v1/images/search?"
            + urllib.parse.urlencode(q)
        )
        try:
            status, body = transport.request(
                "GET", url, headers={"X-Subscription-Token": key, "Accept": "application/json"}
            )
        except transport.TransportError as exc:
            raise _wrap_transport(exc) from exc
        hits = [
            _image_hit(
                title=r.get("title"),
                image_url=(r.get("image") or {}).get("url"),
                context_url=r.get("url"),
                thumbnail_url=(r.get("thumbnail") or {}).get("src")
                or (r.get("thumbnail") or {}).get("url"),
                width=((r.get("properties") or {}).get("width")),
                height=((r.get("properties") or {}).get("height")),
            )
            for r in body.get("results") or []
        ]
        return None, _clean(hits)

    def _call(self, url, headers):
        try:
            return transport.request("GET", url, headers=headers)
        except transport.TransportError as exc:
            raise _wrap_transport(exc) from exc


class Serper(Backend):
    name = "serper"
    env_var = "SERPER_API_KEY"
    setup_hint = "Get a key at https://serper.dev (dashboard)."
    supports_images = True

    def fetch(self, p):
        key = _require_env(self.env_var, self.setup_hint)
        payload = {"q": p["query"], "num": p["num"]}
        payload["page"] = ((p["start"] - 1) // p["num"]) + 1
        if p["lr"]:
            payload["hl"] = _lang_code(p["lr"])
        try:
            status, body = transport.request(
                "POST",
                "https://google.serper.dev/search",
                headers={"X-API-KEY": key},
                payload=payload,
            )
        except transport.TransportError as exc:
            raise _wrap_transport(exc) from exc
        organic = body.get("organic") or []
        hits = []
        for i, r in enumerate(organic):
            hits.append(
                _hit_from(
                    r.get("title"),
                    r.get("link"),
                    r.get("snippet"),
                    _pos([r.get("position")], i, p["start"]),
                )
            )
        return None, _clean(hits)

    def fetch_images(self, p):
        key = _require_env(self.env_var, self.setup_hint)
        payload = {"q": p["query"], "num": p["num"], "page": ((p["start"] - 1) // p["num"]) + 1}
        try:
            status, body = transport.request(
                "POST",
                "https://google.serper.dev/images",
                headers={"X-API-KEY": key},
                payload=payload,
            )
        except transport.TransportError as exc:
            raise _wrap_transport(exc) from exc
        hits = [
            _image_hit(
                title=r.get("title"),
                image_url=r.get("imageUrl"),
                context_url=r.get("link"),
                thumbnail_url=r.get("thumbnailUrl"),
                width=r.get("imageWidth"),
                height=r.get("imageHeight"),
            )
            for r in body.get("images") or []
        ]
        return None, _clean(hits)


class SerpApi(Backend):
    name = "serpapi"
    env_var = "SERPAPI_API_KEY"
    setup_hint = "Get a key at https://serpapi.com/manage-api-key."
    supports_images = True

    def fetch(self, p):
        key = _require_env(self.env_var, self.setup_hint)
        q = {"q": p["query"], "num": p["num"], "start": p["start"], "api_key": key}
        lang = _lang_code(p["lr"])
        if lang:
            q["hl"] = lang
        if p["safe"]:
            q["safe"] = p["safe"]
        url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(q)
        try:
            status, body = transport.request("GET", url)
        except transport.TransportError as exc:
            raise _wrap_transport(exc) from exc
        if isinstance(body, dict) and body.get("error"):
            raise CseError(str(body["error"]), code=400, reason="badRequest")
        total = (body.get("search_information") or {}).get("total_results")
        total = int(total) if total else None
        organic = body.get("organic_results") or []
        hits = []
        for i, r in enumerate(organic):
            hits.append(
                _hit_from(
                    r.get("title"),
                    r.get("link"),
                    r.get("snippet"),
                    _pos([r.get("position")], i, p["start"]),
                )
            )
        return total, _clean(hits)

    def fetch_images(self, p):
        key = _require_env(self.env_var, self.setup_hint)
        q = {"engine": "google_images", "q": p["query"], "api_key": key}
        url = "https://serpapi.com/search.json?" + urllib.parse.urlencode(q)
        try:
            status, body = transport.request("GET", url)
        except transport.TransportError as exc:
            raise _wrap_transport(exc) from exc
        if isinstance(body, dict) and body.get("error"):
            raise CseError(str(body["error"]), code=400, reason="badRequest")
        hits = [
            _image_hit(
                title=r.get("title"),
                image_url=r.get("original"),
                context_url=r.get("source_link") or r.get("link"),
                thumbnail_url=r.get("thumbnail"),
                width=r.get("original_width"),
                height=r.get("original_height"),
            )
            for r in body.get("images_results") or []
        ]
        return None, _clean(hits)


class Tavily(Backend):
    name = "tavily"
    env_var = "TAVILY_API_KEY"
    setup_hint = "Get a key at https://app.tavily.com."
    supports_images = True

    def fetch(self, p):
        key = _require_env(self.env_var, self.setup_hint)
        payload = {"query": p["query"], "max_results": p["num"]}
        try:
            status, body = transport.request(
                "POST",
                "https://api.tavily.com/search",
                headers={"Authorization": f"Bearer {key}"},
                payload=payload,
            )
        except transport.TransportError as exc:
            raise _wrap_transport(exc) from exc
        results = body.get("results") or []
        hits = []
        for i, r in enumerate(results):
            hits.append(_hit_from(r.get("title"), r.get("url"), r.get("content"), p["start"] + i))
        # Tavily is relevance-ranked and unpaginated; positions restart per call.
        return None, _clean(hits)

    def fetch_images(self, p):
        key = _require_env(self.env_var, self.setup_hint)
        payload = {
            "query": p["query"],
            "max_results": p["num"],
            "include_images": True,
            "include_image_descriptions": True,
        }
        try:
            status, body = transport.request(
                "POST",
                "https://api.tavily.com/search",
                headers={"Authorization": f"Bearer {key}"},
                payload=payload,
            )
        except transport.TransportError as exc:
            raise _wrap_transport(exc) from exc
        hits = []
        for r in body.get("images") or []:
            if isinstance(r, str):
                r = {"url": r}
            hits.append(_image_hit(title=r.get("description"), image_url=r.get("url")))
        return None, _clean(hits)


class Searxng(Backend):
    name = "searxng"
    env_var = "SEARXNG_BASE_URL"
    setup_hint = "Point SEARXNG_BASE_URL at your instance, e.g. https://searx.example.org"
    supports_images = True

    def fetch(self, p):
        base = _require_env(self.env_var, self.setup_hint).rstrip("/")
        page = ((p["start"] - 1) // p["num"]) + 1
        q = {"q": p["query"], "format": "json", "pageno": page}
        lang = _lang_code(p["lr"])
        if lang:
            q["language"] = lang
        if p["safe"]:
            q["safesearch"] = 1 if p["safe"] == "active" else 0
        url = f"{base}/search?" + urllib.parse.urlencode(q)
        try:
            status, body = transport.request("GET", url)
        except transport.TransportError as exc:
            raise _wrap_transport(exc) from exc
        raw = body.get("results") or []
        hits = []
        for i, r in enumerate(raw[: p["num"]]):
            positions = r.get("positions") or []
            hits.append(
                _hit_from(r.get("title"), r.get("url"), r.get("content"), _pos(positions, i, p["start"]))
            )
        total = body.get("number_of_results")
        total = int(total) if total else None
        return total, _clean(hits)

    def fetch_images(self, p):
        base = _require_env(self.env_var, self.setup_hint).rstrip("/")
        page = ((p["start"] - 1) // p["num"]) + 1
        q = {"q": p["query"], "format": "json", "pageno": page, "categories": "images"}
        url = f"{base}/search?" + urllib.parse.urlencode(q)
        try:
            status, body = transport.request("GET", url)
        except transport.TransportError as exc:
            raise _wrap_transport(exc) from exc
        hits = []
        for r in (body.get("results") or [])[: p["num"]]:
            thumb = r.get("thumbnail")
            if not isinstance(thumb, str):
                thumb = r.get("thumbnail_src") or ""
            hits.append(
                _image_hit(
                    title=r.get("title"),
                    image_url=r.get("img_src"),
                    context_url=r.get("url"),
                    thumbnail_url=thumb,
                )
            )
        return None, _clean(hits)


class Ddg(Backend):
    """Keyless DuckDuckGo HTML backend. Opt-in only: unofficial, fragile,
    CAPTCHA-prone under load. Fixture-tested; not part of any default order."""

    name = "ddg"
    env_var = None
    setup_hint = "No key needed, but expect rate limiting: set CSEBRIDGE_BACKEND=brave for production."
    NATIVE_PAGE = 30  # DDG html serves ~30 results regardless of requested num

    def fetch(self, p):
        skip = ((p["start"] - 1) // self.NATIVE_PAGE) * self.NATIVE_PAGE
        q = {"q": p["query"], "s": str(skip), "dc": str(skip + 1)}
        url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode(q)
        try:
            status, body = transport.request("GET", url)
        except transport.TransportError as exc:
            raise _wrap_transport(exc) from exc
        html = body if isinstance(body, str) else ""
        if "/captcha" in html or "anomaly" in html.lower():
            raise CseError(
                "duckduckgo demanded a human check (rate limited); "
                "retry later or switch backends",
                code=429,
                reason="rateLimitExceeded",
            )
        parsed = _parse_ddg(html)
        lo = (p["start"] - 1) % self.NATIVE_PAGE
        window = parsed[lo : lo + p["num"]]
        hits = []
        for i, res in enumerate(window):
            hits.append(
                _hit_from(res["title"], res["url"], res["snippet"], p["start"] + i)
            )
        return None, _clean(hits)


BACKENDS = {b.name: b for b in (Brave(), Serper(), SerpApi(), Tavily(), Searxng(), Ddg())}


def get_backend(name):
    backend = BACKENDS.get(name)
    if backend is None:
        raise CseError(
            f"unknown backend {name!r}; available: {', '.join(sorted(BACKENDS))}",
            code=400,
            reason="badRequest",
        )
    return backend


def _wrap_transport(exc):
    code = exc.status or 503
    reason = {
        400: "badRequest",
        401: "missingApiKey",
        403: "forbidden",
        429: "rateLimitExceeded",
    }.get(code, "backendError")
    detail = (exc.body or "")[:300]
    message = f"{exc}: {detail}".rstrip(": ")
    return CseError(message, code=code, reason=reason)
