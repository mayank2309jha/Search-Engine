import re  # regex module, used to find and strip out quoted phrases from the raw query
# shared pipeline: lowercase -> strip punctuation -> split -> remove stopwords -> stem
from app.tokenizer import tokenize

# Parses the raw query string into a structured form: which terms are required (AND), optional (OR), excluded (NOT), and which substrings are quoted phrases. This is the one place that understands query syntax — everything downstream just consumes its output.

# the three literal keywords this parser recognizes as operators -- matched CASE-
# SENSITIVELY (exact-case "AND"/"OR"/"NOT" only), the same convention real search
# engines (Google, PubMed, Westlaw) use for exactly this reason: "cats AND dogs" is
# a deliberate boolean query, but "I like cats and dogs" is an ordinary English
# sentence, and there's no way to tell the two apart from the word alone if matching
# is case-insensitive. This was originally case-insensitive and got measured, not
# assumed, to be a real bug: after fixing the sticky-mode promotion bug below (a bare
# word before the first operator now correctly promotes to required when that
# operator is AND), re-running scripts/evaluate.py showed a natural-language
# semantic-subset query like "teaching kids to read and do math better" collapsing
# from a perfect 1.0 P@10/MRR/nDCG@10 to 0.0 -- its ordinary "and" was being treated
# as a required-AND boolean operator, intersecting four barely-related terms down to
# zero candidates. Every query in the evaluation set that contains a lowercase "and"
# had the same failure mode. Case-sensitive matching fixes it directly: lowercase
# "and"/"or"/"not" already tokenize to nothing at all (they're stopwords -- see
# tokenizer.py), so an ordinary conjunction now contributes zero terms, exactly like
# every other stopword, instead of silently corrupting query structure.
BOOLEAN_OPERATORS = {"AND", "OR", "NOT"}

# matches an optional leading "NOT " followed by a double-quoted phrase; group(1) captures "NOT " (or None), group(2) captures the phrase text
PHRASE_PATTERN = re.compile(r'(NOT\s+)?"([^"]*)"', re.IGNORECASE)


# turns a raw query string into required/optional/excluded terms plus phrase lists
def parse_query(query: str) -> dict:
    required = []  # terms that MUST be present in a matching doc (AND mode)
    # terms where ANY ONE being present is enough (OR mode, and the default when no operator is active)
    optional = []
    # terms that must NOT be present in a matching doc (NOT mode)
    excluded = []
    # list of phrase term-lists that should exactly match somewhere in a doc (used later for the ranking boost)
    phrases = []
    # list of phrase term-lists that must NOT exactly match anywhere in a doc
    excluded_phrases = []

    # callback run once per quoted phrase found; removes it from the string and records it
    def extract_phrase(match: re.Match) -> str:
        # group(1) is the "NOT " prefix — present means this phrase should be excluded
        is_excluded = match.group(1) is not None
        # raw text inside the quotes, not yet tokenized
        phrase_text = match.group(2)
        # run the phrase through the same pipeline used for indexing, so its terms line up with index terms
        phrase_terms = tokenize(phrase_text)
        # only keep the phrase if tokenizing it actually produced terms (guards against empty quotes like "")
        if phrase_terms:
            if is_excluded:  # route based on whether NOT preceded this phrase
                # record as a phrase that must not appear
                excluded_phrases.append(phrase_terms)
            else:
                # record as a phrase to boost if it appears
                phrases.append(phrase_terms)
        # replace the matched text (quotes, NOT, and all) with a single space in the remaining query string
        return " "

    # strip every quoted phrase out of the query, leaving only plain words and boolean keywords behind
    remaining = PHRASE_PATTERN.sub(extract_phrase, query)

    current_mode = None  # sticky mode: None/OR means optional, AND means required, NOT means excluded — changes only when an operator keyword is seen, and persists across words until then
    first_operator_seen = False  # tracks whether we've hit the query's first operator yet
    for word in remaining.split():  # walk what's left of the query, split on whitespace
        # exact-case match only -- see BOOLEAN_OPERATORS' comment above for why. A
        # lowercase "and"/"or"/"not" falls straight through to tokenize() below,
        # same as any other word (and same as any other stopword, in practice).
        if word in BOOLEAN_OPERATORS:  # if this word IS an operator keyword rather than a search term
            # A bare word before ANY operator lands in `optional` by default (the mode-None
            # branch below) -- correct if the first operator turns out to be OR or NOT, since
            # OR is already the default and NOT doesn't retroactively change earlier words.
            # But if the first operator is AND, those words were meant to be required all
            # along: "python AND kubernetes" should mean both are required, not "python OR
            # (kubernetes required)". `optional` contains exactly those pre-operator words
            # and nothing else at this point, since no word after an operator has been
            # processed yet -- so promoting the whole list is correct, not just this word.
            if not first_operator_seen and word == "AND":
                required.extend(optional)
                optional.clear()
            first_operator_seen = True
            # switch mode — this applies to this word and every word after it, until the next operator
            current_mode = word
            continue  # an operator keyword is never itself a search term, move to the next word
        # normalize this single word through the shared pipeline (0 terms if it's a stopword, 1 otherwise)
        terms = tokenize(word)
        for term in terms:  # usually 0 or 1 term, loop defensively in case tokenize ever produces more
            if current_mode == "AND":  # currently in required mode
                required.append(term)
            elif current_mode == "NOT":  # currently in excluded mode
                excluded.append(term)
            else:  # current_mode is None or "OR" — both mean optional
                optional.append(term)

    return {  # hand back the fully structured query for main.py/ranking.py to consume
        "required": required,
        "optional": optional,
        "excluded": excluded,
        "phrases": phrases,
        "excluded_phrases": excluded_phrases,
    }

# Design decision worth stating upfront: I went with a "sticky mode" model for the boolean operators — AND/OR/NOT set a mode that applies to every word that follows, until a different operator appears. So "rust AND matching python" treats both matching and python as required, not just the one word immediately after AND. This matches how people intuitively read boolean queries, and it's simple to implement (no need to track clause boundaries or parentheses). Default with no operator at all is optional (OR) — this deliberately matches your Phase 1 behavior, where every query term was OR'd together with no boolean logic. So old queries behave identically; AND/NOT are additive narrowing on top of that default.
