"""Repo audit: locate Google Custom Search API call sites before the cutoff.

`csebridge scan PATH` walks a file or directory tree and reports every line
that still talks to the dying Custom Search JSON API (hard cutoff Jan 1 2027),
each with a migration checklist pointing at the csebridge swap.
"""

import os
import re

CUTOFF = "2027-01-01"

SKIP_DIRS = {
    ".git", ".hg", ".svn", ".tox", ".venv", "venv", "__pycache__",
    "node_modules", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "dist", "build", ".idea", ".vscode",
}

MAX_FILE_BYTES = 2 * 1024 * 1024


class Rule:
    def __init__(self, rule_id, pattern, checklist):
        self.id = rule_id
        self.regex = re.compile(pattern)
        self.checklist = checklist


_PY_CLIENT = (
    r"googleapiclient\.discovery|"
    r"build\s*\(\s*['\"]customsearch['\"]|"
    r"\.cse\(\)\s*\.\s*list\b|"
    r"from\s+googleapiclient"
)

_JS_CLIENT = (
    r"require\(\s*['\"]googleapis['\"]\s*\)|"
    r"from\s+['\"]googleapis['\"]|"
    r"customsearch\(\s*['\"]v1['\"]\s*\)|"
    r"\bcustomsearch\s*\.\s*(cse|list)\b"
)

_URL = r"www\.googleapis\.com/customsearch/v1"

_GCSE = (
    r"cse\.google\.com/cse\.js\b|"
    r"www\.google\.com/cse/|"
    r"\bgcse\.(?:js|element)\b|"
    r"<gcse:[a-z]+|(?:class|className)\s*=\s*['\"][^'\"]*gcse-|"
    r"google\.search\.cse\.element"
)

_ENV = (
    r"\bGOOGLE_CSE_[A-Z_]+\b|"
    r"\bCUSTOMSEARCH[A-Z_]*\b|"
    r"\bGOOGLE_PROGRAMMABLE_SEARCH[A-Z_]*\b"
)

CHECKLISTS = {
    "py-cse-client": (
        "Drop the googleapiclient discovery client: `pip install csebridge`, then "
        "`from csebridge import api; api.search(q, backend='brave')` returns the "
        "identical items[]/queries/searchInformation JSON — your parsing code is "
        "unchanged."
    ),
    "js-customsearch": (
        "csebridge speaks CSE from any language via its CLI: "
        "`python -m csebridge \"query\" --json --backend serper` emits the exact "
        "CSE payload; parse it like you parsed googleapis responses today."
    ),
    "http-endpoint": (
        "Replace raw customsearch/v1 HTTP calls with csebridge (pip install "
        "csebridge): same response schema, live backends (brave/serper/serpapi/"
        "tavily/searxng) after Google stops serving on Jan 1 2027."
    ),
    "gcse-embed": (
        "The Programmable Search Element rides the same API and dies with it. "
        "Serve results yourself: render a page from csebridge output (CLI or "
        "Python), or accept breakage after Jan 1 2027."
    ),
    "env-var": (
        "Once calls go through csebridge, swap legacy Google-CSE / "
        "CustomSearch secret names for the backend's env var (BRAVE_API_KEY, "
        "SERPER_API_KEY, SERPAPI_API_KEY, TAVILY_API_KEY, SEARXNG_BASE_URL)."
    ),
}

# Order matters: first match claims the line (assistout span-claiming pattern).
RULES = [
    Rule("py-cse-client", _PY_CLIENT, CHECKLISTS["py-cse-client"]),
    Rule("js-customsearch", _JS_CLIENT, CHECKLISTS["js-customsearch"]),
    Rule("http-endpoint", _URL, CHECKLISTS["http-endpoint"]),
    Rule("gcse-embed", _GCSE, CHECKLISTS["gcse-embed"]),
    Rule("env-var", _ENV, CHECKLISTS["env-var"]),
]


def scan_path(target):
    """Scan a file or directory. Returns a result dict; raises ValueError if
    the target does not exist."""
    if not os.path.exists(target):
        raise ValueError(f"no such file or directory: {target}")
    findings = []
    files_scanned = 0
    for path in _iter_files(target):
        files_scanned += 1
        findings.extend(_scan_file(path))
    return {
        "target": target,
        "cutoff": CUTOFF,
        "files_scanned": files_scanned,
        "findings": findings,
        "summary": {
            "total": len(findings),
            "by_rule": _count_by_rule(findings),
        },
    }


def _iter_files(target):
    if os.path.isfile(target):
        yield target
        return
    for root, dirs, names in os.walk(target):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        for name in sorted(names):
            path = os.path.join(root, name)
            if os.path.islink(path) or not os.path.isfile(path):
                continue
            try:
                if os.path.getsize(path) > MAX_FILE_BYTES:
                    continue
                with open(path, "rb") as fh:
                    chunk = fh.read(8192)
            except OSError:
                continue
            if b"\x00" in chunk:
                continue
            yield path


def _scan_file(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            text = fh.read()
    except OSError:
        return []
    claimed_lines = set()
    findings = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if lineno in claimed_lines:
            continue
        for rule in RULES:
            m = rule.regex.search(line)
            if m:
                claimed_lines.add(lineno)
                findings.append({
                    "rule": rule.id,
                    "path": os.path.normpath(path),
                    "line": lineno,
                    "match": line.strip()[:160],
                    "checklist": rule.checklist,
                })
                break
    return findings


def _count_by_rule(findings):
    counts = {}
    for f in findings:
        counts[f["rule"]] = counts.get(f["rule"], 0) + 1
    return counts


def format_report(result):
    lines = [
        f"csebridge scan: {result['summary']['total']} Custom Search call site(s) "
        f"in {result['target']} ({result['files_scanned']} files scanned)",
        f"Google CSE stops serving results {result['cutoff']} — migrate each "
        f"site below to csebridge.",
    ]
    last_checklist = None
    for f in result["findings"]:
        lines.append(f"[{f['rule']}] {f['path']}:{f['line']}")
        lines.append(f"    {f['match']}")
        if f["checklist"] != last_checklist:
            lines.append(f"    fix: {f['checklist']}")
            last_checklist = f["checklist"]
    if not result["findings"]:
        lines.append(
            "No Custom Search usage found. Nothing to migrate here."
        )
    return "\n".join(lines)
