"""Oddiy BM25 — so'z bo'yicha qidiruv (embedding o'zbekchada zaif bo'lgan holatlar uchun)."""
import math
import re
from array import array
from collections import Counter
from functools import lru_cache

import numpy as np

# Oʻ / Gʻ va turli xil apostroflar: "Oʻzbekiston" == "O'zbekiston" == "Ozbekiston"
_APOSTROPHES = re.compile(r"[ʻʼ'’‘`´]")
_WORD = re.compile(r"\w+", re.UNICODE)
# O'zbek tili agglyutinativ (til, tili, tilidir...), shuning uchun so'z boshini olamiz
_PREFIX_LEN = 5
# So'z boshi qisqa o'zaklarda yetmaydi ("kun" / "kunni", "yillik" / "yilgi"), shuning uchun
# qo'shimchalari olib tashlangan o'zak ham alohida token bo'ladi
_SUFFIXES = sorted(
    ["lar", "ning", "ni", "ga", "ka", "qa", "da", "dan", "ta", "tan", "gacha", "dagi", "dir", "imiz", "ingiz",
     "im", "ing", "i", "si", "lik", "liq", "ligi", "lig", "gi", "ki", "qi", "chi"],
    key=len,
    reverse=True,
)


@lru_cache(maxsize=None)
def _stem(word: str) -> str:
    """Oxiridagi qo'shimchalarni ketma-ket olib tashlaydi, o'zak kamida 3 harf qoladi."""
    stripped = True
    while stripped:
        stripped = False
        for suffix in _SUFFIXES:
            if word.endswith(suffix) and len(word) - len(suffix) >= 3:
                word, stripped = word[: -len(suffix)], True
                break
    return word


def tokenize(text: str) -> list[str]:
    text = _APOSTROPHES.sub("", text.lower())
    tokens = []
    for word in _WORD.findall(text):
        prefix, stem = word[:_PREFIX_LEN], _stem(word)
        tokens.append(prefix)
        if stem != prefix:
            tokens.append(stem)
    return tokens


class BM25Index:
    """Teskari indeks: har bir token uchun uni o'z ichiga olgan bo'laklar va chastotalar (ixcham massivlarda).
    So'rovda faqat savol tokenlarining ro'yxatlari ko'riladi — yuz minglab bo'lakda ham tez va kam xotira."""

    def __init__(self, texts: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.size = len(texts)
        docs: dict[str, array] = {}
        freqs: dict[str, array] = {}
        lengths = np.zeros(self.size, np.float32)
        for i, text in enumerate(texts):
            tf = Counter(tokenize(text))
            lengths[i] = sum(tf.values())
            for term, f in tf.items():
                if term not in docs:
                    docs[term], freqs[term] = array("i"), array("H")
                docs[term].append(i)
                freqs[term].append(min(f, 65535))
        self.docs, self.freqs = docs, freqs
        self.idf = {t: math.log(1 + (self.size - len(d) + 0.5) / (len(d) + 0.5)) for t, d in docs.items()}
        avg_len = float(lengths.mean()) if self.size else 1.0
        self.norm = k1 * (1 - b + b * lengths / (avg_len or 1))

    def top(self, query: str, limit: int, mask=None) -> list[int]:
        """Eng mos hujjatlar indekslari (ball > 0 bo'lganlari), kamayish tartibida.
        mask berilsa, faqat mask[i] rost bo'lganlari (masalan, bitta hujjat bo'laklari) qaraladi."""
        scores = np.zeros(self.size, np.float32)
        for term in set(tokenize(query)):
            if term not in self.docs:
                continue
            ids = np.frombuffer(self.docs[term], dtype=np.int32)
            f = np.frombuffer(self.freqs[term], dtype=np.uint16).astype(np.float32)
            scores[ids] += self.idf[term] * f * (self.k1 + 1) / (f + self.norm[ids])
        if mask is not None:
            scores[~mask] = 0
        found = int(np.count_nonzero(scores))
        if not found:
            return []
        k = min(limit, found)
        best = np.argpartition(-scores, k - 1)[:k]
        return [int(i) for i in best[np.argsort(-scores[best])]]
