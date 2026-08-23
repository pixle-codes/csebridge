# Architecture

csebridge keeps Google Custom Search JSON API parsing code alive past the
Jan 1 2027 cutoff by speaking the exact CSE response schema while fetching
from pluggable backends. Zero dependencies; Python 3.13 stdlib only.

```
caller ──> api.search(q, backend=..., num/start/lr/safe/siteSearch/searchType)
                │
                ├─ params.normalize      CSE param validation + normalization
                │                        (q, num<=100, start window, lr, safe…)
                │
                ├─ _check_window         start+num<=100 enforced as CSE 400
                │
                ├─ backends.<Backend>.fetch / fetch_images
                │     adapter owns ALL provider quirks:
                │     auth header, POST vs GET, result path, position math
                │     brave · serper · serpapi · tavily · searxng · ddg*
                │        │ every HTTP call goes through…
                │        ▼
                └─ transport.request(method, url, headers, payload,
                                     timeout=, retries=)
                      urllib wrapper; env knobs CSEBRIDGE_TIMEOUT /
                      CSEBRIDGE_RETRIES read per call; exponential backoff
                      on 429/5xx/network; injectable (tests swap it)
                          │ normalized hits {title,url,snippet,pos}
                          ▼
                cse.build_response       hits -> exact CSE JSON dict
                      (kind/url/context/queries.request echo + nextPage/
                       previousPage/searchInformation/items[] + pagemap)
                      errors surface as CSE-shaped error{} payloads
```

`*ddg` is an opt-in keyless HTML scraper (fixture-tested only; never in the
default backend order).

## Key decisions

- **Normalized hit is the contract.** `{title, url, snippet, pos}` with pos
  GLOBAL 1-based (`start + index`) so CSE pagination math holds across
  backends with per-call vs absolute position semantics.
- **Adapters own quirks; nothing else does.** Adding a backend touches one
  class in `backends.py` and nothing else.
- **num > 10 fans out** in `api._collect`: <=10-result pages fetched,
  deduped by url (or image_url), early stop on short or all-dupe pages.
  Native page sizes own the offset math (DDG serves ~30/page regardless of
  requested num).
- **Errors are CSE-shaped end to end.** `_wrap_transport` converts any
  TransportError into `CseError` whose `.payload` mirrors Google's error
  JSON; existing except-handlers keep working unchanged. UsageError stays a
  separate type so the CLI can exit 2 vs backend 1.
- **Transport is the only I/O seam.** Offline tests inject fake transports /
  `_request_once` stubs; policy knobs live at this seam and are read from
  the environment per call (no import-time capture, no globals mutated).
- **scan is offline-only.** The repo auditor (`scan.py`) never touches the
  network: pure regex rules over walked text files, first match claims a
  line, VCS/dep/binary paths skipped.

## Module map

| Module | Responsibility |
| --- | --- |
| `api.py` | entry point, fan-out collection, window check |
| `params.py` | CSE param validation/normalization |
| `backends.py` | one adapter class per provider + error wrapping |
| `transport.py` | urllib wrapper, timeout/retry policy |
| `cse.py` | normalized hits -> CSE JSON schema |
| `errors.py` | CseError + payload shape |
| `scan.py` | offline repo auditor for CSE call sites |
| `cli.py` | search front-end + `scan` subcommand dispatch |

## Testing

stdlib `unittest`, zero test deps. Fixtures under `tests/fixtures/` pin real
provider response shapes; fakes inject at `csebridge.transport.request`
(whole-HTTP) or `transport._request_once` (retry-loop) level.

```bash
python3 -m unittest discover -s tests -t .
```
