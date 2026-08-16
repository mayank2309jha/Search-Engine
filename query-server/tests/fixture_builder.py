"""Builds a minimal, byte-exact synthetic data/index.bin, mirroring
src/index.cpp's saveToDisk() layout exactly: magic header, a 7-entry offset
table, LEB128 varints for postings, delta-encoded position gaps, LE32/LE64
fixed-width fields, and float/double bit-reinterpretation for PageRank scores
and avg doc length.

Not a test file itself (pytest only collects test_*.py) -- a shared helper
used by tests/test_cpp_reader.py (which needs a fully-known-contents index to
test decoding against) and scripts/generate_ci_index_fixture.py (which needs
a real, valid data/index.bin to exist in CI, where the real 100MB+ one is
correctly gitignored and never checked out). One writer, two consumers,
rather than two independent implementations of this format drifting apart.
"""
import struct

MAGIC = b"MYENGINE"


def varint(value: int) -> bytes:
    """LEB128 unsigned varint -- mirrors EndianUtils::writeVariant32 exactly."""
    out = bytearray()
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value & 0x7F)
    return bytes(out)


def build_fixture_index_bin(
    *, version=2, terms=None, doc_lengths=None, doc_urls=None, doc_pageranks=None,
    avg_doc_length=0.0, total_docs_count=0,
) -> bytes:
    """Builds a minimal, fully-known-contents index.bin, section by section,
    then patches in the real offsets -- same two-pass approach saveToDisk() uses
    (write placeholders, then seek back once real offsets are known), just done
    against an in-memory bytearray instead of a file stream.

    `terms`: {word: {doc_id: [positions]}}, e.g. {"foo": {1: [0], 2: [3]}}
    """
    terms = terms or {}
    doc_lengths = doc_lengths or {}
    doc_urls = doc_urls or {}
    doc_pageranks = doc_pageranks or {}

    # Build postings + the dictionary in sorted term order, matching
    # std::map<std::string, ...>'s iteration order in the real C++ writer.
    postings = []  # (doc_id, term_frequency) pairs, flat pool
    dictionary = []  # (word, posting_start_index, posting_count)
    position_gap_bytes = bytearray()
    total_positions = 0

    for word in sorted(terms.keys()):
        doc_postings = terms[word]
        posting_start = len(postings)
        for doc_id in sorted(doc_postings.keys()):  # sorted, matching std::map<int32_t,...>
            positions = doc_postings[doc_id]
            postings.append((doc_id, len(positions)))
            prev = 0
            for pos in positions:
                position_gap_bytes += varint(pos - prev)
                prev = pos
                total_positions += 1
        dictionary.append((word, posting_start, len(doc_postings)))

    def section(offset_placeholder_index, writer):
        nonlocal buf
        offsets[offset_placeholder_index] = len(buf)
        buf += writer()

    buf = bytearray()
    buf += MAGIC
    buf += struct.pack("<I", version)
    header_offsets_pos = len(buf)
    buf += b"\x00" * (7 * 8)  # placeholders, patched at the end

    offsets = [0] * 7

    def w_global_stats():
        return struct.pack("<d", avg_doc_length) + struct.pack("<Q", total_docs_count)

    def w_posting_pool():
        out = struct.pack("<Q", len(postings))
        for doc_id, tf in postings:
            out += varint(doc_id) + varint(tf) + varint(0)  # posStart unused by the reader
        return out

    def w_position_pool():
        return struct.pack("<Q", total_positions) + bytes(position_gap_bytes)

    def w_doc_lengths():
        out = struct.pack("<Q", len(doc_lengths))
        for doc_id, length in doc_lengths.items():
            out += struct.pack("<I", doc_id) + struct.pack("<I", length)
        return out

    def w_dictionary():
        out = struct.pack("<Q", len(dictionary))
        for word, start, count in dictionary:
            word_bytes = word.encode("utf-8")
            out += struct.pack("<Q", len(word_bytes)) + word_bytes
            out += struct.pack("<I", start) + struct.pack("<I", count)
        return out

    def w_doc_urls():
        out = struct.pack("<Q", len(doc_urls))
        for doc_id, url in doc_urls.items():
            url_bytes = url.encode("utf-8")
            out += struct.pack("<I", doc_id) + struct.pack("<Q", len(url_bytes)) + url_bytes
        return out

    def w_doc_pageranks():
        out = struct.pack("<Q", len(doc_pageranks))
        for doc_id, score in doc_pageranks.items():
            out += struct.pack("<I", doc_id) + struct.pack("<f", score)
        return out

    section(0, w_global_stats)
    section(1, w_posting_pool)
    section(2, w_position_pool)
    section(3, w_doc_lengths)
    section(4, w_dictionary)
    section(5, w_doc_urls)
    section(6, w_doc_pageranks)

    for i, value in enumerate(offsets):
        struct.pack_into("<Q", buf, header_offsets_pos + i * 8, value)

    return bytes(buf)
