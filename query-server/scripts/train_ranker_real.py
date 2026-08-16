"""train_ranker.py, run against the REAL crawled corpus + real, hand-verified
judgments (scripts/evaluate_real.py) instead of the synthetic data/corpus.json.

Why this is the actual point of this whole exercise, not just a variant: the
original train_ranker.py's headline finding -- PAGERANK_WEIGHT should be
~0 -- was explicitly NOT deployed, for one specific, disclosed reason: the
synthetic corpus's link graph is seeded-random by construction, so of course
PageRank carried no relevance signal there. That was always a statement about
the synthetic corpus, not about the live system's real PageRank. This script
is the actual test of that live system: real PageRank (computed by
crawler/ranking/pagerank.py's power iteration over the real, 3.5M-edge
crawled link graph), scored against real relevance judgments over the same
real documents. Whatever this finds is no longer deflectable as "the
synthetic corpus's fault" -- it's real evidence about whether this project's
real PageRank signal is worth its current 0.15 weight.

Same non-negativity constraint as the original, for the same reason: a
fitted result should reflect a real finding, not get free rein to fit noise
in a small judgment set (only 20 queries here too -- a real, disclosed
sample-size caveat that doesn't go away just because the corpus is real).

Reuses extract_training_examples() from train_ranker.py completely
unchanged -- it only depends on the shape of `ctx` and `judgments`.
"""
import json
import statistics
from pathlib import Path

from sklearn.linear_model import Ridge

from scripts.evaluate_real import build_real_context, build_real_judgments
from scripts.train_ranker import extract_training_examples


def check_judgment_set_pagerank_bias(ctx: dict, judgments: list) -> dict:
    """Direct, independent check for the exact failure mode this run is
    otherwise vulnerable to: a hand-built judgment set that (even
    unintentionally) skews toward well-known, high-authority domains would
    make PageRank look like a strong relevance signal for a reason that has
    nothing to do with relevance -- it would just mean "the judge recognized
    this domain as reputable," not "PageRank predicts what users want."

    Run once, on the first real attempt at this: the 14 documents this
    judgment set names as relevant (python.org, MDN, BBC -- domains picked
    largely because they were fast to verify against real content) had a
    mean PageRank 58x the full corpus's mean, against a corpus whose median
    PageRank is 0.0. That's not a subtle effect -- it's confirmed selection
    bias, not a borderline judgment call, and it directly explains an
    otherwise-surprising fitted PAGERANK_WEIGHT. Kept as a permanent, automated
    check rather than a one-off note, since any future judgment set built by
    a similar process (recognize a domain -> trust it -> pick it as relevant)
    would have the same flaw.
    """
    relevant_ids = set()
    for judgment in judgments:
        relevant_ids |= judgment["relevant_ids"]

    pagerank_norm = ctx["pagerank_norm"]
    relevant_scores = [pagerank_norm.get(d, 0.0) for d in relevant_ids]
    all_scores = list(pagerank_norm.values())

    relevant_mean = statistics.mean(relevant_scores) if relevant_scores else 0.0
    corpus_mean = statistics.mean(all_scores) if all_scores else 0.0
    ratio = relevant_mean / corpus_mean if corpus_mean > 0 else float("inf")

    return {
        "num_relevant_docs": len(relevant_ids),
        "relevant_docs_mean_pagerank": relevant_mean,
        "corpus_mean_pagerank": corpus_mean,
        "corpus_median_pagerank": statistics.median(all_scores) if all_scores else 0.0,
        "relevant_vs_corpus_ratio": ratio,
        "likely_selection_bias": ratio > 5.0,  # an arbitrary but generous threshold --
        # real relevant documents being somewhat more authoritative than a random
        # page is plausible; 58x (the actual measured value) is not a borderline
        # case under any reasonable threshold.
    }


def main():
    print("Building the real corpus + real judgment set (reusing scripts/evaluate_real.py)...")
    ctx = build_real_context()
    judgments = build_real_judgments()

    bias_check = check_judgment_set_pagerank_bias(ctx, judgments)
    print(f"\nJudgment-set PageRank bias check: relevant docs' mean PageRank is "
          f"{bias_check['relevant_vs_corpus_ratio']:.1f}x the corpus mean "
          f"(corpus median: {bias_check['corpus_median_pagerank']:.2e}).")
    if bias_check["likely_selection_bias"]:
        print("  >>> LIKELY SELECTION BIAS: this judgment set's relevant documents are "
              "drawn disproportionately from high-PageRank (high-authority) pages. Any "
              "fitted PAGERANK_WEIGHT below is confounded by this and should NOT be "
              "deployed without a bias-corrected judgment set (one that includes "
              "genuinely relevant documents from lower-authority sources too).")

    X, y = extract_training_examples(ctx, judgments)
    n_positive = sum(y)
    print(f"\n{len(X)} training examples from {len(judgments)} judgment queries "
          f"({n_positive} relevant, {len(X) - n_positive} not relevant)")

    if n_positive == 0 or n_positive == len(y):
        print("\nDegenerate label distribution (all-positive or all-negative) -- "
              "cannot fit anything meaningful. Keeping the original 0.85/0.15 split.")
        return

    n = len(y)
    n_pos, n_neg = n_positive, n - n_positive
    sample_weight = [n / (2 * n_pos) if label else n / (2 * n_neg) for label in y]

    model = Ridge(positive=True, alpha=1.0, random_state=42)
    model.fit(X, y, sample_weight=sample_weight)

    raw_bm25_weight, raw_pagerank_weight = model.coef_
    print(f"\nRaw fitted coefficients: bm25={raw_bm25_weight:.4f}, pagerank={raw_pagerank_weight:.4f}")

    weight_sum = raw_bm25_weight + raw_pagerank_weight
    if weight_sum > 0:
        bm25_weight = raw_bm25_weight / weight_sum
        pagerank_weight = raw_pagerank_weight / weight_sum
    else:
        print("\nBoth coefficients fit to ~0 -- no usable signal found; keeping the "
              "original 0.85/0.15 split rather than deploying a degenerate result.")
        bm25_weight, pagerank_weight = 0.85, 0.15

    print("\nFitted fusion weights (replacing ranking.py's hand-set BM25_WEIGHT/PAGERANK_WEIGHT):")
    print(f"  BM25_WEIGHT      = {bm25_weight:.4f}   (was 0.85, hand-set)")
    print(f"  PAGERANK_WEIGHT  = {pagerank_weight:.4f}   (was 0.15, hand-set)")

    if bias_check["likely_selection_bias"]:
        print(f"\nPageRank's fitted weight ({pagerank_weight:.4f}) is NOT trustworthy as "
              f"measured -- confirmed confounded by this judgment set's selection bias "
              f"(see the check above). This is the same discipline that correctly declined "
              f"the synthetic corpus's PageRank finding, applied to a different but equally "
              f"real problem: an unrepresentative judgment set, not an unrepresentative "
              f"link graph. NOT recommended for deployment.")
    elif raw_pagerank_weight <= 1e-6:
        print("\nPageRank's fitted weight is ~0 here too -- but this time that's a "
              "statement about the REAL crawled link graph and REAL judgments, not "
              "a synthetic corpus's seeded-random construction. Worth taking more "
              "seriously than the earlier result, though still only 20 queries --  "
              "see this run's docstring and docs-ml/current-state.md before treating "
              "this as final.")
    else:
        print(f"\nPageRank's fitted weight is meaningfully non-zero ({pagerank_weight:.4f}) "
              f"against real data, and the bias check above didn't flag it -- still worth "
              f"independent verification before deploying, same discipline as every other "
              f"fitted result in this project.")

    out = {
        "bm25_weight": round(float(bm25_weight), 4),
        "pagerank_weight": round(float(pagerank_weight), 4),
        "raw_coefficients": {
            "bm25": round(float(raw_bm25_weight), 4),
            "pagerank": round(float(raw_pagerank_weight), 4),
        },
        "trained_on": "the REAL crawled corpus (data/index.bin + crawler.db, 19,514 docs) "
                       "and scripts/evaluate_real.py's hand-verified judgment set -- 20 "
                       "queries, real documents, real relevance judgments (not "
                       "programmatically derived from corpus-generation metadata)",
        "training_examples": len(X),
        "positive_examples": n_positive,
        "method": "sklearn.linear_model.Ridge(positive=True, alpha=1.0), balanced sample "
                  "weights, coefficients renormalized to sum to 1.",
        "pagerank_bias_check": bias_check,
        "deployment_recommendation": (
            "NOT recommended -- judgment set exhibits confirmed selection bias toward "
            "high-authority domains (relevant docs' mean PageRank is "
            f"{bias_check['relevant_vs_corpus_ratio']:.0f}x the corpus mean), which "
            "directly inflates PageRank's apparent importance independent of whether "
            "it actually predicts relevance. Needs a bias-corrected judgment set before "
            "this weight is trustworthy."
        ) if bias_check["likely_selection_bias"] else (
            "Not yet deployed -- independent verification recommended first, "
            "consistent with every other fitted result in this project."
        ),
    }
    out_path = Path(__file__).resolve().parent.parent / "data" / "ranker_weights_real.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"\nWeights written to {out_path}. This is a one-off analysis script, not a "
          f"runtime dependency -- copy into app/ranking.py by hand if you decide to deploy it.")


if __name__ == "__main__":
    main()
