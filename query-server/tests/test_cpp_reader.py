"""app/cpp_index_reader.py -- decodes the C++ engine's data/index.bin.

This is a contract between two independently-developed components (this
Python service and a teammate's C++ codebase), so it gets the most rigorous
test in this suite: a hand-built, byte-exact synthetic index.bin with fully
known contents, rather than only testing against the real committed index
(which is also checked, as a secondary sanity pass, but skipped if that file
isn't present -- it's a large binary artifact, not guaranteed to exist in
every clone).

The fixture-building helpers live in tests/fixture_builder.py -- shared with
scripts/generate_ci_index_fixture.py, which CI uses to materialize a real
data/index.bin at test time now that the real, 100MB+ one is gitignored and
never checked out (see that script for why app/main.py needs one to exist at
all, even for tests that never touch its actual contents).
"""
import struct
from pathlib import Path

import pytest

from app.cpp_index_reader import CppIndexFormatError, load_cpp_index
from tests.fixture_builder import MAGIC, build_fixture_index_bin


@pytest.fixture
def fixture_path(tmp_path):
    """A small, fully-known 2-document, 2-term index -- alphabetical dictionary
    order ("bar" before "foo") deliberately doesn't match insertion order, the
    same as std::map's real behavior, so a reader that assumed insertion order
    would fail this."""
    data = build_fixture_index_bin(
        terms={
            "foo": {1: [0], 2: [0]},
            "bar": {1: [1]},
        },
        doc_lengths={1: 2, 2: 1},
        doc_urls={1: "http://a.com", 2: "http://b.com"},
        doc_pageranks={1: 0.6, 2: 0.4},
        avg_doc_length=1.5,
        total_docs_count=2,
    )
    path = tmp_path / "test_index.bin"
    path.write_bytes(data)
    return str(path)


class TestLoadCppIndex:
    def test_total_docs_count(self, fixture_path):
        result = load_cpp_index(fixture_path)
        assert result["total_docs_count"] == 2

    def test_avg_doc_length_survives_double_reinterpretation(self, fixture_path):
        # avgDocLength is written as a double bit-reinterpreted through a
        # uint64_t union in the C++ source -- if the reader used readLE64 and
        # treated it as an integer instead of unpacking as '<d', this would
        # come back as a nonsense huge integer instead of 1.5
        result = load_cpp_index(fixture_path)
        assert result["avg_doc_length"] == 1.5

    def test_doc_urls(self, fixture_path):
        result = load_cpp_index(fixture_path)
        assert result["doc_urls"] == {1: "http://a.com", 2: "http://b.com"}

    def test_doc_lengths(self, fixture_path):
        result = load_cpp_index(fixture_path)
        assert result["doc_lengths"] == {1: 2, 2: 1}

    def test_pageranks_survive_float_reinterpretation(self, fixture_path):
        result = load_cpp_index(fixture_path)
        assert result["doc_pageranks"][1] == pytest.approx(0.6, abs=1e-6)
        assert result["doc_pageranks"][2] == pytest.approx(0.4, abs=1e-6)

    def test_inverted_index_shape(self, fixture_path):
        result = load_cpp_index(fixture_path)
        assert result["inverted_index"]["foo"] == {1: [0], 2: [0]}
        assert result["inverted_index"]["bar"] == {1: [1]}

    def test_alphabetically_first_term_in_dictionary_decodes_correctly(self, fixture_path):
        # "bar" sorts before "foo" but was inserted second -- this is the
        # specific case that would break if the reader assumed insertion
        # order matched dictionary order instead of replaying it explicitly
        result = load_cpp_index(fixture_path)
        assert result["inverted_index"]["bar"][1] == [1]

    def test_multi_position_term_decodes_gaps_correctly(self, tmp_path):
        # a term appearing 3 times in one document, at non-trivial gaps --
        # exercises the delta-encoding/accumulation logic specifically
        data = build_fixture_index_bin(
            terms={"repeated": {1: [2, 5, 6]}},
            doc_lengths={1: 7}, doc_urls={1: "http://x.com"},
            doc_pageranks={1: 1.0}, avg_doc_length=7.0, total_docs_count=1,
        )
        path = tmp_path / "multi_pos.bin"
        path.write_bytes(data)
        result = load_cpp_index(str(path))
        assert result["inverted_index"]["repeated"][1] == [2, 5, 6]


class TestErrorHandling:
    def test_bad_magic_bytes_raises(self, tmp_path):
        path = tmp_path / "bad_magic.bin"
        path.write_bytes(b"NOTREAL!" + b"\x00" * 60)
        with pytest.raises(CppIndexFormatError, match="magic"):
            load_cpp_index(str(path))

    def test_wrong_version_raises(self, tmp_path):
        data = bytearray(build_fixture_index_bin(total_docs_count=0))
        struct.pack_into("<I", data, 8, 1)  # patch version 2 -> 1 (the pre-PageRank format)
        path = tmp_path / "old_version.bin"
        path.write_bytes(bytes(data))
        with pytest.raises(CppIndexFormatError, match="version"):
            load_cpp_index(str(path))

    def test_truncated_file_raises_not_crashes_silently(self, tmp_path):
        path = tmp_path / "truncated.bin"
        path.write_bytes(MAGIC + b"\x02\x00\x00\x00")  # magic + version, nothing else
        with pytest.raises(CppIndexFormatError):
            load_cpp_index(str(path))


class TestAgainstRealCommittedIndex:
    """Secondary sanity pass against the actual data/index.bin, if present.
    This is the same byte-exact verification performed manually when this
    reader was first built (decoded position count matches the file's own
    declared count; the read cursor lands exactly on the next section's
    offset) -- now automated instead of a one-off manual check."""

    REAL_INDEX_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "index.bin"

    @pytest.mark.skipif(not REAL_INDEX_PATH.exists(), reason="data/index.bin not present in this clone")
    def test_loads_without_error_and_has_documents(self):
        result = load_cpp_index(str(self.REAL_INDEX_PATH))
        assert result["total_docs_count"] > 0
        assert len(result["doc_urls"]) == result["total_docs_count"]

    @pytest.mark.skipif(not REAL_INDEX_PATH.exists(), reason="data/index.bin not present in this clone")
    def test_every_posting_position_list_is_non_empty(self):
        # a term/doc pair should never exist in the index with zero recorded
        # positions -- that would mean a posting was created but never populated
        result = load_cpp_index(str(self.REAL_INDEX_PATH))
        for term, doc_positions in result["inverted_index"].items():
            for doc_id, positions in doc_positions.items():
                assert len(positions) > 0, f"{term!r} in doc {doc_id} has no positions"
