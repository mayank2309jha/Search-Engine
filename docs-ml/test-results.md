# Test results — retrieval & ranking scope

Scoped to what `docs-ml/overview.md` claims: query understanding, query parsing, and result retrieval/ranking. Full cross-component results (crawler, C++ engine, CI, the live app) are in `../docs-sde/test-results.md` — not duplicated here.

## What's covered by a dedicated test file, and what isn't

`docs-ml/overview.md`'s own scope table names 7 files. 5 have a dedicated test file; 2 don't:

| File | Dedicated tests? | Result |
|---|---|---|
| `app/tokenizer.py` | Yes — `test_tokenizer.py` | 11 passed |
| `app/query_parser.py` | Yes — `test_parser.py` | 17 passed |
| `app/bm25.py` | Yes — `test_bm25.py` | 14 passed |
| `app/ranking.py` | Yes — `test_ranking.py` | 9 passed |
| `app/semantic.py` | Yes — `test_semantic.py` | 8 passed |
| `app/spellcheck.py` | No dedicated file | 70-77% coverage, exercised only indirectly via `test_api.py`'s integration tests |
| `app/index.py` | No dedicated file | 56-63% coverage, same — indirect only |

**59 tests directly exercise the 5 modules with dedicated coverage.** `spellcheck.py` and `index.py` are real, working, and covered well above half — but only through integration paths, not through tests that isolate their own logic the way the other 5 modules get. Worth naming as a real gap rather than smoothing over: a spellcheck- or retrieval-specific regression is less likely to be caught fast and precisely than a bug in, say, `bm25.py`.

## Two data conditions, both verified

Same suite, run against two genuinely different states:

- **Real 19,514-document corpus** (real crawl, real embeddings computed fresh): 113/113 query-server tests passed, 370s.
- **CI's small synthetic fixture** (3 documents, no crawl data) — exactly what GitHub Actions itself runs: 112 passed, 1 skipped, 13.5s.

Both conditions passing on the same code is itself informative for this scope specifically: `query_parser.py`'s case-sensitive AND/OR/NOT handling, `bm25.py`'s scoring, and `ranking.py`'s fusion math are all corpus-size-independent logic — passing identically at 3 documents and at 19,514 is closer to what you'd want from genuine unit-level correctness than a result that only ever held at one scale.

## Real evaluation numbers (separate from pytest — already in `current-state.md`)

The pytest suites above test *correctness* — does the code do what it's supposed to. They don't test *relevance quality* — that's `scripts/evaluate.py`/`evaluate_real.py`'s job, already reported in `current-state.md`'s "Measured evaluation numbers" sections. Not re-run as part of this pass, since nothing in `app/` changed that would affect them.
