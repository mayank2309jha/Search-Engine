# Test & benchmark results — Phase 11, full detail

Raw experiment log for the ML-side work: building real, independent ground truth over the real
crawled corpus, then using it to evaluate and fit parameters. `current-state.md` summarizes
conclusions; this file is the underlying evidence — full per-query results, the full grid search,
and the full bias-check numbers. Companion to `../docs-sde/benchmarks-phase11-12.md` (the
SDE-side verification work from the same session).

## 1. Judgment set — methodology and full query list

20 queries (10 lexical, 10 semantic) against real documents in the real 19,514-document corpus
(`data/index.bin` + `crawler.db`). Built by reading real page content directly via `sqlite3`
queries against `crawler.db` (title *and* a content excerpt, not title alone), then cross-checked
for near-duplicate or wrong-topic pages sharing surface vocabulary — e.g. a `LIKE '%Messi%'` query
against `crawler.db` surfaced several unrelated pages about a place called "Messinias"; confirmed
irrelevant by reading their content, excluded, not assumed absent.

Full judgment set (`scripts/evaluate_real.py`'s `build_real_judgments()`):

| Query | Type | Relevant doc_id(s) | Target page |
|---|---|---|---|
| python 3.14 new features | lexical | 24 | "What's new in Python 3.14" |
| python enhancement proposals index | lexical | 47 | "PEP 0 – Index of Python Enhancement Proposals" |
| python glossary | lexical | 44 | "Glossary — Python 3.14.7 documentation" |
| python deprecations | lexical | 36 | "Deprecations — Python 3.14.7 documentation" |
| python module index | lexical | 75 | "Python Module Index" |
| css cascading style sheets | lexical | 63, 681 | "CSS: Cascading Style Sheets \| MDN"; "CSS Zen Garden" |
| webassembly | lexical | 70 | "WebAssembly \| MDN" |
| http hypertext transfer protocol | lexical | 72 | "HTTP: Hypertext Transfer Protocol \| MDN" |
| eurovision song contest rules | lexical | 107 | "Eurovision Song Contest changes rules for countries at war" |
| messi inter miami | lexical | 103 | "Lionel Messi makes substitute appearance for Inter Miami..." |
| changing how a webpage looks visually | semantic | 63, 681 | (CSS page — paraphrase avoids "css"/"style"/"sheets") |
| sending information between a web browser and a server | semantic | 72 | (HTTP page — avoids "http"/"hypertext"/"transfer"/"protocol") |
| keeping web apps safe from bad actors online | semantic | 65 | "Security \| MDN" — avoids "protecting"/"malicious"/"attackers" despite those exact words appearing in the page's own text |
| singing competition among countries in europe | semantic | 107 | (Eurovision — avoids "eurovision"/"song"/"contest") |
| a famous footballer playing again after family loss | semantic | 103 | (Messi — avoids "father"/"death", uses "footballer" not "soccer star") |
| a reptile's very long trip back to its home | semantic | 98 | "Watch: Endangered sea turtle makes 5,000-mile journey..." — avoids "endangered"/"turtle"/"journey"/place names entirely |
| assembling programs to run fast inside a browser | semantic | 70 | (WebAssembly — avoids the term itself) |
| articles about staying fit and living longer | semantic | 109 | "BBC Health \| Nutrition, Exercise, Relationships, Sleep, Longevity" — avoids "exercise"/"sleep"/"nutrition"/"longevity" despite those being the page's own title words |
| python's built-in dictionary of technical terms | semantic | 44 | (Glossary — avoids "glossary") |
| features being phased out in a programming language | semantic | 36 | (Deprecations — avoids "python"/"deprecat*" entirely, a deliberately hard test) |

Two honest methodology limits, disclosed in `scripts/evaluate_real.py`'s own docstring: this is
single-judge (one read-through per query, not multi-rater consensus), and relevant-document sets
were found by searching for likely candidates by domain/title pattern, not by exhaustively reading
all 19,514 documents (standard IR "pooling" practice — a real but disclosed limit, not hidden).

## 2. Full per-query results

`scripts/evaluate_real.py`, run against the live corpus. `n` = number of results the query mode
returned in total (before the P@10/MRR/nDCG@10 cutoff).

| Query | Type | Rel. | BM25 P@10 | BM25 MRR | BM25 nDCG | BM25 n | Sem P@10 | Sem MRR | Sem nDCG | Sem n |
|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| python 3.14 new features | lex | 1 | 0.100 | 0.250 | 0.431 | 13864 | 0.100 | 0.500 | 0.631 | 13879 |
| python enhancement proposals index | lex | 1 | 0.100 | 0.125 | 0.315 | 813 | 0.100 | 1.000 | 1.000 | 828 |
| python glossary | lex | 1 | 0.000 | 0.040 | 0.000 | 136 | 0.100 | 1.000 | 1.000 | 151 |
| python deprecations | lex | 1 | 0.100 | 0.500 | 0.631 | 119 | 0.100 | 1.000 | 1.000 | 134 |
| python module index | lex | 1 | 0.000 | 0.045 | 0.000 | 516 | 0.100 | 0.167 | 0.356 | 531 |
| css cascading style sheets | lex | 2 | 0.200 | 1.000 | 0.807 | 1396 | 0.200 | 1.000 | 0.877 | 1411 |
| webassembly | lex | 1 | 0.250 | 1.000 | 1.000 | 4 | 0.100 | 1.000 | 1.000 | 19 |
| http hypertext transfer protocol | lex | 1 | 0.100 | 1.000 | 1.000 | 4572 | 0.100 | 1.000 | 1.000 | 4587 |
| eurovision song contest rules | lex | 1 | 0.100 | 1.000 | 1.000 | 1266 | 0.100 | 1.000 | 1.000 | 1281 |
| messi inter miami | lex | 1 | 0.100 | 1.000 | 1.000 | 600 | 0.100 | 1.000 | 1.000 | 615 |
| changing how a webpage looks visually | sem | 2 | 0.000 | 0.033 | 0.000 | 3474 | 0.100 | 0.167 | 0.218 | 3489 |
| sending information between a browser and a server | sem | 1 | 0.100 | 1.000 | 1.000 | 3799 | 0.100 | 1.000 | 1.000 | 3814 |
| keeping web apps safe from bad actors online | sem | 1 | 0.000 | 0.001 | 0.000 | 5546 | 0.000 | 0.001 | 0.000 | 5561 |
| singing competition among countries in europe | sem | 1 | 0.100 | 0.500 | 0.631 | 1815 | 0.100 | 1.000 | 1.000 | 1830 |
| a famous footballer playing again after family loss | sem | 1 | 0.100 | 0.125 | 0.315 | 2819 | 0.100 | 0.333 | 0.500 | 2834 |
| a reptile's very long trip back to its home | sem | 1 | 0.000 | 0.001 | 0.000 | 7551 | 0.000 | 0.001 | 0.000 | 7566 |
| assembling programs to run fast inside a browser | sem | 1 | 0.000 | 0.019 | 0.000 | 2904 | 0.000 | 0.015 | 0.000 | 2919 |
| articles about staying fit and living longer | sem | 1 | 0.000 | 0.034 | 0.000 | 3685 | 0.000 | 0.043 | 0.000 | 3700 |
| python's built-in dictionary of technical terms | sem | 1 | 0.100 | 1.000 | 1.000 | 1400 | 0.100 | 1.000 | 1.000 | 1415 |
| features being phased out in a programming language | sem | 1 | 0.000 | 0.000 | 0.000 | 2450 | 0.000 | 0.067 | 0.000 | 2465 |

**Aggregates** (mean across the relevant subset):

| Subset | Mode | P@10 | MRR | nDCG@10 |
|---|---|--:|--:|--:|
| Overall (n=20) | BM25-only | 0.0725 | 0.4337 | 0.4565 |
| Overall (n=20) | BM25+semantic | 0.0800 | 0.6147 | 0.6291 |
| Lexical (n=10) | BM25-only | 0.1050 | 0.5960 | 0.6184 |
| Lexical (n=10) | BM25+semantic | 0.1100 | 0.8667 | 0.8864 |
| Semantic (n=10) | BM25-only | 0.0400 | 0.2714 | 0.2946 |
| Semantic (n=10) | BM25+semantic | 0.0500 | 0.3627 | 0.3718 |

**Reading the misses honestly:** 4 of 20 queries scored 0.000 on *both* modes (`keeping web apps safe...`, `a reptile's very long trip...`, `assembling programs to run fast...`, `articles about staying fit...`). Spot-checked the turtle query directly — `curl` against the live `rerank=true` endpoint — and confirmed it's not a bug: augmentation correctly retrieves real animal/wildlife-topic pages (a "Centre for Animal Movement Research" blog, a "Birds in my Garden" blog, "WILDLIFE GATEWAY") that genuinely score higher cosine similarity to the paraphrase than the intended turtle article does, in a corpus this large and topically diverse. Direct, first-hand evidence for why cross-encoder re-ranking (not just bi-encoder similarity) is the top item in `roadmap.md`.

## 2b. Comparison: real corpus vs. the synthetic corpus's numbers

| | Synthetic corpus (40 queries) | Real corpus (20 queries) |
|---|--:|--:|
| Semantic-subset BM25-only nDCG@10 | 0.564 | 0.295 |
| Semantic-subset BM25+semantic nDCG@10 | 0.925 | 0.372 |
| Semantic-subset relative improvement | +64% | +26% |

The real corpus is a meaningfully harder, noisier test — not because anything is broken, but
because 19,514 diverse real documents give a bi-encoder far more plausible near-neighbors to
confuse than a small, topically-clean synthetic corpus does. This is the honest, headline
methodological finding of this experiment: **the synthetic corpus's evaluation numbers were
measuring something easier than real retrieval**, and that gap is now quantified rather than
suspected.

## 3. BM25 `k1`/`b` grid search — full results

`scripts/tune_bm25_params_real.py`. Baseline (current production values): **k1=1.2, b=0.75** →
P@10=0.0725, MRR=0.4337, nDCG@10=0.4565.

| k1 | b | P@10 | MRR | nDCG@10 |
|--:|--:|--:|--:|--:|
| 0.80 | 0.00 | 0.0725 | 0.4405 | 0.4690 |
| 0.80 | 0.25 | 0.0725 | 0.5197 | 0.5250 |
| 0.80 | 0.50 | 0.0825 | 0.4507 | 0.4973 |
| 0.80 | 0.75 | 0.0775 | 0.4090 | 0.4509 |
| 0.80 | 1.00 | 0.0675 | 0.4289 | 0.4385 |
| 1.00 | 0.00 | 0.0725 | 0.4448 | 0.4720 |
| 1.00 | 0.25 | 0.0725 | 0.5255 | 0.5290 |
| 1.00 | 0.50 | 0.0825 | 0.4515 | 0.4980 |
| 1.00 | 0.75 | 0.0725 | 0.4334 | 0.4565 |
| 1.00 | 1.00 | 0.0675 | 0.4566 | 0.4592 |
| 1.20 | 0.00 | 0.0725 | 0.4449 | 0.4727 |
| 1.20 | 0.25 | 0.0775 | 0.5266 | 0.5434 |
| 1.20 | 0.50 | 0.0825 | 0.4515 | 0.4980 |
| **1.20** | **0.75 (baseline/current)** | **0.0725** | **0.4337** | **0.4565** |
| 1.20 | 1.00 | 0.0675 | 0.4561 | 0.4585 |
| 1.40 | 0.00 | 0.0725 | 0.4450 | 0.4737 |
| 1.40 | 0.25 | 0.0775 | 0.5278 | 0.5454 |
| 1.40 | 0.50 | 0.0825 | 0.4766 | 0.5170 |
| 1.40 | 0.75 | 0.0725 | 0.4332 | 0.4558 |
| 1.40 | 1.00 | 0.0675 | 0.4601 | 0.4613 |
| 1.60 | 0.00 | 0.0725 | 0.4450 | 0.4737 |
| 1.60 | 0.25 | 0.0775 | 0.5290 | 0.5473 |
| 1.60 | 0.50 | 0.0825 | 0.4848 | 0.5242 |
| 1.60 | 0.75 | 0.0725 | 0.4339 | 0.4570 |
| 1.60 | 1.00 | 0.0675 | 0.4352 | 0.4429 |
| **1.80** | **0.25 (best by nDCG@10)** | **0.0775** | **0.5301** | **0.5484** |
| 1.80 | 0.00 | 0.0725 | 0.4449 | 0.4737 |
| 1.80 | 0.50 | 0.0825 | 0.4598 | 0.5067 |
| 1.80 | 0.75 | 0.0725 | 0.4599 | 0.4764 |
| 1.80 | 1.00 | 0.0675 | 0.4353 | 0.4434 |
| 2.00 | 0.00 | 0.0725 | 0.4450 | 0.4737 |
| 2.00 | 0.25 | 0.0775 | 0.5301 | 0.5484 |
| 2.00 | 0.50 | 0.0825 | 0.4473 | 0.4967 |
| 2.00 | 0.75 | 0.0725 | 0.4611 | 0.4782 |
| 2.00 | 1.00 | 0.0675 | 0.4358 | 0.4441 |

**Best: k1=1.8, b=0.25** — nDCG@10 0.5484 vs. baseline 0.4565 (+20.1% relative). Note `b=0.25` won at
both k1=1.8 *and* k1=2.0 identically (0.5484 both times) — a plateau, not a single sharp optimum,
which is itself a useful signal about how much to trust the exact k1 value vs. the general
direction (lower `b` than the 0.75 default helps this corpus).

**Why this result is more trustworthy than the synthetic-corpus one:** the synthetic corpus's
document lengths have a coefficient of variation of 0.024 (deliberately near-uniform by
construction), so its own `b=0.0`-wins finding couldn't be trusted — there was no real length
variation for `b` to legitimately learn from. This corpus's lengths range from 6 to 239,065 tokens
(coefficient of variation computed separately, but the raw range alone rules out the "artificially
uniform" failure mode). **Not yet deployed** — 20 queries is still a small sample for a production
constant; see `roadmap.md`.

## 4. BM25/PageRank fusion weight fit — full results and the bias check

`scripts/train_ranker_real.py`. Training set: 58,729 (query, candidate) pairs from the 20
judgment queries, 21 positive (relevant) examples, 58,708 negative.

**Bias check (`check_judgment_set_pagerank_bias()`), run first, before the fit:**

| Metric | Value |
|---|---|
| Relevant documents (deduplicated across all 20 queries) | 14 |
| Relevant docs' mean PageRank | 0.0003986 (raw) |
| Corpus mean PageRank | 0.0000068 (raw) |
| Corpus median PageRank | 0.0 |
| Ratio (relevant mean ÷ corpus mean) | **58.24x** |
| `likely_selection_bias` flag | **True** (threshold: >5x) |

**Fit result** (`sklearn.linear_model.Ridge(positive=True, alpha=1.0)`, balanced sample weights):

| | Raw coefficient | Renormalized weight | Current production value |
|---|--:|--:|--:|
| BM25 | 0.7419 | 0.4515 | 0.85 |
| PageRank | 0.9012 | 0.5485 | 0.15 |

**Conclusion: not deployed.** The bias check's own numbers make the reasoning mechanical, not a
judgment call: a PageRank weight fit against a judgment set whose "relevant" documents are 58x
more authoritative than a random corpus document, by construction, cannot be distinguished from a
weight that's simply learned "the judge liked well-known domains." The fitted 0.5485 is real
arithmetic, correctly computed, and not evidence about whether PageRank predicts relevance in
general. Full JSON output, including this bias-check payload, is written to
`data/ranker_weights_real.json` on every run — reproducible, not just asserted here.

**What would actually unblock this:** a second judgment set built with an explicit rule to include
relevant-but-obscure documents (e.g. requiring at least some queries whose correct answer is a
low-traffic blog or a niche page, not just recognized institutional domains), then re-running
`train_ranker_real.py` and checking whether the bias ratio drops below the 5x threshold before
trusting whatever PageRank weight comes out.

## 5. Reproducing these results

```bash
cd query-server
PYTHONPATH=. python scripts/evaluate_real.py          # full per-query table + summary, ~90s
PYTHONPATH=. python scripts/tune_bm25_params_real.py   # full k1/b grid, ~95s
PYTHONPATH=. python scripts/train_ranker_real.py       # fusion fit + bias check, ~80s
```
All three require `data/index.bin` and (optionally, for real snippets/titles feeding the spellcheck
dictionary) `crawler.db` to be present at the paths `app/main.py` itself uses — see
`../docs-sde/architecture.md` for the exact path convention.
