"""Gibrid qidiruv: vektor (ma'no) + BM25 (so'z), Reciprocal Rank Fusion bilan birlashtiriladi,
so'ng eng yaxshi nomzodlar cross-encoder bilan qayta tartiblanadi (rerank.py).

Vektor qidiruv xotirada aniq hisoblanadi (numpy): ChromaDB'ning taxminiy HNSW indeksi qayta yuklangan
hujjatlarda eng mos bo'laklarni ham o'tkazib yuborardi, o'n minglab bo'lak uchun esa aniq hisob bir necha ms.
"""
import re
import threading
import time

import numpy as np

from . import embeddings, rerank, vectorstore
from .bm25 import BM25Index
from .chunking import split_heading
from .config import settings
from .vectorstore import Hit

CANDIDATES = 30  # har bir usuldan olinadigan nomzodlar soni
RRF_K = 60

# Savolda "106-modda", "57-moddasida" kabi aniq havola bo'lsa, o'sha modda bo'laklari birinchi qo'yiladi:
# vektor qidiruv raqamni tushunmaydi, BM25 natijasi esa birlashtirishda boshqa bo'laklar orasida yo'qoladi
_ARTICLE_REF = re.compile(r"\b(\d+)\s*[-‐‑–—]?\s*modda", re.IGNORECASE)
_ARTICLE_LINE = re.compile(r"^(\d+)-modda\b", re.MULTILINE)

# Uzun modda bir necha bo'lakka bo'linadi ("173-modda (davomi)"): qidiruv ko'pincha faqat boshini topadi,
# miqdor yoki istisno esa davomida qoladi. Eng yaxshi natijalarga modda davomi qo'shib beriladi.
_ARTICLE_START = re.compile(r"^(\d[\d.\-]*-modda)\b(?! \(davomi\))", re.MULTILINE)
_CONTINUATION = re.compile(r"^(\d[\d.\-]*-modda) \(davomi\)$", re.MULTILINE)
EXPAND_TOP = 3  # nechta eng yaxshi natijaga davomi qo'shiladi
EXPAND_MAX_CHARS = 2500  # bitta natijaga qo'shiladigan matn chegarasi

_lock = threading.Lock()
_index: BM25Index | None = None
_chunks: list[Hit] = []
_vectors = np.zeros((0, 0), np.float16)
_continuations: dict[tuple[str, str], list[int]] = {}
_index_version = -1
_built_at = 0.0


def _corpus() -> tuple[BM25Index, list[Hit], np.ndarray]:
    """Barcha bo'laklar, ularning vektorlari va BM25 indeksi; baza o'zgarganda qayta yuklanadi.
    Katta bazada qayta qurish ~1 daqiqa oladi, shuning uchun ommaviy yuklash paytida (har hujjatdan keyin baza
    o'zgaradi) ko'pi bilan settings.corpus_rebuild_seconds da bir marta quriladi — yangi hujjatlar biroz kechikib qidiruvga tushadi."""
    global _index, _chunks, _vectors, _continuations, _index_version, _built_at
    with _lock:
        stale = _index_version != vectorstore.version
        if _index is None or (stale and (len(_chunks) < 20000 or time.time() - _built_at > settings.corpus_rebuild_seconds)):
            _chunks, _vectors = vectorstore.all_chunks()
            _index = BM25Index([f"{c.title}\n{c.text}" for c in _chunks])  # vektordagi kabi hujjat nomi bilan
            _continuations = _find_continuations(_chunks)
            _index_version, _built_at = vectorstore.version, time.time()
        return _index, _chunks, _vectors


def _locator_order(hit: Hit) -> tuple[int, str]:
    # lex.uz element id'lari ("-6261740") hujjat ichida tartib bilan o'sadi
    locator = hit.locator or ""
    return (abs(int(locator)), "") if re.fullmatch(r"-?\d+", locator) else (0, locator)


def _find_continuations(chunks: list[Hit]) -> dict[tuple[str, str], list[int]]:
    found: dict[tuple[str, str], list[int]] = {}
    for i, chunk in enumerate(chunks):
        if "(davomi)" in chunk.text:
            for article in _CONTINUATION.findall(chunk.text):
                found.setdefault((chunk.source, article), []).append(i)
    for positions in found.values():
        positions.sort(key=lambda i: _locator_order(chunks[i]))
    return found


def _with_continuation(hit: Hit, chunks: list[Hit]) -> Hit:
    """Modda boshidagi bo'lakka shu moddaning davomini qo'shadi (sarlavhalarsiz, takrorlanuvchi paragraflarsiz)."""
    start = _ARTICLE_START.search(hit.text)
    positions = _continuations.get((hit.source, start.group(1))) if start else None
    if not positions:
        return hit
    seen = set(hit.text.split("\n"))
    added: list[str] = []
    size = 0
    for i in positions:
        for paragraph in split_heading(chunks[i].text)[1].split("\n"):
            if paragraph in seen:
                continue  # bo'laklar orasidagi overlap
            if size + len(paragraph) > EXPAND_MAX_CHARS:
                break
            seen.add(paragraph)
            added.append(paragraph)
            size += len(paragraph) + 1
    return Hit(**{**hit.__dict__, "text": "\n".join([hit.text, *added])}) if added else hit


def warm_up() -> None:
    """Katta bazada bo'laklarni o'qish va BM25 qurish bir daqiqagacha oladi — server ishga tushganda fonda bajariladi."""
    vectorstore.list_documents()
    if not vectorstore.is_empty():
        _corpus()


_BLOCK = 32768


def _similarities(vectors: np.ndarray, queries: np.ndarray) -> np.ndarray:
    """Hamma so'rovlarning har bir bo'lakka o'xshashligi (so'rovlar soni x bo'laklar soni). Vektorlar xotirada float16
    (yarim joy) saqlanadi; hisob float32 da, qismlab: butun matritsani float32 ga o'tkazish xotirani ikki baravar oshirardi."""
    out = np.empty((len(queries), len(vectors)), np.float32)
    for start in range(0, len(vectors), _BLOCK):
        out[:, start:start + _BLOCK] = (vectors[start:start + _BLOCK].astype(np.float32) @ queries.T).T
    return out


def _key(hit: Hit) -> tuple[str, str, str]:
    return (hit.source, hit.locator or "", hit.text[:80])


_ARTICLE_HEAD = re.compile(r"^(\d[\d.\-¹²³⁴⁵⁶⁷⁸⁹⁰]*-modda)\b", re.MULTILINE)
CODE_BOOST = 0.004  # RRF da ~4 o'rin farqiga teng
LAW_BOOST = 0.002


def _authority(title: str) -> float:
    """Kodeks/Konstitutsiya va qonun natijalari Prezident va hukumat qarorlaridan biroz yuqori: eski qarorlardagi
    stavka va muddatlar (masalan, QQS 20%) kodeksdagi amaldagi qoidadan oldin chiqib qolmasin."""
    lower = title.lower()
    old = re.search(r"\(\d{2}\.\d{2}\.(\d{4})\)", title)
    if old and int(old.group(1)) < 2021 and lower.split(":")[0].endswith(("qarori", "farmoni")):
        return -CODE_BOOST  # 2021-yildan oldingi qaror/farmon: stavkalari kodeks bilan almashgan bo'lishi mumkin
    if ":" not in lower:
        return CODE_BOOST if "kodeks" in lower or "konstitutsiya" in lower else 0.0
    return LAW_BOOST if lower.split(":")[0].endswith("qonuni") else 0.0


def _one_per_article(ranked: list, by_key: dict) -> list:
    """Bir moddaning bir necha bo'lagi (boshi va "davomi") natijalarda joy olmasin: moddaga bitta bo'lak, bor bo'lsa
    modda boshi. Davomi baribir eng yaxshi natijalarga _with_continuation orqali qo'shiladi."""
    chosen: dict[tuple[str, str], int] = {}
    out: list = []
    for key in ranked:
        hit = by_key[key]
        match = _ARTICLE_HEAD.search(hit.text)
        if not match:
            out.append(key)
            continue
        article = (hit.source, match.group(1))
        if article not in chosen:
            chosen[article] = len(out)
            out.append(key)
        elif not _ARTICLE_START.search(by_key[out[chosen[article]]].text) and _ARTICLE_START.search(hit.text):
            out[chosen[article]] = key
    return out


def hybrid_search(question: str | list[str], top_k: int, source: str | None = None) -> list[Hit]:
    """Bir yoki bir nechta so'rov bo'yicha qidiradi va natijalarni birlashtiradi.
    Birinchi so'rov — foydalanuvchi savoli (yoki uning mustaqil shakli): modda havolasi faqat undan olinadi,
    LLM yozgan qo'shimcha so'rovlarda raqam to'qilgan bo'lishi mumkin. source berilsa, faqat o'sha hujjatdan.
    score — reranker (o'chirilgan bo'lsa RRF) bali: nisbiy, faqat tartiblash uchun."""
    queries = [question] if isinstance(question, str) else list(dict.fromkeys(question))
    if vectorstore.is_empty():
        return []
    index, chunks, vectors = _corpus()
    mask = np.fromiter((c.source == source for c in chunks), bool, len(chunks)) if source else None

    fused: dict[tuple[str, str, str], float] = {}
    by_key: dict[tuple[str, str, str], Hit] = {}

    def add(hit: Hit, rank: int) -> None:
        key = _key(hit)
        fused[key] = fused.get(key, 0.0) + 1 / (RRF_K + rank)
        by_key.setdefault(key, hit)

    similarities = _similarities(vectors, np.stack([np.asarray(embeddings.embed_query(q), dtype=np.float32) for q in queries]))
    for query, similarity in zip(queries, similarities):
        if mask is not None:
            similarity = np.where(mask, similarity, -np.inf)
        for rank, i in enumerate(np.argsort(-similarity)[:CANDIDATES], start=1):
            if mask is not None and not mask[i]:
                break  # tanlangan hujjatning bo'laklari tugadi
            add(chunks[i], rank)
        for rank, i in enumerate(index.top(query, CANDIDATES, mask), start=1):
            add(chunks[i], rank)

    articles = set(_ARTICLE_REF.findall(queries[0]))
    exact = set()
    if articles:
        for i, chunk in enumerate(chunks):
            if mask is not None and not mask[i]:
                continue
            if articles.intersection(_ARTICLE_LINE.findall(chunk.text)):
                key = _key(chunk)
                fused.setdefault(key, 0.0)
                by_key.setdefault(key, chunk)
                exact.add(key)

    for key in fused:  # kodeks va qonun bir xil darajada mos kelganda eski qaror/farmondan yuqori turadi
        fused[key] += _authority(by_key[key].title)
    ranked = _one_per_article(sorted(fused, key=lambda k: (k in exact, fused[k]), reverse=True), by_key)
    score = fused
    if settings.rerank_model:
        # Savolda tilga olingan moddalar baribir birinchi qoladi, ular ichida ham tartib reranker'dan
        n = settings.rerank_candidates
        ranked = [k for k in ranked if k in exact][:n] + [k for k in ranked if k not in exact][:n]
        score = dict(zip(ranked, rerank.scores(queries[0], [by_key[k] for k in ranked])))
        ranked.sort(key=lambda k: (k in exact, score[k]), reverse=True)
    hits = [Hit(**{**by_key[k].__dict__, "score": round(score[k], 4)}) for k in ranked[:top_k]]
    return [_with_continuation(hit, chunks) if n < EXPAND_TOP else hit for n, hit in enumerate(hits)]
