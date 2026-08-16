"""End-to-end tests against the real, live-loaded FastAPI app -- real index
(data/index.bin), real corpus, real semantic model. Slower than the other
test files (the session-scoped api_client fixture pays a real ~10s startup
cost once, not per test) but this is the only place that proves the whole
pipeline actually works together, not just each piece in isolation.

Requires data/index.bin to exist (main.py's hard startup dependency) --
these tests are skipped as a collection error, not silently, if it's missing;
that's the correct failure mode for a hard dependency.
"""
import pytest


class TestHealth:
    def test_health_returns_ok(self, api_client):
        response = api_client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["corpus_size"] > 0

    def test_health_uptime_is_non_negative(self, api_client):
        body = api_client.get("/health").json()
        assert body["uptime_seconds"] >= 0


class TestSearchValidation:
    def test_empty_query_returns_400(self, api_client):
        response = api_client.get("/search", params={"q": ""})
        assert response.status_code == 400

    def test_page_zero_returns_400(self, api_client):
        response = api_client.get("/search", params={"q": "python", "page": 0})
        assert response.status_code == 400

    def test_page_size_over_max_returns_400(self, api_client):
        response = api_client.get("/search", params={"q": "python", "page_size": 999})
        assert response.status_code == 400

    def test_page_size_zero_returns_400(self, api_client):
        response = api_client.get("/search", params={"q": "python", "page_size": 0})
        assert response.status_code == 400


class TestSearchLexical:
    def test_known_term_returns_results(self, api_client):
        response = api_client.get("/search", params={"q": "python", "page_size": 5})
        assert response.status_code == 200
        body = response.json()
        assert body["total_results"] > 0
        assert len(body["results"]) > 0

    def test_results_have_bm25_and_pagerank_scores(self, api_client):
        # non-reranked results should always carry a real bm25/pagerank
        # breakdown -- this is what the frontend's ranking explanation reads
        body = api_client.get("/search", params={"q": "python", "page_size": 3}).json()
        for result in body["results"]:
            assert result["bm25_score"] is not None
            assert result["pagerank_score"] is not None
            assert result["semantic_score"] is None  # not evaluated -- rerank wasn't requested

    def test_results_are_sorted_descending_by_score(self, api_client):
        body = api_client.get("/search", params={"q": "python", "page_size": 10}).json()
        scores = [r["score"] for r in body["results"]]
        assert scores == sorted(scores, reverse=True)

    def test_pagination_metadata_is_consistent(self, api_client):
        body = api_client.get("/search", params={"q": "python", "page_size": 5}).json()
        assert body["page"] == 1
        assert body["page_size"] == 5
        assert len(body["results"]) <= 5
        assert body["total_pages"] >= 1

    def test_and_operator_is_a_real_intersection(self, api_client):
        # a regression check for the AND-parsing fix, against the real API --
        # results must contain BOTH terms, not just one
        response = api_client.get("/search", params={"q": "python AND wikipedia", "page_size": 10})
        body = response.json()
        if body.get("total_results", 0) == 0:
            pytest.skip("no docs in this corpus snapshot contain both terms")
        # can't inspect full doc content from the API response alone to confirm
        # both terms literally appear in every result, but AND must never
        # return MORE documents than the equivalent OR query -- that's the
        # one invariant true regardless of corpus contents
        or_body = api_client.get("/search", params={"q": "python OR wikipedia", "page_size": 1}).json()
        assert body["total_results"] <= or_body["total_results"]

    def test_lowercase_and_is_not_treated_as_an_operator(self, api_client):
        # regression test for this session's case-sensitivity fix, against the
        # real API: a natural-language query with an ordinary "and" must not
        # come back empty just because "and" got mistaken for boolean syntax
        response = api_client.get("/search", params={"q": "wikipedia and encyclopedia"})
        assert response.status_code == 200
        body = response.json()
        # "and" itself must never show up as an unknown/rejected word -- it's a
        # stopword now, not a search term at all, so it should be invisible to
        # both retrieval and any unknown-word bookkeeping
        assert "and" not in body.get("unknown_words", [])


class TestSearchSemantic:
    def test_rerank_true_returns_valid_response(self, api_client):
        response = api_client.get(
            "/search", params={"q": "python", "rerank": "true", "page_size": 3})
        assert response.status_code == 200

    def test_reranked_results_carry_a_semantic_score(self, api_client):
        body = api_client.get(
            "/search", params={"q": "python", "rerank": "true", "page_size": 5}).json()
        if not body.get("results"):
            pytest.skip("no results for this query in the current corpus snapshot")
        assert any(r["semantic_score"] is not None for r in body["results"])

    def test_augmented_result_has_no_bm25_or_pagerank_score(self, api_client):
        # a doc found purely by semantic augmentation genuinely was never
        # scored by BM25 -- its score should be None (not evaluated), never a
        # fabricated 0.0 that would misrepresent "never looked at" as "looked
        # at and found irrelevant"
        body = api_client.get(
            "/search", params={"q": "ways machines can learn from data",
                                "rerank": "true", "page_size": 10}).json()
        augmented = [r for r in body.get("results", [])
                     if r["bm25_score"] is None and r["semantic_score"] is not None]
        for result in augmented:
            assert result["pagerank_score"] is None

    def test_semantic_query_does_not_crash_on_no_lexical_overlap(self, api_client):
        # a paraphrase query sharing no vocabulary with its target docs at all
        # -- exercises the augmentation-only path end to end
        response = api_client.get(
            "/search", params={"q": "ways machines can learn from data",
                                "rerank": "true", "page_size": 5})
        assert response.status_code == 200


class TestSuggest:
    def test_returns_suggestions_for_a_real_prefix(self, api_client):
        response = api_client.get("/suggest", params={"prefix": "wiki"})
        assert response.status_code == 200
        assert "wiki" in response.json()["suggestions"] or len(response.json()["suggestions"]) > 0

    def test_empty_prefix_returns_no_suggestions(self, api_client):
        response = api_client.get("/suggest", params={"prefix": ""})
        assert response.json()["suggestions"] == []


class TestCaching:
    def test_repeated_query_is_a_cache_hit_and_returns_identical_results(self, api_client):
        first = api_client.get("/search", params={"q": "python", "page_size": 3}).json()
        second = api_client.get("/search", params={"q": "python", "page_size": 3}).json()
        assert first["results"] == second["results"]

    def test_rerank_true_and_false_are_cached_separately(self, api_client):
        # a rerank=true request must never be served a rerank=false cache
        # entry (or vice versa) -- they can legitimately return different orders
        lexical = api_client.get("/search", params={"q": "python", "page_size": 3}).json()
        semantic = api_client.get(
            "/search", params={"q": "python", "rerank": "true", "page_size": 3}).json()
        lexical_scores = [r["semantic_score"] for r in lexical["results"]]
        semantic_scores = [r["semantic_score"] for r in semantic["results"]]
        assert all(s is None for s in lexical_scores)
        # semantic path should have at least attempted to score something
        assert lexical_scores != semantic_scores or len(semantic["results"]) == 0


class TestFeedbackClick:
    def test_valid_click_returns_204(self, api_client):
        first_result = api_client.get(
            "/search", params={"q": "python", "page_size": 1}).json()["results"][0]
        response = api_client.post("/feedback/click", json={
            "query": "python", "doc_id": first_result["doc_id"], "rank": 1, "rerank": False,
        })
        assert response.status_code == 204

    def test_unknown_doc_id_returns_400(self, api_client):
        response = api_client.post("/feedback/click", json={
            "query": "python", "doc_id": 99999999, "rank": 1, "rerank": False,
        })
        assert response.status_code == 400

    def test_missing_required_field_returns_422(self, api_client):
        # doc_id is required -- FastAPI/Pydantic should reject this before it
        # ever reaches the handler, not silently log a click with doc_id=None
        response = api_client.post("/feedback/click", json={"query": "python", "rank": 1})
        assert response.status_code == 422


class TestAuth:
    """api_client (conftest.py) carries a valid X-API-Key by default -- every test
    above this class implicitly proves auth doesn't get in the way of a correctly
    authenticated request. These tests use a bare TestClient with no default
    header instead, to prove the other half: a missing or wrong key is actually
    rejected, not silently ignored.
    """

    @pytest.fixture(scope="class")
    def unauthed_client(self):
        from fastapi.testclient import TestClient
        from app.main import app
        return TestClient(app)

    def test_search_without_key_is_401(self, unauthed_client):
        response = unauthed_client.get("/search", params={"q": "python"})
        assert response.status_code == 401

    def test_search_with_wrong_key_is_401(self, unauthed_client):
        response = unauthed_client.get(
            "/search", params={"q": "python"}, headers={"X-API-Key": "not-the-real-key"})
        assert response.status_code == 401

    def test_suggest_without_key_is_401(self, unauthed_client):
        response = unauthed_client.get("/suggest", params={"prefix": "wiki"})
        assert response.status_code == 401

    def test_feedback_click_without_key_is_401(self, unauthed_client):
        response = unauthed_client.post(
            "/feedback/click", json={"query": "python", "doc_id": 1, "rank": 1})
        assert response.status_code == 401

    def test_health_needs_no_key(self, unauthed_client):
        # /health is deliberately exempt -- an auth-gated health check is a good
        # way to lock yourself out of your own monitoring (see app/main.py).
        response = unauthed_client.get("/health")
        assert response.status_code == 200

    def test_frontend_needs_no_key(self, unauthed_client):
        response = unauthed_client.get("/")
        assert response.status_code == 200
