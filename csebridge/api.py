"""Public entry point: search(q, backend=..., **cse_params) -> CSE JSON dict."""

import os

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
    cx=None,
):
    """Run a web search and return a Custom Search JSON API-shaped dict.

    Raises CseError on any failure; `exc.payload` is the CSE error shape.
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
    )
    if cx:
        p["cx"] = str(cx)
    impl = backends.get_backend(backend)
    started = _now()
    total, hits = impl.fetch(p)
    elapsed = max(_now() - started, 0.0)
    return cse.build_response(p, total, hits, elapsed=elapsed)


def _now():
    import time

    return time.monotonic()
