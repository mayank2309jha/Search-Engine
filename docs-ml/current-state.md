# ML current state

Honest snapshot. Numbers reference `RUNDOWN_ML.html` (at the project root, alongside this `docs-ml/` folder — both flattened to sit side by side as of Phase 13's repo cleanup) — a weighted 6-group scorecard scoped to query understanding/parsing/retrieval; see that file's own footer for the current total.

## Phase 11 (same day): real, independent ground truth now exists — and it caught a real bias

This is the headline update: `scripts/evaluate_real.py`, `tune_bm25_params_real.py`, and `train_ranker_real.py` run the exact same evaluation/fitting logic as their synthetic-corpus counterparts, against 20 hand-verified judgment queries over the real 19,514-document corpus. Full results in "Measured evaluation numbers" and "Two more fitted results" below. The single most important finding: fitting `PAGERANK_WEIGHT` against these real judgments returned 0.5485 (vs. hand-set 0.15) — and a built-in bias check (now a permanent part of `train_ranker_real.py`, not a one-off aside) found this judgment set's relevant documents have a mean PageRank **58x** the corpus mean, confirming selection bias toward well-known domains rather than a genuine relevance signal. **Not deployed.** See below for the full reasoning — this is arguably the most valuable single finding of this whole engagement, because it's the fitting pipeline catching a real, subtle flaw in its own training data rather than a clean success story.

## Phase 10 (same day): real crawled data landed — 240 → 19,514 documents

Your partner shared a real `crawler.db` and rebuilt `data/index.bin`. Real page text now exists for 19,514 documents — the explicit blocker on ever attempting real (non-circular) relevance judgments against the live system. See Phase 11 above for what that unlocked.

## What's fit or tuned right now, and what's actually deployed

| Parameter | Value | Fit/tuned? | Deployed? |
|---|---|---|---|
| BM25 `k1`, `b` | 1.2, 0.75 | **Attempted in Phase 8** (`scripts/tune_bm25_params.py`) — see below for why the result wasn't deployed | Yes, unchanged |
| `ranking.py` `BM25_WEIGHT` / `PAGERANK_WEIGHT` | 0.85 / 0.15 | Fitting attempted (`scripts/train_ranker.py`, Phase 7), result not deployed | Yes, still the original hand-set values |
| `ranking.py` `PHRASE_BOOST` | 2.0 | No — and *can't* be with current data (see below) | Yes |
| `semantic.py` `SEMANTIC_WEIGHT` | 0.7 (was 0.5) | Yes — grid-searched via `scripts/tune_semantic_weight.py` (Phase 7) | Yes |

## Two fitted results, both correctly declined for the same reason

**PageRank fusion weight (Phase 7).** `scripts/train_ranker.py` found `PAGERANK_WEIGHT → 0.0000` is optimal for `corpus.json`'s judgment set. Verified independently (direct relevant-vs-non-relevant PageRank comparison, ~noise-level) that this corpus's seeded-random link graph genuinely carries no relevance signal. Not deployed: the live system's PageRank (`app/cpp_index_reader.py`) is a completely different, real distribution this training run can't speak to.

**BM25 `k1`/`b` (Phase 8).** `scripts/tune_bm25_params.py` found `b=0.0` (fully disabling document-length normalization) marginally beats the baseline (nDCG@10 0.6379 vs. 0.6351). Not deployed, for a directly analogous reason: this corpus's document lengths have a coefficient of variation of **0.024** (325–384 tokens, deliberately uniform by construction — see `scripts/generate_corpus.py`), so there's essentially no real length variation here for `b` to legitimately learn from. A result favoring `b=0` says more about this corpus's artificial uniformity than about real, naturally length-varied web pages.

**The pattern worth internalizing:** a fitted result is only as trustworthy as the data it was fit against being representative of where it'll be deployed. Both of these are real, correct analyses that correctly conclude "don't ship this" — that's not a failure of the tuning scripts, it's what disciplined tuning against a synthetic-but-honestly-disclosed corpus should produce.

## Two more fitted results, against real data this time — one promising, one a real bias caught in the act (Phase 11)

**BM25 `k1`/`b`, real corpus (`scripts/tune_bm25_params_real.py`).** Found **k1=1.8, b=0.25** improves nDCG@10 from 0.4565 to 0.5484 (+20% relative) against 20 real judgment queries. Unlike the synthetic-corpus run, this doesn't hit the suspicious `b=0` edge case — this corpus has genuine document-length variation (6 to 239,065 tokens, nothing artificially uniform about it). A real, promising early signal. **Not yet deployed**: 20 queries is still a small sample to commit a production constant to, and this deserves a second, larger judgment set before shipping — noted as a real next step, not a rejection.

**BM25/PageRank fusion weight, real corpus (`scripts/train_ranker_real.py`).** Raw fit: `PAGERANK_WEIGHT = 0.5485` (vs. hand-set 0.15) — a striking result, and unlike the synthetic-corpus case, there was no obvious reason to distrust it on its face (the link graph is real). Checked anyway: the 14 documents this judgment set names as relevant (`docs.python.org`, `bbc.com`, MDN — domains picked largely because they were fast to verify against real content) have a mean PageRank **58x** the full 19,514-document corpus's mean, against a corpus whose *median* PageRank is exactly 0.0. That's confirmed selection bias in the judgment set, not a subtle judgment call — the fitted weight reflects "did the judge recognize this domain as reputable," not "does PageRank predict relevance." **Not deployed.** The bias check is now a permanent, automated part of `train_ranker_real.py` (`check_judgment_set_pagerank_bias()`), not a one-off note — any future judgment set built the same way (recognize a domain → trust it → pick it) would trip the same check.

**Why this is the most valuable finding in this file, not a failure:** the fitting *pipeline* did exactly what it should — surface a striking number, then get checked against an independent measurement before being trusted. It happened to find a flaw in this round's judgment-set construction, not in the model or the app. The fix is concrete: rebuild the judgment set including verified-relevant documents from lower-authority sources on purpose, not just whatever was fastest to check against real content.

## Two real bugs, closed this session (Phase 8), on top of Phase 7's parser fixes

1. **The semantic path's residual spellcheck bias — closed.** Previously: the query embedding used raw text, but retrieval for the "head" being reranked still ran on the *corrected* query. Fixed: `rerank=true` now uses the raw query throughout. Found to matter immediately: a live query ("ways machines can learn from data") produced a nonsensical "did you mean: bas machines a4 learn from aa?" — `did_you_mean` is now suppressed entirely when `rerank=true`, since showing an unapplied correction would be actively misleading.
2. **A `semantic_rerank()` crash on empty pools — fixed.** When both the BM25 candidate pool and the augmentation pool are empty, the function now returns gracefully instead of raising `ValueError`.

**If you touch `query_parser.py`, `spellcheck.py`, or `semantic.py` again: re-run `scripts/evaluate.py` before and after, every time.** Both of Phase 7's and Phase 8's real bugs were caught exactly this way — a fix for one thing quietly breaking something else, only visible by re-measuring, not by reasoning about the change in isolation.

## Measured evaluation numbers (current, all fixes + doubled judgment set)

`scripts/evaluate.py`, now against **40 judgment queries** (doubled from 20 in Phase 8 — same programmatic methodology, every new lexical phrase confirmed present in the corpus before being added):

| | Precision@10 | MRR | nDCG@10 |
|---|---|---|---|
| BM25-only (overall) | 0.555 | 0.668 | 0.631 |
| BM25+semantic (overall) | 0.730 | 0.917 | 0.819 |
| BM25-only (lexical subset) | 0.540 | 0.777 | 0.698 |
| BM25+semantic (lexical subset) | 0.540 | 0.883 | 0.712 |
| BM25-only (semantic subset) | 0.570 | 0.560 | 0.564 |
| BM25+semantic (semantic subset) | 0.920 | 0.950 | 0.925 |

Broadly consistent with the 20-query numbers, now backed by 2x the sample. One new, honestly disclosed miss: "professional athletes competing in games" scores 0.000 under both modes — surfaced in the per-query table and `data/evaluation_results.json`, not smoothed over.

## Measured evaluation numbers — the REAL corpus, real independent judgments (Phase 11)

`scripts/evaluate_real.py`, 20 hand-verified queries (10 lexical, 10 semantic) against real documents in the real 19,514-document corpus — genuinely independent ground truth, not corpus-generation metadata (there is none; this is real crawled web content):

| | Precision@10 | MRR | nDCG@10 |
|---|---|---|---|
| BM25-only (overall) | 0.073 | 0.434 | 0.457 |
| BM25+semantic (overall) | 0.080 | 0.615 | 0.629 |
| BM25-only (lexical subset) | 0.105 | 0.596 | 0.618 |
| BM25+semantic (lexical subset) | 0.110 | 0.867 | 0.886 |
| BM25-only (semantic subset) | 0.040 | 0.271 | 0.295 |
| BM25+semantic (semantic subset) | 0.050 | 0.363 | 0.372 |

Semantic re-ranking still clearly helps (MRR +42% overall) — but the effect is far more modest than the synthetic corpus's numbers ever suggested (there, the semantic subset improved to ~0.95 nDCG; here, ~0.37). This is the real, honest headline: **the synthetic corpus was measuring something meaningfully easier than real retrieval over 19,514 diverse, noisy documents.** Several harder paraphrase queries scored 0.000 on both modes — spot-checked one directly (a sea-turtle article paraphrase) and confirmed it's not a bug: augmentation correctly finds real animal/wildlife-topic content, several nature blogs just outrank the intended target by pure embedding similarity at this scale. Concrete, first-hand evidence for why cross-encoder re-ranking is the top item below, not a theoretical argument for it.

## What's genuinely still missing

- ~~Independent ground truth~~ — **exists now (Phase 11).** 20 real, hand-verified judgments over the real corpus — genuinely independent, not circular. What's *not* resolved: this judgment set has a confirmed selection bias toward high-authority domains (see above), which specifically blocks trusting the PageRank fusion re-fit. A second, bias-corrected judgment set (deliberately including relevant-but-low-authority pages) is the concrete next step, not a return to "blocked."
- **Cross-encoder re-ranking.** Now backed by direct evidence of real bi-encoder misses at scale (see above), not just the general argument that cross-encoders usually help. The highest-leverage remaining item.
- **ANN indexing.** Not attempted yet — see `roadmap.md`; now also motivated by measured latency (real `rerank=true` queries take ~3s against 19,514 docs).
- ~~No interaction/click-data logging~~ — **the plumbing now exists** (`POST /feedback/click`, wired into the frontend, Phase 8). Nothing consumes it yet — no persistence layer, no click-derived feature in `train_ranker.py`. The gap moved from "no signal exists" to "a real signal exists with nothing built on top of it yet."
