"""Shared fixtures. Kept deliberately small -- most tests build their own tiny,
fully-controlled inputs inline, since a shared "big fixture corpus" tends to hide
which specific input made a test fail. The one thing worth sharing is the FastAPI
TestClient in test_api.py, since importing app.main pays a real, ~10s one-time
cost (loading the sentence-transformers model, embedding the corpus) that every
test in that file would otherwise pay again.
"""
import pytest


@pytest.fixture(scope="session")
def api_client():
    """A TestClient wrapping the real app, imported once per test session.

    Carries the default demo API key as a default header, since /search,
    /suggest, and /feedback/click all require it now (see app/main.py's
    require_api_key). This keeps every existing call site in this file
    unmodified; auth being enforced at all is verified separately, with a
    client that deliberately does NOT carry this header (see TestAuth).
    """
    from fastapi.testclient import TestClient
    from app.main import API_KEY, app
    return TestClient(app, headers={"X-API-Key": API_KEY})
