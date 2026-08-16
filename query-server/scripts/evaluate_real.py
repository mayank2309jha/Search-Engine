"""BM25-only vs. BM25+semantic evaluation against the REAL crawled corpus
(19,514 documents, via data/index.bin + crawler.db) -- not the synthetic
data/corpus.json evaluate.py uses.

GROUND-TRUTH METHODOLOGY -- read this before trusting the numbers below.
evaluate.py's judgment set is honest about being "reproducible by construction,"
not independent human judgment -- a lexical query is relevant to whichever docs
the corpus-generation script happened to title that way. That circularity is
structurally impossible to fully escape on a *synthetic* corpus. It is NOT a
constraint here: this corpus is real, crawled web content nobody templated
relevance labels into. Every judgment below was built by directly reading real
page content (verified via sqlite3 queries against crawler.db -- title AND a
content excerpt, not title alone) and hand-picking documents a person would
actually consider relevant, then cross-checked against the corpus for
near-duplicate or alternate-topic pages that share vocabulary but aren't
actually about the same thing (e.g. a search for "Messi" surfaced several
unrelated pages about a place called "Messinias" -- confirmed irrelevant and
excluded, not just assumed absent).

Two honest limits on what "independent" means here, disclosed rather than
glossed over:
  1. This is single-judge (one read-through), not multi-rater consensus --
     real IR evaluation research usually uses several judges per query and
     reports inter-annotator agreement. That's a real gap from an academic
     standard, appropriate to name even though building that here isn't
     proportionate to this project's scope.
  2. Each query's relevant-document set was found by searching *for* likely
     candidates (by domain, by title pattern), not by exhaustively reading
     all 19,514 documents -- standard IR "pooling" practice, but it does mean
     a genuinely relevant document this search missed would count as a false
     negative if BM25 or semantic search happens to surface it. Precision@10
     and nDCG are robust to this; a very low MRR on an otherwise-plausible
     result would be the tell to go check by hand.

Semantic-category queries deliberately avoid literal vocabulary overlap with
their target document's distinguishing words (not just the exact title
phrase) -- e.g. "a reptile's very long trip back to its home" for a page
about a sea turtle's 5,000-mile journey, sharing no content words at all with
that page's own title or opening text. This is the same design principle as
this project's "ways machines can learn from data" vs. "machine learning" demo
query -- proving semantic retrieval finds real topical matches without
lexical overlap, not just reordering results BM25 already found.

Reuses evaluate.py's metric functions (precision_at_k, mrr, ndcg_at_k) and
search pipelines (search_bm25_only, search_bm25_plus_semantic, summarize)
unchanged -- same code, same /search-mirroring logic, run against a
differently-built ctx. Only the corpus loading and the judgment set differ.
"""
import json
from pathlib import Path

from app.authority import normalize_pagerank
from app.crawler_db import fallback_title, load_doc_texts
from app.cpp_index_reader import load_cpp_index
from app.semantic import build_doc_embeddings, load_embeddings, load_model, save_embeddings
from app.spellcheck import build_symspell

from evaluate import (
    mrr,
    ndcg_at_k,
    precision_at_k,
    search_bm25_only,
    search_bm25_plus_semantic,
    summarize,
)

CPP_INDEX_PATH = "../data/index.bin"
CRAWLER_DB_PATH = "../data/crawler.db"
EMBEDDINGS_CACHE_PATH = "data/embeddings_cache_cpp.pkl"


# ---------------------------------------------------------------------------
# Judgment set -- real documents, hand-verified against real crawler.db content
# ---------------------------------------------------------------------------

def build_real_judgments() -> list:
    lexical = [
        ("python 3.14 new features", {24}),
        ("python enhancement proposals index", {47}),
        ("python glossary", {44}),
        ("python deprecations", {36}),
        ("python module index", {75}),
        ("css cascading style sheets", {63, 681}),
        ("webassembly", {70}),
        ("http hypertext transfer protocol", {72}),
        ("eurovision song contest rules", {107}),
        ("messi inter miami", {103}),
    ]
    judgments = [
        {"query": q, "type": "lexical", "relevant_ids": ids} for q, ids in lexical
    ]

    semantic = [
        # (query, target doc ids, the target's own title -- kept here purely
        # as a comment so a reviewer can see at a glance that the query below
        # shares no distinguishing vocabulary with it)
        ("changing how a webpage looks visually", {63, 681}),  # CSS: Cascading Style Sheets
        ("sending information between a web browser and a server", {72}),  # HTTP: Hypertext Transfer Protocol
        ("keeping web apps safe from bad actors online", {65}),  # Security | MDN
        ("singing competition among countries in europe", {107}),  # Eurovision Song Contest changes rules for countries at war
        ("a famous footballer playing again after family loss", {103}),  # Lionel Messi ... after death of his father
        ("a reptile's very long trip back to its home", {98}),  # Endangered sea turtle makes 5,000-mile journey
        ("assembling programs to run fast inside a browser", {70}),  # WebAssembly | MDN
        ("articles about staying fit and living longer", {109}),  # BBC Health | Nutrition, Exercise, ..., Longevity
        ("python's built-in dictionary of technical terms", {44}),  # Glossary -- Python 3.14.7 documentation
        ("features being phased out in a programming language", {36}),  # Deprecations -- Python 3.14.7 documentation
    ]
    judgments += [
        {"query": q, "type": "semantic", "relevant_ids": ids} for q, ids in semantic
    ]
    return judgments


# ---------------------------------------------------------------------------
# Real-corpus context -- mirrors app/main.py's startup exactly
# ---------------------------------------------------------------------------

def build_real_context() -> dict:
    cpp_index = load_cpp_index(CPP_INDEX_PATH)
    inverted_index = cpp_index["inverted_index"]
    doc_lengths = cpp_index["doc_lengths"]
    avg_doc_length = cpp_index["avg_doc_length"]
    total_docs_count = cpp_index["total_docs_count"]
    doc_urls = cpp_index["doc_urls"]
    pagerank_raw = cpp_index["doc_pageranks"]

    doc_texts = load_doc_texts(CRAWLER_DB_PATH)
    docs = {
        doc_id: {
            "title": doc_texts.get(doc_id, ("", ""))[0] or fallback_title(url),
            "content": doc_texts.get(doc_id, ("", ""))[1],
            "url": url,
            "company": None,
        }
        for doc_id, url in doc_urls.items()
    }

    sym_spell = build_symspell(docs)
    pagerank_norm = normalize_pagerank(pagerank_raw)

    semantic_model = load_model()
    cached = load_embeddings(EMBEDDINGS_CACHE_PATH, CPP_INDEX_PATH)
    if cached is not None:
        doc_embeddings, embedding_doc_id_order = cached
    else:
        doc_embeddings, embedding_doc_id_order = build_doc_embeddings(docs, semantic_model)
        save_embeddings(EMBEDDINGS_CACHE_PATH, CPP_INDEX_PATH, doc_embeddings, embedding_doc_id_order)
    doc_id_to_index = {doc_id: i for i, doc_id in enumerate(embedding_doc_id_order)}

    return {
        "docs": docs, "inverted_index": inverted_index, "doc_lengths": doc_lengths,
        "avg_doc_length": avg_doc_length, "total_docs_count": total_docs_count,
        "sym_spell": sym_spell, "pagerank_norm": pagerank_norm,
        "semantic_model": semantic_model, "doc_embeddings": doc_embeddings,
        "doc_id_to_index": doc_id_to_index, "embedding_doc_id_order": embedding_doc_id_order,
    }


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_evaluation():
    ctx = build_real_context()
    judgments = build_real_judgments()

    rows = []
    for judgment in judgments:
        query = judgment["query"]
        relevant_ids = judgment["relevant_ids"]

        bm25_ranked = search_bm25_only(query, ctx)
        semantic_ranked = search_bm25_plus_semantic(query, ctx)

        rows.append({
            "query": query,
            "type": judgment["type"],
            "num_relevant": len(relevant_ids),
            "bm25": {
                "precision_at_10": precision_at_k(bm25_ranked, relevant_ids),
                "mrr": mrr(bm25_ranked, relevant_ids),
                "ndcg_at_10": ndcg_at_k(bm25_ranked, relevant_ids),
                "num_results": len(bm25_ranked),
            },
            "semantic": {
                "precision_at_10": precision_at_k(semantic_ranked, relevant_ids),
                "mrr": mrr(semantic_ranked, relevant_ids),
                "ndcg_at_10": ndcg_at_k(semantic_ranked, relevant_ids),
                "num_results": len(semantic_ranked),
            },
        })

    return rows


def main():
    rows = run_evaluation()
    summary = summarize(rows)

    print(f"{'Query':<55} {'Type':<10} {'BM25 P@10':>10} {'Sem P@10':>10} {'BM25 MRR':>10} {'Sem MRR':>10} {'BM25 nDCG':>10} {'Sem nDCG':>10}")
    for r in rows:
        print(f"{r['query']:<55} {r['type']:<10} "
              f"{r['bm25']['precision_at_10']:>10.3f} {r['semantic']['precision_at_10']:>10.3f} "
              f"{r['bm25']['mrr']:>10.3f} {r['semantic']['mrr']:>10.3f} "
              f"{r['bm25']['ndcg_at_10']:>10.3f} {r['semantic']['ndcg_at_10']:>10.3f}")

    print()
    for name in ["overall", "lexical", "semantic"]:
        s = summary[name]
        print(f"--- {name} ---")
        print(f"  BM25-only:      P@10={s['bm25']['precision_at_10']:.3f}  MRR={s['bm25']['mrr']:.3f}  nDCG@10={s['bm25']['ndcg_at_10']:.3f}")
        print(f"  BM25+semantic:  P@10={s['semantic']['precision_at_10']:.3f}  MRR={s['semantic']['mrr']:.3f}  nDCG@10={s['semantic']['ndcg_at_10']:.3f}")

    out_path = Path(__file__).resolve().parent.parent / "data" / "real_evaluation_results.json"
    out_path.write_text(json.dumps({
        "rows": [{**r, "bm25": r["bm25"], "semantic": r["semantic"]} for r in rows],
        "summary": summary,
    }, indent=2, default=list))
    print(f"\nFull results written to {out_path}")


if __name__ == "__main__":
    main()
