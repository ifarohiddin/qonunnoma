"""Javobdagi o'zbekcha (lotin) son so'zlarini raqamga aylantiradi: "uch yuz oltmish soat" -> "360 soat"."""
import re

_APOS = "'ʻʼ’‘`"
_ONES = {"bir": 1, "ikki": 2, "uch": 3, "to'rt": 4, "besh": 5, "olti": 6, "yetti": 7, "sakkiz": 8, "to'qqiz": 9}
_TENS = {"o'n": 10, "yigirma": 20, "o'ttiz": 30, "qirq": 40, "ellik": 50, "oltmish": 60, "yetmish": 70, "sakson": 80, "to'qson": 90}
_SCALE = {"ming": 1000, "million": 1_000_000}
# Yolg'iz "bir" faqat shu o'lchov so'zlari oldida son hisoblanadi ("bir necha", "bir gap" kabilar o'zgarmaydi)
_UNITS = r"(?:yil|yilgacha|yildan|oy|oygacha|oydan|kun|kungacha|kundan|soat|soatgacha|soatdan|hafta|yosh|yoshga|yoshdan|foiz|marta|so'm|sutka|daqiqa)"

_WORD = "|".join(sorted((re.escape(w) for w in [*_ONES, *_TENS, "yuz", *_SCALE]), key=len, reverse=True))
_WORD = _WORD.replace("'", f"[{_APOS}]")
_SEQ = re.compile(rf"(?<![\w{_APOS}])(?:{_WORD})(?:\s+(?:{_WORD}))*(?![\w{_APOS}])", re.I)
_UNIT_AFTER = re.compile(rf"\s+{_UNITS.replace(chr(39), f'[{_APOS}]')}(?![\w{_APOS}])", re.I)


def _norm(word: str) -> str:
    return re.sub(f"[{_APOS}]", "'", word.lower())


def _value(words: list[str]) -> int | None:
    """So'zlar ketma-ketligi to'g'ri son bo'lsa qiymatini, aks holda None qaytaradi."""
    total = group = 0
    last = None  # oxirgi so'z turi: 'one', 'ten', 'hundred', 'scale'
    for w in words:
        if w in _ONES:
            if last in ("one",):
                return None
            group += _ONES[w]; last = "one"
        elif w in _TENS:
            if last in ("one", "ten"):
                return None
            group += _TENS[w]; last = "ten"
        elif w == "yuz":
            if last in ("ten", "hundred") or group >= 10:
                return None
            group = (group or 1) * 100; last = "hundred"
        else:
            if group == 0 and total == 0:
                return None
            total += (group or 1) * _SCALE[w]; group = 0; last = "scale"
    return total + group


def to_digits(text: str) -> str:
    def repl(m: re.Match) -> str:
        words = [_norm(w) for w in m.group(0).split()]
        if words == ["yuz"] or words[0] in _SCALE:
            return m.group(0)
        if re.match(r"\s+yarim", text[m.end():], re.I):  # "ikki yarim yil" = 2,5 yil: o'zgartirmaymiz
            return m.group(0)
        if words == ["bir"] and not _UNIT_AFTER.match(text, m.end()):
            return m.group(0)
        value = _value(words)
        return m.group(0) if value is None else f"{value:,}".replace(",", " ")

    return _SEQ.sub(repl, text)
