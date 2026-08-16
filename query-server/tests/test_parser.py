"""app/query_parser.py -- boolean AND/OR/NOT + phrase parsing.

Two real, previously-shipped bugs live in this module's history:
  1. A bare word before the first operator didn't promote to `required` when
     that operator turned out to be AND (fixed: retroactive promotion).
  2. Operator matching was case-INsensitive, so ordinary English "and"/"or"/
     "not" (not intended as syntax) corrupted real queries -- fixed by making
     operator matching case-sensitive. Both fixes get their own regression
     tests below, using the exact queries that exposed them originally.
"""
from app.query_parser import parse_query


class TestBareWords:
    def test_single_word_is_optional_by_default(self):
        result = parse_query("python")
        assert result["optional"] == ["python"]
        assert result["required"] == []

    def test_multiple_bare_words_are_all_optional(self):
        result = parse_query("python java")
        assert set(result["optional"]) == {"python", "java"}


class TestAndOperator:
    def test_and_kubernetes_regression(self):
        # the exact documented bug: a bare word before the first operator used
        # to land in `optional` even when that operator was AND
        result = parse_query("python AND kubernetes")
        assert set(result["required"]) == {"python", "kubernet"}
        assert result["optional"] == []

    def test_three_way_and(self):
        result = parse_query("docker AND linux AND python")
        assert set(result["required"]) == {"docker", "linux", "python"}

    def test_and_then_not(self):
        result = parse_query("engineer AND python NOT google")
        assert set(result["required"]) == {"engin", "python"}
        assert result["excluded"] == ["googl"]


class TestOrOperator:
    def test_or_is_equivalent_to_default(self):
        # OR is already the default for bare words, so an explicit OR shouldn't
        # trigger the AND-specific retroactive-promotion behavior
        result = parse_query("docker OR linux")
        assert set(result["optional"]) == {"docker", "linux"}
        assert result["required"] == []


class TestNotOperator:
    def test_bare_word_before_not_stays_optional(self):
        # unlike AND, a word before NOT should NOT retroactively change buckets --
        # "python NOT kubernetes" means "prefer python, but never show kubernetes
        # docs," not "require python"
        result = parse_query("python NOT kubernetes")
        assert result["optional"] == ["python"]
        assert result["excluded"] == ["kubernet"]


class TestCaseSensitivity:
    """Regression tests for the case-sensitivity fix -- lowercase and/or/not
    must NOT be treated as operators, or ordinary English sentences get
    silently corrupted into nonsensical boolean queries."""

    def test_lowercase_and_is_not_an_operator(self):
        result = parse_query("salt and pepper")
        # "and" tokenizes to nothing (it's a stopword) -- salt and pepper are
        # both just optional terms, no retroactive AND-promotion should fire
        assert set(result["optional"]) == {"salt", "pepper"}
        assert result["required"] == []

    def test_natural_language_query_with_lowercase_and(self):
        # the exact query that exposed this in production: a natural-language,
        # semantic-style query that happens to contain "and" as an ordinary
        # conjunction, not intended as boolean syntax at all
        result = parse_query("ways machines can learn from data")
        assert result["required"] == []
        assert result["excluded"] == []

    def test_uppercase_and_is_still_an_operator(self):
        # the fix must not lose real boolean functionality -- only case changes
        result = parse_query("python AND java")
        assert set(result["required"]) == {"python", "java"}

    def test_mixed_case_and_is_not_an_operator(self):
        # only exact-case "AND"/"OR"/"NOT" count -- "And" is just a word
        result = parse_query("rock And roll")
        assert "and" not in result["required"] + result["optional"]
        assert result["required"] == []


class TestPhrases:
    def test_quoted_phrase_extracted(self):
        result = parse_query('"machine learning"')
        assert result["phrases"] == [["machin", "learn"]]
        assert result["optional"] == []

    def test_not_before_phrase_excludes_it(self):
        result = parse_query('NOT "machine learning"')
        assert result["excluded_phrases"] == [["machin", "learn"]]
        assert result["phrases"] == []

    def test_phrase_plus_bare_word(self):
        result = parse_query('python "machine learning"')
        assert result["optional"] == ["python"]
        assert result["phrases"] == [["machin", "learn"]]

    def test_empty_quotes_produce_no_phrase(self):
        result = parse_query('""')
        assert result["phrases"] == []
        assert result["excluded_phrases"] == []


class TestEmptyAndEdgeCases:
    def test_empty_query(self):
        result = parse_query("")
        assert result == {
            "required": [], "optional": [], "excluded": [],
            "phrases": [], "excluded_phrases": [],
        }

    def test_pure_stopword_query_produces_no_terms(self):
        result = parse_query("the a is")
        assert result["optional"] == []
