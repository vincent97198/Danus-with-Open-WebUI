<!-- Modified for this distribution (2026-09-22): local-model integration and research controls. See THIRD_PARTY_NOTICES.md at the package root. -->

# danus/integrations — arXiv theorem search

## Local-model literature extension

`literature.py` adds arXiv/Crossref record search, local SearXNG discovery and
arXiv HTML/PDF reading. Requires httpx, beautifulsoup4, pypdf and fonttools
(installed by the portal image). `SEARXNG_URL` selects the internal search
endpoint; `DANUS_LITERATURE_CACHE` selects a shared cache. API requests to arXiv
are spaced at least 3 seconds apart across processes. Reads only accept official
arXiv HTTPS URLs or IDs, enforce a 12 MB download limit, and return paginated
excerpts of at most 24,000 characters (600,000 per document, at most 200 PDF pages).
Crossref returns metadata/abstracts; it does not grant access to paywalled text.

`iacr.py` uses IACR ePrint's official OAI-PMH endpoint to maintain a SQLite FTS5
index of title, authors, abstract and category. `search_papers(source="iacr")`
searches it; `all` includes it. First use starts a bounded resumable harvest;
deployment can warm it with `python -m danus.integrations.iacr`. Later searches
refresh stale metadata in the background at most daily. Errors back off, cursors
resume, and OAI withdrawal tombstones remove records. No ePrint search-page
scraping or PDF downloading is performed. Source metadata stays distinguished
from full text. Official terms: https://eprint.iacr.org/rss/.

`literature_log.py` maintains a bounded public source history for main/worker
calls under the selected project's `literature/`. It never writes to global
memory or the fact graph; verifier-role calls do not write project history.
Provider failures are returned explicitly, with successful sources preserved.
Retrieved content is untrusted source material, not agent instructions.

`search_settings.py` stores operator preferences in the runtime volume and
per-project `search-settings.json`. Every integrated retrieval entry point checks
the current scope before cache or network access. Chat and Danus defaults are
independent; projects may inherit or override. The verify HTTP request propagates
the validated project directory to the child via `DANUS_SEARCH_PROJECT_DIR`.
`get_search_settings` is read-only; tool schemas do not expose preference writes.
This controls tools, not arbitrary shell networking. In-flight requests may finish.

## Upstream Matlas integration

A thin, swappable adapter over external literature search. Currently one integration:
`matlas.py`, a stdlib-only client for **Matlas** arXiv theorem search, which returns
verbatim, as-published arXiv theorem/lemma/definition statements (statement fidelity
is load-bearing for math reasoning and citation checking).

```
danus/integrations/
  matlas.py       search(query, num_results=10, timeout=30) -> {query, count, results, endpoint[, error]}
  __init__.py     re-exports search + RESULT_FIELDS
  tests/test_integrations.py
```

## Contract

- `search(...)` **never raises** — on any failure it returns the same envelope with
  `results: []` and an `error` key (empty query, `http …`, `network: …`, bad JSON, …).
- Each result is normalized to exactly `("title", "theorem", "arxiv_id",
  "theorem_id")`, all coerced to `str`.
- Sends a real `User-Agent` (Cloudflare 403s otherwise); endpoint overridable via
  `MATLAS_URL`.

## Exposed as

The gateway wraps it as the MCP tool `search_arxiv_theorems(query, num_results)` — the
one tool **all three** roles (worker/main/verifier) can call for literature grounding.

## Known limitation (cross-module)

It returns theorem **statements**, not bibliographic metadata (authors/venue/year).
The write-paper reference verifier therefore uses the returned `arxiv_id` + a web
lookup for metadata. Keep this in mind if adding a citation-grounding consumer.

## Tests

`python -m pytest danus/integrations/` (offline; the HTTP call is mocked).
