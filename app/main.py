import hmac
import re
import shutil
import threading
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Literal

import anthropic
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from openai import AuthenticationError, RateLimitError
from pydantic import BaseModel, Field

from . import accounts, admin, embeddings, limits, llm, rerank, retrieval, v1, vectorstore
from .chunking import Chunk, make_chunks, split_heading
from .config import settings
from .loaders import SUPPORTED_EXTENSIONS, LoadedDocument, fetch_many_lex, load_file

STATIC_DIR = Path(__file__).parent / "static"
NO_DOCUMENTS = "Bazada hujjat yo'q. Avval /ingest/files yoki /ingest/lex ishlating."


@asynccontextmanager
async def lifespan(_: FastAPI):
    embeddings.warm_up()  # birinchi so'rov sekin bo'lmasligi uchun modellarni oldindan yuklaymiz
    rerank.warm_up()
    threading.Thread(target=retrieval.warm_up, daemon=True).start()  # server shu orada so'rov qabul qilaveradi
    yield


PUBLIC = bool(settings.admin_token)  # internetga chiqarilgan rejim
# Ommaviy rejimda Swagger (/docs) yopiq: u yerdan hujjat yuklash/o'chirish endpointlari ko'rinadi
app = FastAPI(
    title="RAG tizimi",
    version="1.0",
    lifespan=lifespan,
    docs_url=None if PUBLIC else "/docs",
    redoc_url=None,
    openapi_url=None if PUBLIC else "/openapi.json",
)
app.include_router(accounts.router)
app.include_router(admin.router)
app.include_router(v1.router)


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    """Ommaviy rejimda bazani o'zgartiradigan va LLM'ni bevosita chaqiradigan endpointlar faqat administrator uchun."""
    if PUBLIC and not hmac.compare_digest(x_admin_token or "", settings.admin_token):
        raise HTTPException(403, "Bu amal faqat administrator uchun.")


class LexRequest(BaseModel):
    urls: list[str] = Field(min_length=1, description="lex.uz havolalari yoki hujjat ID'lari")


class QueryRequest(BaseModel):
    question: str = Field(min_length=1)
    top_k: int = Field(default=settings.top_k, ge=1, le=20)
    source: str | None = None  # faqat shu hujjatdan qidirish (/documents dagi source)


class Source(BaseModel):
    title: str
    source: str
    url: str | None
    locator: str | None
    score: float
    text: str


class AnswerResponse(BaseModel):
    answer: str
    sources: list[Source]


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=50)
    deep: bool = False  # chuqur qidiruv: ko'proq parcha va qo'shimcha qidiruv so'rovlari
    source: str | None = None  # faqat shu hujjatdan qidirish (/documents dagi source)


class ChatSource(BaseModel):
    n: int  # javobdagi [n] raqami
    title: str
    url: str | None
    section: str  # bob va modda, masalan "14-bob. Dam olish vaqti · 217-modda. ..."
    snippet: str  # modda matnining boshi
    score: float | None  # reranker bahosi 0..1 (reranker o'chirilgan bo'lsa None)


class ChatResponse(BaseModel):
    answer: str
    sources: list[ChatSource]


def _rate_limit_message(error: str) -> str:
    """Groq xabaridagi "tokens per day ... try again in 6m21.024s" dan foydalanuvchiga tushunarli matn."""
    kind = "kunlik " if "per day" in error else ""
    wait = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", error)
    if not wait or not any(wait.groups()):
        return f"LLM'ning {kind}so'rovlar limiti tugadi. Birozdan so'ng qayta urinib ko'ring."
    hours, minutes, seconds = (float(g or 0) for g in wait.groups())
    total = int(hours * 3600 + minutes * 60 + seconds) + 1
    when = f"{total // 60} daqiqa {total % 60} soniyadan" if total >= 60 else f"{total} soniyadan"
    return f"LLM'ning {kind}so'rovlar limiti tugadi. Taxminan {when} so'ng qayta urinib ko'ring."


@contextmanager
def _llm_errors():
    try:
        yield
    except (RateLimitError, anthropic.RateLimitError) as exc:
        raise HTTPException(429, _rate_limit_message(str(exc))) from exc
    except (AuthenticationError, anthropic.AuthenticationError) as exc:
        raise HTTPException(502, "LLM API kaliti noto'g'ri (.env dagi LLM_API_KEY ni tekshiring).") from exc
    except Exception as exc:
        raise HTTPException(502, f"LLM bilan bog'lanib bo'lmadi: {exc}") from exc


def _link(hit: vectorstore.Hit) -> str | None:
    return f"{hit.url}#{hit.locator}" if hit.url and hit.locator else hit.url


def _chat_source(n: int, hit: vectorstore.Hit) -> ChatSource:
    headings, body = split_heading(hit.text)
    section = " · ".join(headings[-2:])  # bo'lim nomi uzun va katta harfli — bob va modda yetarli
    if not section and not hit.url:
        section = hit.locator or ""  # fayllarda sarlavha o'rniga bet raqami
    body = " ".join(body.split())
    snippet = body if len(body) <= 240 else body[:240].rsplit(" ", 1)[0] + " …"
    return ChatSource(
        n=n,
        title=hit.title,
        url=_link(hit),
        section=section,
        snippet=snippet,
        score=hit.score if settings.rerank_model else None,
    )


def _index(doc: LoadedDocument) -> int:
    chunks = make_chunks(doc.segments, settings.chunk_chars, settings.chunk_overlap)
    # Hujjat nomi ham vektorga kiradi: kodekslar ko'p bo'lganda "Mehnat kodeksi bo'yicha ..." savoli o'sha kodeksni topadi
    vectors = embeddings.embed_passages([f"{doc.title}\n{c.text}" for c in chunks])
    vectorstore.replace_document(doc.source, doc.title, doc.url, chunks, vectors)
    return len(chunks)


def _sources(hits: list[vectorstore.Hit]) -> list[Source]:
    return [
        Source(
            title=hit.title,
            source=hit.source,
            url=_link(hit),
            locator=hit.locator,
            score=hit.score,
            text=hit.text,
        )
        for hit in hits
    ]


@app.get("/", include_in_schema=False)
def landing_page(http: Request):
    accounts.log_event("visit", detail="landing", visitor=accounts.visitor_id(http))
    # no-cache: sahifa yangilanganda brauzer eski nusxani ko'rsatmasin
    return FileResponse(STATIC_DIR / "landing.html", headers={"Cache-Control": "no-cache"})


@app.get("/app", include_in_schema=False)
def chat_page(http: Request):
    accounts.log_event("visit", detail="app", visitor=accounts.visitor_id(http))
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/admin", include_in_schema=False)
def admin_page():
    # Sahifaning o'zi ochiq: ma'lumotlar /admin/api dan faqat admin sessiyasi bilan keladi
    return FileResponse(STATIC_DIR / "admin.html", headers={"Cache-Control": "no-cache"})


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    # Service worker butun saytni (scope "/") qamrashi uchun ildizdan beriladi
    return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest", include_in_schema=False)
def web_manifest():
    return FileResponse(STATIC_DIR / "manifest.webmanifest", media_type="application/manifest+json",
                        headers={"Cache-Control": "no-cache"})


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(STATIC_DIR / "favicon-32.png", media_type="image/png")


# Logo, ikonkalar va ulashish rasmi (/static/logo.svg, /static/og.png ...)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/health", tags=["Tizim"])
def health():
    # uploads: sahifadagi "Fayl" tugmasi ko'rinsinmi (ommaviy rejimda bazaga faqat administrator yuklaydi)
    return {"status": "ok", "llm_model": settings.llm_model, "embed_model": settings.embed_model, "uploads": not PUBLIC}


@app.post("/ingest/files", dependencies=[Depends(require_admin)], tags=["Hujjatlar bazasi"])
def ingest_files(files: list[UploadFile] = File(...)):
    """PDF / DOCX / TXT fayllarni yuklab, indekslaydi."""
    results, errors = [], {}
    upload_dir = settings.data_dir / "uploads"
    for upload in files:
        name = (upload.filename or "").replace("\\", "/").split("/")[-1]
        ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext not in SUPPORTED_EXTENSIONS:
            errors[name or "?"] = f"Faqat {', '.join(sorted(SUPPORTED_EXTENSIONS))} qo'llab-quvvatlanadi"
            continue
        target = upload_dir / name
        with target.open("wb") as out:
            shutil.copyfileobj(upload.file, out)
        try:
            doc = load_file(target)
            if not doc.segments:
                raise ValueError("Fayldan matn topilmadi (skan qilingan PDF bo'lishi mumkin)")
            results.append({"source": doc.source, "chunks": _index(doc)})
        except Exception as exc:
            errors[name] = str(exc)
    return {"indexed": results, "errors": errors}


@app.post("/ingest/lex", dependencies=[Depends(require_admin)], tags=["Hujjatlar bazasi"])
def ingest_lex(request: LexRequest):
    """lex.uz hujjatlarini yuklab, indekslaydi."""
    documents, errors = fetch_many_lex(request.urls)
    results = [{"source": d.source, "title": d.title, "chunks": _index(d)} for d in documents]
    return {"indexed": results, "errors": errors}


class PrecomputedChunk(BaseModel):
    text: str
    locator: str | None = None


class PrecomputedDocument(BaseModel):
    source: str = Field(max_length=500)
    title: str = Field(max_length=1000)
    url: str | None = None
    chunks: list[PrecomputedChunk] = Field(min_length=1, max_length=5000)
    embeddings: list[list[float]] = Field(description="Har bir bo'lak uchun vektor (bge-m3, 1024 o'lchamli, normallashgan)")


@app.post("/ingest/precomputed", dependencies=[Depends(require_admin)], tags=["Hujjatlar bazasi"])
def ingest_precomputed(doc: PrecomputedDocument):
    """Bo'laklari va vektorlari tayyor hujjatni qo'shadi (embedding boshqa joyda, masalan GPU li kompyuterda hisoblangan:
    serverning CPU'sida bitta hujjat ~30 soniya, GPU'da soniyalar). Bor hujjat almashtiriladi."""
    if len(doc.chunks) != len(doc.embeddings):
        raise HTTPException(422, "Bo'laklar va vektorlar soni bir xil bo'lishi kerak.")
    if len({len(v) for v in doc.embeddings}) != 1:
        raise HTTPException(422, "Vektorlar bir xil o'lchamda bo'lishi kerak.")
    vectorstore.replace_document(doc.source, doc.title, doc.url, [Chunk(c.text, c.locator) for c in doc.chunks], doc.embeddings)
    return {"source": doc.source, "chunks": len(doc.chunks)}


@app.get("/documents", tags=["Hujjatlar bazasi"])
def documents():
    return vectorstore.list_documents()


@app.delete("/documents", dependencies=[Depends(require_admin)], tags=["Hujjatlar bazasi"])
def delete_document(source: str):
    removed = vectorstore.delete_document(source)
    if not removed:
        raise HTTPException(404, "Bunday manba topilmadi")
    return {"removed_chunks": removed}


@app.post("/search", response_model=list[Source], dependencies=[Depends(require_admin)], tags=["Qidiruv va savol-javob"])
def search(request: QueryRequest):
    """Faqat qidiruv (LLM'siz) — sifatni tekshirish uchun."""
    hits = retrieval.hybrid_search(request.question, request.top_k, source=request.source)
    return _sources(hits)


@app.post("/ask", response_model=AnswerResponse, dependencies=[Depends(require_admin)], tags=["Qidiruv va savol-javob"])
def ask(request: QueryRequest):
    """Javob + topilgan bo'laklarning to'liq matni (tekshirish uchun)."""
    hits = retrieval.hybrid_search(request.question, request.top_k, source=request.source)
    if not hits:
        raise HTTPException(409, NO_DOCUMENTS)
    with _llm_errors():
        text = llm.answer(request.question, hits)
    return AnswerResponse(answer=text, sources=_sources(hits))


@app.post("/chat", response_model=ChatResponse, tags=["Qidiruv va savol-javob"])
def chat(request: ChatRequest, http: Request, user=Depends(accounts.optional_user)):
    """Chatbot: qisqa javob va faqat javobda tilga olingan manbalar (modda nomi va qisqa parcha bilan)."""
    if settings.chat_requires_login and user is None:
        raise HTTPException(401, "Savol berish uchun avval tizimga kiring yoki ro‘yxatdan o‘ting.")
    if user is not None and not accounts.is_approved(user):
        raise HTTPException(403, "Hisobingiz hali tasdiqlanmagan. Administrator ruxsat bergach savol bera olasiz.")
    # Kirgan foydalanuvchiga ikki baravar ko'p; mehmonlar IP bo'yicha hisoblanadi
    key, factor = (f"user:{user['id']}", 2) if user else (f"ip:{limits.client_ip(http)}", 1)
    limits.check(key, settings.chat_per_minute * factor, settings.chat_per_day * factor, "savol berish")
    if vectorstore.is_empty():
        raise HTTPException(409, NO_DOCUMENTS)
    started, ok = time.perf_counter(), False
    try:
        history = [m.model_dump() for m in request.history][-settings.chat_history_messages :]
        queries = [request.message]
        if history or request.deep or settings.rewrite_always:
            # Suhbatdagi xabar ("bu qaysi moddada?") qidiruvga yaroqsiz bo'lishi mumkin — LLM uni mustaqil savolga
            # aylantiradi; birinchi savolga ham qonun uslubidagi lotincha so'rov qo'shiladi: kirill/ruscha va og'zaki
            # savollar ("xotinim urdi") rasmiy lotincha matn bilan aks holda mos kelmaydi (~900 token)
            try:
                with _llm_errors():
                    rewritten = llm.search_queries(request.message, history)
            except HTTPException:
                if history:
                    raise
                rewritten = []  # birinchi savol: qayta yozish ishlamasa, savolning o'zi bilan qidiramiz
            queries = rewritten if history else [request.message, *rewritten]
        top_k = settings.deep_top_k if request.deep else settings.top_k
        hits = retrieval.hybrid_search(queries, top_k, source=request.source)
        with _llm_errors():
            text = llm.answer(request.message, hits, history)
        cited = llm.cited_numbers(text)
        sources = [_chat_source(n, hit) for n, hit in enumerate(hits, start=1) if n in cited]
        ok = True
        return ChatResponse(answer=text, sources=sources)
    finally:
        # Admin panel uchun: kim, nima so'radi, javob qancha vaqt oldi, xato bo'ldimi
        accounts.log_event("question", user["id"] if user else None, request.message,
                           int((time.perf_counter() - started) * 1000), ok)
