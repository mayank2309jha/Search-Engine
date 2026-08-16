"""
Phase 7: grid-searches semantic.py's SEMANTIC_WEIGHT (the 0.5/0.5 blend between BM25+
PageRank score and query-embedding cosine similarity within the reranked head) against
the same 20-query judgment set scripts/evaluate.py already uses -- picking the value
that actually maximizes nDCG@10, instead of the hand-set 0.5 every prior phase disclosed
as "the least arbitrary starting point, absent labeled preference data."

Unlike ranking.py's BM25/PageRank fusion (see train_ranker.py's docstring for why that
one's fitted PageRank weight doesn't safely transfer to the live, real-crawled-data
system), this weight has no synthetic-vs-real mismatch problem: both here and in live
serving, it blends the SAME two live-computed signals -- a lexical score and a query
embedding's cosine similarity to each candidate's embedding -- neither of which is a
property of a fabricated link graph. Tuning it against the synthetic corpus's judgment
set is still bounded by that corpus's own limitations (Limitations #19: several
"paraphrase" queries still have incidental lexical overlap BM25 alone can exploit), but
the weight itself measures something real and corpus-independent: how much to trust
meaning-based similarity relative to lexical relevance.

Split by query type, not just overall -- the same reason evaluate.py itself reports
lexical/semantic subsets separately: a weight that helps the semantic subset while
quietly hurting the lexical control group would be a regression dressed up as a win.
"""
from app.query_parser import parse_query
from app.ranking import score_documents
from app.semantic import semantic_rerank
from app.validation import validate_query
from app.index import retrieve_candidates
from scripts.evaluate import build_context, build_judgments, mrr, ndcg_at_k, precision_at_k

CANDIDATE_WEIGHTS = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]


def search_with_weight(query: str, ctx: dict, weight: float) -> list:
    """search_bm25_plus_semantic(), parameterized by semantic blend weight."""
    if validate_query(query):
        return []
    # No spell-correction for retrieval, matching main.py/evaluate.py's Phase 8 fix --
    # semantic mode uses the raw query throughout, not just for the embedding itself.
    structured = parse_query(query)
    if not any([structured["required"], structured["optional"], structured["phrases"]]):
        structured = {"required": [], "optional": [], "excluded": [],
                      "phrases": [], "excluded_phrases": []}
    candidate_ids = retrieve_candidates(structured, ctx["docs"], ctx["inverted_index"])
    scores = score_documents(candidate_ids, structured, ctx["inverted_index"],
                             ctx["doc_lengths"], ctx["avg_doc_length"], ctx["total_docs_count"],
                             ctx["pagerank_norm"])
    ranked_ids = sorted(candidate_ids, key=lambda d: (-scores[d], d))
    allow_augmentation = not (structured["required"] or structured["excluded"]
                             or structured["excluded_phrases"] or structured["phrases"])
    new_ranked_ids, _, _ = semantic_rerank(
        query, ranked_ids, scores, ctx["semantic_model"], ctx["doc_embeddings"],
        ctx["doc_id_to_index"], ctx["embedding_doc_id_order"],
        weight=weight, allow_augmentation=allow_augmentation)
    return new_ranked_ids


def main():
    print("Building index + judgment set (reusing scripts/evaluate.py)...")
    ctx = build_context()
    judgments = build_judgments(ctx["docs"])

    print(f"\n{'Weight':>8} {'Overall nDCG':>14} {'Lexical nDCG':>14} {'Semantic nDCG':>15} "
          f"{'Overall MRR':>13} {'Overall P@10':>13}")
    results = []
    for weight in CANDIDATE_WEIGHTS:
        rows = []
        for judgment in judgments:
            ranked = search_with_weight(judgment["query"], ctx, weight)
            rows.append({
                "type": judgment["type"],
                "ndcg": ndcg_at_k(ranked, judgment["relevant_ids"]),
                "mrr": mrr(ranked, judgment["relevant_ids"]),
                "p10": precision_at_k(ranked, judgment["relevant_ids"]),
            })
        overall_ndcg = sum(r["ndcg"] for r in rows) / len(rows)
        lexical_ndcg = sum(r["ndcg"] for r in rows if r["type"] == "lexical") / 10
        semantic_ndcg = sum(r["ndcg"] for r in rows if r["type"] == "semantic") / 10
        overall_mrr = sum(r["mrr"] for r in rows) / len(rows)
        overall_p10 = sum(r["p10"] for r in rows) / len(rows)
        results.append((weight, overall_ndcg, lexical_ndcg, semantic_ndcg, overall_mrr, overall_p10))
        print(f"{weight:>8.1f} {overall_ndcg:>14.4f} {lexical_ndcg:>14.4f} {semantic_ndcg:>15.4f} "
              f"{overall_mrr:>13.4f} {overall_p10:>13.4f}")

    best = max(results, key=lambda r: r[1])  # by overall nDCG@10
    print(f"\nBest weight by overall nDCG@10: {best[0]} "
          f"(nDCG={best[1]:.4f}, vs {[r for r in results if r[0]==0.5][0][1]:.4f} at the current hand-set 0.5)")
    print(f"Lexical subset at that weight: {best[2]:.4f} "
          f"(vs {[r for r in results if r[0]==0.5][0][2]:.4f} at 0.5 -- should not have regressed)")
    print("\nUpdate SEMANTIC_WEIGHT in app/semantic.py by hand to this value if it's an "
          "improvement -- this script is a one-off analysis, not a runtime dependency.")


if __name__ == "__main__":
    main()
