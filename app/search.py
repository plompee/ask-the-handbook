"""BM25 keyword search over chunks - no embeddings service needed, works offline, handles any language with words."""
from __future__ import annotations

import math
import re
from collections import Counter

STOP = set("""a an and are as at be been but by can could do does for from had has have how i if in into is it its
me my no not of on or our so than that the their them then there these they this to was we were what when where which
who why will with would you your about any all also am did get just more most should some such very""".split())


def stem(word: str) -> str:
    """Tiny suffix stripper so 'cancelling', 'cancelled' and 'cancel' match."""
    for suffix in ("ations", "ation", "ings", "ing", "ies", "ied", "ed", "es", "s", "ly"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            word = word[: -len(suffix)] + ("y" if suffix in ("ies", "ied") else "")
            # "stopp(ed)" -> "stop", British "cancell(ing)" -> "cancel"; keep real doubles like "pass", "staff", "call".
            if suffix in ("ing", "ings", "ed") and len(word) > 3 and word[-1] == word[-2]:
                if word[-1] not in "aeiouslfz" or (word[-1] == "l" and len(word) > 5):
                    word = word[:-1]
            return word
    return word


def tokenize(text: str) -> list[str]:
    return [stem(w) for w in re.findall(r"\w+", text.lower()) if w not in STOP and (len(w) > 1 or w.isdigit())]


class Index:
    """Okapi BM25 over a list of chunks (each a dict with 'text' and 'doc_name')."""

    def __init__(self, chunks: list[dict], k1: float = 1.5, b: float = 0.75):
        self.chunks, self.k1, self.b = chunks, k1, b
        self.tf = [Counter(tokenize(f"{c['doc_name']} {c['text']}")) for c in chunks]
        self.len = [sum(t.values()) for t in self.tf]
        self.avg = (sum(self.len) / len(self.len)) if self.len else 0
        df = Counter(term for t in self.tf for term in t)
        n = len(chunks)
        self.idf = {term: math.log(1 + (n - f + 0.5) / (f + 0.5)) for term, f in df.items()}

    def search(self, query: str, k: int = 8) -> list[tuple[dict, float]]:
        terms = set(tokenize(query))
        scored = []
        for i, tf in enumerate(self.tf):
            s = 0.0
            for term in terms:
                f = tf.get(term)
                if f:
                    s += self.idf[term] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg))
            if s > 0:
                scored.append((self.chunks[i], s))
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]


_cache: tuple[tuple, Index] | None = None


def index_for(chunks: list[dict]) -> Index:
    """Reuses the index until the set of chunks changes (upload or delete)."""
    global _cache
    key = (len(chunks), chunks[-1]["id"] if chunks else None, sum(c["id"] for c in chunks))
    if _cache is None or _cache[0] != key:
        _cache = (key, Index(chunks))
    return _cache[1]
