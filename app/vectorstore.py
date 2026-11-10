import hashlib
import re
import time
from dataclasses import dataclass

import chromadb
import numpy as np

from .chunking import Chunk
from .config import settings

_client = chromadb.PersistentClient(path=str(settings.data_dir / "chroma"))
# Vektor o'lchami modelga bog'liq, shuning uchun har bir embedding modeli o'z kolleksiyasida saqlanadi
_collection = _client.get_or_create_collection(
    "chunks_" + re.sub(r"[^a-z0-9]+", "_", settings.embed_model.lower()).strip("_"),
    metadata={"hnsw:space": "cosine"},
)

# Baza o'zgarganda oshadi — BM25 indeksi eskirganini bilish uchun
version = 0


@dataclass
class Hit:
    text: str
    source: str
    title: str
    url: str | None
    locator: str | None
    score: float  # qidiruv bali (reranker yoki RRF; faqat tartiblash uchun)


def replace_document(
    source: str,
    title: str,
    url: str | None,
    chunks: list[Chunk],
    embeddings: list[list[float]],
) -> None:
    """Hujjatni qayta yuklashda eski bo'laklar o'chiriladi (dublikat bo'lmaydi)."""
    global version
    version += 1
    _collection.delete(where={"source": source})
    if not chunks:
        return
    ids = [hashlib.sha1(f"{source}#{i}".encode()).hexdigest() for i in range(len(chunks))]
    metadatas = [
        {"source": source, "title": title, "url": url or "", "locator": c.locator or "", "chunk": i}
        for i, c in enumerate(chunks)
    ]
    documents = [c.text for c in chunks]
    step = _client.get_max_batch_size()  # katta kodeks bir martada qo'shish chegarasidan oshib ketishi mumkin
    for start in range(0, len(ids), step):
        part = slice(start, start + step)
        _collection.add(
            ids=ids[part],
            documents=documents[part],
            embeddings=embeddings[part],
            metadatas=metadatas[part],
        )


def _to_hit(text: str, meta: dict) -> Hit:
    return Hit(
        text=text,
        source=meta["source"],
        title=meta["title"],
        url=meta["url"] or None,
        locator=meta["locator"] or None,
        score=0.0,
    )


_PAGE = 5000
_docs_cache: tuple[int, list[dict], float] | None = None


def _get_all(include: list[str], dtype=np.float32) -> dict:
    """Kolleksiyani qismlab o'qiydi: hammasini bir so'rovda olsa, katta bazada (yuz minglab bo'lak) SQLite
    "too many SQL variables" xatosini beradi. Avval id lar offset bilan, keyin ma'lumot id paketlari bo'yicha
    olinadi — ChromaDB offset bilan vektorlarni so'raganda "Error finding id" beradi."""
    all_ids: list[str] = []
    while True:
        page = _collection.get(include=[], limit=_PAGE, offset=len(all_ids))
        if not page["ids"]:
            break
        all_ids += page["ids"]
    ids: list[str] = []
    columns: dict[str, list] = {name: [] for name in include}
    for start in range(0, len(all_ids), _PAGE):
        page = _collection.get(ids=all_ids[start:start + _PAGE], include=include)
        ids += page["ids"]
        for name in include:
            columns[name].append(np.asarray(page[name], dtype=dtype) if name == "embeddings" else page[name])
    data: dict = {"ids": ids}
    for name, parts in columns.items():
        if name == "embeddings":
            data[name] = np.concatenate(parts) if parts else np.zeros((0, 0), dtype)
        else:
            data[name] = [item for part in parts for item in part]
    return data


def all_chunks() -> tuple[list[Hit], np.ndarray]:
    """Barcha bo'laklar va ularning vektorlari (BM25 va aniq vektor qidiruv uchun), tartibi barqaror."""
    # Vektorlar float16 da: float32 da ular sahifalar -> birlashtirish -> tartiblash bosqichlarida 3 marta nusxalanib,
    # yuklash paytida xotira cho'qqisini ~3 GB ga chiqarardi; sifatga ta'siri sezilmaydi (o'xshashlik 3-4 xona aniqlikda)
    data = _get_all(["documents", "metadatas", "embeddings"], dtype=np.float16)
    # O'qish paytida hujjat qo'shilsa, bir id ikki marta kelishi mumkin — oxirgisi qoladi
    order = list({data["ids"][i]: i for i in sorted(range(len(data["ids"])), key=lambda i: data["ids"][i])}.values())
    hits = [_to_hit(data["documents"][i], data["metadatas"][i]) for i in order]
    vectors = data["embeddings"][order] if order else np.zeros((0, 0), np.float16)
    del data
    return hits, vectors


def list_documents() -> list[dict]:
    """Hujjatlar ro'yxati; katta bazada sekin bo'lgani uchun baza o'zgarmaguncha keshlanadi."""
    global _docs_cache
    # ommaviy yuklash paytida baza har hujjatda o'zgaradi — katta bazada ro'yxat 10 daqiqada bir yangilanadi
    if _docs_cache and (_docs_cache[0] == version or (len(_docs_cache[1]) > 500 and time.time() - _docs_cache[2] < 600)):
        return _docs_cache[1]
    docs: dict[str, dict] = {}
    for meta in _get_all(["metadatas"])["metadatas"]:
        entry = docs.setdefault(
            meta["source"],
            {"source": meta["source"], "title": meta["title"], "url": meta["url"] or None, "chunks": 0},
        )
        entry["chunks"] += 1
    result = sorted(docs.values(), key=lambda d: d["source"])
    _docs_cache = (version, result, time.time())
    return result


def is_empty() -> bool:
    return _collection.count() == 0


def delete_document(source: str) -> int:
    global version
    version += 1
    existing = _collection.get(where={"source": source})["ids"]
    if existing:
        _collection.delete(ids=existing)
    return len(existing)
