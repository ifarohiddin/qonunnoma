"""Qayta tartiblash (reranking): savol va bo'lakni birga o'qiydigan cross-encoder model.

Gibrid qidiruv o'xshash moddalar ko'p bo'lganda (masalan, ta'til haqida o'nlab modda) kerakli moddani
10-20-o'ringa tushirib qo'yadi; cross-encoder esa savolga aynan javob beradigan moddani yuqoriga chiqaradi.
"""
from functools import lru_cache

from sentence_transformers import CrossEncoder

from .config import settings
from .vectorstore import Hit


@lru_cache(maxsize=1)
def _model() -> CrossEncoder:
    model = CrossEncoder(settings.rerank_model, max_length=512, device=settings.device or None)
    if model.device.type == "cuda":
        model.half()
    return model


def scores(question: str, hits: list[Hit]) -> list[float]:
    """Har bir bo'lakning savolga mosligi (katta — mosroq). Hujjat nomi ham beriladi, chunki savolda
    "Mehnat kodeksiga ko'ra ..." kabi kodeks nomi bo'lishi mumkin."""
    if not hits:
        return []
    pairs = [(question, f"{hit.title}\n{hit.text}") for hit in hits]
    return [float(s) for s in _model().predict(pairs, batch_size=16)]


def warm_up() -> None:
    if settings.rerank_model:
        _model()
