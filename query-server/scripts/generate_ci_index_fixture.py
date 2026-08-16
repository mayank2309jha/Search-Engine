"""Materializes a small, valid data/index.bin for CI.

Why this needs to exist at all: app/main.py's module-level startup code calls
load_cpp_index(CPP_INDEX_PATH) unconditionally, with no fallback -- by design
(see main.py's own comment: "this service should fail loudly at startup
rather than silently serving stale synthetic data instead"). That means
`from app.main import app` -- which every test in tests/test_api.py depends
on via the api_client fixture -- crashes with FileNotFoundError if
data/index.bin doesn't exist. Confirmed directly: `mv data/index.bin
data/index.bin.tmp && python -c "from app.main import app"` raises exactly
that.

Locally that's never a problem: data/index.bin is a real, large (100MB+),
gitignored build artifact that's just... there, on whoever's machine actually
ran the crawl and the C++ engine. In CI, a fresh `actions/checkout` has no
such file -- it was deliberately untracked from git (Phase 10) specifically
to avoid committing a 100MB+ binary into this repo's permanent history. This
script is the other half of that decision: instead of committing a binary
fixture as a workaround, generate a small, valid one on the fly, using the
exact same writer tests/fixture_builder.py already uses (and is independently
verified against, in tests/test_cpp_reader.py) -- one source of truth for the
byte format, not a second implementation that could quietly drift from it.

Usage (from query-server/, matching this repo's other scripts):
    PYTHONPATH=. python scripts/generate_ci_index_fixture.py
"""
import sys
from pathlib import Path

from tests.fixture_builder import build_fixture_index_bin

OUTPUT_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "index.bin"

# A handful of documents/terms, not one -- exercises retrieval/ranking/
# spellcheck/embedding code paths with more than a trivial single-doc corpus,
# without approaching real data's size or the multi-minute startup cost that
# comes with it.
#
# Doc URLs are deliberately slugs that fallback_title() (app/crawler_db.py)
# turns into real title words -- since CI has no crawler.db either, every
# doc's only text is its URL-derived title, and the spellcheck dictionary
# (app/spellcheck.py's build_symspell) is built from that title text. The
# specific words here ("python", "wikipedia", "encyclopedia", "and") aren't
# arbitrary -- they're exactly the vocabulary tests/test_api.py's queries use,
# discovered by running the suite against this fixture and fixing what a real,
# far richer 19,514-document corpus's natural vocabulary would never be
# missing (e.g. "and" appearing in unknown_words purely because this tiny
# fixture's title text never happened to contain the word "and" at all).
FIXTURE_TERMS = {
    "python": {1: [0, 12], 2: [3]},
    "programming": {1: [1]},
    "language": {1: [2], 2: [0]},
    "search": {2: [1, 5]},
    "engine": {2: [2]},
    "wikipedia": {3: [0]},
    "encyclopedia": {3: [1]},
}
FIXTURE_DOC_LENGTHS = {1: 15, 2: 8, 3: 6}
FIXTURE_DOC_URLS = {
    1: "https://example.com/python-and-programming-language",
    2: "https://example.com/search-engine",
    3: "https://example.com/wikipedia-encyclopedia",
}
FIXTURE_DOC_PAGERANKS = {1: 0.4, 2: 0.35, 3: 0.25}


def main() -> None:
    if OUTPUT_PATH.exists():
        print(f"{OUTPUT_PATH} already exists -- leaving it alone.")
        return

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    data = build_fixture_index_bin(
        terms=FIXTURE_TERMS,
        doc_lengths=FIXTURE_DOC_LENGTHS,
        doc_urls=FIXTURE_DOC_URLS,
        doc_pageranks=FIXTURE_DOC_PAGERANKS,
        avg_doc_length=sum(FIXTURE_DOC_LENGTHS.values()) / len(FIXTURE_DOC_LENGTHS),
        total_docs_count=len(FIXTURE_DOC_URLS),
    )
    OUTPUT_PATH.write_bytes(data)
    print(f"Wrote a {len(data)}-byte CI fixture index to {OUTPUT_PATH}")


if __name__ == "__main__":
    sys.exit(main())
