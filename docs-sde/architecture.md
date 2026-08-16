# SDE architecture — how the whole system fits together

This is the structural companion to `overview.md` (who owns what, why) and `current-state.md`
(what's actually verified working right now). This file answers a different question: given
all three components, how does a request actually flow end to end, and what does the system
look like at rest vs. under load. Status/priority calls belong in `roadmap.md`, not here — this
file describes shape, not progress.

## The three components, and the one hard truth about them

```mermaid
flowchart LR
    subgraph Crawl["crawler/ (Python) — teammate-owned"]
        A[Frontier] --> B[PoliteChecker]
        B --> C[Fetcher]
        C --> D[Parser.extract]
        D --> E[Storage.save]
        E -->|pages, links, frontier| DB[(crawler.db<br/>SQLite, gitignored)]
        DB -.-> PR[ranking/pagerank.py<br/>power iteration over links]
        PR -->|pagerank table| DB
    end

    subgraph Index["src/ + include/ (C++) — teammate-owned"]
        F[Parser::parseDatabase] -->|title+content per doc| G[InvertedIndex::build]
        G -->|tokenize, postings, positions| H[InvertedIndex::saveToDisk]
    end

    subgraph Serve["query-server/ (Python) — this folder"]
        I[cpp_index_reader.py] --> J[main.py startup]
        K[crawler_db.py] --> J
        J --> L["/search, /suggest,<br/>/feedback/click"]
        L --> M[static/ frontend]
    end

    DB -->|SQL read| F
    H -->|"data/index.bin<br/>committed build artifact"| I
    DB -.->|"optional: title/content<br/>for snippets"| K
```

**The single fact everything else follows from:** the C++ engine's `InvertedIndex::searchBM25()`
takes exactly one word. It cannot answer a real query. `main.cpp` runs one hardcoded query and
exits — it is not a server, has no HTTP interface, and was never meant to be queried directly.
Everything that makes this a usable search engine — boolean AND/OR/NOT, phrases, multi-term
BM25, spell correction, semantic search, pagination, an HTTP API, a frontend — lives entirely in
`query-server/`. The C++ engine's actual job is narrower than its name suggests: read
`crawler.db`, build a compact on-disk inverted index (`data/index.bin`), and get out of the way.

## What each artifact actually is

| Artifact | Produced by | Consumed by | Committed to git? |
|---|---|---|---|
| `crawler.db` (SQLite: `pages`, `links`, `frontier`, `pagerank`) | `crawler/` | `src/parser.cpp` (build-time), `app/crawler_db.py` (serve-time, optional) | No — gitignored crawl output, lives on whoever ran the crawl's machine |
| `data/index.bin` (binary: postings, positions, doc lengths, URLs, PageRank) | `src/index.cpp`'s `saveToDisk()` | `app/cpp_index_reader.py` — hard startup dependency | **Yes** — committed build artifact |
| Sentence-embedding cache (`data/embeddings_cache_cpp.pkl`) | `app/semantic.py`, built once at startup or loaded from cache | `app/semantic.py`'s `semantic_rerank()` | No — regenerated if stale (keyed against `data/index.bin`'s mtime) |

`index.bin` deliberately does **not** carry page text — it's a word→document mapping, not a
content store. Duplicating full text into it would bloat the index and duplicate `crawler.db`'s
job. This is why `crawler.db`'s absence degrades snippets/spellcheck/embeddings gracefully
instead of breaking search entirely: the index (structure) and the text (content) were always
two separate concerns, read by two separate, independently-optional code paths
(`cpp_index_reader.py` is a hard dependency; `crawler_db.py` is not).

## Request lifecycle: `GET /search?q=...&rerank=...`

```mermaid
sequenceDiagram
    participant C as Client (browser or curl)
    participant MW as Middleware<br/>(GZip, rate limiter, auth)
    participant H as search() handler
    participant Cache as search_cache
    participant SC as spellcheck.py
    participant QP as query_parser.py
    participant IDX as index.py<br/>retrieve_candidates
    participant RK as ranking.py<br/>score_documents_detailed
    participant SEM as semantic.py<br/>semantic_rerank (if rerank=true)
    participant SN as snippets.py

    C->>MW: GET /search?q=...
    MW->>MW: check X-API-Key (401 if missing/wrong)
    MW->>MW: check rate limit (429 if over 30/min)
    MW->>H: validated request
    H->>H: validate_query() -- basic sanity checks
    H->>Cache: get(cache_key)
    alt cache hit
        Cache-->>H: cached (deduped, did_you_mean, structured)
    else cache miss
        H->>SC: correct_query(q)
        SC-->>H: corrected_query, unknown_words
        H->>QP: parse_query(...)
        QP-->>H: structured {required, optional, excluded, phrases}
        H->>IDX: retrieve_candidates(structured, docs, inverted_index)
        IDX-->>H: candidate_ids
        H->>RK: score_documents_detailed(...)
        RK-->>H: per-doc {bm25, pagerank, phrase_bonus, final}
        opt rerank=true
            H->>SEM: semantic_rerank(raw query, ranked_ids, scores, ...)
            SEM-->>H: reordered ids, updated scores, semantic_components
        end
        H->>H: dedup_results(...)
        H->>Cache: set(cache_key, ...)
    end
    H->>SN: build_snippet() -- only for the current page, not the whole result set
    SN-->>H: highlighted snippets
    H-->>C: SearchResponse (results + per-signal scores + did_you_mean)
```

Two design choices worth naming explicitly because they're easy to miss just reading the code
top to bottom:

- **Snippets are generated after pagination, not before.** The cache stores the full
  ranked+deduped list; snippet generation (the most expensive per-result step, since it
  re-tokenizes document text) only runs on the ~10 results actually being returned, cache hit
  or miss. This is what keeps a 1,000-candidate query cheap to paginate through.
- **`rerank=true` re-derives retrieval from the raw query, not the spell-corrected one.**
  Fixed in Phase 8 after it was found to bias which documents even entered the reranked pool —
  see `docs-ml/current-state.md` for the full story. The two search modes (`rerank=false` /
  `rerank=true`) are genuinely two different retrieval paths sharing the same scoring code, not
  one path with a toggle at the end.

## Auth and scale layer (Phase 9)

```mermaid
flowchart TD
    Req[Incoming request] --> GZ[GZipMiddleware<br/>compresses responses > 500 bytes]
    GZ --> RL{Rate limiter<br/>slowapi + limits}
    RL -->|storage_uri| Store{REDIS_URL set?}
    Store -->|yes| Redis1[(Redis)]
    Store -->|no, default| Mem1[In-process memory]
    RL -->|under limit| Auth{require_api_key<br/>X-API-Key header}
    Auth -->|missing/wrong| E401[401]
    Auth -->|correct| Route[/search, /suggest,<br/>/feedback/click handlers/]
    Route --> Cache{build_search_cache}
    Cache -->|REDIS_URL set & reachable| Redis2[(Redis,<br/>pickled values, TTL)]
    Cache -->|REDIS_URL unset,<br/>or Redis unreachable| Mem2[In-process LRUCache]
```

**Current live state, stated plainly:** `REDIS_URL` is unset on this machine, and no Redis
server is installed here. Both the rate limiter and the result cache are running on their
in-memory fallback right now — the Redis code paths exist, are unit-tested against a fake
client, and are ready to activate, but have never been exercised against a real Redis instance.
`/health` and `/` (the frontend) are the only two routes not behind `require_api_key` — a
health check that needs auth is a good way to lock yourself out of your own monitoring, and the
frontend is a static page, not a capability worth gating.

**Why API-key auth, not user accounts:** this system has no per-user state — no saved searches,
no personalization, no login-worthy identity — so there's nothing a username/password pair would
protect that an API key doesn't already. API keys answer "is this caller allowed to hit the API
at all," which is the actual question here. Username/password becomes the right tool the moment
a feature needs a real person behind it (e.g. saved searches, or click history feeding back into
`scripts/train_ranker.py` per-user) — not before.

## Deployment topology: today vs. target

```mermaid
flowchart TB
    subgraph Today["Today -- single local process"]
        U1[Your browser] -->|localhost:8000| P1[uvicorn, 1 worker<br/>in-memory cache + rate limiter]
    end

    subgraph Target["Target -- once actually deployed"]
        U2[Any visitor] --> LB[Host: Render / Fly.io / Railway]
        LB --> P2A[uvicorn worker 1]
        LB --> P2B[uvicorn worker 2]
        LB --> P2C[uvicorn worker N]
        P2A --> R[(Redis)]
        P2B --> R
        P2C --> R
    end
```

The gap between these two diagrams is almost entirely Group H in `docs-sde/current-state.md`'s
scorecard: no `Dockerfile`, no hosting, no live link. The auth and Redis-readiness work already
done means the *right* diagram doesn't require new application code to reach — just
infrastructure (a real Redis instance, a real host, `API_KEY`/`REDIS_URL` set for real) that
doesn't exist yet.

## What this file deliberately leaves out

- **Byte-level `data/index.bin` format** (magic bytes, section offsets, varint encoding) — that
  level of detail lives in `overview.md`'s "binary format you'll need if this ever needs
  revisiting" section, not duplicated here.
- **Per-item status and ROI-ranked next steps** — `current-state.md` and `roadmap.md`.
- **The query-understanding/ranking pipeline's internal architecture** (parsing grammar,
  BM25/PageRank/semantic fusion, the evaluation harness) — scoped narrowly and covered in
  `docs-ml/architecture.md`, since that's a genuinely ML-framed piece of this same system.
