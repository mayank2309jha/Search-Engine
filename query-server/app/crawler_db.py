# Reads page title/content text out of crawler.db -- the other half of the real-data
# integration alongside cpp_index_reader.py. data/index.bin has postings, positions,
# doc lengths, URLs, and PageRank scores, but never the documents' actual text: the C++
# engine only ever needed that text transiently, at index-build time, to tokenize it.
#
# crawler.db itself is gitignored (crawler output, not source -- see crawler/README.md),
# so it may genuinely not exist on a given machine yet, even though data/index.bin (a
# committed build artifact) does. That's not an error case to work around with a flag;
# it's just what "the crawl hasn't been run here yet" looks like, and every caller of
# load_doc_texts() below already treats a missing id as "no text available" rather than
# assuming one exists.
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit


# {doc_id: (title, content)} for every row in crawler.db's `pages` table, or {} if the
# database file isn't present on this machine. Read-only: this process only ever
# consumes crawl output, never writes to the crawler's database.
#
# immutable=1 (on top of mode=ro) tells SQLite the file won't change for the
# lifetime of this connection, so it skips creating/checking WAL/journal
# companion files entirely -- a real promise this function's own shape makes
# true (open, one SELECT, close, all within milliseconds), not just a Docker
# workaround. Needed for real, not just in theory: crawler.db is written in
# WAL mode (crawler/storage/indexer.py), and without immutable=1, even a pure
# read attempts to touch -wal/-shm files alongside it -- which fails with
# "attempt to write a readonly database" the moment the containing directory
# isn't writable by this process, exactly what happens when crawler.db is
# bind-mounted into a container running as a non-root user (see
# docker-compose.yml).
def load_doc_texts(db_path: str) -> dict[int, tuple[str, str]]:
    if not Path(db_path).exists():
        return {}
    conn = sqlite3.connect(f"file:{db_path}?mode=ro&immutable=1", uri=True)
    try:
        cursor = conn.execute("SELECT id, title, content FROM pages")
        return {row[0]: (row[1] or "", row[2] or "") for row in cursor}
    finally:
        conn.close()


# Same fallback chain's last two rungs as crawler/worker/parser.py's Parser.extract()
# (URL slug, then domain) -- used here only when crawler.db has no row for a doc_id
# that data/index.bin's docUrls section does have, so every result still gets a
# readable title instead of an empty one (schemas.SearchResultItem.title is required).
def fallback_title(url: str) -> str:
    parts = urlsplit(url)
    slug = parts.path.rstrip("/").rsplit("/", 1)[-1]
    if slug:
        return slug.replace("-", " ").replace("_", " ").strip() or parts.netloc
    return parts.netloc
