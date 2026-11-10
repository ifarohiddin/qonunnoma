"""Hujjatlarni (PDF/DOCX/TXT va lex.uz) matn bo'laklariga (Segment) aylantirish."""
import re
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from docx import Document as DocxDocument
from pypdf import PdfReader

from .config import settings

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt"}
LEX_HOST = "https://lex.uz"
_LEX_ID_RE = re.compile(r"docs/(-?\d+)")


@dataclass
class Segment:
    text: str
    # Manba ichidagi joy: sahifa raqami (PDF) yoki element id (lex.uz)
    locator: str | None = None


@dataclass
class LoadedDocument:
    source: str  # barqaror identifikator (fayl nomi yoki lex.uz URL)
    title: str
    url: str | None
    segments: list[Segment]


def load_file(path: Path) -> LoadedDocument:
    ext = path.suffix.lower()
    if ext == ".pdf":
        segments = _read_pdf(path)
    elif ext == ".docx":
        segments = _read_docx(path)
    elif ext == ".txt":
        segments = _read_txt(path)
    else:
        raise ValueError(f"Qo'llab-quvvatlanmaydigan format: {ext}")
    return LoadedDocument(source=path.name, title=path.stem, url=None, segments=segments)


def _read_pdf(path: Path) -> list[Segment]:
    reader = PdfReader(str(path))
    segments = []
    for number, page in enumerate(reader.pages, start=1):
        # Qatorma-qator: shunda "N-modda" kabi sarlavhalar bo'laklashda aniqlanadi
        for line in (page.extract_text() or "").splitlines():
            if line.strip():
                segments.append(Segment(line.strip(), f"bet {number}"))
    return segments


def _read_docx(path: Path) -> list[Segment]:
    doc = DocxDocument(str(path))
    segments = [Segment(p.text.strip()) for p in doc.paragraphs if p.text.strip()]
    for table in doc.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                segments.append(Segment(" | ".join(cells)))
    return segments


def _read_txt(path: Path) -> list[Segment]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "cp1251", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeError:
            continue
    return [Segment(block.strip()) for block in re.split(r"\n\s*\n", text) if block.strip()]


# --------------------------------------------------------------------------- lex.uz


def parse_lex_url(value: str) -> tuple[str, str]:
    """URL yoki 'docs/-123' / '-123' ko'rinishidan (doc_id, kanonik URL) qaytaradi."""
    value = value.strip()
    match = _LEX_ID_RE.search(value)
    if match:
        doc_id = match.group(1)
    elif re.fullmatch(r"-?\d+", value):
        doc_id = value
    else:
        raise ValueError(f"lex.uz hujjat havolasi emas: {value}")
    lang = "uz"
    lang_match = re.search(r"lex\.uz/(uz|ru|oz)/", value)
    if lang_match:
        lang = lang_match.group(1)
    return doc_id, f"{LEX_HOST}/{lang}/docs/{doc_id}"


def fetch_lex(value: str, client: httpx.Client | None = None) -> LoadedDocument:
    doc_id, url = parse_lex_url(value)
    own_client = client is None
    client = client or httpx.Client(
        headers={"User-Agent": "Mozilla/5.0 (compatible; RAG-study-bot)"},
        follow_redirects=True,
        timeout=60,
    )
    try:
        response = client.get(url)
        response.raise_for_status()
    finally:
        if own_client:
            client.close()
    return _parse_lex_html(response.text, doc_id, url)


def _parse_lex_html(html: str, doc_id: str, url: str) -> LoadedDocument:
    soup = BeautifulSoup(html, "lxml")
    if soup.title and "404" in soup.title.get_text():
        raise ValueError(f"lex.uz da hujjat topilmadi: {url}")
    # Kuchini yo'qotgan hujjat bo'yicha chatbot eskirgan qonunni hozirgidek aytib qo'yadi
    warning = soup.select_one("div.act_warning")
    status = re.sub(r"\s+", " ", warning.get_text(" ", strip=True)) if warning else ""
    if re.search(r"kuchini yo|кучини йў|утратил", status, re.IGNORECASE):
        raise ValueError(f"{status} — eskirgan hujjat qo'shilmadi: {url}")

    segments: list[Segment] = []
    title = ""
    for element in soup.select("div.lx_elem"):
        # Har bir elementning ichida menyu (lx_elem2) va haqiqiy matn (id'li div) bor
        for menu in element.select(".lx_elem2"):
            menu.decompose()
        body = element.find("div", id=True)
        text = re.sub(r"\s+", " ", (body or element).get_text(" ", strip=True)).strip()
        if not text:
            continue
        if not title and "ACT_TITLE" in (element.get("class") or []):
            title = text
        segments.append(Segment(text, body.get("id") if body else None))

    if not segments:
        raise ValueError(f"lex.uz sahifasidan matn ajratib bo'lmadi: {url}")
    page_title = re.sub(r"\s+", " ", soup.title.get_text()).strip() if soup.title else ""
    if page_title and "lex.uz" not in page_title.lower():
        title = _lex_title(page_title, [s.text for s in segments[:2]])
    return LoadedDocument(source=url, title=title or doc_id, url=url, segments=segments)


# <title>: "349-I-сон 27.12.1996. Advokatura toʻgʻrisida" yoki "21.12.1995. ... Fuqarolik kodeksi (birinchi qism)"
_PAGE_TITLE = re.compile(r"^(?:(\S+)-(?:сон|son)\s+)?(\d{2}\.\d{2}\.\d{4})\.\s*(.+)$")
_KIND_END = re.compile(r"(qonuni|qarori|farmoni|farmoyishi)$", re.IGNORECASE)


def _lex_title(page_title: str, first_segments: list[str]) -> str:
    """Hujjat nomi turi va sanasi bilan: "Oʻzbekiston Respublikasining qonuni: Advokatura toʻgʻrisida (27.12.1996)".
    <title> dagi nom to'g'ri harflarda va qismi bilan (ACT_TITLE esa katta harfda va qismsiz), lekin unda hujjat
    turi yo'q — tur sahifa boshidagi "Oʻzbekiston Respublikasining qonuni" / "... Prezidentining" + "Qarori" dan olinadi."""
    match = _PAGE_TITLE.match(page_title)
    if not match:
        return page_title
    _, day, name = match.groups()
    head = first_segments[0] if first_segments else ""
    if len(first_segments) > 1 and head.lower().endswith("ning") and _KIND_END.search(first_segments[1]):
        head = f"{head} {first_segments[1]}"
    if len(head) > 120 or not _KIND_END.search(head):
        return name  # kodekslar: nomning o'zida turi bor ("... Mehnat kodeksi")
    return f"{head}: {name} ({day})"


def fetch_many_lex(values: list[str]) -> tuple[list[LoadedDocument], dict[str, str]]:
    """Bir nechta lex.uz hujjatini ketma-ket (saytga yuk tushirmasdan) yuklaydi."""
    documents: list[LoadedDocument] = []
    errors: dict[str, str] = {}
    with httpx.Client(
        headers={"User-Agent": "Mozilla/5.0 (compatible; RAG-study-bot)"},
        follow_redirects=True,
        timeout=60,
    ) as client:
        for index, value in enumerate(values):
            if index:
                time.sleep(settings.lex_delay_seconds)
            try:
                documents.append(fetch_lex(value, client))
            except Exception as exc:  # bitta xato butun ro'yxatni to'xtatmasin
                errors[value] = str(exc)
    return documents, errors
