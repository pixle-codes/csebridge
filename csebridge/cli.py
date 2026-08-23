"""CLI: python -m csebridge "query" [options]"""

import argparse
import json
import sys

from . import api
from .backends import BACKENDS
from .errors import CseError
from .scan import format_report, scan_path

EXIT_OK = 0
EXIT_BACKEND_ERROR = 1
EXIT_USAGE = 2
EXIT_FINDINGS = 1

SCAN_HELP = (
    "scan a file or directory for Google Custom Search API usage "
    "(dies Jan 1 2027) and print a migration checklist per call site"
)


def build_parser():
    parser = argparse.ArgumentParser(
        prog="csebridge",
        description=(
            "Google Custom Search JSON API-compatible search over live backends. "
            "Keeps CSE-parsing code alive after Google's Jan 1 2027 cutoff."
        ),
    )
    parser.add_argument("q", help="search terms")
    parser.add_argument(
        "--backend",
        default=None,
        help=f"one of: {', '.join(sorted(BACKENDS))} (default: $CSEBRIDGE_BACKEND or brave)",
    )
    parser.add_argument("--num", type=int, default=10, help="results wanted, up to 100; fetched via transparent fan-out")
    parser.add_argument("--start", type=int, default=1, help="1-based result index to start at")
    parser.add_argument("--lr", default=None, help="language, e.g. lang_en or en")
    parser.add_argument("--safe", default=None, choices=["active", "off"], help="safe search")
    parser.add_argument("--search-type", dest="search_type", default=None, choices=["image"], help="image search (omit for web)")
    parser.add_argument("--site", dest="site_search", default=None, help="restrict to domain")
    parser.add_argument(
        "--site-filter",
        dest="site_search_filter",
        default="i",
        choices=["i", "e"],
        help="i=include site only, e=exclude site",
    )
    parser.add_argument("--json", action="store_true", help="print the full CSE JSON payload")
    parser.add_argument("--version", action="version", version="%(prog)s 0.3.0")
    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "scan":
        scan_main(argv[1:])
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = int(exc.code) if isinstance(exc.code, int) else EXIT_USAGE
        sys.exit(code)

    try:
        payload = search_from_args(args)
    except CseError as exc:
        if args.json:
            print(json.dumps(exc.payload, indent=2))
        else:
            print(f"csebridge: error: {exc}", file=sys.stderr)
            print(f"hint: {hint_for(args.backend)}", file=sys.stderr)
        sys.exit(EXIT_BACKEND_ERROR)
    except ValueError as exc:
        print(f"csebridge: error: {exc}", file=sys.stderr)
        sys.exit(EXIT_USAGE)

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        info = payload["searchInformation"]
        print(
            f"About {info['formattedTotalResults']} results "
            f"({info['formattedSearchTime']} seconds)"
        )
        for i, item in enumerate(payload["items"], start=args.start):
            print(f"{i}. {item['title']}")
            print(f"   {item['link']}")
            if item["snippet"]:
                print(f"   {item['snippet']}")
    sys.exit(EXIT_OK)


def search_from_args(args):
    return api.search(
        args.q,
        backend=args.backend,
        num=args.num,
        start=args.start,
        lr=args.lr,
        safe=args.safe,
        site_search=args.site_search,
        site_search_filter=args.site_search_filter,
        search_type=args.search_type,
    )


def hint_for(backend):
    backend = backend or "brave"
    impl = BACKENDS.get(backend)
    if impl and impl.env_var:
        return f"{backend} needs ${impl.env_var}: {impl.setup_hint}"
    return "set the API key env var for your chosen backend"


def build_scan_parser():
    parser = argparse.ArgumentParser(
        prog="csebridge scan",
        description=(
            "Audit a repo for Google Custom Search JSON API call sites "
            "(googleapis URLs, googleapiclient clients, gcse embeds, "
            "GOOGLE_CSE_* env vars). The API stops serving Jan 1 2027; each "
            "finding comes with a migration checklist pointing at csebridge."
        ),
    )
    parser.add_argument("path", help="file or directory to scan")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON report")
    return parser


def scan_main(argv):
    parser = build_scan_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        code = int(exc.code) if isinstance(exc.code, int) else EXIT_USAGE
        sys.exit(code)

    try:
        result = scan_path(args.path)
    except ValueError as exc:
        print(f"csebridge scan: error: {exc}", file=sys.stderr)
        sys.exit(EXIT_USAGE)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_report(result))
    sys.exit(EXIT_FINDINGS if result["findings"] else EXIT_OK)


if __name__ == "__main__":
    main()
