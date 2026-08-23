# Migrating googleapiclient CSE code to csebridge

A worked example of the swap `csebridge scan` recommends. The parsing code
below the search call is **identical before and after** — that is the point.

## Before (dies Jan 1, 2027)

```python
from googleapiclient.discovery import build

service = build("customsearch", "v1", developerKey=API_KEY)
res = (
    service.cse()
    .list(q="tailwind vs vanilla css", cx=CX, num=10)
    .execute()
)
for item in res["items"]:
    print(item["title"], item["link"])
print(res["searchInformation"]["totalResults"])
```

`csebridge scan` flags this as `[py-cse-client]`.

## After

```bash
pip install csebridge
export BRAVE_API_KEY=...        # or SERPER_API_KEY / SERPAPI_API_KEY /
                                # TAVILY_API_KEY / SEARXNG_BASE_URL
```

```python
from csebridge import api

res = api.search("tailwind vs vanilla css", backend="brave", num=10)
for item in res["items"]:               # same fields: title/link/snippet/
    print(item["title"], item["link"])  # displayLink/htmlTitle/pagemap…
print(res["searchInformation"]["totalResults"])
```

No discovery doc, no Google account, no quota cliff — and the response dict
keeps the exact CSE shape (`items[]`, `queries.nextPage`,
`searchInformation`, even the error object), so everything downstream is
untouched.

## Pagination parity

CSE callers loop with `start=11, 21…`. That keeps working:

```python
res = api.search("q", start=11)          # queries.nextPage echoes start=21
```

`num` above 10 works too: csebridge fans out transparently and merges one
response, exactly like requesting `num=30` from CSE did.

## Raw-HTTP variant

If you called `https://www.googleapis.com/customsearch/v1?key=..&cx=..&q=..`
directly (`[http-endpoint]` in scan output), replace the request+parse pair
with `api.search(...)` or shell out to the JSON-emitting CLI:

```bash
python -m csebridge "query" --json --backend serper
```

Any language can consume that payload with the same parser you used for
Google's responses.

## Env var cleanup

Retire `GOOGLE_CSE_ID` / `CUSTOMSEARCH_*` secrets and set the backend's key
variable instead. `csebridge scan --json` gives you the full machine-readable
checklist to work through.
