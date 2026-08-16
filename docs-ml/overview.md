# ML overview — context for picking up query understanding / parsing / retrieval work here

Read this first if you're resuming this project for an ML-framed session. Scope is deliberate and narrow: **query understanding, query parsing, and result retrieval/ranking** — not crawling, not indexing infrastructure, not general API/systems engineering, not deployment. Those are covered in `../docs-sde/` if you need them.

## What's in scope, concretely

| File | Role |
|---|---|
| `app/tokenizer.py` | Shared normalization: lowercase → strip punctuation → stopword removal → Snowball stemming. Identical pipeline for documents and queries — the invariant everything else depends on. |
| `app/spellcheck.py` | SymSpell correction, dictionary built from the corpus itself (not a general English dictionary). |
| `app/query_parser.py` | Boolean AND/OR/NOT (sticky-mode), quoted phrases → structured query dict. |
| `app/bm25.py` | Hand-rolled, from-scratch BM25 (ported from a teammate's C++ reference, generalized to multi-term). The **only** multi-term BM25 in the whole system — the C++ engine's is single-word-only. |
| `app/ranking.py` | Fuses BM25 + PageRank (+ a phrase-match bonus) into one score. |
| `app/semantic.py` | Embedding-based (`all-MiniLM-L6-v2`) re-ranking + "augmentation" (surfacing documents BM25 never retrieved at all, via whole-corpus embedding similarity). |
| `app/index.py` | Boolean/phrase retrieval logic (`retrieve_candidates`, `phrase_match`) — the mechanism the parser's structured query gets executed against. |
| `scripts/evaluate.py` | Precision@10/MRR/nDCG@10 offline evaluation, BM25-only vs. BM25+semantic, against a 40-query judgment set (doubled from 20 in Phase 8). |
| `scripts/train_ranker.py` | Fits `ranking.py`'s fusion weights against the evaluation judgment set. |
| `scripts/tune_semantic_weight.py` | Grid-searches `semantic.py`'s blend weight against the same set. |
| `scripts/tune_bm25_params.py` | Grid-searches BM25's `k1`/`b` against the same set (Phase 8) — see `current-state.md` for why the result wasn't deployed. |
| `tests/` | 92 pytest tests, 86% coverage on `app/`, added Phase 8 — run with `pytest` from `query-server/` (see `pytest.ini`). |

## The one architectural fact worth internalizing before touching anything

**All evaluation and training in this project runs against `data/corpus.json`** — a synthetic, template-generated corpus with programmatically-derived ground truth (a lexical query is "relevant" to any doc whose title contains its exact topic phrase; a semantic query is "relevant" to any doc in its target `category`). This is *not* the same data the live server (`main.py`) now serves against — as of a recent integration phase, live serving reads the real crawled corpus via `app/cpp_index_reader.py` instead.

This split matters a lot for anything you fit or tune:

- **Weights tuned on live-computed, corpus-independent signals** (e.g. the BM25/semantic blend weight — both signals are computed fresh at query time regardless of which corpus is loaded) **transfer safely** from the synthetic evaluation to live serving.
- **Weights that depend on a specific corpus's fabricated properties** (e.g. the BM25/PageRank blend weight — `corpus.json`'s link graph is seeded-random and genuinely uncorrelated with its own relevance labels) **do not transfer**, and applying them to live serving would be scope-creeping a valid finding past where its evidence actually reaches. See `current-state.md` for the concrete example of exactly this happening.

Before fitting or tuning anything new, ask which category it falls into.

## Ground truth, honestly

The evaluation judgment set (`scripts/evaluate.py`'s `build_judgments()`) is real, useful, and honestly disclosed as circular: it's derived from the same generation process that built the corpus, not independent human (or LLM) judgment. This is the single biggest methodological ceiling on ML work here — see `roadmap.md`.
