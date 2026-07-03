"""Deterministic text-similarity helpers used by the checker, baselines, eval,
and leakage steps.

Design goal: the whole offline pipeline must run with the standard library
ALONE. So every third-party accelerator (scikit-learn, sentence-transformers)
is optional and imported lazily; when it is missing we fall back to a
documented pure-Python implementation and record which backend was used.

Metrics implemented here:

* ``tokenize``            -- lowercase content-word tokens (stopwords removed).
* ``overlap_coefficient`` -- |A n B| / |A|  (used for grounding: how much of the
                             answer is covered by the source).
* ``jaccard``             -- |A n B| / |A u B| (used for transfer/dup checks).
* ``tfidf_cosine_matrix`` -- TF-IDF cosine similarity (sklearn if available,
                             else a pure-Python TF-IDF).
* ``embed`` / cosine      -- a vector-retrieval signal: sentence-transformers if
                             installable, else a documented hashing embedding
                             proxy (feature hashing of tokens + char n-grams).
* ``ngram_overlap``       -- normalized shared n-gram fraction (leakage).
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Dict, List, Optional, Sequence, Set, Tuple

# A small, generic English stopword list -- deliberately not exhaustive; it just
# removes function words so overlap reflects content, not grammar.
_STOPWORDS: Set[str] = {
    "a", "an", "the", "and", "or", "but", "if", "then", "else", "when", "of",
    "to", "in", "on", "for", "with", "as", "by", "at", "from", "into", "is",
    "are", "was", "were", "be", "been", "being", "it", "its", "this", "that",
    "these", "those", "which", "who", "whom", "whose", "what", "how", "why",
    "where", "will", "would", "can", "could", "should", "may", "might", "do",
    "does", "did", "has", "have", "had", "not", "no", "yes", "than", "so",
    "such", "there", "here", "their", "they", "them", "he", "she", "we", "you",
    "i", "his", "her", "our", "your", "about", "over", "under", "between",
    "because", "during", "each", "more", "most", "some", "any", "all", "both",
    "one", "two", "also", "very", "up", "down", "out", "off", "per", "via",
    "following", "question", "choose", "correct", "best", "answer", "option",
}

_WORD_RE = re.compile(r"[a-z0-9][a-z0-9\-']*")

# Which similarity backends actually loaded (reported in artifacts for honesty).
BACKENDS: Dict[str, str] = {"tfidf": "pure-python", "vector": "pure-python-hashing"}


def tokenize(text: str, keep_stopwords: bool = False) -> List[str]:
    """Lowercase content tokens. Strips a common set of stopwords by default."""
    toks = _WORD_RE.findall((text or "").lower())
    if keep_stopwords:
        return toks
    return [t for t in toks if t not in _STOPWORDS and len(t) > 1]


def token_set(text: str) -> Set[str]:
    return set(tokenize(text))


def overlap_coefficient(a: str, b: str) -> float:
    """|tokens(a) n tokens(b)| / |tokens(a)|. 1.0 => a fully covered by b.

    Used for grounding: does the *source* (b) cover the *answer* (a)?
    """
    ta = token_set(a)
    tb = token_set(b)
    if not ta:
        return 0.0
    return len(ta & tb) / len(ta)


def jaccard(a: str, b: str) -> float:
    """|A n B| / |A u B| over content tokens."""
    ta = token_set(a)
    tb = token_set(b)
    if not ta and not tb:
        return 0.0
    union = ta | tb
    if not union:
        return 0.0
    return len(ta & tb) / len(union)


# --------------------------------------------------------------------------
# TF-IDF cosine -- sklearn accelerated, pure-python fallback
# --------------------------------------------------------------------------
def _sklearn_tfidf_cosine(docs: Sequence[str]) -> Optional["list[list[float]]"]:
    try:
        from sklearn.feature_extraction.text import TfidfVectorizer  # type: ignore
        from sklearn.metrics.pairwise import cosine_similarity  # type: ignore
    except Exception:
        return None
    try:
        vec = TfidfVectorizer(stop_words="english", token_pattern=r"(?u)\b[a-zA-Z0-9][a-zA-Z0-9\-']+\b")
        matrix = vec.fit_transform(list(docs))
        sim = cosine_similarity(matrix)
        BACKENDS["tfidf"] = "scikit-learn"
        return sim.tolist()
    except Exception:
        return None


def _pure_tfidf_vectors(docs: Sequence[str]) -> List[Dict[str, float]]:
    tokenized = [tokenize(d) for d in docs]
    n_docs = len(tokenized)
    df: Dict[str, int] = {}
    for toks in tokenized:
        for t in set(toks):
            df[t] = df.get(t, 0) + 1
    vectors: List[Dict[str, float]] = []
    for toks in tokenized:
        tf: Dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        vec: Dict[str, float] = {}
        for t, c in tf.items():
            idf = math.log((1 + n_docs) / (1 + df.get(t, 0))) + 1.0
            vec[t] = (c / max(1, len(toks))) * idf
        # L2 normalize
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        vectors.append({t: v / norm for t, v in vec.items()})
    return vectors


def _sparse_cosine(a: Dict[str, float], b: Dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())


def tfidf_cosine_matrix(docs: Sequence[str]) -> List[List[float]]:
    """Full pairwise TF-IDF cosine similarity matrix for ``docs``."""
    if len(docs) == 0:
        return []
    sk = _sklearn_tfidf_cosine(docs)
    if sk is not None:
        return sk
    vecs = _pure_tfidf_vectors(docs)
    n = len(vecs)
    out = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i, n):
            s = _sparse_cosine(vecs[i], vecs[j])
            out[i][j] = s
            out[j][i] = s
    return out


def tfidf_cross_similarity(queries: Sequence[str], corpus: Sequence[str]) -> List[List[float]]:
    """Rows = queries, cols = corpus; TF-IDF cosine over the joint vocabulary.

    Fits one TF-IDF space on (corpus + queries) so both sides share vocabulary.
    """
    if not queries or not corpus:
        return [[0.0] * len(corpus) for _ in queries]
    joint = list(corpus) + list(queries)
    matrix = tfidf_cosine_matrix(joint)
    nc = len(corpus)
    out: List[List[float]] = []
    for qi in range(len(queries)):
        row_idx = nc + qi
        out.append([matrix[row_idx][cj] for cj in range(nc)])
    return out


# --------------------------------------------------------------------------
# Vector / embedding retrieval -- sentence-transformers, else hashing proxy
# --------------------------------------------------------------------------
_ST_MODEL = None
_ST_TRIED = False


def _load_sentence_transformer():
    global _ST_MODEL, _ST_TRIED
    if _ST_TRIED:
        return _ST_MODEL
    _ST_TRIED = True
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore

        _ST_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
        BACKENDS["vector"] = "sentence-transformers/all-MiniLM-L6-v2"
    except Exception:
        _ST_MODEL = None
    return _ST_MODEL


_HASH_DIM = 512


def _hashing_embed(text: str) -> List[float]:
    """Documented fallback embedding: feature-hash content tokens and character
    trigrams into a fixed-dim L2-normalized vector.

    LIMITATION: this is a bag-of-features proxy, NOT a learned semantic
    embedding. It captures lexical/morphological overlap (so paraphrases with
    shared roots score higher) but has no real notion of synonymy. It exists so
    the "vector retrieval" baseline runs everywhere; when sentence-transformers
    is installed we use it instead and record that in the backend report.
    """
    vec = [0.0] * _HASH_DIM
    toks = tokenize(text)
    features: List[str] = list(toks)
    for tok in toks:
        padded = "#" + tok + "#"
        for i in range(len(padded) - 2):
            features.append("$" + padded[i : i + 3])
    for feat in features:
        h = int(hashlib.md5(feat.encode("utf-8")).hexdigest(), 16)
        idx = h % _HASH_DIM
        sign = 1.0 if (h >> 16) & 1 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def embed(texts: Sequence[str]) -> List[List[float]]:
    """Embed a list of texts, preferring sentence-transformers."""
    model = _load_sentence_transformer()
    if model is not None:
        try:
            arr = model.encode(list(texts), normalize_embeddings=True)
            return [list(map(float, row)) for row in arr]
        except Exception:
            pass
    return [_hashing_embed(t) for t in texts]


def dense_cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def vector_cross_similarity(queries: Sequence[str], corpus: Sequence[str]) -> List[List[float]]:
    if not queries or not corpus:
        return [[0.0] * len(corpus) for _ in queries]
    q_emb = embed(list(queries))
    c_emb = embed(list(corpus))
    return [[dense_cosine(q, c) for c in c_emb] for q in q_emb]


# --------------------------------------------------------------------------
# n-gram overlap for leakage
# --------------------------------------------------------------------------
def _ngrams(text: str, n: int) -> Set[Tuple[str, ...]]:
    toks = tokenize(text, keep_stopwords=True)
    if len(toks) < n:
        return {tuple(toks)} if toks else set()
    return {tuple(toks[i : i + n]) for i in range(len(toks) - n + 1)}


def ngram_overlap(a: str, b: str, n: int) -> float:
    """Fraction of a's n-grams that also appear in b (containment). High => a is
    substantially copied from / into b."""
    ga = _ngrams(a, n)
    gb = _ngrams(b, n)
    if not ga:
        return 0.0
    return len(ga & gb) / len(ga)


def normalized(text: str) -> str:
    """Whitespace/punct-insensitive normalized form for exact-match detection."""
    return " ".join(tokenize(text, keep_stopwords=True))
