"""Emit Google Custom Search JSON API-shaped responses from normalized hits."""

import html as _html
import re
import time
import urllib.parse

from .errors import CseError

URL_TEMPLATE = (
    "https://www.googleapis.com/customsearch/v1?q={searchTerms}&num={count?}"
    "&start={startIndex?}&lr={language?}&safe={safe?}&cx={cx?}&sort={sort?}"
    "&filter={filter?}&gl={gl?}&cr={cr?}&googlehost={googleHost?}"
    "&c2coff={disableCnTwTranslation?}&hq={hq?}&hl={hl?}&siteSearch={siteSearch?}"
    "&siteSearchFilter={siteSearchFilter?}&exactTerms={exactTerms?}"
    "&excludeTerms={excludeTerms?}&linkSite={linkSite?}&orTerms={orTerms?}"
    "&dateRestrict={dateRestrict?}&lowRange={lowRange?}&highRange={highRange?}"
    "&searchType={searchType?}&fileType={fileType?}&rights={rights?}"
    "&imgSize={imgSize?}&imgType={imgType?}&imgColorType={imgColorType?}"
    "&imgDominantColor={imgDominantColor?}&alt=json"
)

_BOLD_CACHE = {}


def build_response(p, total, hits, elapsed=None, context_title="csebridge"):
    now = time.time()
    if p["search_type"] == "image":
        items = [_image_item(h, p["q"]) for h in hits]
    else:
        items = [_item(h, p["q"]) for h in hits]
    resp = {
        "kind": "customsearch#search",
        "url": {"type": "application/json", "template": URL_TEMPLATE},
        "queries": _queries(p, total, len(items)),
        "context": {"title": context_title},
        "searchInformation": {
            "searchTime": round(elapsed if elapsed is not None else 0.0, 2),
            "formattedSearchTime": f"{round(elapsed if elapsed is not None else 0.0, 2):.2f}",
            "totalResults": str(total if total is not None else _visible_total(p, items)),
            "formattedTotalResults": _format_int(
                total if total is not None else _visible_total(p, items)
            ),
        },
        "items": items,
    }
    return resp


def build_error_payload(exc):
    return exc.payload


def error_response(exc):
    """Some callers prefer the error inline; keep both paths available."""
    return build_error_payload(exc)


def _queries(p, total, n_items):
    request_block = {
        "title": f"Google Custom Search - {p['q']}",
        "totalResults": str(total if total is not None else ""),
        "searchTerms": p["q"],
        "count": p["num"],
        "startIndex": p["start"],
        "inputEncoding": "utf8",
        "outputEncoding": "utf8",
        "safe": "true" if p["safe"] == "active" else "false",
    }
    if p.get("cx"):
        request_block["cx"] = p["cx"]
    queries = {"request": [request_block]}
    if n_items == p["num"]:
        nxt = dict(request_block)
        nxt["startIndex"] = p["start"] + p["num"]
        queries["nextPage"] = [nxt]
    if p["start"] > 1:
        prev = dict(request_block)
        prev["startIndex"] = max(1, p["start"] - p["num"])
        queries["previousPage"] = [prev]
    return queries


def _visible_total(p, items):
    return (p["start"] - 1) + len(items)


def _item(hit, q):
    link = hit["url"]
    display = urllib.parse.urlsplit(link).netloc
    title = hit["title"] or link
    snippet = hit["snippet"]
    item = {
        "title": title,
        "htmlTitle": _bold_terms(title, q),
        "link": link,
        "displayLink": display,
        "snippet": snippet,
        "htmlSnippet": _bold_terms(snippet, q),
        "formattedUrl": link,
        "htmlFormattedUrl": _html.escape(link),
    }
    pagemap = _pagemap(hit)
    if pagemap:
        item["pagemap"] = pagemap
    return item


def _pagemap(hit):
    """Best-effort pagemap: only populated when the backend supplied extras."""
    pagemap = {}
    if hit.get("image_url"):
        pagemap["cse_image"] = [{"src": hit["image_url"]}]
    if hit.get("thumbnail_url"):
        entry = {"src": hit["thumbnail_url"]}
        if hit.get("width"):
            entry["width"] = str(hit["width"])
        if hit.get("height"):
            entry["height"] = str(hit["height"])
        pagemap.setdefault("cse_thumbnail", []).append(entry)
    metatags = hit.get("metatags")
    if isinstance(metatags, dict) and metatags:
        pagemap["metatags"] = [metatags]
    return pagemap


def _image_item(hit, q):
    image_url = hit["image_url"]
    context = hit.get("context_url") or image_url
    display = urllib.parse.urlsplit(context).netloc
    title = hit.get("title") or image_url.rsplit("/", 1)[-1] or image_url
    image_block = {"contextLink": context}
    for src_key, dst_key in (
        ("thumbnail_url", "thumbnailLink"),
        ("thumbnail_width", "thumbnailWidth"),
        ("thumbnail_height", "thumbnailHeight"),
        ("width", "width"),
        ("height", "height"),
        ("byte_size", "byteSize"),
    ):
        val = hit.get(src_key)
        if val not in (None, ""):
            image_block[dst_key] = val
    item = {
        "title": title,
        "htmlTitle": _bold_terms(title, q),
        "link": context,
        "displayLink": display,
        "formattedUrl": context,
        "htmlFormattedUrl": _html.escape(context),
        "image": image_block,
    }
    mime = _guess_mime(image_url)
    if mime:
        item["mime"] = mime
        item["fileFormat"] = mime
    pagemap = _pagemap(hit)
    if pagemap:
        item["pagemap"] = pagemap
    return item


def _guess_mime(url):
    ext = url.rsplit(".", 1)[-1].lower() if "." in url.rsplit("/", 1)[-1] else ""
    return {
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
        "gif": "image/gif",
        "webp": "image/webp",
        "svg": "image/svg+xml",
    }.get(ext)


def _bold_terms(text, q):
    """CSE bolds matched query terms inside html* fields. Approximate it."""
    escaped = _html.escape(text)
    terms = [t for t in re.findall(r"[A-Za-z0-9']{3,}", q) if t.lower() not in ("site",)]
    seen = set()
    for term in terms:
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        pattern = re.compile(r"\b" + re.escape(_html.escape(term)) + r"\b", re.IGNORECASE)
        escaped = pattern.sub(lambda m: f"<b>{m.group(0)}</b>", escaped)
    return escaped


def _format_int(n):
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "0"
