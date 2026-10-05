"""Relatedness for the visual field: texts → unit vectors.

The field arranges what the agent sees by how related it is to what it is
looking at. SentenceEmbedder uses the same MiniLM model as the memory
vault; HashEmbedder is a dependency-free fallback (and what tests use).
"""

import hashlib
import logging
import math
import re
import threading
from typing import Callable, List, Optional

log = logging.getLogger(__name__)

Embedder = Callable[[List[str]], List[List[float]]]

_TOKEN = re.compile(r"[a-z0-9']+")


class HashEmbedder:
    """Bag of words and word pairs hashed into a fixed vector. Crude, fast, deterministic."""

    close_floor = 0.12   # unrelated text scores ~0 here

    def __init__(self, dim: int = 256):
        self.dim = dim

    def _one(self, text: str) -> List[float]:
        vec = [0.0] * self.dim
        toks = _TOKEN.findall((text or "").lower())
        grams = toks + [f"{a} {b}" for a, b in zip(toks, toks[1:])]
        for g in grams:
            h = int.from_bytes(hashlib.md5(g.encode()).digest()[:8], "little")
            vec[h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def __call__(self, texts: List[str]) -> List[List[float]]:
        return [self._one(t) for t in texts]


class SentenceEmbedder:
    """MiniLM sentence embeddings, loaded on first use; falls back to hashing if unavailable."""

    @property
    def close_floor(self) -> float:
        # MiniLM gives unrelated text ~0.1–0.2; the hashed fallback gives ~0.
        return self._fallback.close_floor if self._fallback else 0.25

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model_name = model_name
        self._model = None
        self._fallback: Optional[HashEmbedder] = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._model is not None or self._fallback is not None:
                return
            try:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer(self.model_name)
                log.info("[loop] field embedder: %s", self.model_name)
            except Exception as exc:
                log.warning("[loop] sentence embedder unavailable (%s) — using hashed fallback", exc)
                self._fallback = HashEmbedder()

    def __call__(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        self._load()
        if self._fallback:
            return self._fallback(texts)
        vecs = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return [list(map(float, v)) for v in vecs]


def cosine(a: Optional[List[float]], b: Optional[List[float]]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))
