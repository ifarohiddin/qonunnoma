"""Tashqi baholash API (/v1): "RAG API — test spetsifikatsiyasi (lex.uz)" talablari.

Test jamoasi 10 tadan savol yuboradi, har bir savolga javob, manbalar (hujjat + modda) va topilgan kontekst
bo'laklarini oladi. Autentifikatsiya: Authorization: Bearer <kalit> (kalitlar .env dagi EVAL_API_KEYS).
"""
import asyncio
import hashlib
import hmac
import json
import re
import sqlite3
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import anthropic
from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse
from openai import APIConnectionError, APITimeoutError, RateLimitError

from . import llm, retrieval, vectorstore
from .config import settings

router = APIRouter(prefix="/v1", tags=["Baholash API (v1)"])

PIPELINE_VERSION = "1.0.0"
MAX_ITEMS = 10
SYNC_SECONDS = 90  # Cloudflare ~100 s dan keyin 524 beradi, shuning uchun 90 s dan oshsa 202 va GET orqali olinadi
LANGUAGES = {"uz-Latn", "uz-Cyrl", "ru"}
RATE_PER_MINUTE = 120  # kamida 1 batch/soniya
TZ = timezone(timedelta(hours=5))

# Xotira: har bir qidiruv vaqtincha ~130 MB oladi, serverda bo'sh joy kam — bir vaqtda 3 savol
_ITEMS = ThreadPoolExecutor(max_workers=3, thread_name_prefix="v1-item")
_BATCHES = ThreadPoolExecutor(max_workers=2, thread_name_prefix="v1-batch")

_db_lock = threading.Lock()
_db = sqlite3.connect(settings.data_dir / "v1.db", check_same_thread=False)
_db.execute(
    "CREATE TABLE IF NOT EXISTS batches (batch_id TEXT PRIMARY KEY, run_id TEXT, request_hash TEXT, status TEXT,"
    " response TEXT, created REAL)"
)
_db.execute("DELETE FROM batches WHERE status = 'processing'")  # qayta ishga tushganda yarim qolganlar qayta hisoblansin
_db.commit()


def _sql(query: str, args: tuple = ()) -> list[tuple]:
    with _db_lock:
        rows = _db.execute(query, args).fetchall()
        _db.commit()
    return rows


# ---------------------------------------------------------------- yordamchi


def _now() -> datetime:
    return datetime.now(TZ)


def _error(status: int, code: str, message: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status, headers=headers)


_rate: dict[str, deque] = {}
_rate_lock = threading.Lock()


def _auth(authorization: str | None) -> JSONResponse | None:
    """None — ruxsat; aks holda tayyor xato javobi (401 kalit yo'q, 403 kalit noto'g'ri, 429 limit)."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return _error(401, "UNAUTHORIZED", "Authorization: Bearer <API_KEY> sarlavhasi kerak.")
    token = authorization[7:].strip()
    keys = [k.strip() for k in settings.eval_api_keys.split(",") if k.strip()]
    if not any(hmac.compare_digest(token.encode(), k.encode()) for k in keys):
        return _error(403, "FORBIDDEN", "API kalit noto'g'ri.")
    now = time.monotonic()
    with _rate_lock:
        window = _rate.setdefault(hashlib.sha256(token.encode()).hexdigest(), deque())
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= RATE_PER_MINUTE:
            return _error(429, "RATE_LIMITED", "So'rovlar juda tez.", {"Retry-After": "1"})
        window.append(now)
    return None


_corpus_info: dict[int, tuple[int, int]] = {}


def _index_stats() -> tuple[int, int]:
    """(hujjatlar soni, bo'laklar soni) — qidiruv indeksidan (u keshlangan)."""
    _, chunks, _ = retrieval._corpus()
    cached = _corpus_info.get(id(chunks))
    if cached is None:
        cached = (len({c.source for c in chunks}), len(chunks))
        _corpus_info.clear()
        _corpus_info[id(chunks)] = cached
    return cached


def _system() -> dict:
    docs, chunks = _index_stats() if not vectorstore.is_empty() else (0, 0)
    return {
        "pipeline_version": PIPELINE_VERSION,
        "llm_model": settings.llm_model,
        "embedding_model": settings.embed_model,
        "reranker": settings.rerank_model or None,
        "index_version": f"lex-idx-{settings.lex_snapshot_date}-{docs}d-{chunks}c",
        "lex_snapshot_date": settings.lex_snapshot_date,
    }


# ---------------------------------------------------------------- manba maydonlari

NO_ANSWER_TEXT = {
    "uz-Latn": "Bu haqda hujjatlarda ma'lumot topilmadi.",
    "uz-Cyrl": "Бу ҳақда ҳужжатларда маълумот топилмади.",
    "ru": "В документах информация по этому вопросу не найдена.",
}
_REFUSAL = re.compile(
    r"(?:ma'lumot|ma’lumot|maʼlumot|javob|информаци\w*|маълумот|жавоб)[^.!?]{0,80}(?:topilmadi|топилмади|не найден\w*)|"
    r"(?:topilmadi|топилмади)\W*$|"
    r"(?:hujjatlarda|manbalarda|ҳужжатларда|документах)[^.!?]{0,120}(?:yo'q|yo‘q|mavjud emas|йўқ|нет|отсутствует)",
    re.IGNORECASE,
)
_ARTICLE = re.compile(r"^\s*(\d[\d.\-¹²³⁴⁵⁶⁷⁸⁹⁰]*)-modda\b", re.IGNORECASE | re.MULTILINE)
_LEX_ID = re.compile(r"lex\.uz/(?:[\w-]+/)?docs/(-?\d+)")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"\w{3,}", re.UNICODE)


def _doc_id(hit) -> str:
    m = _LEX_ID.search(hit.url or "") or _LEX_ID.search(hit.source or "")
    return f"lex:{m.group(1)}" if m else "src:" + hashlib.sha1((hit.source or hit.title).encode()).hexdigest()[:10]


def _doc_type(title: str) -> str:
    head = title.split(":")[0].lower() if ":" in title else title.lower()
    if re.search(r"\bsud|plenum|prokuratur", head) and not re.search(r"vazirlar mahkamasi|prezident", head):
        return "sud"
    if head.endswith("qonuni"):
        return "qonun"
    if head.endswith("farmoni"):
        return "farmon"
    if head.endswith("qarori"):
        return "qaror"
    if "konstitutsiya" in title.lower():
        return "konstitutsiya"
    if "kodeks" in title.lower():
        return "kodeks"
    return "boshqa"


def _article(hit) -> str | None:
    m = _ARTICLE.search(hit.text)
    return f"{m.group(1)}-modda" if m else None


def _chunk_id(hit) -> str:
    art = _article(hit)
    slug = f"art-{art[:-len('-modda')]}" if art else "x"
    return f"{_doc_id(hit)}#{slug}#{hashlib.sha1(hit.text.encode()).hexdigest()[:8]}"


def _quote(hit, answer: str, ref: int) -> str:
    """Javobdagi [ref] gaplariga eng mos bo'lak qatori — bo'lakdan so'zma-so'z olinadi."""
    wanted = set(_WORD.findall(" ".join(s for s in _SENTENCE.split(answer) if f"[{ref}]" in s).lower()))
    lines = [ln.strip() for ln in hit.text.split("\n") if len(ln.strip()) > 20]
    best = max(lines, key=lambda ln: len(wanted & set(_WORD.findall(ln.lower()))), default=hit.text.strip())
    return best[:400]


def _context(rank: int, hit, used: bool, with_text: bool) -> dict:
    return {
        "rank": rank,
        "chunk_id": _chunk_id(hit),
        "doc_id": _doc_id(hit),
        "article": _article(hit),
        "text": hit.text if with_text else None,
        "retrieval_score": hit.score,
        "rerank_score": hit.score if settings.rerank_model else None,
        "used_in_answer": used,
    }


def _citation(ref: int, hit, answer: str) -> dict:
    return {
        "ref": ref,
        "doc_id": _doc_id(hit),
        "doc_title": hit.title,
        "doc_type": _doc_type(hit.title),
        "url": hit.url,
        "article": _article(hit),
        "part": None,  # qism (band) darajasi indekslanmagan
        "edition_date": None,  # lex.uz tahrir sanasi saqlanmagan; snapshot sanasi /v1/meta da
        "doc_status": "amalda" if hit.url and "lex.uz" in hit.url else "noma'lum",
        "chunk_id": _chunk_id(hit),
        "quote": _quote(hit, answer, ref),
    }


# ---------------------------------------------------------------- bitta savol


def _fail(item_id: str, status: str, code: str, message: str, retryable: bool, timing: dict | None = None) -> dict:
    return {
        "id": item_id, "status": status, "answer": None, "answer_language": None, "no_answer": False, "confidence": None,
        "citations": [], "contexts": [], "debug": None, "timing": timing, "usage": None,
        "error": {"code": code, "message": message, "retryable": retryable},
    }


def _llm_error(exc: Exception) -> tuple[str, str, str, bool]:
    if isinstance(exc, (APITimeoutError, anthropic.APITimeoutError)):
        return "timeout", "LLM_TIMEOUT", "LLM javobi vaqtida kelmadi", True
    retryable = isinstance(exc, (RateLimitError, anthropic.RateLimitError, APIConnectionError, anthropic.APIConnectionError)) \
        or getattr(exc, "status_code", 0) >= 500
    return "error", "LLM_ERROR", f"LLM xatosi: {type(exc).__name__}", bool(retryable)


def _detect_language(text: str) -> str:
    """Savol tilini taxminan aniqlaydi (tester `language` bermasa va javob tili auto bo'lsa)."""
    low = text.lower()
    if sum("а" <= ch <= "я" or ch in "ўқғҳё" for ch in low) < len(low) * 0.3:
        return "uz-Latn"
    if re.search(r"[ўқғҳ]", low):
        return "uz-Cyrl"
    return "ru" if re.search(r"[ыэщъё]|\b(что|как|какой|какая|и|в|на|не)\b", low) else "uz-Cyrl"


def _run_item(item: dict, opts: dict) -> dict:
    started = time.perf_counter()
    item_id, question = item["id"], item["question"].strip()
    usage = {"input_tokens": 0, "output_tokens": 0}
    llm.usage_var.set(usage)

    language = item.get("language")
    if language is not None and language not in LANGUAGES:
        return _fail(item_id, "error", "INVALID_LANGUAGE", f"language: {sorted(LANGUAGES)} dan biri bo'lishi kerak", False)
    if vectorstore.is_empty():
        return _fail(item_id, "error", "INDEX_UNAVAILABLE", "Indeks bo'sh", True)

    top_k = opts["top_k"]
    try:
        try:
            rewritten = llm.search_queries(question, [])
        except Exception:  # qayta yozish ishlamasa, savolning o'zi bilan qidiramiz (chatdagi kabi)
            rewritten = []
        queries = [question, *rewritten]
        hits = retrieval.hybrid_search(queries, max(top_k, settings.top_k))
    except Exception as exc:
        return _fail(item_id, "error", "RETRIEVAL_FAILED", f"Qidiruv xatosi: {type(exc).__name__}", True)
    retrieval_ms = int((time.perf_counter() - started) * 1000)

    answer_language = opts["answer_language"]
    target = language if answer_language == "auto" else answer_language  # tester tilni aytgan bo'lsa, modelga ham aytamiz
    generation_started = time.perf_counter()
    try:
        text = llm.answer(question, hits, None, language=target)
    except Exception as exc:
        status, code, message, retryable = _llm_error(exc)
        return _fail(item_id, status, code, message, retryable, {"retrieval_ms": retrieval_ms})
    generation_ms = int((time.perf_counter() - generation_started) * 1000)
    if text == llm.EMPTY_ANSWER:
        return _fail(item_id, "error", "LLM_ERROR", "Model bo'sh javob qaytardi", True,
                     {"retrieval_ms": retrieval_ms, "generation_ms": generation_ms})

    cited = sorted(n for n in llm.cited_numbers(text) if 1 <= n <= len(hits))
    # Javob "ma'lumot topilmadi" deb boshlansa (model kontekstdan bir parchani keltirib bo'lsa ham), bu rad etishdir
    no_answer = not cited or bool(_REFUSAL.search(re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0]))
    shown = min(len(hits), max(top_k, max(cited, default=0)))  # keltirilgan bo'lak har doim contexts ichida bo'ladi
    contexts = [_context(n, hit, n in cited, opts["return_contexts"]) for n, hit in enumerate(hits[:shown], start=1)]
    raw_answer = text
    if no_answer:  # manbasiz javob asoslanmagan hisoblanadi: o'ylab topilgan qo'shimcha gaplar o'rniga qisqa standart javob
        text = NO_ANSWER_TEXT[target or _detect_language(question)]
    detected = _detect_language(text)  # javobning haqiqiy tili (so'ralgani emas)
    result = {
        "id": item_id,
        "status": "no_answer" if no_answer else "ok",
        "answer": text,
        "answer_language": detected,
        "no_answer": no_answer,
        "confidence": None,
        "citations": [_citation(n, hits[n - 1], text) for n in cited],
        "contexts": contexts,
        "debug": {
            "rewritten_query": " | ".join(rewritten),
            "retrieved_total": len(hits),
            "raw_answer": raw_answer if no_answer else None,
            "as_of_date_applied": False,
            "temperature_applied": False,
        } if opts["return_debug"] else None,
        "timing": {
            "retrieval_ms": retrieval_ms,
            "rerank_ms": None,
            "generation_ms": generation_ms,
            "total_ms": int((time.perf_counter() - started) * 1000),
        },
        "usage": usage,
        "error": None,
    }
    return result


# ---------------------------------------------------------------- so'rovni tekshirish


def _options(raw) -> tuple[dict | None, str | None]:
    raw = raw if isinstance(raw, dict) else {}
    top_k = raw.get("top_k", 5)
    if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 20:
        return None, "options.top_k 1–20 oralig'ida butun son bo'lishi kerak"
    language = raw.get("answer_language", "auto")
    if language != "auto" and language not in LANGUAGES:
        return None, "options.answer_language: auto, uz-Latn, uz-Cyrl yoki ru"
    return {
        "top_k": top_k,
        "return_contexts": bool(raw.get("return_contexts", True)),
        "return_debug": bool(raw.get("return_debug", False)),
        "answer_language": language,
    }, None


def _validate(body) -> tuple[dict | None, str | None]:
    if not isinstance(body, dict):
        return None, "So'rov JSON obyekt bo'lishi kerak"
    for key in ("run_id", "batch_id"):
        if not isinstance(body.get(key), str) or not body[key].strip():
            return None, f"{key} (string) majburiy"
    items = body.get("items")
    if not isinstance(items, list) or not items:
        return None, "items: kamida 1 ta savol"
    if len(items) > MAX_ITEMS:
        return None, f"items: {MAX_ITEMS} tadan ko'p bo'lmasligi kerak (yuborildi: {len(items)})"
    seen = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].strip():
            return None, "Har bir savolda id (string) bo'lishi kerak"
        if item["id"] in seen:
            return None, f"Takroriy id: {item['id']}"
        seen.add(item["id"])
        question = item.get("question")
        if not isinstance(question, str) or not question.strip():
            return None, f"{item['id']}: question bo'sh"
        if len(question) > 2000:
            return None, f"{item['id']}: question 2000 belgidan oshmasligi kerak"
    opts, problem = _options(body.get("options"))
    if problem:
        return None, problem
    return opts, None


# ---------------------------------------------------------------- batch


def _process(body: dict, opts: dict, received: datetime) -> dict:
    started = time.perf_counter()
    futures = [_ITEMS.submit(_run_item, item, opts) for item in body["items"]]
    results = []
    for item, future in zip(body["items"], futures):
        try:
            results.append(future.result())
        except Exception as exc:  # bitta savoldagi kutilmagan xato butun batchni yiqitmasin
            results.append(_fail(item["id"], "error", "LLM_ERROR", f"Ichki xato: {type(exc).__name__}", True))
    done = _now()
    count = lambda s: sum(r["status"] == s for r in results)  # noqa: E731
    return {
        "run_id": body["run_id"],
        "batch_id": body["batch_id"],
        "status": "completed",
        "system": _system(),
        "timing": {
            "received_at": received.isoformat(timespec="seconds"),
            "completed_at": done.isoformat(timespec="seconds"),
            "total_ms": int((time.perf_counter() - started) * 1000),
        },
        "summary": {
            "total": len(results), "ok": count("ok"), "no_answer": count("no_answer"),
            "error": count("error") + count("timeout"), "timeout": count("timeout"),
        },
        "results": results,
    }


def _job(body: dict, opts: dict, received: datetime) -> dict:
    try:
        response = _process(body, opts, received)
        status = "completed"
    except Exception as exc:
        response = {"run_id": body["run_id"], "batch_id": body["batch_id"], "status": "failed",
                    "error": {"code": "INTERNAL", "message": type(exc).__name__, "retryable": True}}
        status = "failed"
    _sql("UPDATE batches SET status = ?, response = ? WHERE batch_id = ?",
         (status, json.dumps(response, ensure_ascii=False), body["batch_id"]))
    return response


@router.get("/health")
def health():
    """Servis ishlayaptimi (kalit shart emas)."""
    return {"status": "ok", "time": _now().isoformat(timespec="seconds")}


@router.get("/meta")
def meta(authorization: str | None = Header(default=None)):
    """Tizim versiyalari va imkoniyatlari: model, embedding, indeks, lex.uz snapshot sanasi."""
    if (denied := _auth(authorization)) is not None:
        return denied
    return {
        "system": _system(),
        "limits": {"max_items_per_batch": MAX_ITEMS, "sync_timeout_seconds": SYNC_SECONDS,
                   "rate_limit_batches_per_minute": RATE_PER_MINUTE, "batch_retention_days": 30},
        "capabilities": {
            "temperature": False, "seed": False, "as_of_date": False, "idempotent_batch_id": True,
            "async_mode": True, "languages": sorted(LANGUAGES),
        },
        "notes": {
            "determinism": "Claude modelida temperature/seed yo'q; qidiruv (indeks, BM25, vektor) bir xil indeksda deterministik, "
                           "LLM bilan qayta yozilgan so'rov va javob matni esa har safar biroz farq qilishi mumkin.",
            "chunking": "Modda bo'yicha: har modda alohida bo'lak (uzun moddalar bir nechta bo'lak, boshlanishi modda sarlavhasi).",
            "documents": "Faqat lex.uz dagi amaldagi hujjatlar indekslangan; kuchini yo'qotganlari olinmagan.",
            "chunk_id": "doc_id + modda raqami + bo'lak matni xeshi: matn o'zgarmasa barqaror.",
            "unavailable_fields": ["citations[].part", "citations[].edition_date", "contexts[].rerank_score", "confidence"],
            "contexts": "Kamida options.top_k ta; javobda keltirilgan bo'lak top_k dan keyinda bo'lsa, u ham qo'shiladi.",
        },
    }


@router.post("/rag/batch")
async def batch(request: Request, authorization: str | None = Header(default=None)):
    """1–10 savolni yuboradi. Javob 120 s ichida tayyor bo'lmasa 202 qaytadi va natija GET orqali olinadi."""
    if (denied := _auth(authorization)) is not None:
        return denied
    try:
        body = json.loads((await request.body()).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return _error(400, "INVALID_REQUEST", "Tanasi to'g'ri JSON (UTF-8) emas.")
    opts, problem = _validate(body)
    if problem:
        return _error(400, "INVALID_REQUEST", problem)

    request_hash = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    existing = _sql("SELECT request_hash, status, response FROM batches WHERE batch_id = ?", (body["batch_id"],))
    if existing:
        stored_hash, status, response = existing[0]
        if stored_hash != request_hash:
            return _error(409, "BATCH_ID_CONFLICT", "Bu batch_id boshqa mazmun bilan yuborilgan; yangi batch_id ishlating.")
        if status == "processing":
            return JSONResponse({"batch_id": body["batch_id"], "status": "processing"}, status_code=202)
        return JSONResponse(json.loads(response))

    _sql("INSERT INTO batches (batch_id, run_id, request_hash, status, response, created) VALUES (?, ?, ?, 'processing', NULL, ?)",
         (body["batch_id"], body["run_id"], request_hash, time.time()))
    future = asyncio.wrap_future(_BATCHES.submit(_job, body, opts, _now()))
    done, _ = await asyncio.wait({future}, timeout=SYNC_SECONDS)  # wait_for emas: u ishni bekor qilib yuborardi
    if not done:
        return JSONResponse({"batch_id": body["batch_id"], "status": "processing"}, status_code=202)
    return JSONResponse(future.result())


@router.get("/rag/batch/{batch_id}")
def batch_result(batch_id: str, authorization: str | None = Header(default=None)):
    """Saqlangan batch natijasi (async rejim yoki qayta tekshirish)."""
    if (denied := _auth(authorization)) is not None:
        return denied
    rows = _sql("SELECT status, response FROM batches WHERE batch_id = ?", (batch_id,))
    if not rows:
        return _error(404, "NOT_FOUND", "Bunday batch_id topilmadi.")
    status, response = rows[0]
    if status == "processing":
        return JSONResponse({"batch_id": batch_id, "status": "processing"}, status_code=202)
    return JSONResponse(json.loads(response))


@router.post("/rag/query")
async def query(request: Request, authorization: str | None = Header(default=None)):
    """Bitta savol (debug uchun): {"question": "...", "language": "uz-Latn", "options": {...}}."""
    if (denied := _auth(authorization)) is not None:
        return denied
    try:
        body = json.loads((await request.body()).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return _error(400, "INVALID_REQUEST", "Tanasi to'g'ri JSON (UTF-8) emas.")
    if not isinstance(body, dict):
        return _error(400, "INVALID_REQUEST", "So'rov JSON obyekt bo'lishi kerak")
    wrapped = {"run_id": "query", "batch_id": "query", "items": [{
        "id": "q", "question": body.get("question"), "language": body.get("language")}], "options": body.get("options")}
    opts, problem = _validate(wrapped)
    if problem:
        return _error(400, "INVALID_REQUEST", problem)
    opts["return_debug"] = bool((body.get("options") or {}).get("return_debug", True))
    result = await asyncio.get_running_loop().run_in_executor(_ITEMS, _run_item, wrapped["items"][0], opts)
    return JSONResponse({"system": _system(), "result": result})
