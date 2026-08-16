"""Phase 8: grid-searches BM25's k1/b against the evaluation judgment set.
k1=1.2, b=0.75 were copied from a teammate's C++ reference (standard Lucene/
Elasticsearch defaults), never validated against this project's own data.

Unlike ranking.py's BM25/PageRank fusion weight (see train_ranker.py's
docstring for the full reasoning), k1/b are safe to tune against the
synthetic corpus and expect the result to transfer to live serving: they
govern how BM25 itself turns term frequency and document length into a
relevance score -- a property of the scoring function, not of this corpus's
specific fabricated link graph. Real term frequencies and real document
lengths behave the same way regardless of which corpus produced them.

Measured on BM25-ONLY metrics deliberately, not BM25+semantic -- semantic
re-ranking can mask a BM25 regression by fixing it back up, which would defeat
the point of isolating what k1/b actually contribute.
"""
from app.bm25 import B, K1, score_candidates
from app.index import retrieve_candidates
from app.query_parser import parse_query
from app.ranking import BM25_WEIGHT, PAGERANK_WEIGHT, _normalize
from app.spellcheck import correct_query
from app.validation import validate_query
from scripts.evaluate import (
    build_context, build_judgments, mrr, ndcg_at_k, precision_at_k,
)

K1_CANDIDATES = [0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0]
B_CANDIDATES = [0.0, 0.25, 0.5, 0.75, 1.0]


def search_with_params(query: str, ctx: dict, k1: float, b: float) -> list:
    """search_bm25_only(), parameterized by k1/b instead of the module defaults."""
    if validate_query(query):
        return []
    correction = correct_query(query, ctx["sym_spell"])
    if correction["unknown_words"]:
        return []
    search_query = correction["corrected_query"] if correction["suggestions"] else query
    structured = parse_query(search_query)
    if not any([structured["required"], structured["optional"], structured["phrases"]]):
        return []
    candidate_ids = retrieve_candidates(structured, ctx["docs"], ctx["inverted_index"])
    if not candidate_ids:
        return []

    query_terms = structured["required"] + structured["optional"]
    raw_bm25 = score_candidates(
        candidate_ids, query_terms, ctx["inverted_index"], ctx["doc_lengths"],
        ctx["avg_doc_length"], ctx["total_docs_count"], k1=k1, b=b)
    bm25_norm = _normalize(raw_bm25)

    # PageRank fusion mirrors ranking.py's real weights, so this measures what
    # actually reaches a user, not BM25 in isolation from the formula it's part of
    scores = {
        doc_id: BM25_WEIGHT * bm25_norm.get(doc_id, 0.0)
        + PAGERANK_WEIGHT * ctx["pagerank_norm"].get(doc_id, 0.0)
        for doc_id in candidate_ids
    }
    return sorted(candidate_ids, key=lambda d: (-scores[d], d))


def evaluate_params(ctx: dict, judgments: list, k1: float, b: float) -> dict:
    rows = []
    for judgment in judgments:
        ranked = search_with_params(judgment["query"], ctx, k1, b)
        rows.append({
            "p10": precision_at_k(ranked, judgment["relevant_ids"]),
            "mrr": mrr(ranked, judgment["relevant_ids"]),
            "ndcg": ndcg_at_k(ranked, judgment["relevant_ids"]),
        })
    n = len(rows)
    return {
        "p10": sum(r["p10"] for r in rows) / n,
        "mrr": sum(r["mrr"] for r in rows) / n,
        "ndcg": sum(r["ndcg"] for r in rows) / n,
    }


def main():
    print("Building index + judgment set (reusing scripts/evaluate.py)...")
    ctx = build_context()
    judgments = build_judgments(ctx["docs"])

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
        print("No improvement over the current k1/b -- keeping them as-is. "
              "A non-improving grid search is still a real result: it means "
              "index.cpp's ported defaults were already a reasonable choice "
              "for this corpus, not that the search failed.")
    else:
        print("Update K1/B in app/bm25.py by hand to these values if you want "
              "to deploy this -- this script is a one-off analysis, not a "
              "runtime dependency.")


if __name__ == "__main__":
    main()
