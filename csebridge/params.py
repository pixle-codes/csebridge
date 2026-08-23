"""CSE parameter validation + normalization, and backend-agnostic rewrites."""

import re

CSE_MAX_PAGE = 10  # CSE never returned more than 10 results per call
CSE_MAX_WINDOW = 100  # Google only ever served the first 100 results

SAFE_MODES = {"off", "active"}
SEARCH_TYPES = {None, "image"}  # web is default; image via searchType=image
_SITE_RE = None


class UsageError(ValueError):
    """Raised for caller-side bad arguments (maps to CLI exit code 2)."""


def normalize(
    q,
    num=10,
    start=1,
    lr=None,
    safe=None,
    site_search=None,
    site_search_filter="i",
    search_type=None,
):
    if not isinstance(q, str) or not q.strip():
        raise UsageError("q must be a non-empty search string")
    q = q.strip()
    try:
        num = int(num)
        start = int(start)
    except (TypeError, ValueError) as exc:
        raise UsageError("num and start must be integers") from exc
    if not 1 <= num <= CSE_MAX_WINDOW:
        num = min(max(num, 1), CSE_MAX_WINDOW)
    if start < 1:
        raise UsageError("start must be >= 1")
    if safe is not None:
        safe = str(safe).lower()
        if safe in ("true", "1"):
            safe = "active"
        if safe in ("false", "0"):
            safe = "off"
        if safe not in SAFE_MODES:
            raise UsageError(f"safe must be one of {sorted(SAFE_MODES)}")
    lr = _normalize_lr(lr)
    if search_type is not None:
        search_type = str(search_type).strip().lower()
    if search_type not in SEARCH_TYPES:
        raise UsageError(
            f"unsupported searchType {search_type!r} (supported: image; omit for web)"
        )
    query = q
    if site_search:
        domain = str(site_search).strip()
        if not domain:
            raise UsageError("site_search must be a non-empty domain")
        op = "+" if site_search_filter == "i" else "-"
        query = f"{query} {op}site:{domain}"
    return {
        "q": q,
        "query": query,
        "num": num,
        "start": start,
        "lr": lr,
        "safe": safe,
        "site_search": site_search or None,
        "site_search_filter": "e" if site_search_filter == "e" else "i",
        "search_type": search_type,
    }


def _normalize_lr(lr):
    """`lang_en`, `en`, `EN-us` -> `lang_en`; None stays None. Bad forms raise."""
    if lr is None:
        return None
    lr = str(lr).strip().lower()
    if not lr:
        return None
    m = re.fullmatch(r"(?:lang_)?([a-z]{2})(?:[-_]([a-z]{2}))?", lr)
    if not m:
        raise UsageError(f"unrecognized lr value: {lr!r} (want lang_en / en / en-US)")
    return f"lang_{m.group(1)}"
