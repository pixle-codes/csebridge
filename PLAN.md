# PLAN — csebridge

Keep Google Custom Search JSON API code working after Google kills it.
A zero-dependency Python library + CLI that speaks the **exact CSE response
schema** while fetching results from pluggable backends (Brave, Serper,
SerpApi, Tavily, SearXNG, …). Swap the engine, keep the parser.

## Problem

Google closed the Custom Search JSON API to new customers and set a hard
cutoff: **existing customers stop being served on January 1, 2027**
(https://developers.google.com/custom-search/v1/overview). The recommended
replacement, Vertex AI Search, is an enterprise semantic-search product with
~1000 QPM / 50 GiB minimums that does not return public web results at all.

Who hurts:
- **AI-agent / MCP builders** who wired CSE in as their web-search tool
  (a top Japanese dev-community writeup addresses exactly this cohort:
  https://qiita.com/Bacchus/items/1a8d6f15a73d3bc144fe)
- Rank trackers, monitoring tools, indie apps parsing `items[].title/link/
  snippet` and `searchInformation.totalResults`
- Sites embedding the `gcse-*` widget (long tail; widget rides the same API)

This is the crowd's **second burn**: Bing Search APIs were retired Aug 11,
2025 (https://learn.microsoft.com/en-us/bing/search-apis/bing-web-search/overview).
Every migration guide found is vendor content marketing pushing one SERP API;
the only "open-source" compat path surfaced is an Apify paid-platform actor
(scrape-based, per-result billing).

## Why existing solutions fail

| Existing option | Shortcoming |
| --- | --- |
| Vertex AI Search (official steer) | Wrong product: indexes *your* corpus; no public-web JSON; enterprise minimums |
| SERP vendors (SerpApi/Serper/BrightData/DataForSEO…) | Each has its own schema → "significant code refactoring" (press coverage says so verbatim); vendor-locked pricing |
| Apify GOOGLE_SERP actor | Paid platform lock-in; network egress via their proxy; not pip-installable |
| Rewrite to Brave/Tavily/etc. by hand | Every app re-solves the same field mapping; pagination (`start=`), quotas, error shapes all differ |
| Keep CSE until Jan 1 2027 | Hard 410 after; no grace |

Nothing on GitHub provides a CSE-schema-compatible client over alternative
backends (searches for "custom search json api" alternatives, "serp api
compatible", "google cse replacement", "programmable search engine
alternative", "csebridge": only tutorial clones and wrappers of the dying
API itself — checked s19).

## Your edge

1. **Schema contract, not another wrapper.** Returns byte-for-byte the CSE
   JSON shape apps already parse: `items[]`, `queries.nextPage`,
   `searchInformation`, `url`, `context`, even CSE-style error objects.
   Golden-fixture tests pin the contract.
2. **Multi-backend with env-var switching.** `CSEBRIDGE_BACKEND=brave`
   vs `serper` vs `serpapi` vs `tavily` vs `searxng` — same parsed output.
   No single-vendor lock-in; compare backends by flipping one var.
3. **Pagination parity.** CSE paginates via `start=11,21…`; callers loop.
   csebridge emits correct `queries.nextPage`/`previousPage` request blocks
   translated into each backend's paging scheme.
4. **Zero dependencies, stdlib-only** (urllib), offline-testable via injected
   transports. Sane for agents and CI. MIT.
5. **CLI included**: quick sanity checks without writing code
   (`python -m csebridge "query" --backend brave --json`).

## Architecture

```
caller code ──> csebridge.search(q, backend=…, **cse_params)
                        │
                 params.py   CSE param validation/normalization (q,num,start,
                 │           lr, safe, siteSearch, searchType …)
                 backends.py Backend protocol: fetch(query) -> normalized hits
                 │           brave / serper / serpapi / tavily / searxng (+ddg M2)
                 cse.py      normalized hits -> CSE JSON dict
                 │           (kind/url/context/searchInformation/items/queries)
                 transport.py injectable urllib wrapper (tests stub it)
                 cli.py      argparse front-end; --json exits raw payload
```

Key decisions:
- Internal normalized hit = {title,url,snippet,pos} + optional extras; each
  backend adapter owns ALL provider quirks (auth header style, POST vs GET,
  result-path extraction, position semantics).
- `num`: CSE caps at 10/call; backends differ (Serper 100) — honor caller's
  num by fan-out when needed later (M2), clamp now, document.
- Keys from env vars only (BRAVE_API_KEY, SERPER_API_KEY, SERPAPI_API_KEY,
  TAVILY_API_KEY, SEARXNG_BASE_URL); never logged, echoed or persisted.
- Errors surface as CSE-shaped `error{code,message,errors[]}` dicts so
  existing except-handlers keep working.

## Milestones

- [x] M1 (v0.1.0, SHIPPED s19): package scaffold; params normalize; Brave +
      Serper + SerpApi + Tavily + SearXNG adapters; full CSE-shape emission
      incl. queries.request echo + nextPage/previousPage; CSE-style error
      object; CLI (--json, exit 0/1/2); golden-fixture offline tests (49);
      README; published github.com/pixle-codes/csebridge tag v0.1.0.
      Gotcha: urlencode encodes literal '+' as %2B — assert on %2B form;
      UsageError deliberately NOT CseError so CLI can exit 2 vs backend 1.
- [x] M2 (v0.2.0, SHIPPED s20): num>10 fan-out (api._collect: <=10-result
      pages, dedupe-by-url, early stop on short/dup pages, start+num<=100
      window enforced as CSE 400); searchType=image over brave/serper/
      serpapi/tavily/searxng (Backend.fetch_images + supports_images; image
      items emit CSE shape: image.contextLink/thumbnailLink/dims +
      pagemap.cse_image/cse_thumbnail + mime/fileFormat); pagemap best-effort
      from hit extras (image_url/thumbnail_url/metatags) — absent when the
      backend gives nothing, like real CSE; keyless `ddg` backend opt-in only
      (html.duckduckgo.com HTMLParser scraper: uddg unwrap, y.js ad skip,
      captcha->429, native ~30/page windowing w/ local slice; fixture-tested).
      Gotcha: DDG ignores num and serves ~30/page — offset must be
      ((start-1)//30)*30 then slice locally, NOT page=num math.
      Gotcha: fan-out dedupe must key on url OR image_url (image hits have no
      url field).
- [ ] M3 (v0.3.0): `csebridge scan PATH` — repo audit listing CSE call sites
      (googleapis.com/customsearch URLs, googleapiclient customsearch builds,
      gcse embeds, GOOGLE_CSE_* env usage) with a migration checklist per
      finding (assistout-proven scanner pattern).
- [ ] M4 (v1.0.0): hardening pass — timeout/retry policy, rate-limit
      backoff hints, ARCHITECTURE.md, example migration diff doc, tag v1.0.

## Gotchas / decisions log

- s19: no servers listening — this ships as lib+CLI only; any HTTP-shim
  serving is explicitly out of scope (documented in README FAQ).
- s19: DDG HTML scraping deferred to M2 as opt-in: fragile + CAPTCHA-prone;
  fixture-tested only, never in default backend order.
- s19: position semantics: SerpApi/Serper give absolute positions across
  pages, Brave/Tavily are per-call — adapters must emit global pos =
  start + index so CSE pagination math holds.
