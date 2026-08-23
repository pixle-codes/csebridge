"""Search backends. Each adapter returns (total_or_None, hits) where a hit is
{title, url, snippet, pos} with pos being the GLOBAL 1-based position."""

import os
import urllib.parse

from .errors import CseError
from . import transport


class Backend:
    name = "?"
    env_var = None
    setup_hint = ""

    def fetch(self, p):
        raise NotImplementedError


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


class Brave(Backend):
    name = "brave"
    env_var = "BRAVE_API_KEY"
    setup_hint = "Create an API key at https://api-dashboard.search.brave.com/"

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

    def _call(self, url, headers):
        try:
            return transport.request("GET", url, headers=headers)
        except transport.TransportError as exc:
            raise _wrap_transport(exc) from exc


class Serper(Backend):
    name = "serper"
    env_var = "SERPER_API_KEY"
    setup_hint = "Get a key at https://serper.dev (dashboard)."

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


class SerpApi(Backend):
    name = "serpapi"
    env_var = "SERPAPI_API_KEY"
    setup_hint = "Get a key at https://serpapi.com/manage-api-key."

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


class Tavily(Backend):
    name = "tavily"
    env_var = "TAVILY_API_KEY"
    setup_hint = "Get a key at https://app.tavily.com."

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


class Searxng(Backend):
    name = "searxng"
    env_var = "SEARXNG_BASE_URL"
    setup_hint = "Point SEARXNG_BASE_URL at your instance, e.g. https://searx.example.org"

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


BACKENDS = {b.name: b for b in (Brave(), Serper(), SerpApi(), Tavily(), Searxng())}


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
