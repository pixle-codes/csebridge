"""CLI: python -m csebridge "query" [options]"""

import argparse
import json
import sys

from . import api
from .backends import BACKENDS
from .errors import CseError

EXIT_OK = 0
EXIT_BACKEND_ERROR = 1
EXIT_USAGE = 2


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
    parser.add_argument("--num", type=int, default=10, help="results per page, CSE max is 10")
    parser.add_argument("--start", type=int, default=1, help="1-based result index to start at")
    parser.add_argument("--lr", default=None, help="language, e.g. lang_en or en")
    parser.add_argument("--safe", default=None, choices=["active", "off"], help="safe search")
    parser.add_argument("--site", dest="site_search", default=None, help="restrict to domain")
    parser.add_argument(
        "--site-filter",
        dest="site_search_filter",
        default="i",
        choices=["i", "e"],
        help="i=include site only, e=exclude site",
    )
    parser.add_argument("--json", action="store_true", help="print the full CSE JSON payload")
    parser.add_argument("--version", action="version", version="%(prog)s 0.1.0")
    return parser


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
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
    )


def hint_for(backend):
    backend = backend or "brave"
    impl = BACKENDS.get(backend)
    if impl and impl.env_var:
        return f"{backend} needs ${impl.env_var}: {impl.setup_hint}"
    return "set the API key env var for your chosen backend"


if __name__ == "__main__":
    main()
