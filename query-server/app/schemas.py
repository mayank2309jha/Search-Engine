# Pydantic response models for every endpoint -- gives FastAPI's response_model
# validation + auto-generated OpenAPI docs instead of hand-shaped dicts.
from typing import Optional
from pydantic import BaseModel, Field


class SearchResultItem(BaseModel):
    doc_id: int
    title: str
    company: Optional[str] = None
    url: Optional[str] = None
    score: float
    snippet: str
    # Per-signal breakdown behind `score`, added in Phase 8 for the frontend's ranking-
    # explanation feature. None (not 0.0) means "this signal never evaluated this
    # document" -- concretely, a semantic-augmentation-only find that BM25 never
    # retrieved has no bm25_score/pagerank_score at all, and a non-reranked result
    # (rerank=false, or ranked beyond semantic.py's TOP_K) has no semantic_score.
    bm25_score: Optional[float] = None
    pagerank_score: Optional[float] = None
    semantic_score: Optional[float] = None


# the normal, successful /search shape: a ranked, paginated result set
class SearchResponse(BaseModel):
    query: str
    page: int
    page_size: int
    total_results: int
    total_pages: int
    results: list[SearchResultItem]
    # only present when spellcheck actually corrected something
    did_you_mean: Optional[str] = None


# covers both zero-result branches in main.py: unknown-word rejections
# (unknown_words populated) and "no searchable terms" queries (message only)
class NoResultsResponse(BaseModel):
    query: str
    message: str
    unknown_words: list[str] = Field(default_factory=list)
    results: list[SearchResultItem] = Field(default_factory=list)


class SuggestResponse(BaseModel):
    prefix: str
    suggestions: list[str]


class HealthResponse(BaseModel):
    status: str
    corpus_size: int
    uptime_seconds: float
    started_at: str


class ErrorResponse(BaseModel):
    detail: str


# Phase 8: what the frontend posts to /feedback/click when a user opens a
# result -- the relevance-feedback signal this project's docs have named as
# missing since Phase 4. doc_id/rank/rerank identify exactly which result in
# which ranked list got clicked; query is the original search text, not
# whatever spell-correction did to it, so click data lines up with what a
# real user actually typed.
class ClickEvent(BaseModel):
    query: str
    doc_id: int
    rank: int
    rerank: bool = False
