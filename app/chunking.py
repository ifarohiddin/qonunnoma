"""Segmentlarni qidiruv uchun mos uzunlikdagi bo'laklarga (chunk) yig'ish.

Qonun matnlarida har bir modda alohida bo'lak bo'ladi va boshiga bo'lim hamda bob sarlavhasi qo'shiladi —
aks holda bir bo'lakka bir nechta modda aralashib, qidiruv aniqligi tushib ketadi. Bo'lim nomi ham kerak:
Soliq kodeksidagi "Soliq stavkalari" moddasi qaysi soliq haqida ekani faqat bo'lim nomidan bilinadi.
"""
import re
from dataclasses import dataclass

from .loaders import Segment

_SECTION = re.compile(r"^(\d+|[IVXLCDM]+|\S+nchi)[\s-]+bo\S?lim\b", re.IGNORECASE)  # BIRINCHI BOʻLIM.
_CHAPTER = re.compile(r"^(\d+|[IVXLCDM]+)[\s-]+bob\b", re.IGNORECASE)  # XIX bob. / 3-bob.
_ARTICLE = re.compile(r"^\d[\d.\-¹²³⁴⁵⁶⁷⁸⁹⁰]*-modda\b", re.IGNORECASE)  # 106-modda.
_MAX_HEADING_CHARS = 200


@dataclass
class Chunk:
    text: str
    locator: str | None  # bo'lakning boshlanish joyi (bet yoki lex.uz element id)


def _split_long(text: str, max_chars: int) -> list[str]:
    """max_chars dan uzun bitta paragrafni gap chegarasida bo'ladi."""
    if len(text) <= max_chars:
        return [text]
    parts, current = [], ""
    for sentence in text.replace("\n", " ").split(". "):
        piece = sentence if sentence.endswith(".") else sentence + "."
        while len(piece) > max_chars:  # gap o'zi juda uzun bo'lsa
            parts.append(piece[:max_chars])
            piece = piece[max_chars:]
        if current and len(current) + len(piece) + 1 > max_chars:
            parts.append(current)
            current = piece
        else:
            current = f"{current} {piece}".strip()
    if current:
        parts.append(current)
    return parts


def split_heading(text: str) -> tuple[list[str], str]:
    """Bo'lak boshidagi sarlavha qatorlari (bo'lim, bob, modda) va qolgan matn — manbani ko'rsatish uchun."""
    lines = text.split("\n")
    count = 0
    for line in lines:
        if len(line) > _MAX_HEADING_CHARS or not (_SECTION.match(line) or _CHAPTER.match(line) or _ARTICLE.match(line)):
            break
        count += 1
    return lines[:count], "\n".join(lines[count:])


def make_chunks(segments: list[Segment], max_chars: int, overlap: int) -> list[Chunk]:
    chunks: list[Chunk] = []
    buffer: list[str] = []
    buffer_len = 0
    start_locator: str | None = None
    has_new_text = False  # buffer'da overlap qoldig'idan boshqa matn bormi
    section = ""  # joriy bo'lim sarlavhasi
    chapter = ""  # joriy bob sarlavhasi
    article = ""  # joriy modda raqami, masalan "106-modda"

    def flush(carry_overlap: bool) -> None:
        nonlocal buffer, buffer_len, start_locator, has_new_text
        if has_new_text:
            prefix = [h for h in (section, chapter) if h]
            if article and not buffer[0].startswith(article):
                prefix.append(f"{article} (davomi)")
            chunks.append(Chunk("\n".join(prefix + buffer), start_locator))
        # Modda ichida bo'linganda keyingi bo'lakka kontekst o'tishi uchun oxirgi paragraf(lar)ni qoldiramiz
        tail: list[str] = []
        tail_len = 0
        if carry_overlap:
            for paragraph in reversed(buffer):
                if tail_len + len(paragraph) > overlap:
                    break
                tail.insert(0, paragraph)
                tail_len += len(paragraph) + 1
        buffer, buffer_len, start_locator, has_new_text = tail, tail_len, None, False

    for segment in segments:
        text = segment.text
        if len(text) <= _MAX_HEADING_CHARS and _SECTION.match(text):
            flush(carry_overlap=False)
            section, chapter, article = text, "", ""
            continue
        if len(text) <= _MAX_HEADING_CHARS and _CHAPTER.match(text):
            flush(carry_overlap=False)
            chapter, article = text, ""
            continue
        article_match = _ARTICLE.match(text)
        if article_match:
            flush(carry_overlap=False)
            article = article_match.group(0)
        for piece in _split_long(text, max_chars):
            if has_new_text and buffer_len + len(piece) + 1 > max_chars:
                flush(carry_overlap=True)
            if start_locator is None:
                start_locator = segment.locator
            buffer.append(piece)
            buffer_len += len(piece) + 1
            has_new_text = True
    flush(carry_overlap=False)
    return chunks
