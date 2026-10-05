"""Search-text normalization shared by the list query and the count query.

Case, accents, repeated whitespace, hyphens and ordinary surrounding punctuation never change what matches. Technical tokens
(C++, C#, .NET, Node.js) and deliberately quoted phrases are preserved. The same folding is applied to the stored text
(`fold_sql`) and to the query (`fold_text`) so the two always agree.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import List

# Identical mapping on both sides (PostgreSQL translate() is character-for-character, so every entry is 1:1).
_ACCENT_GROUPS = (
    ("àáâãäåāăą", "a"), ("çćč", "c"), ("ďđ", "d"), ("èéêëēėęě", "e"), ("ğ", "g"), ("ìíîïīį", "i"), ("ł", "l"),
    ("ñńň", "n"), ("òóôõöøōő", "o"), ("ř", "r"), ("śšş", "s"), ("ť", "t"), ("ùúûüūůűų", "u"), ("ýÿ", "y"),
    ("źżž", "z"), ("-–—‑", " "),
)
_ACCENT_FROM = "".join(chars for chars, _ in _ACCENT_GROUPS)
_ACCENT_TO = "".join(ascii_ * len(chars) for chars, ascii_ in _ACCENT_GROUPS)
assert len(_ACCENT_FROM) == len(_ACCENT_TO)
_FOLD_TABLE = {ord(src): dst for src, dst in zip(_ACCENT_FROM, _ACCENT_TO)}

_EDGE_PUNCT = ",;:!?()[]{}<>\"'`“”‘’«»…*"
_QUERY_TOKEN = re.compile(r'"([^"]*)"|(\S+)')


def fold_text(text: str) -> str:
    """Lower-case, NFC-normalize, drop accents and treat hyphens as spaces (mirror of fold_sql)."""
    return unicodedata.normalize("NFC", text).lower().translate(_FOLD_TABLE)


def fold_sql(expression: str) -> str:
    """SQL expression equivalent of fold_text for a column/expression (no extension required)."""
    return f"translate(lower({expression}), '{_ACCENT_FROM}', '{_ACCENT_TO}')"


@dataclass(frozen=True)
class SearchTerm:
    text: str          # folded, punctuation-trimmed
    phrase: bool = False


def _trim_token(token: str) -> str:
    token = token.strip(_EDGE_PUNCT)
    # a trailing period is sentence punctuation ("python.") but ".NET" / "Node.js" keep their dots
    while token.endswith(".") and len(token) > 1:
        token = token[:-1]
    return token


_PHRASE_SYNONYMS = (
    (re.compile(r"\bco ?ops?\b"), "coop"),
    (re.compile(r"\bnew ?grad(?:uate)?s?\b"), "newgrad"),
    (re.compile(r"\bentry ?level\b"), "entrylevel"),
    (re.compile(r"\bsite reliability\b"), "sre"),
    (re.compile(r"\bmachine learning\b"), "ml"),
    (re.compile(r"\bartificial intelligence\b"), "ai"),
    (re.compile(r"\bback ?end\b"), "backend"),
    (re.compile(r"\bfront ?end\b"), "frontend"),
    (re.compile(r"\bfull ?stack\b"), "fullstack"),
)


def parse_search_query(raw: str) -> List[SearchTerm]:
    """Split a user query into terms. Quoted text is one phrase; everything else is folded, de-punctuated words."""
    if not raw:
        return []
    text = unicodedata.normalize("NFC", raw).replace("\u00a0", " ")
    if text.count('"') % 2 == 1:                      # an unmatched quote is just punctuation
        index = text.rfind('"')
        text = text[:index] + " " + text[index + 1 :]
    terms: List[SearchTerm] = []
    for position, segment in enumerate(text.split('"')):
        quoted = position % 2 == 1
        folded = " ".join(fold_text(segment).split())
        if quoted:
            phrase = " ".join(filter(None, (_trim_token(word) for word in folded.split())))
            if phrase:
                terms.append(SearchTerm(phrase, phrase=True))
            continue
        for pattern, replacement in _PHRASE_SYNONYMS:     # same vocabulary the list already understood ("co-op", "machine learning", ...)
            folded = pattern.sub(replacement, folded)
        for word in folded.split():
            word = _trim_token(word)
            if word:
                terms.append(SearchTerm(word))
    return terms


_COLUMN = r"(?:jp\.title|c\.name|l\.location|jl\.location|jp\.workplace_type|s_s\.name)"
_LIKE = re.compile(rf"\b({_COLUMN})\s+(NOT\s+)?ILIKE\b")
_REGEX = re.compile(rf"\b({_COLUMN})\s+(!?~\*)")


def fold_search_clause(sql: str) -> str:
    """Rewrite a per-term search clause so every text comparison runs on folded text."""
    sql = _LIKE.sub(lambda m: f"{fold_sql(m.group(1))} {m.group(2) or ''}ILIKE", sql)
    return _REGEX.sub(lambda m: f"{fold_sql(m.group(1))} {m.group(2)}", sql)


def unfold_sql(sql: str) -> str:
    """Inverse of fold_search_clause's column wrapping (used by tests that assert on the original clause shapes)."""
    for column in ("jp.title", "c.name", "l.location", "jl.location", "jp.workplace_type", "s_s.name"):
        sql = sql.replace(fold_sql(column), column)
    return sql
