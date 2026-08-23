# csebridge

**Keep your Google Custom Search JSON API code working after Google shuts the
API down on January 1, 2027.**

`csebridge` is a zero-dependency Python library + CLI that returns responses
in the **exact Custom Search JSON API schema** — `items[]`, `queries.nextPage`,
`searchInformation.totalResults`, even CSE-style error objects — while
fetching results from the live backend of your choice:

| Backend | Key env var | Notes |
| --- | --- | --- |
| Brave Search | `BRAVE_API_KEY` | independent index, free tier available |
| Serper.dev | `SERPER_API_KEY` | fast Google SERP JSON |
| SerpApi | `SERPAPI_API_KEY` | broad engine coverage |
| Tavily | `TAVILY_API_KEY` | AI/RAG-oriented retrieval |
| SearXNG | `SEARXNG_BASE_URL` | self-hosted, no key |

Swap backends by changing one environment variable. Your parsing code never
changes.

## Why

[Google closed the Custom Search JSON API to new customers and will stop
serving existing ones on **January 1, 2027**](https://developers.google.com/custom-search/v1/overview).
The recommended replacement, Vertex AI Search, is an enterprise semantic-search
product over *your own* corpus — it does not return public web results.
Meanwhile [Bing Search APIs were already retired in August 2025](https://learn.microsoft.com/en-us/bing/search-apis/bing-web-search/overview),
so "public web search as JSON" is an orphaned workload with a graveyard of
incompatible vendor schemas. Every migration guide out there is a SERP vendor
pitching their own shape; rewriting every call site by hand is the only other
option.

`csebridge` collapses that migration to one import change:

```python
# before
res = service.cse().list(q=q, cx=cx, num=10).execute()
for item in res["items"]:
    print(item["title"], item["link"])

# after
from csebridge import search
res = search(q, num=10)          # same dict shape, live backend behind it
for item in res["items"]:
    print(item["title"], item["link"])
```

## Install

No dependencies, Python 3.9+:

```bash
git clone https://github.com/pixle-codes/csebridge
export BRAVE_API_KEY=...        # or any other backend's env var
```

(Or drop the `csebridge/` directory into your project — it is deliberately a
single package.)

## Usage

### Library

```python
from csebridge import search

# default backend = $CSEBRIDGE_BACKEND or brave
res = search("site reliability engineering", num=10)

res["kind"]                                # "customsearch#search"
res["searchInformation"]["totalResults"]   # "95300000"
res["items"][0]["displayLink"]             # "sre.google"
res["items"][0]["htmlTitle"]               # matched terms in <b>
res["queries"]["nextPage"][0]["startIndex"]  # pagination, exactly like CSE

# page through like you always did
page2 = search("site reliability engineering", start=11)

# CSE params map onto every backend where meaningful
search("docs", lr="lang_en", safe="active",
       site_search="python.org")           # include-only
search("docs", site_search="pinterest.com",
       site_search_filter="e")             # exclude

# failures raise CseError; exc.payload is the exact CSE error JSON:
from csebridge import CseError
try:
    search("x")
except CseError as e:
    e.payload["error"]["code"]             # 401, 403, 429 ... as CSE returned them
```

### CLI

```bash
python -m csebridge "query" --backend serper          # human-readable
python -m csebridge "query" --json                    # full CSE payload
python -m csebridge "query" --start 11                # second page
python -m csebridge "query" --site python.org         # site-restricted
```

Exit codes: `0` ok · `1` backend/network failure (CSE-shaped error via
`--json`) · `2` usage error.

## What's compatible today

- Response envelope: `kind`, `url.template`, `context`, `queries.request`
  echo, `queries.nextPage` / `previousPage`, `searchInformation`
  (`totalResults` uses the backend total when it has one; otherwise a visible
  count), `items[]` with `title/htmlTitle/link/displayLink/snippet/htmlSnippet/
  formattedUrl/htmlFormattedUrl`.
- `<b>` term highlighting inside `html*` fields, word-boundary accurate.
- Error surface: HTTP-status-mapped CSE `error{code,message,errors[],status}`
  objects, raised as `CseError` with `.payload`.
- Params: `q`, `num` (CSE caps at 10/call and so do we), `start`, `lr`,
  `safe`, `siteSearch`/`siteSearchFilter`.

Not yet (planned): >10-result fan-out, image search, pagemap population —
see PLAN.md milestones.

### Honest caveats

- Backends without a result-count concept (Brave, Serper, Tavily) report a
  conservative visible total instead of Google-style estimates. Handlers that
  merely display counts are unaffected; rank-tracker arithmetic on totals is
  the one behavior that cannot be faked honestly.
- Tavily is relevance-ranked and unpaginated: `start>1` repeats its top hits
  rather than true page 2. Prefer paginating backends for deep crawls.
- SearXNG per-page sizes vary by instance; `pageno` mapping is approximate.
- This is not affiliated with or endorsed by Google.

## FAQ

**Why not just rewrite my app for one SERP vendor?**
You'd trade Google lock-in for vendor lock-in right before another deadline.
csebridge keeps the *schema* you wrote against and makes the engine a config
value — if a backend dies or raises prices, flip an env var.

**Why isn't this an HTTP shim I can point old code at?**
Deliberate scope: csebridge ships as a library + CLI, nothing listens on
ports. Pointing `googleapis.com`-hardcoded clients at a local shim requires
TLS/DNS tricks that belong in 2010. One-line import changes age better.

**Does it scrape Google?**
No. It calls documented APIs of the configured backend (or your own SearXNG
instance).

## Development

```bash
python3 -m unittest discover -s tests -t .
```

49 offline tests; network transport is injected, so the suite never touches
the internet.

## License

MIT — see [LICENSE](LICENSE).
