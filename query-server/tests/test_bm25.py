"""app/bm25.py -- the from-scratch BM25 implementation, ported from a teammate's
C++ reference and generalized to multi-term queries. Tests a hand-computed
expected value against a tiny, fully-controlled index, not just "did it run."
"""
import math

from app.bm25 import K1, B, _idf, _term_score, score_candidates


# A tiny, fully-known positional index: 3 documents, "python" appears in all
# three (common), "rare" appears in only one (rare). Doc lengths are exact
# token counts, not estimates, so every expected score below can be hand-verified.
INDEX = {
    "python": {1: [0], 2: [0, 5], 3: [2]},
    "rare": {1: [1]},
}
DOC_LENGTHS = {1: 4, 2: 6, 3: 3}
AVG_DOC_LENGTH = (4 + 6 + 3) / 3
TOTAL_DOCS = 3


class TestIdf:
    def test_rarer_term_has_higher_idf(self):
        # "rare" (df=1) should score a higher idf than "python" (df=3, appears
        # in every document) -- this is the entire point of idf weighting
        idf_common = _idf("python", INDEX, TOTAL_DOCS)
        idf_rare = _idf("rare", INDEX, TOTAL_DOCS)
        assert idf_rare > idf_common

    def test_idf_never_negative(self):
        # the "+1" idf variant (ported from index.cpp/Lucene) guarantees this by
        # construction, unlike the classic Robertson/Sparck-Jones formula --
        # verify it holds even for a term appearing in every document
        idf = _idf("python", INDEX, TOTAL_DOCS)
        assert idf >= 0

    def test_matches_hand_computed_formula(self):
        # log((N - df + 0.5) / (df + 0.5) + 1.0), df=3, N=3
        expected = math.log((3 - 3 + 0.5) / (3 + 0.5) + 1.0)
        assert _idf("python", INDEX, TOTAL_DOCS) == expected

    def test_unseen_term_has_df_zero(self):
        # a term with no postings at all has df=0 -- should not raise, and idf
        # should be the maximum possible (rarest term imaginable)
        idf = _idf("nonexistent", INDEX, TOTAL_DOCS)
        expected = math.log((3 - 0 + 0.5) / (0 + 0.5) + 1.0)
        assert idf == expected


class TestTermScore:
    def test_zero_term_frequency_scores_zero(self):
        assert _term_score(term_idf=1.5, tf=0, dl=10, avg_doc_length=10) == 0.0

    def test_zero_avg_doc_length_scores_zero(self):
        # guards the division in the tf-saturation term against a corpus with
        # no tokens at all (shouldn't happen in practice, but shouldn't crash either)
        assert _term_score(term_idf=1.5, tf=3, dl=10, avg_doc_length=0) == 0.0

    def test_higher_term_frequency_scores_higher(self):
        low = _term_score(term_idf=1.0, tf=1, dl=10, avg_doc_length=10)
        high = _term_score(term_idf=1.0, tf=5, dl=10, avg_doc_length=10)
        assert high > low

    def test_term_frequency_saturates_not_linear(self):
        # BM25's whole point vs. raw tf*idf: doubling tf should NOT double the
        # score -- the marginal contribution of each additional occurrence shrinks
        score_1 = _term_score(term_idf=1.0, tf=1, dl=10, avg_doc_length=10)
        score_2 = _term_score(term_idf=1.0, tf=2, dl=10, avg_doc_length=10)
        score_20 = _term_score(term_idf=1.0, tf=20, dl=10, avg_doc_length=10)
        assert score_2 < 2 * score_1
        assert (score_20 - score_2) < 9 * (score_2 - score_1)  # heavy saturation by tf=20

    def test_longer_document_scores_lower_for_same_term_frequency(self):
        # length normalization: the same raw term frequency should count for
        # less in a document that's much longer than the corpus average
        short_doc = _term_score(term_idf=1.0, tf=2, dl=5, avg_doc_length=10)
        long_doc = _term_score(term_idf=1.0, tf=2, dl=50, avg_doc_length=10)
        assert short_doc > long_doc

    def test_uses_the_documented_constants(self):
        # k1/b are ported verbatim from index.cpp -- pin them so a future
        # "tune BM25" pass has to change this test deliberately, not by accident
        assert K1 == 1.2
        assert B == 0.75


class TestScoreCandidates:
    def test_only_scores_requested_candidates(self):
        # must never touch a document outside candidate_ids -- that's the whole
        # point of this being hand-rolled instead of a whole-corpus rescan
        scores = score_candidates({1}, ["python"], INDEX, DOC_LENGTHS, AVG_DOC_LENGTH, TOTAL_DOCS)
        assert set(scores.keys()) == {1}

    def test_multi_term_query_sums_contributions(self):
        # "rare" only appears in doc 1 -- doc 1 should score meaningfully higher
        # than doc 2/3 on a "python rare" query, since it gets both terms' scores summed
        scores = score_candidates({1, 2, 3}, ["python", "rare"], INDEX,
                                   DOC_LENGTHS, AVG_DOC_LENGTH, TOTAL_DOCS)
        assert scores[1] > scores[2]
        assert scores[1] > scores[3]

    def test_document_with_no_matching_terms_scores_zero(self):
        scores = score_candidates({1, 2, 3}, ["nonexistent"], INDEX,
                                   DOC_LENGTHS, AVG_DOC_LENGTH, TOTAL_DOCS)
        assert all(score == 0.0 for score in scores.values())

    def test_duplicate_query_terms_do_not_double_count_idf(self):
        # score_candidates() de-dupes query_terms internally (idf computed once
        # per unique term) -- "python python" shouldn't score differently than
        # "python" alone for idf purposes, only tf still comes from the index itself
        once = score_candidates({2}, ["python"], INDEX, DOC_LENGTHS, AVG_DOC_LENGTH, TOTAL_DOCS)
        twice = score_candidates({2}, ["python", "python"], INDEX, DOC_LENGTHS, AVG_DOC_LENGTH, TOTAL_DOCS)
        assert once[2] == twice[2]
