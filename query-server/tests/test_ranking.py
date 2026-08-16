"""app/ranking.py -- BM25 + PageRank fusion, plus the phrase-match bonus.

score_documents_detailed() is the source of truth (added this session so the
frontend's ranking-explanation feature has real per-signal numbers to show);
score_documents() is a thin wrapper kept for backward compatibility with
scripts/evaluate.py, train_ranker.py, and tune_semantic_weight.py. Both get
tested here, including that the wrapper's contract genuinely didn't change.
"""
from app.ranking import (
    BM25_WEIGHT, PAGERANK_WEIGHT, PHRASE_BOOST,
    _normalize, score_documents, score_documents_detailed,
)

INDEX = {
    "python": {1: [0], 2: [0]},
    "machine": {1: [1]},
    "learning": {1: [2]},
}
DOC_LENGTHS = {1: 3, 2: 1}
AVG_DOC_LENGTH = 2.0
TOTAL_DOCS = 2
PAGERANK_NORM = {1: 0.8, 2: 0.2}


class TestNormalize:
    def test_empty_input_returns_empty(self):
        assert _normalize({}) == {}

    def test_min_max_scales_to_zero_one_range(self):
        result = _normalize({"a": 10, "b": 20, "c": 30})
        assert result["a"] == 0.0
        assert result["c"] == 1.0
        assert result["b"] == 0.5

    def test_all_equal_values_normalize_to_one(self):
        # a zero-span input has nothing to differentiate -- treated as fully
        # normalized (1.0) rather than dividing by zero
        result = _normalize({"a": 5, "b": 5})
        assert result == {"a": 1.0, "b": 1.0}


class TestScoreDocumentsDetailed:
    def _structured(self, phrases=None):
        return {
            "required": [], "optional": ["python"], "excluded": [],
            "phrases": phrases or [], "excluded_phrases": [],
        }

    def test_final_score_is_weighted_sum_of_components(self):
        detailed = score_documents_detailed(
            {1, 2}, self._structured(), INDEX, DOC_LENGTHS, AVG_DOC_LENGTH,
            TOTAL_DOCS, PAGERANK_NORM)
        for doc_id, components in detailed.items():
            expected = (
                BM25_WEIGHT * components["bm25"]
                + PAGERANK_WEIGHT * components["pagerank"]
                + components["phrase_bonus"]
            )
            assert components["final"] == expected

    def test_pagerank_component_matches_input(self):
        # the pagerank component in the breakdown should be exactly the
        # normalized score passed in, not recomputed or altered
        detailed = score_documents_detailed(
            {1, 2}, self._structured(), INDEX, DOC_LENGTHS, AVG_DOC_LENGTH,
            TOTAL_DOCS, PAGERANK_NORM)
        assert detailed[1]["pagerank"] == 0.8
        assert detailed[2]["pagerank"] == 0.2

    def test_phrase_match_adds_flat_bonus(self):
        structured = self._structured(phrases=[["machine", "learning"]])
        detailed = score_documents_detailed(
            {1, 2}, structured, INDEX, DOC_LENGTHS, AVG_DOC_LENGTH,
            TOTAL_DOCS, PAGERANK_NORM)
        # doc 1 has "machine learning" as a consecutive phrase; doc 2 doesn't
        # even contain those terms at all
        assert detailed[1]["phrase_bonus"] == PHRASE_BOOST
        assert detailed[2]["phrase_bonus"] == 0.0

    def test_no_phrase_in_query_means_no_bonus_for_anyone(self):
        detailed = score_documents_detailed(
            {1, 2}, self._structured(), INDEX, DOC_LENGTHS, AVG_DOC_LENGTH,
            TOTAL_DOCS, PAGERANK_NORM)
        assert all(c["phrase_bonus"] == 0.0 for c in detailed.values())


class TestScoreDocumentsWrapper:
    def test_returns_plain_float_per_doc(self):
        # the exact contract scripts/evaluate.py and friends depend on --
        # a plain {doc_id: float}, not the detailed breakdown
        structured = self._structured = {
            "required": [], "optional": ["python"], "excluded": [],
            "phrases": [], "excluded_phrases": [],
        }
        scores = score_documents(
            {1, 2}, structured, INDEX, DOC_LENGTHS, AVG_DOC_LENGTH,
            TOTAL_DOCS, PAGERANK_NORM)
        assert all(isinstance(v, float) for v in scores.values())

    def test_matches_the_detailed_final_field(self):
        structured = {
            "required": [], "optional": ["python"], "excluded": [],
            "phrases": [], "excluded_phrases": [],
        }
        detailed = score_documents_detailed(
            {1, 2}, structured, INDEX, DOC_LENGTHS, AVG_DOC_LENGTH,
            TOTAL_DOCS, PAGERANK_NORM)
        plain = score_documents(
            {1, 2}, structured, INDEX, DOC_LENGTHS, AVG_DOC_LENGTH,
            TOTAL_DOCS, PAGERANK_NORM)
        assert plain == {doc_id: v["final"] for doc_id, v in detailed.items()}
