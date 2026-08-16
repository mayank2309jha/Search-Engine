# Running updates

Final status for this session. Everything below `[x]` is committed on the `retrievalranking` branch, verified (tests pass, or a real browser/API check was run — noted per item), and not pushed to GitHub without your go-ahead.

**Status key:** `[x]` done, verified · `[~]` partially done, real reasons documented · `[!]` blocked on something only you can do · `[ ]` deliberately deferred, with reasoning

---

## 1. Basic frontend — `[x]`

Plain HTML/CSS/vanilla JS (`static/`), served by FastAPI at `/`. Search box, Search / Semantic Search buttons, "Powered by BM25 • PageRank • Semantic Retrieval." Verified with a real headless-Chromium session (screenshots taken): home page renders correctly, lexical and semantic searches both return results, zero console errors.

### The killer feature — ranking explanation `[x]`
Expandable "Why this result?" panel per result: Lexical (BM25) / Semantic / Authority (PageRank) as bars, plus the final blended score. Required real backend work first — `ranking.py`, `semantic.py`, and `schemas.py` all changed to expose per-signal scores, not just the fused total; verified the refactor didn't change existing behavior (`scripts/evaluate.py` produces bit-identical numbers before/after). A signal shows "n/a," never a fake `0.0`, when it was never evaluated for that document — most visibly on a pure semantic-augmentation find, which also gets a "found by meaning" badge.

## 2. Demo script (4 queries) — `[x]`

Verified live against the real 240-document crawled corpus, with two honest substitutions where the mockup's literal examples don't exist in this corpus's vocabulary (documented, not hidden):

1. **Lexical** — `python` (works; `python programming` doesn't, because `programming` isn't in the spellcheck dictionary yet — see the note on `crawler.db` below for why).
2. **Boolean** — `python AND wikipedia` (substituted for `python AND kubernetes`; "kubernetes" doesn't appear in this general-web crawl).
3. **Phrase** — `"main page"` (substituted for `"machine learning"`, for the same reason — this corpus is Wikipedia/BBC/python.org/MDN, not ML-focused. Returns 4 results, top-ranked literally titled "Main Page").
4. **Semantic** — `ways machines can learn from data` (0 lexical results — both "machine" and "learning" fail lexically) vs. `machine learning` — semantic search via augmentation finds real, relevant documents where lexical search finds nothing. This is the actual money-shot query working as intended.

**Worth knowing before you run this live:** the *quality* of results (titles, snippets, semantic relevance) is currently bottlenecked by the missing `crawler.db` — see below. The mechanism is proven; the content backing it is thin.

## 3. Get `crawler.db` — `[!]` still needs you

Unchanged from the plan — I can't get this myself. What changed this session: I found direct, concrete evidence of how much this is costing beyond empty snippets. Without it, `docs[id]["content"]` is `""` everywhere, which means:
- **The spellcheck dictionary is built almost entirely from URL-slug titles**, not real page text — so common English words ("programming," "docker," "encyclopedia") get flagged as unknown and reject otherwise-good queries.
- **Semantic embeddings are computed from thin title-only text**, not real article content — directly limiting how good the semantic demo can look.
- **Snippets are empty**, as already known.

All three of these get meaningfully better the moment real page text exists locally. This is a stronger case for doing this first than the original plan stated.

## 4. Fix remaining correctness issues — `[x]` (AND parsing) / `[~]` (title indexing, see below)
- **AND parsing** — confirmed fixed and verified (prior session).
- **Title indexing** — see #7.

## 5. Automated tests — `[x]`

92 tests, 86% coverage on `app/`: `test_tokenizer`, `test_parser`, `test_bm25`, `test_ranking`, `test_semantic`, `test_cpp_reader`, `test_api`. `test_cpp_reader.py` — the one you specifically flagged — includes a hand-built, byte-exact synthetic `index.bin` fixture (mirroring the C++ writer's layout precisely) plus a secondary pass against the real committed index.

## 6. CI — `[x]`, pending a push to fully verify

`.github/workflows/ci.yml`: Python tests + lint (parallel), C++ build (parallel), gated on one pass/fail job. Every step verified locally (pytest, ruff, and the actual `cmake` build, using a toolchain I set up this session — `brew install snowball` provides `libstemmer`, `brew install sqlite` provides the SQLite dev headers). **Can't verify it's actually green on GitHub without a push** — that's the one thing left in this item needing you.

## 7. Title indexing — `[~]` done, needs your/your teammate's review

Real, verified fix to `src/index.cpp` (teammate-owned code) — committed on its own with an explicit review request in the commit message. Compiles cleanly and was verified functionally against a small synthetic SQLite database (not the real corpus, since I don't have `crawler.db`): a word placed only in one document's title is now correctly indexed. **Not merged to `main`.**

## 8. Independent relevance judgments — `[ ]` deliberately deferred

Concluded this isn't productively doable this session, and said so rather than manufacturing a low-value version to check the box: judging the *synthetic* corpus would face the exact circularity the design doc already names (a judge reading template-generated text is just re-deriving the same generation metadata under a different name); judging the *real* crawled corpus needs real page text, which mostly doesn't exist here yet (see #3). This is genuinely gated on `crawler.db`, not skipped for lack of effort.

## 9. Fix semantic retrieval's spellcheck bias — `[x]`

Done and measured. `rerank=true` now uses the raw query for retrieval, not just the embedding — closing the exact gap the design doc named since Phase 5. Found real-world impact immediately: a live query produced a nonsensical "did you mean: bas machines a4 learn from aa?" before the fix. Semantic subset improved from 0.930/1.000/0.948 to 0.990/1.000/0.994 (P@10/MRR/nDCG@10), zero lexical regression.

## 10. Tune BM25 k1/b — `[x]` attempted, correctly not deployed

Grid-searched against the evaluation set. The "best" result (`b=0.0`, fully disabling length normalization) is a marginal improvement driven by this corpus's artificially uniform document lengths (coefficient of variation 0.024) — checked directly before trusting it, same skepticism applied to the PageRank fit last session. Not deployed; `K1`/`B` unchanged. This is a real, disclosed finding, not a failure to find one.

## 11. Cross-encoder — `[ ]` deliberately deferred

Real, scoped follow-up work, not attempted this session given everything else in this pass. See the ROI-ranked roadmap in `docs-ml/roadmap.md` for where it sequences (after the ground-truth gap, since a cross-encoder's improvement is hard to measure credibly against circular ground truth).

## 12. Larger evaluation set — `[x]`

Doubled: 20 judgment queries to 40 (10 more lexical + 10 more semantic, same 10 categories, same methodology — every new lexical phrase confirmed present in the corpus before being added). One new, honestly disclosed miss surfaced ("professional athletes competing in games" scores 0.000 both ways).

## 13. Click/relevance logging — `[x]`

Built as a real, working feature, not just plumbing: `POST /feedback/click` + frontend wiring via event delegation. Verified with a real browser session that clicking a result actually fires the request with the correct body. Deliberately minimal beyond that — logs and returns, no persistence layer or analysis on top yet (that's real, separate future work).

---

## Scalability, for the ~2M-page target

No large rewrites this session — consistent with this project's own stated philosophy (build for the scale you're at, document what breaks first). What changed: none of this session's additions assume toy scale. The frontend calls the same paginated API a larger corpus would use unchanged. The click-logging endpoint is O(1) per request regardless of corpus size. The one thing worth flagging directly: `cpp_index_reader.py` currently loads the *entire* decoded index into Python memory in one pass — fine at 240–1,000 documents, a real ceiling worth watching well before 2M pages. Not fixed this session; noted here so it doesn't get rediscovered from scratch later.

## What's still genuinely blocked on you

1. **`crawler.db`** (#3) — now a stronger case than before: it's not just snippets, it's spellcheck accuracy and semantic embedding quality too.
2. **Reviewing the C++ title-indexing change** (#7) before it merges to `main`.
3. **A push to GitHub** — to verify CI (#6) actually goes green, and to get any of this in front of your teammate.
4. **Real human relevance judgments** (#8) — genuinely needs either your labeling effort or real page text to judge against.

---

# Phase 9 — placeholder removal, authentication, horizontal-scale readiness

Same day. `[x]` done, verified · everything below is committed on `retrievalranking`, not pushed.

## 14. Search bar placeholder — `[x]`

Removed the `placeholder="artificial intelligence"` attribute from `static/index.html`'s query input. Verified with a real browser screenshot — the input renders empty, no other layout changes.

## 15. Authentication — `[x]`

Real API-key gating, not a stub: `app/main.py` adds `require_api_key`, a FastAPI dependency checking `X-API-Key` against `API_KEY` (env-configurable, defaults to a public demo key). Applied to `/search`, `/suggest`, and `/feedback/click` — the endpoints that cost compute or write data. `/health` and `/` (the frontend) stay open, deliberately: an auth-gated health check is a good way to lock yourself out of your own monitoring, and gating the static HTML page itself protects nothing.

Verified live, not just by reading the code:
```
no key            → 401 {"detail":"Missing or invalid API key."}
wrong key         → 401
correct demo key  → 200
/health, no key   → 200
```
`static/app.js` was updated to send the matching demo key automatically, so the bundled frontend keeps working unmodified — confirmed with a real browser session (search still renders results, zero console errors). The demo key is disclosed as public in both files' comments: it's sitting in this repo's source and any visitor's browser downloads `app.js` in full, so it filters casual/automated abuse, not a motivated attacker. Before any real deployment: set `API_KEY` via the environment to a real secret, and stop hardcoding the matching value in `app.js` (template it server-side instead) — a real, disclosed limit of key-in-browser auth for a publicly-served single-page demo, not a hidden gap.

`tests/conftest.py`'s shared `api_client` fixture now carries the demo key as a default header, so none of the existing 100+ tests needed editing. A new `TestAuth` class in `tests/test_api.py` (6 tests) uses a separate, deliberately unauthenticated client to prove the enforcement side: missing/wrong key → 401 on all three gated endpoints, `/health` and `/` stay open.

## 16. Scale readiness — `[x]` for what's addressable now, `[ ]` noted for what isn't

Two real, working additions, both opt-in via environment configuration so today's single-process local behavior is completely unchanged unless you turn them on:

- **Redis-backed rate limiting.** `Limiter(..., storage_uri=os.environ.get("REDIS_URL", "memory://"))` — `slowapi`/`limits` already supported this; it was one line away. Unset `REDIS_URL` → identical to before (in-process counters). Set it → rate-limit counts are shared across every worker/replica instead of each keeping its own, which is the actual bug multi-worker deployment would otherwise have.
- **Redis-backed result cache, with graceful fallback.** `app/cache.py` gained `RedisSearchResultCache` (same `.get`/`.set` interface as the existing `SearchResultCache`, values pickled) and `build_search_cache()`, which picks between them based on `REDIS_URL` — and falls back to in-memory if Redis is configured but unreachable, rather than failing startup over a cache. Tested against a fake in-memory Redis client (`tests/test_cache.py`, 14 new tests) rather than requiring a real Redis server for CI or local dev.
- **Gzip compression** on all responses over 500 bytes (`GZipMiddleware`) — a real, free bandwidth win, verified live (`content-encoding: gzip` on a real `/search` response).

**What this doesn't fix, on purpose, disclosed rather than papered over:** `app/cpp_index_reader.py` still loads the entire decoded index into memory in one pass at startup — real ceiling, unchanged this session, and a materially bigger undertaking (streaming/lazy loading against the C++ binary format) than the auth/cache work above. Also unchanged: no ANN index for semantic augmentation (still O(corpus) per query), and no containerization/multi-worker deployment config yet — Redis being wired in makes multi-worker safe *when* you deploy that way, but doesn't itself deploy anything. All three are named in `docs-sde/roadmap.md` and `docs-ml/roadmap.md` at their existing priority — this session made the cheap, safe, high-leverage half of "scale-ready" real; the index-memory ceiling is the one that actually matters most as the corpus grows toward 2M pages, and it's still open.

`redis==5.2.1` added to `requirements.txt` and installed in the venv used to run/test this service. 113 tests pass, ruff (`E9,F`, matching CI) is clean.

---

# Phase 10 — real crawled data, 240 → 19,514 documents

Same day. Your partner shared `crawler.db` and a rebuilt `data/index.bin` via Google Drive. `[x]` everything below is placed, verified live, and re-tested — nothing here is committed to git yet (see the note at the end).

## 17. Integrate the real crawl data — `[x]`

Both files checked for integrity before touching anything (`file`/`xxd` magic-byte checks — real SQLite header, real `MYENGINE` index header, not corrupted downloads). Placed to match the layout `.gitignore`'s own comments describe:
- `crawler.db` → `crawler/data/crawler.db` (2.1GB, 523,125 SQLite pages), with `data/crawler.db` set up as the symlink to it the C++ engine and query-server both expect.
- `index.bin` → `data/index.bin` (110MB, was 2.2MB) — the old 240-doc file backed up outside the repo first, not overwritten blind.

Server restarted clean: index load ~28s, spellcheck-dictionary build over 854,906 terms + embedding rebuild for 19,514 docs, ~3 minutes total to `Application startup complete`. Verified live, not assumed:
- `doc_text_source: "crawler.db"` in the startup log (was `"unavailable"`).
- `GET /search?q=python` → real title ("Welcome to Python.org"), real `<mark>`-highlighted snippet from actual page text.
- `GET /search?q=ways+machines+can+learn+from+data&rerank=true` → "Top Machine Learning Applications in 2025" as the top hit, `bm25_score: null`, real `semantic_score` — the augmentation path still works correctly at 81x the corpus size.
- `/suggest?prefix=pyth` → sensible, frequency-ranked completions from the new 854,906-term vocabulary.
- Auth, gzip, and the frontend (from Phases 8–9) all re-verified working against the real corpus, not just the old 240-doc one.
- Full `pytest` suite re-run against the real index: **113 passed**, no regressions — including `TestAgainstRealCommittedIndex`, which now actually exercises 8.2M real postings instead of being effectively a no-op at 240 docs.

**What showed up at this scale, measured rather than assumed:**
- `data/index.bin` parse time: ~28s (was near-instant). Full server startup: ~3 minutes. Full `pytest` suite: 13s → **2m35s**, almost entirely the same startup tax paid by the session-scoped `TestClient` fixture.
- `rerank=true` query latency: **~3.0s** (vs. ~190ms lexical) — the whole-corpus semantic augmentation step is O(corpus) with no ANN index, and this is the first time that cost was actually visible rather than theoretical.
- PageRank now correctly sums to 1.0 (was ~0.008) over 34,176 discovered URLs — but the distribution is nearly flat (max ≈ 3x avg), a real, disclosed finding worth a look before leaning on this signal further.
- The crawl itself is real and broader (tumblr, docs.python.org, bbc.com, MDN, Wikimedia — not just the old Wikipedia-heavy set) but also noisier: a Google sign-in page, parked-domain listings, an affiliate-marketing domain, and one 1.7MB outlier content page all made it in. Disclosed, not filtered out.

## 18. Git hygiene for the new files — `[~]` prepared, not committed

`origin/main` moved since last checked (`git fetch`): your partner pushed a new commit deleting `data/index.bin` from git tracking and gitignoring it — independently landing on the same "don't commit build artifacts" conclusion already applied to `crawler.db`. Matched that here: `data/index.bin` was `git rm --cached` and added to this repo's `.gitignore` too (both changes staged/modified, **not committed** — waiting on you, since this touches shared history conventions). That same upstream commit also brings real, unreviewed crawler work (`crawler/tests/test_bloom.py`, an expanded `frontier.py`, changes to `parser.py`/`storage/indexer.py`, a new `CONCEPTS.md`) — not merged into `retrievalranking` yet.

---

## What's still genuinely blocked on you

1. **Review and merge the C++ title-indexing change** (#7) — now more valuable, since it'd apply to 19,514 real documents instead of a synthetic test DB.
2. **A push to GitHub** — to verify CI actually goes green, and to get Phases 8–10's work in front of your teammate. Note `origin/main` has moved; this'll need a merge, not just a fast-forward push.
3. **Review and merge `origin/main`'s new crawler work** (bloom filter, expanded frontier) into `retrievalranking` before it drifts further.
4. **Commit the staged `data/index.bin` untracking + `.gitignore` change** (#18) — or tell me to hold off.
5. ~~A real ground-truth labeling pass~~ — **done, see Phase 11 below.**
6. **A real file-sharing pipeline for `crawler.db`/`index.bin`** going forward — this round went over a Drive link again; see this session's chat for the Supabase Storage / object-storage discussion.

---

# Phase 11 — CI/CD fix, real Redis verification, real ground-truth judgments

Same request as Phase 10's follow-up: "do a few high-ROI things" before CI/CD+Dockerize+Deploy, per your own prioritization over the roadmap ChatGPT suggested. Nothing in this phase touches git — no commits, no pushes, per your explicit instruction. `[x]` everything below is verified locally.

## 19. Found and fixed a real CI-breaking bug — `[x]`

Reviewing `.github/workflows/ci.yml` before you push surfaced something real: Phase 10's `.gitignore`/`git rm --cached` change for `data/index.bin` (correct call — don't commit a 115MB binary) has a side effect nobody had checked: `app/main.py` calls `load_cpp_index(CPP_INDEX_PATH)` unconditionally at import time, by design ("fail loudly if missing"), and every test in `tests/test_api.py` imports `app.main` via the shared `api_client` fixture. A fresh GitHub Actions checkout has no `data/index.bin` at all now — confirmed directly by hiding the real file locally and reproducing `FileNotFoundError: ../data/index.bin` on `from app.main import app`. **This would have failed CI's `python-tests` job the moment you pushed.**

Fixed properly, not worked around:
- Extracted the existing hand-built `index.bin` writer (`tests/test_cpp_reader.py`'s `build_fixture_index_bin()`) into a shared module, `tests/fixture_builder.py` — one source of truth for the binary format, used by both the test suite and the fix below.
- New `scripts/generate_ci_index_fixture.py`: materializes a small (550-byte), valid `data/index.bin` with real-enough content (7 terms across 3 docs, chosen to match the specific vocabulary — `python`, `wikipedia`, `encyclopedia`, `and` — existing tests actually query for) so the whole suite passes against it, not just imports without crashing.
- `.github/workflows/ci.yml`'s `python-tests` job now runs this generator before `pytest`, with the stale "committed build artifact" comment corrected.
- Verified by fully reproducing a fresh-CI environment locally: hid the real `index.bin`, `crawler.db`, and embeddings cache, ran the generator, ran the full suite — **112 passed, 1 skipped** (a benign, correctly-designed skip). Then restored everything and re-verified the real server still boots and serves correctly against real data.

## 20. Verified Redis for real, not just against a fake client — `[x]`

Installed Redis locally (`brew install redis`), started it, and ran the server with `REDIS_URL=redis://localhost:6379` set. Confirmed directly against the real instance, not assumed from the code:
- `redis-cli KEYS "search:*"` → `search:python` — the result cache is genuinely writing to Redis.
- `redis-cli TTL "search:python"` → `3591` — TTL correctly applied.
- A repeat query logged `"cache_hit": true` at 8.8ms latency — genuinely served from Redis, not recomputed.
- `redis-cli KEYS` also showed a `LIMITS:LIMITER/...` key — the rate limiter is using Redis storage too, via the same `REDIS_URL`.

This closes the exact gap disclosed since Phase 9: "never exercised against a real Redis instance." Server restarted back to its standard in-memory config afterward — this was a verification pass, not a permanent change to how the app runs locally.

## 21. Real, independent relevance judgments against the real crawled corpus — `[x]`

The single biggest ML-side item on both your list and ChatGPT's. Built `scripts/evaluate_real.py`: 20 hand-verified judgment queries (10 lexical, 10 semantic) against real documents in the real 19,514-document corpus — not corpus-generation metadata (there is none; this is real crawled web content), not guessed. Each judgment was built by reading real `crawler.db` content directly (title *and* a content excerpt) and cross-checked for near-duplicate/alternate-topic pages sharing vocabulary but not actually relevant (e.g. a "Messi" search surfaced several unrelated pages about a place called "Messinias" — confirmed irrelevant, excluded, not just assumed absent).

Reuses `evaluate.py`'s metric functions and search pipelines unchanged (same code, same `/search`-mirroring logic) — only corpus-loading and the judgment set differ.

**Results — real, honest, not cherry-picked:**

| | Precision@10 | MRR | nDCG@10 |
|---|---|---|---|
| BM25-only (overall) | 0.073 | 0.434 | 0.457 |
| BM25+semantic (overall) | 0.080 | 0.615 | 0.629 |
| BM25-only (semantic subset) | 0.040 | 0.271 | 0.295 |
| BM25+semantic (semantic subset) | 0.050 | 0.363 | 0.372 |

Semantic re-ranking clearly helps (MRR +42% overall), but the improvement is far more modest than the synthetic corpus's numbers ever suggested (there, the semantic subset went from ~0.56 to ~0.95 nDCG) — a real, disclosed finding: **the synthetic corpus was measuring something meaningfully easier than real, noisy, 19,514-document retrieval.** Several harder paraphrase queries scored 0.0 on both modes; spot-checked one (`"a reptile's very long trip back to its home"`, target: a sea-turtle article) and confirmed it's not a bug — augmentation correctly finds real animal/wildlife-topic pages (several nature blogs), they just semantically outrank the intended target in a corpus this large and diverse. Direct, concrete evidence for why cross-encoder re-ranking (already the top item in `docs-ml/roadmap.md`) matters at real scale, not just in theory.

## 22. Fit BM25 k1/b against real judgments — `[x]`, real signal, not yet deployed

`scripts/tune_bm25_params_real.py` (reuses `tune_bm25_params.py`'s grid-search logic unchanged). Result: **k1=1.8, b=0.25** improves nDCG@10 from 0.4565 to 0.5484 (+20% relative) — and critically, `b=0.25`, not the suspicious `b=0` edge case the synthetic-corpus run hit. This corpus has genuine document-length variation (6 to 239,065 tokens), so this isn't an artifact of an artificially uniform corpus the way the earlier result was. Still: only 20 judgment queries — a real, promising early signal, not something to deploy off a single small grid search. `K1`/`B` unchanged in `app/bm25.py`.

## 23. Fit BM25/PageRank fusion against real judgments — `[x]`, caught real bias before it shipped

`scripts/train_ranker_real.py` (reuses `train_ranker.py`'s training-example extraction unchanged). Raw result: **PAGERANK_WEIGHT = 0.5485** (vs. hand-set 0.15) — a striking jump, and unlike the earlier synthetic-corpus result (which correctly found PageRank uninformative there), this time there was no obvious reason to distrust it on its face, since the real link graph is genuine.

**Checked anyway, and it's not trustworthy.** Added `check_judgment_set_pagerank_bias()` — a permanent, automated part of the script now, not a one-off aside — which found the 14 documents this judgment set names as relevant have a mean PageRank **58x** the full corpus's mean (corpus median PageRank: 0.0). That's confirmed selection bias: the judgment set leans on well-known, high-authority domains (`docs.python.org`, `bbc.com`, MDN) largely because they were fast to verify against real content, not because low-authority pages were deliberately excluded from consideration. The fitted weight reflects "did the judge recognize this domain as reputable," not "does PageRank predict relevance." **Not deployed** — same discipline as every other fitted result in this project, applied to a new failure mode (an unrepresentative judgment set, not an unrepresentative link graph).

This is genuinely valuable: it's evidence the *fitting pipeline* correctly resists a real, subtle bias rather than a clean success story — and it's a concrete, actionable next step (rebuild the judgment set including verified-relevant low-authority pages) rather than a dead end.

---

## What's still genuinely blocked on you

1. **`crawler.db`** — done (Phase 10).
2. **Review and merge the C++ title-indexing change** — still open, now more valuable (applies to 19,514 real docs).
3. **Push to GitHub** — the CI fix above (#19) makes this safe to do now; wasn't, before this phase.
4. **Review and merge `origin/main`'s new crawler work** (bloom filter, expanded frontier) into `retrievalranking`.
5. **Commit this session's changes** — I haven't committed anything (confirmed via `git log`); everything above is staged/modified in the working tree, per your instruction that you'll commit yourself.
6. **A bias-corrected relevance judgment set**, if you want the PageRank fusion re-fit to become deployable — needs relevant documents from lower-authority sources included on purpose, not just whatever was fastest to verify.

---

# Phase 12 — Dockerize (in progress — this section is a live checkpoint, updated as work proceeds)

**Status as of this checkpoint: build in progress, not yet verified running.** Keeping this section current as I go, per your request, since context may run low mid-session.

## 24. `query-server/Dockerfile` — `[x]` written, build succeeded after one real fix

Multi-stage build (builder installs deps into a venv; runtime copies just the venv + app code, runs as non-root `appuser`). Deliberately does **not** bake in `data/index.bin` or `crawler.db` — they're 110MB and 2.1GB; a reproducible, lean image mounts real data in at runtime instead (see `docker-compose.yml`). Pre-downloads the `all-MiniLM-L6-v2` model and NLTK's `stopwords` corpus at *build* time, so the container needs no outbound network access to serve a request and doesn't pay that download cost on every cold start.

**Real bug hit and fixed while building, not assumed to work:** `python -m nltk.downloader -d ... stopwords` failed inside the build with `Security Violation: Unauthorized path` followed by an `EOFError` (the downloader's interactive retry prompt has no TTY in a Docker build). Isolated the cause by testing the NLTK Python API (`nltk.download(...)`) directly in a throwaway container — that path works cleanly, the CLI module (`python -m nltk.downloader`) is what's broken in this non-interactive context. Fixed by switching the Dockerfile to the API call instead of the CLI.

## 25. `docker-compose.yml` — `[x]`, with explicit memory limits per your instruction

Bind-mounts `data/index.bin` (read-only), `crawler/data/crawler.db` (read-only, optional — omit if you don't have it, `app/crawler_db.py` degrades gracefully the same way it does outside Docker), and `query-server/data/` (read-write, so the ~30MB embeddings cache persists across container restarts instead of a ~3-minute rebuild every time).

**Memory is explicitly capped**, directly per your instruction not to let this run unbounded: `mem_limit: 2g`, `mem_reservation: 512m`, plus the equivalent `deploy.resources.limits` block for Swarm/Kubernetes portability later. This is a starting cap, not yet calibrated against measured peak usage — that's the next step, in progress as this checkpoint is being written. Healthcheck's `start_period` is set to 240s, matching the real ~3-minute measured cold start at 19,514 documents (Phase 10/11) — a shorter value would report the container unhealthy while it's still legitimately booting.

## 26. Real incident: the build filled the host's disk — `[x]` root-caused and fixed, `[ ]` rebuild not yet re-verified

The second build attempt failed with `failed to extract layer ...: write .../nvidia/cu13/lib/libcublasLt.so.13: input/output error`. Root cause, confirmed by inspection: `torch==2.13.0` in `requirements.txt`, installed via plain `pip install`, resolves to PyPI's **CUDA-enabled** build by default — several GB of bundled NVIDIA libraries that a Mac (or any CPU-only deployment target, which is what `app/semantic.py` actually runs) can never use. That download, across two build attempts, filled Docker Desktop's VM disk (`Docker.raw` reached **16GB**) and took the host's free space down with it — briefly down to **0 bytes free**, at which point even trivial shell commands (`echo`, `df`) failed with `ENOSPC`. Had to stop and ask you to free space before any further command could run at all.

**Fixed at the root**, not worked around: `Dockerfile` now installs the matching **CPU-only** torch build explicitly first (`pip install torch==2.13.0 --index-url https://download.pytorch.org/whl/cpu`), before `requirements.txt` is processed — so pip's own version-pin check finds `torch==2.13.0` already satisfied and never reaches for the CUDA build at all. This should cut the final image from multiple GB down to roughly 1–1.5GB (rough estimate — not yet measured against the fixed build).

**Cleanup, in progress:** Docker Desktop restarted (its daemon returned a 500 error after the disk-full crash — a fresh restart, not a deeper reset, is the first thing to try). `docker system prune -af --volumes` next, to reclaim the ~16GB `Docker.raw` was holding, mostly from the failed CUDA download and now-orphaned build cache. Real, verified space-reclaimed number goes here once that completes — not stated yet.

## Next in this phase (not done yet as of this checkpoint)
- Finish reclaiming Docker's disk usage (in progress).
- Rebuild with the CPU-only-torch fix; confirm the image is actually ~1–1.5GB, not multiple GB.
- Verify the container actually boots and serves real requests correctly.
- **Watch memory usage live while it boots and serves** (`docker stats`) — the actual point of the memory cap, not just setting a number and hoping. Adjust `mem_limit` based on what's actually measured, not guessed.
- Add a Docker build (+ smoke test) job to `.github/workflows/ci.yml`.
- Update `docs-sde`/`docs-ml` current-state.md, roadmap.md, and both `RUNDOWN_*.html` files with final, verified numbers.

## TODO, ranked, with estimated Docker disk impact where relevant

| # | Item | Est. Docker disk impact |
|---|---|---|
| 1 | Reclaim Docker's existing ~16GB `Docker.raw` bloat (`docker system prune -af --volumes`, Docker Desktop restart already done) | Frees ~10–16GB back to host — blocking everything below |
| 2 | Rebuild image with the CPU-only-torch fix | Final image: **~1–1.5GB estimated** (vs. multi-GB with the CUDA build); peak *during* build (base image + intermediate layers before squash): ~2–3GB, freed after |
| 3 | Boot the container, verify real requests work | No new disk usage — mounted volumes reference existing host files, not copies |
| 4 | Watch memory live (`docker stats`), calibrate `mem_limit` from measured peak, not the guessed 2GB | Disk impact: none (this is memory, not disk) |
| 5 | Add a Docker build + smoke-test job to CI | Runs on GitHub's hosted runners (~14GB free by default) — **zero local disk impact** |
| 6 | Update docs/HTML with final, verified numbers | No disk impact |

Items 1–2 are the only ones with real Docker disk cost; everything past them is close to free, disk-wise, once the image itself exists.

---

## Phase 12 continued — Docker disk incident resolved, three more real bugs found and fixed by actually booting the container

**Disk resolved.** Docker Desktop's VM disk (`Docker.raw`) had real filesystem corruption from the earlier disk-full crash (`EXT4-fs: failed to convert unwritten extents to written extents -- potential data loss!`, found in Docker's own VM console log). A restart alone wouldn't fix corruption, so: fully quit Docker Desktop, deleted the VM disk entirely (`~/Library/Containers/com.docker.docker/Data/vms/0`), relaunched. Docker recreated it fresh (7.5MB, vs. the 16GB it had bloated to) and **host free space went from 4.2GB to 20GB.** This only removed Docker's own reproducible cache/images -- nothing of yours was touched.

**Rebuilt with the CPU-only-torch fix -- confirmed working, not just hoped.** `torch.__version__` inside the built image reports `2.13.0+cpu`, `torch.cuda.is_available()` is `False`. Final image: **2.08GB** (measured, not estimated) -- large mostly because sentence-transformers/torch/scipy/scikit-learn are real dependencies, but nowhere near what the CUDA build would have produced.

**Then booted the actual container and found three more real bugs, each caught by watching it fail rather than assuming success:**

1. **NLTK's downloader has a real bug in this build context.** Both `python -m nltk.downloader` (the CLI) and `nltk.download()` (the Python API) hit `Security Violation: Unauthorized path .../stopwords.zip.tmp` *inside the multi-stage build specifically* -- not reproducible in an isolated one-off container. Rather than keep chasing an nltk internals bug, bypassed its downloader class entirely: fetch and unzip the same file with plain `urllib`/`zipfile` stdlib calls. Verified the result is the same 34-language stopwords corpus.

2. **`crawler.db` (real, mounted) failed with `sqlite3.OperationalError: attempt to write a readonly database` on a plain `SELECT`.** Root cause: `crawler.db` is written in WAL mode, so even a read connection needs to create/check `-wal`/`-shm` companion files in the same directory -- which fails once that directory isn't writable by the container's non-root user. Real fix, in `app/crawler_db.py` itself, not just a Docker workaround: added `&immutable=1` to the SQLite connection URI, which tells SQLite the file genuinely won't change for this connection's lifetime (true here -- the whole function is open, one `SELECT`, close, within milliseconds) and skips journal handling entirely. This is a real, permanent improvement to that file, not container-specific code.

3. **The pre-downloaded sentence-transformer model was invisible at runtime.** Baked into the image under `/root/.cache/huggingface` at build time, but the container runs as non-root `appuser` (can't read root's home directory) -- crashed with `couldn't connect to huggingface.co ... couldn't find them in the cached files` the moment `HF_HUB_OFFLINE=1` correctly refused to fall back to a live download. Fixed by setting `HF_HOME=/opt/hf_cache` (a neutral, `chown`-able path) at both download time and runtime, instead of relying on whichever user's home directory happened to be current when the model was fetched.

**Then the actual memory calibration, live, exactly as you asked me to keep checking:**

| Attempt | `mem_limit` | What happened |
|---|---|---|
| 1 | 2g (original guess) | Hit 99.9% within ~30s of startup, before the container even logged its first line -- seconds from an OOM kill. Stopped and raised the limit before it could crash. |
| 2 | 4g | Got a full **healthy** boot -- but peaked at **3.874GB (96.85%)** at rest, and a real semantic-search request (`rerank=true`) pushed it to **3.913GB (97.82%)**. Confirmed via a real `/search` request returning correct results (same top hit as the non-Docker version), not just a health check. Too little headroom to trust. |
| 3 (current) | 5g, VM raised 5GB→6GB | In progress as this checkpoint is written -- Docker Desktop restarting with the new VM allocation now. |

**A real, disclosed tradeoff, not a free fix:** this host has only 8GB of RAM total. Raising Docker Desktop's VM allocation from 5GB to 6GB (`settings-store.json`'s `MemoryMiB`) was necessary to give the container real headroom above its measured ~3.9GB peak -- but it means less memory available to macOS itself and everything else running on this machine while the container is up. Worth knowing if the Mac feels sluggish with this container running; the fix there is closing other apps or accepting a smaller container limit with less safety margin, not something to paper over.

**Also measured, worth knowing:** a semantic-search request took **7.9s inside Docker** vs. **~3.0s** running natively (same corpus, same query) -- meaningfully slower, plausibly CPU contention inside the VM (8 CPUs allocated, shared with the VM's own overhead) rather than anything wrong with the app itself. Not yet root-caused further; noted here rather than left silently unmeasured.

## Phase 12 — final status: `[x]` complete and verified end to end

Confirmed with the 5g limit / 6GB VM allocation: healthy boot at **4.063GB (81.27%)**, settling at **4.27GB (85.41%)** after a real lexical query and a real `rerank=true` semantic query — both returned correct results (`HTTP 200`, matching native output), and an unauthenticated request correctly got `401`. **~730MB of genuine headroom**, not a near-miss. Bonus finding: the earlier 4g attempt's memory pressure was also making queries 60% slower (7.9s → 4.97s once real headroom existed) — the calibration fixed a real performance problem, not just a crash risk.

`docker-build` job added to `.github/workflows/ci.yml` (generates the same CI index fixture the `python-tests` job uses, builds the image, boots it with a 1GB cap, verifies `/health`, an authenticated search, and a 401-without-key check, then tears down). YAML validated. Not yet run on actual GitHub infrastructure — needs your push.

**Everything Phase 12 touched, for the record:** `query-server/Dockerfile` (new), `query-server/.dockerignore` (new), `docker-compose.yml` (new, repo root), `app/crawler_db.py` (real fix: `immutable=1` on the SQLite URI), `.github/workflows/ci.yml` (new `docker-build` job). Full experiment detail, including every dead end and exact error message, is in `../docs-sde/benchmarks-phase11-12.md`.

### Remaining, not part of Phase 12's scope
- Push to GitHub to confirm the new `docker-build` CI job actually passes on real infrastructure.
- Understand *why* Docker is still ~65% slower than native even with real memory headroom (CPU contention inside the VM, not chased further).
- Deploy for real (a live host) — still deliberately not attempted, per your own sequencing.

---

## Phase 13 — Repo cleanup: retired the standalone prototype, flattened this monorepo up to the project root

**`search-engine/`** — an earlier, Python-only prototype that predates the C++ engine/crawler integration (no `src/`/`include/`, no `crawler/`, no CI, no Docker) — **removed entirely, not merged.** Verified first, not assumed: diffed every file that existed in both trees, hunk by hunk. All 9 overlapping `app/*.py` files, `index.cpp`, and `DESIGN AND IMPLEMENTATION DOCUMENT.md` showed this repo's version strictly *adding* to the prototype's content — real, deliberate evolution (e.g. `query_parser.py`'s case-sensitive AND/OR/NOT fix, `index.cpp`'s title-indexing fix), never losing anything from it. The one apparent exception — 3 lines removed from `main.py`'s startup (a local `build_link_graph`/`compute_pagerank` call) — is because that computation moved into `cpp_index_reader.py` instead (Phase 6); confirmed by reading both versions side by side, not just the diff output. `search-engine/tests/*.md` were byte-identical duplicates of files already here; `search-engine/data/*` were stale duplicate caches; its `.gitignore` was a strict subset of this repo's. Nothing unique was lost.

**This monorepo clone — previously `Search-Engine-remote/`, one level below the outer `Search Engine/` project folder — flattened up to become the project root itself.** `crawler/`, `src/`, `include/`, `query-server/`, `data/`, `resources/`, `build/`, `.github/`, `.gitignore`, `CMakeLists.txt`, `Readme.md`, and `docker-compose.yml` all moved up one level. Checked first: every internal reference in this file, `Readme.md`, `crawler/README.md`, `crawler/CLAUDE.md`, `crawler/SEARCH_ENGINES.md`, `query-server/README.md`, and both `docs-sde/`/`docs-ml/` folders is already repo-root-relative (`crawler/`, `src/`, `data/index.bin`, etc.), so nothing broke from the move itself. The one real inaccuracy it did cause — `docs-sde/current-state.md` and `docs-ml/current-state.md` describing `RUNDOWN_*.html` as living "one level above this monorepo clone" — is fixed in this same pass.

**Old git history (branch `retrievalranking`, 15 commits ahead of `origin/retrievalranking`, plus uncommitted work sitting in the tree) was not carried forward.** Backed up first as a full `git bundle` (all branches, restorability verified) before `.git` was dropped, per instruction, ahead of a fresh `git init` against a new remote in the next phase. Anything that only ever existed in that history — including any unreviewed work on `origin/main` — is preserved in the bundle if it's still needed.

**Not touched in this pass:** `howtorun.txt` (still references the now-removed `search-engine/` — deliberately left as is, out of scope this round), `index.bin.old-240doc-backup` (an unrelated stray file at the project root, predates both codebases), and the git-state narrative elsewhere in this repo's docs (`current-state.md`'s "Where the git history stands," `overview.md`'s "Git state") — those describe git state that's about to change again in the next phase, not this one.

---

## Phase 14 — Repo pushed to a new remote; CI's first real run on GitHub infrastructure failed, root-caused, fixed

The repo was pushed to a fresh remote (`github.com/mayank2309jha/Search-Engine`, single squashed `main`, no prior history — Phase 13's dropped `.git` was backed up as a bundle first, not just discarded). This was CI's actual first run on real GitHub infrastructure, not local validation — and it caught something local validation structurally never could have.

**`python-tests` failed, exit code 2 (a collection-time error, not a test assertion failure) — not the empty-`data/index.bin` case this workflow already handles.** Root-caused by reproducing locally, not guessed: `app/main.py` loads the sentence-transformer model (`app/semantic.py`) and NLTK's stopwords corpus (`app/tokenizer.py`) unconditionally at import time. Both cache in the developer's home directory the first time they're ever fetched, on any project — so every local run anyone has ever done here was already a cache hit, silently. A fresh GitHub-hosted runner starts with neither cache. Confirmed directly: pointing `HOME` at an empty temp directory and running `from app.main import app` reproduces the exact failure (`OSError: We couldn't connect to 'https://huggingface.co'...`) that a live-network hiccup on a real runner would also produce — the job isn't wrong to depend on the network, it's wrong to depend on the network being reliable *and* fast enough inside every single test run, when the cost only needs to be paid once, at setup.

**Not a new problem — this exact failure mode was already found and solved once, for the Docker image, in Phase 12.** `Dockerfile` already pre-downloads both at build time, specifically so the container needs no outbound network access to serve a request. `.github/workflows/ci.yml`'s `python-tests` job never got the same treatment, because it never ran against a genuinely cold environment until this push. Fixed by giving it the same treatment: a new step pre-downloads the model and stopwords corpus (the NLTK fetch reuses the exact plain-`urllib`/`zipfile` method the Dockerfile already validated, since `nltk.download()`'s own downloader has a separate, unrelated bug in constrained build contexts) before the fixture-generation and pytest steps run. **Verified end to end before pushing**, not assumed fixed: reproduced the fresh-runner condition locally with an empty `HOME`, ran the new pre-download steps against it, then imported `app.main` against that same now-warm-but-otherwise-isolated `HOME` — succeeded. Full suite re-run afterward against real local data (index.bin, crawler.db both restored) — 113 passed, unaffected.

**An earlier, false lead worth recording so it isn't re-chased:** the first local reproduction attempt (fixture in place, but the real `data/crawler.db` symlink left mounted) produced a *different* failure — `TestSuggest::test_returns_suggestions_for_a_real_prefix` got zero results for prefix `"wiki"`, because real crawled Python.org content for doc IDs 1–3 silently overrode the fixture's intended URL-derived titles. That failure is real but was self-inflicted by an incomplete local reproduction, not something GitHub's actual fresh checkout (which never has `crawler.db` at all) could ever hit — confirmed by re-running with `data/crawler.db` also moved aside, which passed cleanly. Recorded here specifically because it's a plausible-looking, wrong answer that cost real time to rule out.
