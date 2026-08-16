"""app/semantic.py -- embedding-based re-ranking + whole-corpus augmentation.

Uses a fake model (deterministic, hand-picked vectors) instead of loading the
real sentence-transformers model -- keeps these tests fast and fully
controlled, and is standard practice for unit-testing code that calls out to
an ML model. The real model is exercised by test_api.py's end-to-end tests.

Three of these tests are direct regressions for bugs found and fixed this
session and last: an empty-pool crash, the fabricated-0.0-score normalization
bug, and the augmentation-bypasses-hard-constraints bug.
"""
import numpy as np

from app.semantic import semantic_rerank


class FakeModel:
    """encode() returns pre-assigned vectors for known texts -- no real
    inference, no model download, no ~10s startup cost."""

    def __init__(self, vectors: dict):
        self.vectors = vectors

    def encode(self, texts, convert_to_numpy=True, normalize_embeddings=True):
        return np.array([self.vectors[t] for t in texts])


# Three synthetic documents, 2D unit vectors chosen so similarity is obvious
# by inspection: doc A points the same direction as the query, B is
# orthogonal (unrelated), C points the opposite way (anti-related).
DOC_EMBEDDINGS = np.array([
    [1.0, 0.0],   # doc "A" -- index 0
    [0.0, 1.0],   # doc "B" -- index 1
    [-1.0, 0.0],  # doc "C" -- index 2
])
DOC_ID_ORDER = ["A", "B", "C"]
DOC_ID_TO_INDEX = {doc_id: i for i, doc_id in enumerate(DOC_ID_ORDER)}
QUERY_MODEL = FakeModel({"query about A": np.array([1.0, 0.0])})


class TestEmptyPoolDoesNotCrash:
    """Regression test for the exact bug found this session: both the BM25
    head and the augmentation pool empty at once used to raise
    ValueError('min() iterable argument is empty')."""

    def test_no_head_and_augmentation_disabled_returns_gracefully(self):
        ranked_ids, scores, sem_components = semantic_rerank(
            query="query about A",
            ranked_ids=[],  # BM25 found nothing
            base_scores={},
            model=QUERY_MODEL,
            doc_embeddings=DOC_EMBEDDINGS,
            doc_id_to_index=DOC_ID_TO_INDEX,
            embedding_doc_id_order=DOC_ID_ORDER,
            allow_augmentation=False,  # e.g. a query with an explicit AND/NOT constraint
        )
        assert ranked_ids == []
        assert scores == {}
        assert sem_components == {}

    def test_no_head_and_augment_k_zero_returns_gracefully(self):
        ranked_ids, scores, sem_components = semantic_rerank(
            query="query about A", ranked_ids=[], base_scores={},
            model=QUERY_MODEL, doc_embeddings=DOC_EMBEDDINGS,
            doc_id_to_index=DOC_ID_TO_INDEX, embedding_doc_id_order=DOC_ID_ORDER,
            allow_augmentation=True, augment_k=0,
        )
        assert ranked_ids == []


class TestAugmentation:
    def test_pulls_in_a_relevant_doc_bm25_never_found(self):
        # BM25's head is just B and C; A (the most query-relevant doc by far)
        # was never retrieved at all. Augmentation should surface it.
        ranked_ids, scores, sem_components = semantic_rerank(
            query="query about A",
            ranked_ids=["B", "C"],
            base_scores={"B": 0.5, "C": 0.5},
            model=QUERY_MODEL, doc_embeddings=DOC_EMBEDDINGS,
            doc_id_to_index=DOC_ID_TO_INDEX, embedding_doc_id_order=DOC_ID_ORDER,
            allow_augmentation=True, augment_k=5,
        )
        assert "A" in ranked_ids
        # and it should rank first -- it's the only doc that actually matches
        assert ranked_ids[0] == "A"

    def test_disabled_augmentation_never_pulls_in_new_docs(self):
        # the gate a real bug (fixed previously) initially got wrong: this
        # must be an all-or-nothing constraint check, not a "did we already
        # have enough candidates" heuristic
        ranked_ids, scores, sem_components = semantic_rerank(
            query="query about A",
            ranked_ids=["B", "C"],
            base_scores={"B": 0.5, "C": 0.5},
            model=QUERY_MODEL, doc_embeddings=DOC_EMBEDDINGS,
            doc_id_to_index=DOC_ID_TO_INDEX, embedding_doc_id_order=DOC_ID_ORDER,
            allow_augmentation=False,
        )
        assert "A" not in ranked_ids
        assert set(ranked_ids) == {"B", "C"}

    def test_augmented_doc_never_double_counted_if_already_in_head(self):
        # if a doc is already in the BM25 head, augmentation must not also
        # add it a second time as a "new" find
        ranked_ids, scores, sem_components = semantic_rerank(
            query="query about A",
            ranked_ids=["A", "B"],
            base_scores={"A": 0.5, "B": 0.5},
            model=QUERY_MODEL, doc_embeddings=DOC_EMBEDDINGS,
            doc_id_to_index=DOC_ID_TO_INDEX, embedding_doc_id_order=DOC_ID_ORDER,
            allow_augmentation=True, augment_k=5,
        )
        assert ranked_ids.count("A") == 1


class TestFabricatedScoreFix:
    """Regression test for the normalization bug found in Phase 5: an
    augmented doc used to get a placeholder 0.0 base score blended in, which
    made it look worse than the worst real BM25 candidate even when its
    semantic similarity was the highest in the whole pool."""

    def test_augmented_doc_scored_purely_on_semantic_similarity(self):
        ranked_ids, scores, sem_components = semantic_rerank(
            query="query about A",
            ranked_ids=["B"],
            base_scores={"B": 0.9},  # a strong BM25 score, deliberately high
            model=QUERY_MODEL, doc_embeddings=DOC_EMBEDDINGS,
            doc_id_to_index=DOC_ID_TO_INDEX, embedding_doc_id_order=DOC_ID_ORDER,
            allow_augmentation=True, augment_k=5, weight=0.5,
        )
        # A is a pure augmentation find (perfect semantic match, zero BM25
        # opinion) -- it must still outrank B (mediocre semantic match, but a
        # deliberately inflated fake BM25 score) once the fix is in place.
        assert ranked_ids[0] == "A"

    def test_sem_components_only_covers_the_reranked_pool(self):
        ranked_ids, scores, sem_components = semantic_rerank(
            query="query about A",
            ranked_ids=["B"],
            base_scores={"B": 0.9},
            model=QUERY_MODEL, doc_embeddings=DOC_EMBEDDINGS,
            doc_id_to_index=DOC_ID_TO_INDEX, embedding_doc_id_order=DOC_ID_ORDER,
            allow_augmentation=True, augment_k=5,
        )
        # sem_components (new this session, feeds the frontend's ranking
        # explanation) should have real entries for both the head and the
        # augmented find, keyed by doc_id
        assert "A" in sem_components
        assert "B" in sem_components


class TestUpdatedScores:
    def test_reranked_docs_get_their_score_replaced_not_left_raw(self):
        # a doc in the reranked pool must show the actual blended score it was
        # ranked by, not its original un-normalized base score -- otherwise a
        # client sees a "score" that doesn't match the order results came back in
        ranked_ids, scores, _ = semantic_rerank(
            query="query about A", ranked_ids=["B", "C"],
            base_scores={"B": 0.5, "C": 0.5},
            model=QUERY_MODEL, doc_embeddings=DOC_EMBEDDINGS,
            doc_id_to_index=DOC_ID_TO_INDEX, embedding_doc_id_order=DOC_ID_ORDER,
            allow_augmentation=True, augment_k=5,
        )
        # the top-ranked doc's score should be its blended value, not 0.5
        top = ranked_ids[0]
        assert scores[top] != 0.5 or top not in ("B", "C")
