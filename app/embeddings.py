from functools import lru_cache

from sentence_transformers import SentenceTransformer

from .config import settings


@lru_cache(maxsize=1)
def _model() -> SentenceTransformer:
    model = SentenceTransformer(settings.embed_model, device=settings.device or None)
    if model.device.type == "cuda":
        model.half()  # GPU'da yarim aniqlik: xotira 2 baravar kam va tezroq, vektorlar deyarli o'zgarmaydi
    return model


def embed_passages(texts: list[str]) -> list[list[float]]:
    prefixed = [settings.embed_passage_prefix + t for t in texts]
    return _model().encode(prefixed, batch_size=16, normalize_embeddings=True).tolist()


def embed_query(text: str) -> list[float]:
    return _model().encode(settings.embed_query_prefix + text, normalize_embeddings=True).tolist()


def warm_up() -> None:
    _model()
