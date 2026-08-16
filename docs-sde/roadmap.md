# SDE roadmap — ranked by ROI (impact vs. effort), not just importance

Every item below is real and would move the score in `RUNDOWN_SDE.html`. They're ordered by return on effort, not by "what sounds most senior" — cheap, high-visibility wins first.

**Phase 8 update (same day):** items 3, 4, and 6 below were built/attempted this session — see `current-state.md` for outcomes. Original text left in place (still accurate as reasoning), with a status line added under each heading.

## 1. Get `crawler.db` (or an export of `pages.title`/`pages.content`) onto this machine

**Status: done (Phase 10).** Real `crawler.db` (2.1GB, 19,514 pages) and a rebuilt `data/index.bin` (110MB) received via Google Drive and verified live — real titles, real `<mark>`-highlighted snippets, `doc_text_source: "crawler.db"` in the startup log. This was the single highest-ROI item on this list and it's now closed; see `current-state.md` for what it unlocked and what showed up at the new scale (startup cost, semantic-query latency, crawl-quality noise). The *process* gap discussed alongside this (no professional artifact-sharing pipeline — this went over a Drive link) is still open; see the note below and the "next steps" discussion in this session's chat log.

**Effort: trivial (a file copy, or a small export script). Impact: high.** Every search result currently has an empty snippet and a URL-derived title instead of the real thing — this is the single most visible gap between "works" and "looks finished" in any demo. Nothing downstream needs to change; `app/crawler_db.py` already reads it correctly the moment it's present, and `main.py`'s startup log already tells you whether it found it (`doc_text_source` field). This is the highest ROI item on this entire list — ask whoever ran the crawl for the file, or write a 10-line script exporting just `title`/`content` if the full DB is too large/sensitive to share.

## 2. Ship it live

**Status: Dockerized (Phase 12), not yet hosted.** `query-server/Dockerfile` + `docker-compose.yml` exist, verified working end to end — real memory calibration (2GB nearly OOM-killed it; the verified, working value is 5GB with ~730MB genuine headroom under real query load), real bug fixes found by actually booting the container (a CUDA-vs-CPU torch mixup, a SQLite WAL-mode read failure, a HuggingFace cache path bug). Full detail in `query-server/benchmarks-phase11-12.md`. What's left is purely the hosting step below — the container itself is ready to deploy as-is.

**Effort: medium (an afternoon with Render/Fly.io/Railway). Impact: very high.** A live link is categorically more valuable than a local repo for anyone evaluating this — recruiters don't clone repos. Concretely:
- Push the already-built Docker image to a registry and host it (no external database dependency — it reads local/mounted files at startup, same as the local Docker setup).
- The demo frontend (Phase 8) already covers "a minimal frontend" — this item's original framing (Swagger `/docs` as a fallback) is now a smaller concern than it was.
- Verify `rerank=true`'s difference is visibly demonstrable (the whole semantic-search story is wasted if nobody can see it working) — already true locally, needs re-confirming once live.

## 3. A real `pytest` suite for `query-server/`

**Status: done.** 92 tests, 86% coverage on `app/`, including a byte-exact `cpp_index_reader.py` fixture test. See `current-state.md`.

**Effort: medium. Impact: high, and compounding** (every future change gets safer). Structure it around the existing module boundaries — `tokenizer.py`, `query_parser.py`, `bm25.py`, `ranking.py`, `snippets.py`, `dedup.py`, `cache.py`, `cpp_index_reader.py` (this one especially: it's new, has zero automated coverage, and the byte-format decode logic is exactly the kind of thing that fails silently if it regresses). The manual test log at `tests/test_queries.md` (55+ hand-verified cases) is a ready-made source of test cases to convert, not something to write from scratch.

## 4. CI pipeline (GitHub Actions)

**Status: done, and a real bug in it was caught and fixed before you could hit it (Phase 11).** `.github/workflows/ci.yml` — Python tests + lint (parallel), C++ build (parallel), gated pass/fail job. Reviewing it ahead of a push surfaced that Phase 10's `data/index.bin` untracking (correct call — don't commit a 115MB binary) would have broken CI's `python-tests` job: `app/main.py` hard-crashes at import if that file is missing, and every API test imports it. Fixed with a generated CI fixture (`scripts/generate_ci_index_fixture.py`, wired into the workflow), verified by fully reproducing a fresh-CI environment locally (hid the real files, ran the suite, got 112 passed / 1 skipped). Safe to push now — wasn't, before this fix.

**Effort: low once item 3 exists, otherwise not worth doing yet. Impact: medium-high** as a signal of engineering maturity, and it catches regressions for real. Two jobs: lint + `pytest` for `query-server/`, and a C++ build check for the engine. The crawler already has real tests that currently only run if someone remembers to run them by hand — wiring even just that into CI first is a fast, cheap win if you want to sequence before item 3 is fully done.

## 5. Authentication + move cache/rate-limiter to Redis

**Status: done (Phase 9), and the Redis half is now verified against a real instance, not just a fake client (Phase 11).** Real API-key auth gates `/search`/`/suggest`/`/feedback/click` (401 on missing/wrong key, verified live). Redis-backed cache/rate-limiting: installed Redis locally, ran the server with `REDIS_URL` set, and confirmed directly via `redis-cli` — a real `search:python` key with a correct ~3591s TTL, a real cache-hit response (8.8ms), and a real rate-limiter key (`LIMITS:LIMITER/...`). Both features are now proven end-to-end against real infrastructure, not just unit-tested against a mock. Still true: none of this is exercised in production until item 2 actually ships something publicly reachable.

**Effort: medium-high. Impact: low right now, high the moment item 2 (live deploy) ships.** Don't do this before deploying — it's solving a problem ("this is public and someone could abuse it") that doesn't exist until it's actually public. Once it is, both are explicitly named in the design doc as "fine for one process, not once this is public" — do them together, since Redis-backed rate limiting and auth are usually adjacent concerns in a real deploy checklist.

## 6. Fix the C++ engine's title-indexing gap

**Status: fix written and functionally verified this session, NOT merged — needs review from whoever owns `src/index.cpp`.** Committed separately with an explicit review request in the commit message.

**Effort: small (a teammate's codebase, but a scoped, well-understood one-line-ish fix — add `document.title` to what `InvertedIndex::build()` tokenizes). Impact: medium.** Not something to do unilaterally without coordinating with whoever owns `src/index.cpp`, but worth flagging to them directly — it's a real, currently-silent gap (confirmed by reading the source), and title text is usually the highest-signal text on a page.

## Explicitly lower priority right now

- **Flat-array index layout for the Python side** — the C++ side already has this; the Python side's dict-of-dicts is fine at current corpus size. Revisit only if corpus size actually becomes a measured bottleneck.
- **Index sharding, distributed crawling** — not remotely close to being needed at 240–1,000 documents.
- **Fuzzy/near-duplicate detection** — a real gap (both the crawler and query-server only do exact-hash dedup), but lower urgency than the items above; worth doing once real crawl volume makes near-duplicates a visible problem, not before.
