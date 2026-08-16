# Test results — full suite run

Every automated test suite in this repo, run directly and confirmed this pass — not assumed from the fact that the files exist. The crawler suite specifically had never been confirmed run in any session before this one; the project's own docs had repeatedly flagged it as something that "only runs if someone remembers to run it by hand." See `runningUpdates.md` Phase 14 for the CI-specific bugs this same broader push surfaced and fixed.

## query-server — 113 passed (real data) / 112 passed, 1 skipped (CI's exact fixture)

Run with `pytest --cov=app --cov-report=term-missing` from `query-server/`, using a `.venv` set up there this session. Two conditions verified, since they exercise genuinely different code paths:

| Condition | Result | What it proves |
|---|---|---|
| Real data present (`data/index.bin`, 19,514 docs; `data/crawler.db`, real crawl) | **113 passed**, 370s | The full real-world path: real titles/snippets from `crawler.db`, real embeddings computed fresh |
| Real data absent — CI's exact fixture path (small synthetic 3-doc index, no `crawler.db`) | **112 passed, 1 skipped**, 13.5s | Exactly what GitHub Actions itself runs against |

Per-file breakdown (real-data run, 113 total, counted programmatically from the run's own output — not hand-tallied):

| File | Tests | Module |
|---|---|---|
| `test_api.py` | 29 | `main.py` / integration + API layer |
| `test_parser.py` | 17 | `query_parser.py` |
| `test_bm25.py` | 14 | `bm25.py` |
| `test_cpp_reader.py` | 13 | `cpp_index_reader.py` |
| `test_cache.py` | 12 | `cache.py` |
| `test_tokenizer.py` | 11 | `tokenizer.py` |
| `test_ranking.py` | 9 | `ranking.py` |
| `test_semantic.py` | 8 | `semantic.py` |

Coverage: 86-88% on `app/` (varies slightly by which data condition is active). Weakest-covered modules: `authority.py` (53%), `persistence.py` (0% — dead code, superseded by `cpp_index_reader.py` since Phase 6, never removed), `index.py` (56-63%), `spellcheck.py` (70-77%) — all four have no dedicated test file and are exercised only indirectly, through `test_api.py`'s integration tests.

## crawler — 58 passed, 0 failed

Run with `.venv/bin/python -m pytest crawler/tests/ -v` from the repo root, exactly as `crawler/CLAUDE.md` documents (a root-level `.venv`, created fresh this session; never a bare `pip`, per that file's own rule). Checked `conftest.py` and every test file first, before running anything: all fixtures use pytest's isolated `tmp_path`, so this suite never touches the real 2.1GB `crawler.db`.

| File | Tests |
|---|---|
| `test_parser.py` | 30 |
| `test_polite_check.py` | 10 |
| `test_frontier.py` | 9 |
| `test_storage.py` | 9 |

## C++ engine (`src/`, `include/`) — no automated tests exist

Confirmed directly, not assumed: no `test` target anywhere in `CMakeLists.txt`, no test files under `src/` or `include/`. CI's `cpp-build` job checks compilation only, not behavior. This is a real, disclosed gap, not an oversight in this write-up — see `docs-sde/roadmap.md` and `RUNDOWN_SDE.html`'s "what concerns me" list.

## CI (GitHub Actions) — all 5 jobs green

`python-tests`, `python-lint`, `cpp-build`, `docker-build`, `all-checks-passed` — confirmed via the GitHub API against the actual run, not assumed from a local pass. See `runningUpdates.md` Phase 14 for the two real bugs this pipeline caught (one before the first push, a second, different one on the first push itself) and exactly how each was root-caused and fixed.

## Live application — verified end to end

Booted `uvicorn app.main:app` against the real 19,514-document corpus (~3 min cold start, matching previously measured numbers). Confirmed live, through the actual endpoints: `/health`, auth enforcement (401 without a key, 200 with one), lexical search with real BM25/PageRank scores and highlighted snippets, semantic re-ranking correctly surfacing a lexically-unrelated but semantically-relevant result, and `/suggest` autocomplete.
