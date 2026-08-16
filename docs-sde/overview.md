# SDE overview — context for picking up backend/systems work here

Read this first if you're resuming this project for a systems-engineering / SDE-framed session and don't remember the details. It orients you; `current-state.md` and `roadmap.md` in this same folder give you the specifics and the next moves.

## The framing

This is a 3-person team project (one M.Tech portfolio search engine, per `crawler/CLAUDE.md`). Two components are teammate-owned; this one is yours:

| Component | Owner | Language | What it does |
|---|---|---|---|
| `crawler/` | Teammate (Hemal Kisku) | Python | Concurrent, polite, resumable web crawl → SQLite (`crawler.db`: pages, links, frontier) + PageRank power iteration |
| `src/`, `include/` (repo root) | Teammate | C++ | Reads `crawler.db`, builds a flat-array positional inverted index, **single-word-only** BM25+PageRank search, serializes to `data/index.bin` |
| `query-server/` (this folder) | You | Python | Reads `data/index.bin` directly (no C++ query interface exists — `main()` runs one hardcoded query and exits), builds the actual multi-term/boolean/semantic query-serving layer, exposes it as a REST API, serves a demo frontend (`static/`) at `/`, and has a real test suite (`tests/`, 92 tests) + CI (`.github/workflows/ci.yml`), all added Phase 8 |

**The single most important fact about the architecture**: the C++ engine cannot answer a real multi-word query. `InvertedIndex::searchBM25(const std::string &word)` takes exactly one word. Everything that makes this a usable search engine — boolean AND/OR/NOT, phrases, multi-term ranking, spell correction, semantic search, an actual HTTP API — lives in `query-server/`. This isn't a redundant or optional layer; it's the reason the combined system works at all.

## How the pieces actually connect

```
crawler/ (Python)                    src/ + include/ (C++)              query-server/ (Python, YOU)
  fetch, parse, store        →         Parser::parseDatabase()    
  crawler.db (SQLite)                  Tokenizer, Stemmer                
    pages, links, frontier             InvertedIndex::build()            
  ranking/pagerank.py        →         docPageRanks                      
    writes `pagerank` table            saveToDisk()                      
                                          ↓                               
                                      data/index.bin  ─────────────→  app/cpp_index_reader.py
                                      (committed build artifact)          decodes into the same
                                                                           {term:{doc_id:[pos]}} /
                                                                           doc_lengths / PageRank
                                                                           shape app/index.py and
                                                                           app/bm25.py already used

                                      crawler.db (gitignored,       →  app/crawler_db.py
                                      NOT committed, lives on            reads title/content when
                                      whoever ran the crawl's            present; falls back to
                                      machine)                           URL-derived titles + empty
                                                                          content when absent
```

`main.py`'s startup reads `../data/index.bin` (hard dependency — fails loudly if missing) and `../data/crawler.db` (optional — degrades gracefully to URL-derived titles/empty snippets if absent, which is the actual state of this specific clone right now).

## The binary format you'll need if this ever needs revisiting

`app/cpp_index_reader.py` decodes `data/index.bin`. If the C++ engine's format ever changes, or the reader needs debugging, the exact byte layout (confirmed by reading `src/index.cpp`'s `saveToDisk()`/`loadFromDisk()` directly, and verified byte-exact against the real committed index — decoded position count and post-decode file offset both matched the file's own declared values exactly) is:

- 8 bytes magic `"MYENGINE"`, 4 bytes version (LE32, must be `2`), then 7×8 bytes (LE64) of absolute section offsets: globalStats, postingPool, positionPool, docLengths, dictionary, docUrls, docPageRanks.
- `globalStats`: avgDocLength (double, via LE64 bit-reinterpretation — **not** a plain float), totalDocsCount (LE64).
- `postingPool`: count (LE64), then per posting: varint32 docId, varint32 termFrequency, varint32 positionStartIndex (the last one is written but the Python reader ignores it and rebuilds offsets fresh).
- `dictionary`: count (LE64), then per term: wordLen (LE64), word bytes, postingStartIndex (LE32), postingCount (LE32).
- `positionPool`: count (LE64), then **delta-encoded, gap-only** varint32 positions — decoding requires replaying the exact nested loop the C++ writer used (`termDictionary` order → that term's postings → that posting's positions), not a flat independently-addressable read. This is the part most likely to bite you if you ever touch this code.
- `docLengths` / `docUrls` / `docPageRanks`: straightforward count-prefixed arrays; PageRank scores are floats via LE32 bit-reinterpretation.

Full reasoning and the verification methodology are in `DESIGN AND IMPLEMENTATION DOCUMENT.md`'s Phase 6 section and the `cpp_index_reader.py` Component Documentation entry.

## Git state (as of the work described in these docs)

As of Phase 13/14, this is a fresh, standalone repo (`github.com/mayank2309jha/Search-Engine`, branch `main`) — pushed for the first time, CI verified green on real GitHub infrastructure (Phase 14). It's intentionally decoupled from the original team repo: that history (branch `retrievalranking`, the teammate coordination below) was backed up as a full `git bundle` before being dropped, not carried forward — see `runningUpdates.md`'s Phase 13. Team coordination (the title-indexing review, the teammate's unmerged crawler work) is still against the *original* repo, not this one — check there, not here, before assuming review status.
