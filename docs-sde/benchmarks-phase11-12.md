# Test & benchmark results — Phases 11–12, full detail

Raw experiment log for the SDE-side verification work: real Redis, the CI-breaking bug, real-scale
timing, and the Docker build incident. `current-state.md` summarizes conclusions; this file is the
evidence — commands run, exact numbers, what was checked and how. Companion to
`../docs-ml/benchmarks-phase11.md` (the ML-side evaluation experiments).

## 1. Real corpus scale, measured exactly

Source: `app/cpp_index_reader.py` read directly against the real `data/index.bin`.

| Metric | Value |
|---|---|
| Documents | 19,514 |
| Unique terms (dictionary) | 854,906 |
| Total postings (term–doc pairs) | 8,217,258 |
| Total positions | 22,589,060 |
| Average doc length | 1,157.58 tokens |
| Min / max doc length | 6 / 239,065 tokens |
| `data/index.bin` size | 115,332,397 bytes (~110MB) |
| `crawler.db` size | 2,142,720,000 bytes (~2.1GB), 523,125 SQLite pages |
| Recorded links | 3,506,039 |
| URLs with a PageRank score | 34,176 |

PageRank distribution (`app/authority.py`'s `normalize_pagerank()` output over `doc_pageranks`):

| Stat | Value |
|---|---|
| Min | 2.90594321405944e-05 |
| Mean | 2.92602996254682e-05 |
| Max | 8.77570869288735e-05 |
| Sum (sanity check) | 1.0 |

Max is only ~3x the mean — a real, disclosed finding: this corpus's PageRank distribution is far flatter than a typical hub-heavy web graph, despite being computed correctly (see `../docs-ml/current-state.md` for what this means for the fusion-weight fitting result).

## 2. Startup timing, measured with a stopwatch, not estimated

Method: `date`-stamped log lines from a real `uvicorn` boot against the real corpus, `tail -f` watched live.

| Phase | Elapsed |
|---|---|
| `data/index.bin` parse (`load_cpp_index`) alone, isolated | 27.83s |
| Full server boot, index load → symspell dict (854,906 terms) → embeddings rebuild (19,514 docs, cache cold) | ~3 minutes (16:29:06 → 16:32:07 in one measured run) |
| Full server boot, embeddings cache warm | Faster — index load (~28s) + model load + cached-embeddings load, no ~2.5min embedding rebuild |

Command used to reproduce the cold-start measurement:
```
cd query-server
PYTHONPATH=. python -m uvicorn app.main:app --port 8000 > /tmp/uvicorn.log 2>&1 &
until grep -qE "Application startup complete|Traceback|Error" /tmp/uvicorn.log; do sleep 3; done
```

## 3. Query latency, real corpus, real requests

Method: `time curl` against the running server, `X-API-Key` header included.

| Query type | Latency |
|---|---|
| Lexical (`q=python`) | 189ms |
| Semantic (`q=ways+machines+can+learn+from+data&rerank=true`) | 3.015s |

The 3s semantic-search latency is the whole-corpus embedding-similarity augmentation step running O(19,514) comparisons with no ANN index — a real, now-measured cost that was previously only a theoretical concern (see `../docs-ml/roadmap.md`'s ANN-indexing item).

## 4. Memory footprint, as measured locally (macOS `ps`, not yet cross-verified in Docker)

```
ps -o pid,rss,command -p <uvicorn pid>
```
Result: **RSS ~78.6MB** at rest, after startup completed and serving requests. Flagged directly, not
just reported: this is lower than naively expected given ~1GB of loaded libraries (torch,
transformers) plus the in-memory index/dictionary/embeddings structures. Worth re-measuring via
Docker's cgroup-based accounting (`docker stats`), which is typically more reliable than macOS's own
`ps` RSS (subject to memory compression quirks) — see the Docker section below; that re-measurement
is the actual point of this entry, and hadn't completed as of this file's last edit (see the
Docker section's status).

## 5. Real pytest suite, timed against real data

| Run | Result | Time |
|---|---|---|
| Full suite, real 19,514-doc `data/index.bin` present | 113 passed | 2m53s (was ~13s at the old 240-doc scale) |
| `TestAgainstRealCommittedIndex` alone | 2 passed | 61s (was near-instant at 240 docs) |
| Full suite, simulated fresh CI (real `index.bin`/`crawler.db`/embeddings cache all hidden, CI-generated fixture in place) | 112 passed, 1 skipped | 13.7s |

The last row is the actual CI-fix verification: it proves the generated fixture (`scripts/generate_ci_index_fixture.py`) makes the suite pass in exactly the conditions a fresh GitHub Actions checkout will face — no real data files present at all.

## 6. The CI-breaking bug — reproduction and fix, in full

**Reproduction** (proving the bug is real before claiming a fix):
```
mv data/index.bin data/index.bin.tmp-hidden
python -c "from app.main import app"
```
Result: `FileNotFoundError: [Errno 2] No such file or directory: '../data/index.bin'`, raised from `app/cpp_index_reader.py:70`'s `open(index_path, "rb")`, on import of `app.main`. Since `tests/conftest.py`'s `api_client` fixture does `from app.main import app`, every test in `tests/test_api.py` would fail at fixture setup in a fresh CI checkout, where `data/index.bin` is correctly gitignored and never committed.

**Root cause:** `app/main.py` calls `load_cpp_index(CPP_INDEX_PATH)` unconditionally at module import time, by explicit design (fail loudly if the index is missing, rather than silently serve stale data). That design choice is correct for a real deployment; the gap was that CI's checkout never had a substitute file to load.

**Fix, verified working:**
1. Extracted `tests/test_cpp_reader.py`'s hand-built `index.bin` writer into `tests/fixture_builder.py` (shared module — one implementation of the binary format, not two).
2. `scripts/generate_ci_index_fixture.py` — writes a small (550-byte), valid `data/index.bin` with 3 documents / 7 terms, chosen specifically to cover the vocabulary (`python`, `wikipedia`, `encyclopedia`, `and`) that `tests/test_api.py`'s existing queries need.
3. `.github/workflows/ci.yml`'s `python-tests` job runs this generator before `pytest`.
4. Verified end to end: hid `data/index.bin`, `crawler.db`, and the embeddings cache locally, ran the generator, ran the full suite — **112 passed, 1 skipped** (a benign, correctly-designed skip: `"no docs in this corpus snapshot contain both terms"`). Then restored all real files and re-verified the real server still boots correctly.

## 7. Redis, verified against a real local instance

Setup: `brew install redis`, `redis-server --daemonize yes --port 6379 --save "" --appendonly no`, then `REDIS_URL=redis://localhost:6379` on the app.

| Check | Command | Result |
|---|---|---|
| Cache key exists | `redis-cli KEYS "search:*"` | `search:python` |
| TTL correctly applied | `redis-cli TTL "search:python"` | `3591` (of a 3600s default) |
| Cache-hit latency | live request, log inspection | `"cache_hit": true`, `"latency_ms": 8.8` |
| Rate limiter using Redis | `redis-cli KEYS "*"` | `LIMITS:LIMITER/127.0.0.1//search/30/1/minute` present |

Both `app/cache.py`'s `RedisSearchResultCache` and `slowapi`'s rate-limiter storage were previously verified only against a fake/mock client in `tests/test_cache.py`. This is the first time either touched a real Redis server.

## 8. Docker — full incident log: disk, three runtime bugs, and live memory calibration

### 8a. The disk incident

`requirements.txt` pins `torch==2.13.0`. A plain `pip install torch==2.13.0` (no index override) resolves to PyPI's default wheel, which is the **CUDA-enabled** build — it bundles several GB of NVIDIA libraries (`nvidia/cu13/lib/libcublasLt.so.13` among them) that a Mac, or any CPU-only deployment target, can never use (`app/semantic.py` explicitly runs CPU inference). Across two build attempts, that download filled Docker Desktop's VM disk image (`Docker.raw`) to **16GB**, and took the host's free disk space down with it — briefly to **0 bytes free**, at which point even `echo` and `df -h` failed with `ENOSPC`.

Build failure signature:
```
failed to extract layer sha256:...: write .../nvidia/cu13/lib/libcublasLt.so.13: input/output error
```

The VM's own console log (`~/Library/Containers/com.docker.docker/Data/log/vm/console.log`) showed real filesystem corruption from the disk-full crash: `EXT4-fs (vda1): failed to convert unwritten extents to written extents -- potential data loss!`. A daemon restart alone didn't fix this (subsequent `docker system df` returned `500 Internal Server Error`) — recovery required fully quitting Docker Desktop and deleting the VM disk entirely (`rm -rf ~/Library/Containers/com.docker.docker/Data/vms/0`), then relaunching to let it recreate fresh. Result: `Docker.raw` went from 16GB to 7.5MB, and **host free space went from 4.2GB to 20GB.**

**Fix, in `query-server/Dockerfile`:**
```dockerfile
RUN pip install --no-cache-dir torch==2.13.0 --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt
```
Verified working, not just hoped: `torch.__version__` inside the built image is `2.13.0+cpu`, `torch.cuda.is_available()` is `False`. Final image: **2.08GB** (measured).

### 8b. Three runtime bugs, found by actually booting the container

1. **NLTK's downloader (both the CLI and the Python API) hit `Security Violation: Unauthorized path .../stopwords.zip.tmp`** — reproducible inside this specific multi-stage build, not reproducible in an isolated one-off container (tested both ways). Root cause not chased further; worked around by bypassing nltk's downloader class entirely — fetched and extracted the same zip with plain `urllib`/`zipfile` stdlib calls. Verified the result matches (34-language stopwords corpus, `english` present).

2. **`sqlite3.OperationalError: attempt to write a readonly database` on a plain `SELECT` against the mounted `crawler.db`.** Root cause: `crawler.db` is written in WAL mode (`crawler/storage/indexer.py`), so even a read-only connection needs to create/check `-wal`/`-shm` companion files alongside it — which fails once the containing directory isn't writable by the container's non-root user. Reproduced with the bind mount both as `:ro` and read-write (same failure either way — a permissions issue inside the VM's file-sharing layer, not the mount flag). Real fix, in `app/crawler_db.py` itself: added `&immutable=1` to the SQLite URI, telling SQLite the file provably won't change for this connection's short lifetime (open → one `SELECT` → close, milliseconds), which skips journal handling entirely. A genuine improvement to that file, not a container-only workaround.

3. **The pre-downloaded sentence-transformer model was invisible at runtime**: `couldn't connect to huggingface.co ... couldn't find them in the cached files`. Baked in at `/root/.cache/huggingface` during the build (root), but the container runs as non-root `appuser`, which can't read root's home directory. Fixed by setting `HF_HOME=/opt/hf_cache` (a neutral, explicitly-`chown`ed path) at both download time and runtime.

### 8c. Memory calibration, live, exactly as instructed to "keep checking"

| Attempt | `mem_limit` | Result |
|---|--:|---|
| 1 | 2g (initial guess) | **99.9% within ~30s of startup** — before the container even logged its first line. Stopped before an OOM kill. |
| 2 | 4g | Reached a healthy boot, but peaked at **3.874GB (96.85%)** at rest, and **3.913GB (97.82%)** under a real `rerank=true` semantic-search request. ~90MB headroom — too tight to trust. |
| 3 (final) | 5g, Docker Desktop VM raised 5GB→6GB (settings-store.json's `MemoryMiB`, confirmed via `docker info` reporting 5.79GB total afterward) | Healthy boot at **4.063GB (81.27%)**, settling at **4.27GB (85.41%)** after a real lexical query + a real `rerank=true` semantic query. **~730MB genuine headroom** — the calibration this instruction was actually asking for. |

**Real, disclosed tradeoff:** this host has 8GB of RAM total. Raising the VM's own allocation from 5GB to 6GB to give the container real headroom means ~1GB less available to macOS and everything else running on this Mac while the container is up — not a free change. Docker Desktop's restart after this settings change took unusually long (multiple attempts, one force-kill of stuck processes) — noted in case this recurs; not fully root-caused.

**Query latency, measured across all three memory attempts — a secondary confirmation the calibration mattered, not just a safety margin:**

| Attempt | `rerank=true` semantic-query latency (Docker) | Native (no Docker) |
|---|--:|--:|
| 2 (4g, ~98% memory pressure) | 7.9s | ~3.0s |
| 3 (5g, ~85% memory pressure) | 4.97s | ~3.0s |

Under real memory pressure (97-98%), the same query ran **60% slower** than with genuine headroom — the memory ceiling wasn't just a crash risk, it was actively degrading performance before it ever got close to OOM-killing anything. Docker is still ~65% slower than native at best (4.97s vs 3.0s), plausibly CPU contention inside the VM's 8-CPU allocation shared with the VM's own overhead — not fully root-caused, noted as a real, disclosed gap rather than left unmeasured.
