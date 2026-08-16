"""app/tokenizer.py -- the shared normalization pipeline every other module
(indexing, parsing, spellcheck, snippets) depends on being consistent."""
from app.tokenizer import basic_tokenize, tokenize


class TestTokenize:
    def test_lowercases(self):
        assert tokenize("PYTHON") == tokenize("python")

    def test_strips_punctuation(self):
        assert tokenize("hello, world!") == tokenize("hello world")

    def test_removes_stopwords(self):
        # "the"/"is"/"a" carry no retrieval signal and should vanish entirely,
        # not just get stemmed into something unrecognizable
        tokens = tokenize("the cat is a cat")
        assert "the" not in tokens
        assert "is" not in tokens
        assert "a" not in tokens

    def test_stems_related_word_forms_to_the_same_term(self):
        # this is the entire point of stemming: "running"/"runs"/"run" must
        # collapse to one indexed term, or a query for one misses the others
        assert tokenize("running")[0] == tokenize("runs")[0] == tokenize("run")[0]

    def test_and_or_not_are_stopwords(self):
        # load-bearing for query_parser.py's case-sensitive operator fix: lowercase
        # "and"/"or"/"not" MUST tokenize to nothing, or they'd leak into required/
        # optional/excluded as real search terms once they stop being treated as
        # operator syntax
        assert tokenize("and") == []
        assert tokenize("or") == []
        assert tokenize("not") == []

    def test_empty_string_returns_empty_list(self):
        assert tokenize("") == []

    def test_pure_punctuation_returns_empty_list(self):
        assert tokenize("!!! ??? ...") == []

    def test_full_pipeline_example(self):
        # the exact example from the design doc's Component Documentation --
        # kept here so the documented behavior has a real regression test, not
        # just prose asserting it
        result = tokenize("The Python Developers were Running Fast.")
        assert result == ["python", "develop", "run", "fast"]


class TestBasicTokenize:
    def test_no_stemming(self):
        # basic_tokenize exists specifically so spellcheck/suggest can show real,
        # readable word forms -- stemming would turn "engineering" into "engin"
        assert "running" in basic_tokenize("running")
        assert "run" not in basic_tokenize("running")

    def test_no_stopword_removal(self):
        # spell-checking "the" against a corpus dictionary needs "the" to survive
        # tokenization, unlike the indexing pipeline where it's pure noise
        assert "the" in basic_tokenize("the cat")

    def test_still_lowercases_and_strips_punctuation(self):
        assert basic_tokenize("Hello, World!") == ["hello", "world"]
