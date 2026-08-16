# Reads the C++ engine's data/index.bin directly -- the Python side of the integration
# between query-server and the teammate-built indexer (src/index.cpp). No new indexing
# work happens here; this only decodes what InvertedIndex::saveToDisk() already wrote,
# into the same {term: {doc_id: [positions]}} / doc_lengths / avg_doc_length shape
# app/bm25.py and app/index.py already expect -- so nothing downstream of this module
# needs to know or care that the index was built in C++, not by app/index.build_index().
#
# Byte format (confirmed against src/index.cpp's saveToDisk()/loadFromDisk(), version 2):
#   8 bytes   magic "MYENGINE"
#   4 bytes   version (LE32) -- must be 2
#   7 x 8 bytes  section offsets (LE64): globalStats, postingPool, positionPool,
#                docLengths, dictionary, docUrls, docPageRanks
#
#   globalStats:   avgDocLength (double, via LE64 reinterpret), totalDocsCount (LE64)
#   postingPool:   count (LE64), then per posting: varint32 docId, varint32 termFrequency,
#                  varint32 positionStartIndex
#   dictionary:    count (LE64), then per term: wordLen (LE64), word bytes,
#                  postingStartIndex (LE32), postingCount (LE32)
#   positionPool:  count (LE64), then delta-encoded (varint32 gap) positions, written by
#                  walking termDictionary in order -> that term's postings in postingPool
#                  order -> that posting's termFrequency positions. Decoding MUST replay
#                  this exact nested order (not raw sequential order) to know which
#                  posting each run of gaps belongs to.
#   docLengths:    count (LE64), then per entry: id (LE32), length (LE32)
#   docUrls:       count (LE64), then per entry: id (LE32), urlLen (LE64), url bytes
#   docPageRanks:  count (LE64), then per entry: id (LE32), score (float, via LE32 reinterpret)
import struct

MAGIC = b"MYENGINE"
SUPPORTED_VERSION = 2


class CppIndexFormatError(Exception):
    """The file at the given path isn't a version-2 MYENGINE index, or is truncated/corrupt."""


def _read_le32(f) -> int:
    data = f.read(4)
    if len(data) != 4:
        raise CppIndexFormatError("Unexpected EOF reading a 4-byte field")
    return struct.unpack("<I", data)[0]


def _read_le64(f) -> int:
    data = f.read(8)
    if len(data) != 8:
        raise CppIndexFormatError("Unexpected EOF reading an 8-byte field")
    return struct.unpack("<Q", data)[0]


# LEB128 unsigned varint, matching EndianUtils::readVariant32 exactly: 7 payload bits
# per byte, continuation signaled by the top bit.
def _read_varint32(f) -> int:
    value = 0
    shift = 0
    while True:
        byte = f.read(1)
        if not byte:
            raise CppIndexFormatError("Unexpected EOF reading a varint")
        b = byte[0]
        value |= (b & 0x7F) << shift
        if not (b & 0x80):
            return value
        shift += 7


# Loads data/index.bin and returns everything app/bm25.py, app/index.py, and
# app/authority.normalize_pagerank() need -- already in their expected shapes.
def load_cpp_index(index_path: str) -> dict:
    with open(index_path, "rb") as f:
        magic = f.read(8)
        if magic != MAGIC:
            raise CppIndexFormatError(
                f"Bad magic bytes {magic!r} in {index_path!r}, expected {MAGIC!r} "
                "-- is this really a MYENGINE index.bin?"
            )
        version = _read_le32(f)
        if version != SUPPORTED_VERSION:
            raise CppIndexFormatError(
                f"{index_path!r} is index format version {version}, this reader only "
                f"understands version {SUPPORTED_VERSION}. Rebuild it with the current "
                "C++ engine (./build/search_engine)."
            )

        global_stats_offset = _read_le64(f)
        posting_pool_offset = _read_le64(f)
        position_pool_offset = _read_le64(f)
        doc_lengths_offset = _read_le64(f)
        dictionary_offset = _read_le64(f)
        doc_urls_offset = _read_le64(f)
        pageranks_offset = _read_le64(f)

        # -- global stats: avgDocLength was written as a double reinterpreted through
        # a uint64_t union, so it has to be read back the same way, not as a plain LE64 --
        f.seek(global_stats_offset)
        avg_doc_length = struct.unpack("<d", f.read(8))[0]
        total_docs_count = _read_le64(f)

        # -- posting pool: docId was cast to uint32_t before being varint-encoded (see
        # index.cpp's saveToDisk) -- safe to read back as unsigned since real doc ids
        # are non-negative SQLite autoincrement values --
        f.seek(posting_pool_offset)
        posting_count = _read_le64(f)
        # (doc_id, term_frequency) per posting, indexed by its position in the pool --
        # position_start_index from disk is ignored, since positions are reconstructed
        # by replaying dictionary/posting order below, not by trusting stored offsets
        # into a pool we're rebuilding fresh anyway
        postings = [None] * posting_count
        for i in range(posting_count):
            doc_id = _read_varint32(f)
            term_frequency = _read_varint32(f)
            _read_varint32(f)  # positionStartIndex -- unused when rebuilding in Python
            postings[i] = (doc_id, term_frequency)

        # -- term dictionary --
        f.seek(dictionary_offset)
        dict_count = _read_le64(f)
        term_records = []  # (word, posting_start_index, posting_count), in on-disk order
        for _ in range(dict_count):
            word_len = _read_le64(f)
            word = f.read(word_len).decode("utf-8")
            posting_start_index = _read_le32(f)
            term_posting_count = _read_le32(f)
            term_records.append((word, posting_start_index, term_posting_count))

        # -- position pool: delta-encoded gaps, written in termDictionary -> postings ->
        # positions order. Must decode in that exact same nested order; there is no way
        # to jump directly to a given posting's positions -- everything before it in
        # this ordering has to be walked (and its gap-count consumed) first. --
        f.seek(position_pool_offset)
        _read_le64(f)  # total position count -- not needed, since we already know each
        #                posting's termFrequency (= how many gaps belong to it)
        positions_by_posting = [None] * posting_count
        for word, posting_start_index, term_posting_count in term_records:
            for i in range(term_posting_count):
                posting_idx = posting_start_index + i
                _doc_id, term_frequency = postings[posting_idx]
                accumulated = 0
                positions = []
                for _ in range(term_frequency):
                    gap = _read_varint32(f)
                    accumulated += gap
                    positions.append(accumulated)
                positions_by_posting[posting_idx] = positions

        # -- assemble the {term: {doc_id: [positions]}} shape app/index.py/app/bm25.py
        # already consume, regardless of whether the index came from build_index() or here --
        inverted_index: dict[str, dict[int, list[int]]] = {}
        for word, posting_start_index, term_posting_count in term_records:
            doc_positions = {}
            for i in range(term_posting_count):
                posting_idx = posting_start_index + i
                doc_id, _tf = postings[posting_idx]
                doc_positions[doc_id] = positions_by_posting[posting_idx]
            inverted_index[word] = doc_positions

        # -- doc lengths --
        f.seek(doc_lengths_offset)
        len_count = _read_le64(f)
        doc_lengths: dict[int, int] = {}
        for _ in range(len_count):
            doc_id = _read_le32(f)
            length = _read_le32(f)
            doc_lengths[doc_id] = length

        # -- doc urls --
        f.seek(doc_urls_offset)
        url_count = _read_le64(f)
        doc_urls: dict[int, str] = {}
        for _ in range(url_count):
            doc_id = _read_le32(f)
            url_len = _read_le64(f)
            doc_urls[doc_id] = f.read(url_len).decode("utf-8")

        # -- doc pageranks: raw scores from crawler/ranking/pagerank.py's power iteration,
        # summing to ~1.0 across the corpus -- same shape authority.normalize_pagerank()
        # already takes, so ranking.py needs zero changes to consume real PageRank here --
        f.seek(pageranks_offset)
        pr_count = _read_le64(f)
        doc_pageranks: dict[int, float] = {}
        for _ in range(pr_count):
            doc_id = _read_le32(f)
            score = struct.unpack("<f", f.read(4))[0]
            doc_pageranks[doc_id] = score

    return {
        "inverted_index": inverted_index,
        "doc_lengths": doc_lengths,
        "avg_doc_length": avg_doc_length,
        "total_docs_count": total_docs_count,
        "doc_urls": doc_urls,
        "doc_pageranks": doc_pageranks,
    }
