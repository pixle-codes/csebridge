"""Public entry point: search(q, backend=..., **cse_params) -> CSE JSON dict."""

import os
import time

from . import backends, cse, params
from .errors import CseError


def search(
    q,
    backend=None,
    num=10,
    start=1,
    lr=None,
    safe=None,
    site_search=None,
    site_search_filter="i",
    search_type=None,
    cx=None,
):
    """Run a web or image search and return a Custom Search JSON API-shaped dict.

    num may exceed CSE's 10-per-call cap (up to 100): requests are transparently
    fanned out into <=10-result pages and merged into one response. Raises
    CseError on any failure; `exc.payload` is the CSE error shape.
    """
    backend = backend or os.environ.get("CSEBRIDGE_BACKEND", "brave")
    p = params.normalize(
        q,
        num=num,
        start=start,
        lr=lr,
        safe=safe,
        site_search=site_search,
        site_search_filter=site_search_filter,
        search_type=search_type,
    )
    if cx:
        p["cx"] = str(cx)
    impl = backends.get_backend(backend)
    _check_window(p)
    fetch = impl.fetch_images if p["search_type"] == "image" else impl.fetch
    total, hits, elapsed = _collect(impl, fetch, p)
    return cse.build_response(
        p, total, hits, elapsed=elapsed, context_title="csebridge"
    )


def _check_window(p):
    last = p["start"] + p["num"] - 1
    if last > params.CSE_MAX_WINDOW:
        raise CseError(
            "start + num must not exceed "
            f"{params.CSE_MAX_WINDOW} (Google only served the first "
            f"{params.CSE_MAX_WINDOW} results; requested through {last})",
            code=400,
            reason="badRequest",
        )


def _collect(impl, fetch, p):
    """Fetch results, fanning out into <=CSE_MAX_PAGE pages when num > page size."""
    target = p["num"]
    cursor = p["start"]
    collected = []
    seen = set()
    total = None
    elapsed = 0.0
    while len(collected) < target and cursor <= params.CSE_MAX_WINDOW:
        page_size = min(params.CSE_MAX_PAGE, target - len(collected))
        pp = dict(p)
        pp["num"] = page_size
        pp["start"] = cursor
        started = time.monotonic()
        page_total, hits = fetch(pp)
        elapsed += max(time.monotonic() - started, 0.0)
        if total is None:
            total = page_total
        fresh = []
        for h in hits:
            key = h["url"] if "url" in h else h.get("image_url")
            if key not in seen:
                seen.add(key)
                fresh.append(h)
        if not fresh and len(collected) < target:
            break  # provider keeps repeating itself (e.g. unpaginated backends)
        collected.extend(fresh)
        if len(hits) < page_size:
            break
        cursor += page_size
    return total, collected, elapsed
