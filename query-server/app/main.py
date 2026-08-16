import os
import time
from datetime import datetime, timezone
from typing import Union

# HTTPException lets us return clean 4xx errors instead of default 500s
from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security.api_key import APIKeyHeader
# Phase 8: the demo frontend's static assets (index.html, style.css, app.js)
from fastapi.staticfiles import StaticFiles
# rate limiting: per-client-IP. storage_uri defaults to in-process memory, the
# right choice for a single process, but becomes wrong the moment this runs as
# more than one -- set REDIS_URL to share limiter + cache state across workers
# and processes instead (see build_search_cache() in app/cache.py for the same
# pattern applied to the result cache).
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

# index primitives -- retrieve_candidates() is data-source-agnostic (it only ever reads
# the inverted_index dict handed to it), so it works unchanged against a C++-built index
from app.index import retrieve_candidates
# combined BM25 + PageRank scoring, whole-candidate-set-at-once
from app.ranking import score_documents_detailed
# turns a raw query string into required/optional/excluded/phrases
from app.query_parser import parse_query
from app.validation import validate_query  # raw-input sanity checks
# corpus-dictionary-based spelling suggestions
from app.spellcheck import build_symspell, correct_query
# PageRank itself now comes pre-computed from data/index.bin (see below); only the
# min-max normalization step is still needed here
from app.authority import normalize_pagerank
# highlighted excerpt generation for each result
from app.snippets import build_snippet
# collapses duplicate postings, keeping the best-scored copy
from app.dedup import dedup_results
# Phase 4: typed response models, repeated-query cache, structured logging, autocomplete
from app.schemas import SearchResponse, NoResultsResponse, SuggestResponse, HealthResponse, ErrorResponse, ClickEvent
from app.cache import build_search_cache
from app.logging_config import get_logger, log_request, log_click
from app.suggest import build_suggest_index, get_suggestions
# Phase 6: reads the C++ engine's data/index.bin directly (postings, positions, doc
# lengths, URLs, PageRank) and crawler.db (page text) -- the real-data integration
# replacing the synthetic corpus.json this service used through Phase 5
from app.cpp_index_reader import load_cpp_index
from app.crawler_db import load_doc_texts, fallback_title
# Phase 5: semantic re-ranking (sentence-transformers embeddings + cosine similarity)
from app.semantic import (
    load_model as load_semantic_model,
    build_doc_embeddings,
    save_embeddings,
    load_embeddings,
    semantic_rerank,
)

logger = get_logger()

# REDIS_URL unset -> "memory://" (in-process, current single-instance behavior,
# unchanged). Set it and this same Limiter shares rate-limit counters across
# every worker/replica instead of each keeping its own -- the fix named in this
# project's own docs for "fine for one process, not once this is public."
limiter = Limiter(key_func=get_remote_address, storage_uri=os.environ.get("REDIS_URL", "memory://"))

app = FastAPI()  # the API application instance
app.state.limiter = limiter
# a client over the limit gets slowapi's default 429 JSON body, not a raw exception
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
# Compresses JSON search responses over the wire -- a real, free bandwidth win at
# any corpus size, and specifically matters once result payloads (snippets, per-
# signal scores for every result) get shipped to more concurrent clients.
app.add_middleware(GZipMiddleware, minimum_size=500)

# --- Auth -------------------------------------------------------------------
# API-key gating for the endpoints that actually cost compute or write data
# (/search, /suggest, /feedback/click). /health and the frontend stay open --
# a health check that itself needs auth is a common way to lock yourself out of
# your own monitoring, and gating "/" would break the bundled demo frontend for
# no security benefit (it's a static HTML page, not a capability).
#
# The default key below is intentionally public -- it's committed in this repo's
# source, so it is NOT a secret and provides no real protection on its own. Its
# job today is making the demo frontend and `pytest` work unmodified out of the
# box while still exercising real auth-enforcement code (a wrong or missing key
# genuinely gets rejected with 401 -- see tests/test_api.py::TestAuth). Before
# any real deployment: set API_KEY to a real secret via the environment, and
# update static/app.js's matching constant (or template it in server-side)
# rather than shipping a key inside public JS -- a browser-embedded key can
# only ever filter casual/automated abuse, not a motivated attacker who reads
# the page source, which is a real, disclosed limit of key-in-browser auth for
# a publicly-served single-page demo like this one.
API_KEY_NAME = "X-API-Key"
API_KEY = os.environ.get("API_KEY", "dev-demo-key-change-me")
_api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)


def require_api_key(key: str = Security(_api_key_header)):
    if key != API_KEY:
        raise HTTPException(status_code=401, detail="Missing or invalid API key.")
    return key


# Phase 8: demo frontend. Mounted at /static (not "/"), so it can't shadow the API
# routes below -- "/" itself is one explicit route (returns index.html), not a
# catch-all mount, so there's no routing-order ambiguity between the frontend and
# /health, /suggest, /search.
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", include_in_schema=False)
def serve_frontend():
    return FileResponse("static/index.html")


# last line of defense: an unexpected bug should never leak a raw traceback to the client
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error("unhandled_exception", extra={
                 "extra_fields": {"path": str(request.url), "error": str(exc)}})
    return JSONResponse(status_code=500, content={"detail": "Internal server error."})


# Real crawled + indexed data, not the synthetic corpus this service ran against
# through Phase 5: data/index.bin is built by the C++ engine (src/index.cpp) from
# crawler.db, one directory up from this service in the monorepo. This is a hard
# dependency now, not a fallback-if-present -- if it's missing, that means the C++
# engine hasn't been run yet, and this service should fail loudly at startup rather
# than silently serving stale synthetic data instead.
CPP_INDEX_PATH = "../data/index.bin"
CRAWLER_DB_PATH = "../data/crawler.db"

cpp_index = load_cpp_index(CPP_INDEX_PATH)
inverted_index = cpp_index["inverted_index"]
doc_lengths = cpp_index["doc_lengths"]
avg_doc_length = cpp_index["avg_doc_length"]
total_docs_count = cpp_index["total_docs_count"]
doc_urls = cpp_index["doc_urls"]
# Computed once, upstream, by crawler/ranking/pagerank.py's real power iteration over
# the actual crawled link graph -- baked into data/index.bin by the C++ engine, so
# there's no synthetic link graph to build or PageRank to compute in this process at all.
pagerank_raw = cpp_index["doc_pageranks"]

# crawler.db holds the page text data/index.bin doesn't (title/content were only ever
# needed transiently, at C++ index-build time, to tokenize them). It's gitignored crawl
# output, so it may genuinely not exist on this machine yet even though index.bin (a
# committed build artifact) does -- every doc still gets a real title either way (from
# the crawl if present, else derived from its URL, same fallback chain the crawler's
# own parser uses) since schemas.SearchResultItem.title is required; content is simply
# "" when unavailable, which tokenizing/snippet/embedding code already handles as
# "this doc matches nothing and has no snippet," not as an error.
doc_texts = load_doc_texts(CRAWLER_DB_PATH)
docs = {
    doc_id: {
        "title": doc_texts.get(doc_id, ("", ""))[0] or fallback_title(url),
        "content": doc_texts.get(doc_id, ("", ""))[1],
        "url": url,
        "company": None,  # general crawled web pages now, not a job-postings corpus
    }
    for doc_id, url in doc_urls.items()
}
logger.info("startup", extra={"extra_fields": {
    "index_source": "cpp_engine", "path": CPP_INDEX_PATH, "doc_count": total_docs_count,
    "doc_text_source": "crawler.db" if doc_texts else "unavailable (titles from URL, no content)",
}})

# build the corpus-derived spelling dictionary once at startup
sym_spell = build_symspell(docs)

pagerank_norm = normalize_pagerank(pagerank_raw)

# autocomplete vocabulary (unstemmed terms + corpus frequency), built once at startup
suggest_terms, suggest_frequencies = build_suggest_index(docs)

# Phase 5/6: semantic re-ranking model + per-document embeddings, built/loaded once.
# Staleness is checked against CPP_INDEX_PATH now, not a corpus.json that no longer
# exists as this service's data source -- if the C++ engine rebuilds the index, these
# embeddings correctly rebuild too, the same on-disk-cache pattern as before.
EMBEDDINGS_CACHE_PATH = "data/embeddings_cache_cpp.pkl"
semantic_model = load_semantic_model()
cached_embeddings = load_embeddings(EMBEDDINGS_CACHE_PATH, CPP_INDEX_PATH)
if cached_embeddings is not None:
    doc_embeddings, embedding_doc_id_order = cached_embeddings
    logger.info("startup", extra={
                "extra_fields": {"embeddings_source": "cache", "path": EMBEDDINGS_CACHE_PATH}})
else:
    doc_embeddings, embedding_doc_id_order = build_doc_embeddings(docs, semantic_model)
    save_embeddings(EMBEDDINGS_CACHE_PATH, CPP_INDEX_PATH, doc_embeddings, embedding_doc_id_order)
    logger.info("startup", extra={
                "extra_fields": {"embeddings_source": "rebuilt", "path": EMBEDDINGS_CACHE_PATH}})
# maps doc_id -> row index into doc_embeddings, since the embeddings matrix (like
# the old BM25 model) has no concept of doc_id, only array position
doc_id_to_embedding_index = {doc_id: i for i,
                             doc_id in enumerate(embedding_doc_id_order)}

# repeated-query cache: holds the full ranked+deduped list per normalized query,
# taken *before* pagination -- so page 2 of an already-seen query is still a cache hit.
# build_search_cache() picks Redis-backed (shared across processes) or in-memory
# (this process only) based on REDIS_URL -- same .get()/.set() interface either way.
search_cache = build_search_cache()

# for /health's uptime figure
STARTED_AT = datetime.now(timezone.utc)
_start_perf = time.perf_counter()

# hard ceiling so a client can't request one page containing the entire corpus
MAX_PAGE_SIZE = 50


@app.get("/health", response_model=HealthResponse)
def health():
    return HealthResponse(
        status="ok",
        corpus_size=len(docs),
        uptime_seconds=round(time.perf_counter() - _start_perf, 3),
        started_at=STARTED_AT.isoformat(),
    )


@app.post(
    "/feedback/click",
    status_code=204,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    dependencies=[Depends(require_api_key)],
)
@limiter.limit("30/minute")
# Phase 8: the relevance-feedback signal this project's docs have named as
# missing since Phase 4 -- structured request logging existed, but nothing
# captured whether a returned result was actually useful. Deliberately
# minimal: log the event and return, no persistence layer or click-through
# analysis built on top of it yet (see docs-ml/roadmap.md for why that's a
# real, separate, larger piece of work -- this endpoint is the plumbing it
# would consume, not the analysis itself).
def record_click(request: Request, event: ClickEvent):
    if event.doc_id not in docs:
        raise HTTPException(status_code=400, detail="Unknown doc_id.")
    log_click(logger, query=event.query, doc_id=event.doc_id,
              rank=event.rank, rerank=event.rerank)


@app.get(
    "/suggest",
    response_model=SuggestResponse,
    responses={401: {"model": ErrorResponse}},
    dependencies=[Depends(require_api_key)],
)
@limiter.limit("30/minute")
# prefix-based autocomplete; deliberately skips validate_query() since partial,
# in-progress input (e.g. a single letter) is exactly what this endpoint expects
def suggest(request: Request, prefix: str = "", limit: int = 10):
    suggestions = get_suggestions(
        prefix, suggest_terms, suggest_frequencies, limit=limit)
    return SuggestResponse(prefix=prefix, suggestions=suggestions)


@app.get(
    "/search",
    response_model=Union[SearchResponse, NoResultsResponse],
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
    dependencies=[Depends(require_api_key)],
)
@limiter.limit("30/minute")
# q defaults to "" for our own clean validation error
def search(request: Request, q: str = "", page: int = 1, page_size: int = 10, rerank: bool = False):
    request_start = time.perf_counter()

    # run basic sanity checks on the raw input first, before any real work
    validation_error = validate_query(q)
    if validation_error:  # input failed validation
        raise HTTPException(status_code=400, detail=validation_error)

    if page < 1:  # page numbers start at 1, not 0
        raise HTTPException(
            status_code=400, detail="page must be 1 or greater.")
    if page_size < 1 or page_size > MAX_PAGE_SIZE:  # keep page sizes sane in both directions
        raise HTTPException(
            status_code=400, detail=f"page_size must be between 1 and {MAX_PAGE_SIZE}.")

    # rerank changes result ORDER for the same query text, so it has to be part
    # of the cache key -- otherwise a rerank=true request could be served a
    # rerank=false cache entry (or vice versa) written by an earlier request
    cache_key = f"{q}\x1frerank" if rerank else q

    # cache lookup -- a hit skips spellcheck, parsing, retrieval, scoring,
    # semantic re-ranking, and dedup entirely. Snippets are still generated
    # below, since they're only ever built for the current page, cache hit or not.
    cached = search_cache.get(cache_key)
    if cached is not None:
        deduped, did_you_mean, structured = cached
        response = _build_search_response(
            q, page, page_size, deduped, did_you_mean, structured)
        log_request(logger, query=q, rerank=rerank, latency_ms=round((time.perf_counter() - request_start) * 1000, 2),
                    result_count=len(deduped), cache_hit=True)
        return response

    # spell-check the raw query against the corpus dictionary
    correction = correct_query(q, sym_spell)
    # an unrecognized word is a dead end for lexical (BM25) matching -- but NOT
    # for semantic re-ranking, which works on meaning rather than dictionary
    # membership. So this early rejection only applies to the default (lexical)
    # path; with rerank=True, an unknown word just means BM25 won't find a
    # lexical match for it, which the semantic augmentation step can still work
    # around (see app/semantic.py's semantic_rerank docstring).
    if correction["unknown_words"] and not rerank:
        log_request(logger, query=q, rerank=rerank, latency_ms=round((time.perf_counter() - request_start) * 1000, 2),
                    result_count=0, cache_hit=False)
        return NoResultsResponse(
            query=q,
            message="No results found.",
            unknown_words=correction["unknown_words"],
            results=[],
        )

    # search the corrected form if anything was actually corrected, otherwise use the original untouched.
    # Phase 8: this now only feeds retrieval when rerank=False. Previously, rerank=True still
    # parsed/retrieved against the CORRECTED query -- so a correction like "sick"->"since" or
    # "get"->"gem" (both valid English words, just absent from a narrow corpus vocabulary; see
    # app/semantic.py's docstring) didn't just bias which documents got embedded, it biased which
    # documents were even IN the candidate pool being semantically reranked in the first place.
    # Directly observed while testing this: a real query ("ways machines can learn from data")
    # against the current corpus produced a garbled "did you mean: bas machines a4 learn from aa?"
    # -- confirming this wasn't a theoretical risk. Using the raw query for rerank=True's own
    # retrieval isn't a loss for genuine typos either: a raw word BM25 can't match is exactly the
    # case semantic augmentation already exists to cover (see semantic_rerank()'s docstring).
    search_query = q if rerank else (
        correction["corrected_query"] if correction["suggestions"] else q)

    # parse the (possibly corrected) query into required/optional/excluded/phrases
    structured = parse_query(search_query)
    if not any([structured["required"], structured["optional"], structured["phrases"]]):
        log_request(logger, query=q, rerank=rerank, latency_ms=round((time.perf_counter() - request_start) * 1000, 2),
                    result_count=0, cache_hit=False)
        return NoResultsResponse(
            query=q, message="Query did not contain any searchable terms.", results=[])

    # boolean + phrase-aware retrieval from the index (unchanged from Phase 2)
    candidate_ids = retrieve_candidates(structured, docs, inverted_index)

    # hand-rolled BM25 (scored directly against candidate_ids) + a PageRank lookup per candidate,
    # combined into one score. The _detailed variant (Phase 8) keeps the per-signal breakdown
    # (bm25/pagerank/phrase_bonus) alongside the fused "final" value, so the API response can
    # show a ranking explanation instead of just a single opaque number.
    detailed_scores = score_documents_detailed(candidate_ids, structured, inverted_index,
                             doc_lengths, avg_doc_length, total_docs_count, pagerank_norm)
    scores = {doc_id: v["final"] for doc_id, v in detailed_scores.items()}

    # sort by score, tie-breaking on doc_id -- a Python set's iteration order isn't something we want
    # user-visible ranking to depend on, so equal scores always come back in the same deterministic order
    ranked_ids = sorted(
        candidate_ids, key=lambda doc_id: (-scores[doc_id], doc_id))

    # Phase 5: optionally re-rank the top of the list by semantic (embedding)
    # similarity to the query, blended with the existing BM25+PageRank score --
    # and pull in documents BM25 missed entirely, via pure embedding similarity
    # across the whole corpus (see app/semantic.py's semantic_rerank docstring
    # for why that second part is necessary, not optional).
    # semantic-similarity component per doc_id, populated only when rerank=True and only
    # for docs actually in the reranked pool (head + augmented) -- None for everything
    # else, which the frontend reads as "not semantically evaluated for this query"
    semantic_components = {}
    if rerank:
        # only let augmentation (semantic-only, whole-corpus finds) run for
        # queries with no explicit hard constraint it could bypass -- see
        # semantic_rerank()'s docstring for why this is a constraint check,
        # not a candidate-count check
        allow_augmentation = not (
            structured["required"] or structured["excluded"]
            or structured["excluded_phrases"] or structured["phrases"]
        )
        # embed the RAW query, not the spell-corrected one -- SymSpell "corrects"
        # any word absent from this corpus to the nearest in-corpus word within
        # edit distance 2, even when the original word is perfectly valid
        # English (e.g. "sick" -> "since", "get" -> "gem", observed directly
        # while testing this). That correction actively hurts a semantic model,
        # which handles real-world text (typos included) far better than
        # edit-distance correction does, and doesn't need it in the first place.
        ranked_ids, scores, semantic_components = semantic_rerank(
            q, ranked_ids, scores, semantic_model,
            doc_embeddings, doc_id_to_embedding_index, embedding_doc_id_order,
            allow_augmentation=allow_augmentation)

    scored = [  # build the result objects, in ranked order -- NO snippet yet;
        # generating one requires re-tokenizing the full document, which is by
        # far the most expensive step per result (see the design doc's Phase 4
        # corpus-scaling notes), so it's deferred until we know which handful of
        # results actually need to be shown, in _build_search_response() below
        {
            "doc_id": doc_id,
            "title": docs[doc_id]["title"],
            "company": docs[doc_id].get("company"),
            "url": docs[doc_id].get("url"),
            "score": scores[doc_id],
            # None (not 0.0) for a doc score_documents_detailed() never evaluated --
            # concretely, a semantic-augmentation-only find that BM25 never retrieved
            # at all has no lexical or authority opinion to show, and 0.0 would
            # misleadingly look like "scored and found irrelevant" instead of
            # "never scored on this signal in the first place"
            "bm25_score": detailed_scores.get(doc_id, {}).get("bm25"),
            "pagerank_score": detailed_scores.get(doc_id, {}).get("pagerank"),
            "semantic_score": semantic_components.get(doc_id),
        }
        for doc_id in ranked_ids
    ]

    # collapse duplicate postings (same title+content), keeping the highest-scoring copy of each
    deduped = dedup_results(scored, docs)

    # only cache the success path -- the unknown-word / no-searchable-terms
    # branches above are cheap early exits, not worth caching forever.
    # `structured` is cached alongside the results because snippet generation
    # (deferred to _build_search_response) needs it on a cache HIT too, not
    # just on the miss path that originally parsed the query.
    #
    # Suppressed entirely when rerank=True: retrieval no longer uses the correction
    # (see above), so showing "did you mean: X" when X wasn't actually applied would
    # be actively misleading, not just unused -- confirmed directly while testing this
    # fix ("ways machines can learn from data" -> a nonsensical "did you mean: bas
    # machines a4 learn from aa?" that had nothing to do with what was searched). The
    # underlying cause -- this corpus's narrow spellcheck vocabulary treating any word
    # it doesn't recognize as a typo of the nearest in-corpus word, even when the
    # original is valid English -- isn't fixed by this; only its user-facing exposure
    # in the one path (rerank=True) where it was actively wrong, not just unused.
    did_you_mean = None
    if not rerank and correction["suggestions"]:
        did_you_mean = correction["corrected_query"]
    search_cache.set(cache_key, (deduped, did_you_mean, structured))

    response = _build_search_response(
        q, page, page_size, deduped, did_you_mean, structured)
    log_request(logger, query=q, rerank=rerank, latency_ms=round((time.perf_counter() - request_start) * 1000, 2),
                result_count=len(deduped), cache_hit=False)
    return response


# shared by both the cache-hit and cache-miss paths: slice the (already ranked
# + deduped) result list into the requested page, THEN generate snippets only
# for that page -- not for the full candidate/result set, which is what made
# large-corpus queries slow (see design doc, Phase 4 corpus-scaling notes)
def _build_search_response(q: str, page: int, page_size: int, deduped: list, did_you_mean, structured: dict):
    total_results = len(deduped)
    start = (page - 1) * page_size
    end = start + page_size
    page_results = deduped[start:end]  # slice out just the requested page

    results_with_snippets = [
        {**result, "snippet": build_snippet(docs[result["doc_id"]], structured)}
        for result in page_results
    ]

    return SearchResponse(
        query=q,
        page=page,
        page_size=page_size,
        total_results=total_results,
        total_pages=(total_results + page_size - 1) // page_size if total_results else 0,
        results=results_with_snippets,
        did_you_mean=did_you_mean,
    )
