"""tune_bm25_params.py, run against the REAL crawled corpus + real,
hand-verified judgments (scripts/evaluate_real.py) instead of the synthetic
data/corpus.json.

Why this matters more here than it did for the synthetic corpus: the
synthetic corpus's document lengths were deliberately uniform by construction
(coefficient of variation 0.024), which is exactly the kind of corpus
property that made the earlier k1/b tuning result untrustworthy -- a "b=0.0
wins" finding on a corpus with no real length variation says nothing about
whether that generalizes. The real crawled corpus has none of that
artificial uniformity (document lengths range from 6 to 239,065 tokens,
spanning single-line stub pages to a 1.7MB list page) -- so a result here is
evidence about something real, not an artifact of how the evaluation data
happened to be built. Still measured on BM25-only metrics, for the same
reason as the original: semantic re-ranking can mask a BM25 regression.

Reuses search_with_params() and evaluate_params() from tune_bm25_params.py
completely unchanged -- both only depend on the shape of `ctx` and
`judgments`, not on which corpus built them.
"""
from app.bm25 import B, K1
from scripts.evaluate_real import build_real_context, build_real_judgments
from scripts.tune_bm25_params import B_CANDIDATES, K1_CANDIDATES, evaluate_params


def main():
    print("Building the real corpus + real judgment set (reusing scripts/evaluate_real.py)...")
    ctx = build_real_context()
    judgments = build_real_judgments()

    baseline = evaluate_params(ctx, judgments, K1, B)
    print(f"\nBaseline (k1={K1}, b={B}): "
          f"P@10={baseline['p10']:.4f}  MRR={baseline['mrr']:.4f}  nDCG@10={baseline['ndcg']:.4f}")

    print(f"\n{'k1':>6} {'b':>6} {'P@10':>8} {'MRR':>8} {'nDCG@10':>8}")
    results = []
    for k1 in K1_CANDIDATES:
        for b in B_CANDIDATES:
            metrics = evaluate_params(ctx, judgments, k1, b)
            results.append((k1, b, metrics))
            print(f"{k1:>6.2f} {b:>6.2f} {metrics['p10']:>8.4f} {metrics['mrr']:>8.4f} {metrics['ndcg']:>8.4f}")

    best = max(results, key=lambda r: r[2]["ndcg"])
    print(f"\nBest by nDCG@10: k1={best[0]}, b={best[1]} "
          f"(nDCG@10={best[2]['ndcg']:.4f} vs baseline {baseline['ndcg']:.4f})")
    if best[2]["ndcg"] <= baseline["ndcg"]:
        print("No improvement over the current k1/b -- keeping them as-is. Against a "
              "corpus with genuine length variation, this is a real, meaningful "
              "negative result, not an artifact of a deliberately-uniform corpus.")
    else:
        improvement = best[2]["ndcg"] - baseline["ndcg"]
        print(f"Improvement of {improvement:.4f} nDCG@10 over the current k1/b, "
              f"measured against real document-length variation this time -- "
              f"a materially more trustworthy signal than the synthetic-corpus "
              f"result. Still: only {len(judgments)} judgment queries here; treat "
              f"this as a real, disclosed early signal, not a large-sample result.")
        print("Update K1/B in app/bm25.py by hand to these values if you want "
              "to deploy this -- this script is a one-off analysis, not a "
              "runtime dependency.")


if __name__ == "__main__":
    main()
