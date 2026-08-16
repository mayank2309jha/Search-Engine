# ML roadmap — ranked by ROI (impact vs. effort), not just importance

Ordered by return on effort. The two cheapest, safest wins first; the one expensive-but-necessary unlock third, since everything past it depends on it.

**Phase 8 update (same day):** items 1, 2, and 6 below were attempted/built this session — see `current-state.md` for outcomes. Left the original text in place below (still accurate as the *reasoning* for each), with a status line added under each heading.

## 1. Tune BM25's `k1`/`b` against the evaluation set

**Status: done, correctly not deployed.** `scripts/tune_bm25_params.py` found `b=0.0` marginally wins, but this corpus's document lengths are artificially uniform (coefficient of variation 0.024) — the result doesn't generalize. See `current-state.md`.

**Effort: low — same pattern as `scripts/tune_semantic_weight.py`, already built and proven this session. Impact: medium.** `k1=1.2, b=0.75` were copied from a teammate's C++ reference, never validated against this project's own data. Unlike the PageRank fusion weight, `k1`/`b` govern how BM25 itself scores term frequency and document length — properties of the scoring *function*, not of a specific corpus's fabricated link structure — so this one is safe to fit against the synthetic evaluation set and should transfer reasonably to live serving. Grid-search a small range around the current values, measure via `scripts/evaluate.py`'s BM25-only metrics specifically (don't let semantic reranking mask a regression), and check the lexical subset doesn't move backward — the same discipline `tune_semantic_weight.py` already used.

## 2. Give the semantic path its own uncorrected retrieval pass

**Status: done.** `rerank=true` now uses the raw query throughout (retrieval and embedding both), and `did_you_mean` is suppressed when reranking. Measured improvement on the semantic subset — see `current-state.md`.

**Effort: medium — a real change to the `/search` flow in `main.py`, not a tuning script. Impact: medium-high.** Currently, when `rerank=true`, the query embedding correctly uses raw (uncorrected) text, but BM25's own candidate ordering — which determines the "head" that gets semantically re-ranked — still runs on the spell-corrected query. The fix: run retrieval a second time against the raw query specifically for the semantic path (or skip correction entirely when `rerank=true`), union or otherwise reconcile the two candidate sets, and re-verify via `scripts/evaluate.py` before/after — same discipline that caught the case-sensitivity regression this session. This is the single most valuable remaining *architectural* (not just tuning) fix in the semantic-retrieval path.

## 3. Build real, independent ground truth

**Status: done (Phase 11) — 20 hand-verified judgment queries over the real 19,514-document corpus, in `scripts/evaluate_real.py`.** Genuinely independent this time, not corpus-generation metadata. Immediately valuable: re-fitting `PAGERANK_WEIGHT` against these judgments returned 0.5485, and a built-in bias check caught why that's not trustworthy (the judgment set's relevant docs skew 58x toward high-PageRank domains — selection bias, not signal). **Next step, concretely scoped by this finding:** a second, bias-corrected judgment set that deliberately includes relevant-but-low-authority documents, not a return to "no ground truth exists." A larger sample (20 queries is still small) would also strengthen the BM25 k1/b real-data result (`tune_bm25_params_real.py`: k1=1.8, b=0.25, +20% nDCG@10, promising but not yet deployed).

**Effort: high. Impact: very high — this is the actual blocker behind two other roadmap items, not just one more nice-to-have.** Two paths, either sufficient:
- **Real judged relevance data over the crawled corpus** — even a small set (10-20 queries, hand-labeled against the real 240 Wikipedia/BBC/etc. documents) would be enough to finally validate (or invalidate) a PageRank fusion re-fit for the *live* system, which the current synthetic-corpus training run structurally cannot do.
- **A non-random link graph for `corpus.json`** — if the synthetic corpus's own links were generated with some real structure (e.g. topically-related documents linking to each other) instead of pure seeded-random, PageRank would stop being noise-by-construction there too, and the existing `train_ranker.py` pipeline could produce a deployable result without touching the live data path at all.

Once either exists: re-run `train_ranker.py`, and this time the PageRank weight decision in `current-state.md` gets revisited for real.

## 4. Cross-encoder re-ranking

**Effort: medium-high (a new model — `sentence-transformers.CrossEncoder` — plus more per-query inference cost). Impact: potentially the largest single quality lever available**, typically outperforming bi-encoder cosine similarity by a wide margin once a bi-encoder baseline (already built here) works. Apply it only within the existing top-K reranked pool, not corpus-wide — same reasoning `TOP_K` already uses for the bi-encoder path. Measure via `scripts/evaluate.py` before deciding it's worth the added latency.

## 5. ANN indexing (FAISS/HNSW)

**Effort: medium. Impact: low right now, real later.** Augmentation's whole-corpus embedding comparison is a single cheap matrix multiply at 240–1,000 documents — O(corpus), not yet a bottleneck. Worth doing once corpus size grows another order of magnitude or two (tracked in the SDE roadmap's crawl-budget item), not before.

## 6. Interaction / click-data logging

**Status: plumbing built this session** (`POST /feedback/click`, wired into the frontend, fires correctly per a real browser check) — but nothing persists or consumes it yet, so the reasoning below (sequence after real traffic exists) still applies to the *analysis* half of this item.

**Effort: medium. Impact: low until there's real traffic.** The structured JSON logs already capture query/latency/result-count/cache-hit and were explicitly designed to be extensible — but click data is only valuable once real users are generating it, which depends on the SDE roadmap's deployment items landing first. Sequence this after `../docs-sde/roadmap.md`'s "ship it live" step, not before.

## Explicitly not worth doing yet

- **A learned reranker with a richer feature set** (recency, click-through, more than the current 2 BM25/PageRank features) — blocked on item 3 (there's no additional labeled signal to add features against) and item 6 (no click data to build a recency/CTR feature from in the first place).
- **Query intent/entity classification** (e.g. recognizing "remote" as a location facet) — real, but lower priority than closing the ground-truth gap; revisit once retrieval quality itself is on firmer footing.
