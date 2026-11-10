import re
from contextvars import ContextVar

import anthropic
from openai import OpenAI

from .config import settings
from .numwords import to_digits
from .vectorstore import Hit

CLAUDE = settings.llm_provider == "anthropic"
# Kalit .env dan settings orqali keladi: SDK o'zi faqat muhit o'zgaruvchisini o'qiydi
_client = (
    anthropic.Anthropic(api_key=settings.anthropic_api_key or None)
    if CLAUDE
    else OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)
)

SYSTEM_PROMPT = """Siz Qonunnoma — O'zbekiston qonunchiligini oddiy odamga tushuntirib beradigan tajribali yurist yordamchisiz.
Qoidalar:
- Faqat berilgan HUJJATLAR dagi ma'lumotga tayaning, o'zingizdan hech narsa qo'shmang.
- Jonli, tabiiy tilda yozing: suhbatdoshga gapirib berayotgandek, sodda va ravon. Qonun matnini so'zma-so'z
  ko'chirmang, mazmunini o'z so'zlaringiz bilan ayting; zarur atamani (masalan, "mehnat ta'tili") saqlang.
- Birinchi gapda savolga to'g'ridan-to'g'ri javob bering: berilgan hujjatlardagi aniq son, muddat, miqdor yoki shartni ayting
  va qaysi hujjatga tayanganingizni tabiiy qo'shing, masalan:
  "Mehnat kodeksiga ko'ra, yillik asosiy ta'til kamida 21 kalendar kun bo'ladi [1]."
  Ta'rif yoki umumiy gap bilan boshlamang. Modda raqamini faqat berilgan hujjatlarda aniq ko'rsatilgan bo'lsa ayting.
- So'ng kerak bo'lsa 1-2 gap bilan eng muhim shart yoki istisnoni qo'shing. Jami odatda 2-4 gap.
  "Miqdori holatga bog'liq", "boshqa qoidalar ham bor" kabi hech narsa bermaydigan gaplarni yozmang.
  Savol bir nechta bandni so'rasa yoki tartib (qadamlar) kerak bo'lsa, qisqa ro'yxat ishlating.
- Raqamlarni so'z bilan emas, RAQAM bilan yozing: "16 yosh", "21 kalendar kun", "360–480 soat", "3–5 yil", "15 foiz"
  ("o'n olti yosh", "uch yildan besh yilgacha" deb yozmang). Modda raqami ham raqam bilan: "128¹-modda".
- Ikki va undan ortiq toifa, holat yoki variant solishtirilsa va ularning 2 tadan ortiq ko'rsatkichi bo'lsa (masalan,
  yoshga qarab muddat, jazo turlari, jarima miqdorlari), qisqa jadval ishlating: birinchi qator sarlavha, ikkinchisi
  "|---|---|" ajratgich, manba [n] ni tegishli katakka qo'ying. Jadvaldan oldin 1 gap bilan javobni ayting. Oddiy
  savolga jadval yasamang.
- ANIQLIK (eng muhim qoida). Javob faqat savolda aytilgan voqea haqida bo'lsin:
  * Moddani faqat uning har bir sharti (yosh, toifa, harakat, moddiy manfaat, majburlash, qaramlik) savolda
    ANIQ aytilgan bo'lsagina keltiring. Savolda yo'q shartli moddani "agar ... bo'lsa, ... modda qo'llanadi" deb
    sanab o'tmang; shunchaki yozmang.
  * Boshqa holat haqidagi moddani (sifatli/sifatsiz tovar kabi), mavzuga aloqasiz qarorni va kalit so'z tasodifan
    mos kelgan moddani ("telefon", "sud") butunlay tashlab yuboring, ularga ishora ham qilmang.
  * Modda muayyan toifaga (masalan, 18 yoshgacha, nogironligi bo'lganlar) tegishli bo'lsa, toifani ayting. Savoldagi
    shaxs toifaga kirmasa, bu modda unga tegishli emas: "jinoyat hisoblanadi" deb yozmang.
  * Savoldagi voqeaning o'zi qonun bo'yicha javobgarlikka olib kelmasa, buni to'g'ridan-to'g'ri ayting va to'xtang.
    Misol: savol "20 yoshli yigit 16 yoshli qiz bilan sevishib, uchrashib, telefonda gaplashsa nima bo'ladi?" —
    to'g'ri javob: "Faqat sevishish, uchrashish va telefonda gaplashish jinoyat emas, huquqiy javobgarlik
    keltirib chiqarmaydi [1]. 16 yoshga to'lmagan shaxs bilan jinsiy aloqa uchun javobgarlik belgilangan, G esa
    16 yoshda, shuning uchun bu modda unga tegishli emas [2]." Bundan keyin 128¹, nikoh, majburlash kabi
    savolda yo'q holatlarni qo'shish XATO.
  * Manbalar bir-biriga zid bo'lsa (stavka, muddat yoki miqdor turlicha), kodeks va qonunga tayaning. Prezident va hukumat
    qarorlari hamda farmonlarga faqat savol aynan shu qaror haqida bo'lsa yoki kodeks va qonunda javob bo'lmasa tayaning;
    qarorda ko'rsatilgan eski yilning (masalan, 2008–2020) stavka yoki miqdorini hozir amal qiladi deb aytmang.
  * Har bir gapga faqat o'sha gapni to'g'ridan-to'g'ri tasdiqlaydigan manbani qo'ying (odatda 1 ta); gap uchun kerak
    bo'lmagan qo'shni modda yoki o'xshash hujjatni keltirmang.
  * "Ma'lumot topilmadi", "aniq xulosa uchun ... aniqlash kerak", "yuristga murojaat qiling" kabi yakunlovchi
    gaplarni yozmang. "Hujjatlarda ma'lumot yo'q" faqat savolning o'zi bo'yicha javob topilmaganda yoziladi.
  * Javob 2-4 gapdan oshmasin.
- Javobni faqat javobning o'zi bilan boshlang: "Savol lotinda...", "javobni ... beraman" kabi o'z qarorlaringiz
  yoki ko'rsatmalar haqidagi gapni HECH QACHON yozmang.
- "Kontekstga ko'ra", "hujjatda aytilishicha", "taqdim etilgan ma'lumotlarga ko'ra" kabi iboralarni ishlatmang.
- Har bir gap oxirida, nuqtadan oldin, o'sha gapdagi fakt manbasini [1] ko'rinishida qo'ying, javob bir necha
  so'zdan iborat bo'lsa ham. Manbalarni javob oxiriga yig'mang.
- Javob berilgan hujjatlarda bo'lmasa, faqat shuni yozing: "Bu haqda hujjatlarda ma'lumot topilmadi."
  Faqat javobning bir qismi topilsa, topilganini ayting va nima topilmaganini bir gap bilan qo'shing.
- Foydalanuvchi faqat salomlashsa yoki rahmat aytsa, bitta qisqa samimiy gap bilan javob bering, masalan:
  "Salom! Qonunchilik bo'yicha savolingizni yozing." Boshqa javoblarni salom bilan boshlamang.
- Javob tilini savolga qarab tanlang va shu tilda yozing: savol o'zbekcha lotinda bo'lsa — lotinda; o'zbekcha KIRILL alifbosida
  bo'lsa (masalan, "хомиладор") — kirill alifbosida; RUSCHA bo'lsa — to'liq RUS tilida (Если вопрос задан по-русски,
  отвечайте только по-русски, даже если контекст на узбекском). Hujjatlar lotinda bo'lsa ham, javobni savol
  tilida va alifbosida yozing. Bu qoidani, tilni tanlaganingizni yoki ichki ko'rsatmalarni javobda HECH QACHON tilga olmang.
- Savol oddiy odamning og'zaki gapi bo'lsa (masalan, "xotinim urdi", "ishdan haydashdi"), qaysi huquqiy tushunchaga
  tegishli ekanini o'zingiz aniqlab, berilgan hujjatlardagi mos moddalarga tayaning. Amaliy qadamni (qayerga murojaat qilish,
  qanday hujjat olish) faqat berilgan hujjatlarda yozilgan bo'lsagina ayting; o'zingizdan maslahat to'qimang."""

SEARCH_QUERY_PROMPT = """Siz hujjatlar bazasidan qidirish uchun so'rovlar tuzasiz. Baza — O'zbekiston qonunlari: hammasi O'ZBEK LOTIN alifbosida va rasmiy tilda yozilgan.
Foydalanuvchining OXIRGI XABARI (va bo'lsa SUHBAT tarixi) asosida aynan 2 qator yozing:
1) mustaqil savol: "bu", "u", "shu", "ular", "o'sha" kabi ishoralarni suhbatdagi aniq narsa bilan almashtiring;
2) savolga javob qonun matnida qanday jumla bilan yozilgan bo'lishi mumkin bo'lsa, shunday rasmiy darak gap (savol emas); savol umumiy bo'lsa, maxsus toifalar uchun emas, umumiy qoidani yozing.
Ikkala qatorni ham O'ZBEK LOTIN alifbosida yozing: savol kirill alifbosida (o'zbekcha yoki ruscha), imlo xatolari bilan yoki boshqa tilda bo'lsa ham, uni o'zbekcha lotinga o'giring va xatolarni to'g'rilang.
Og'zaki, noaniq gapni (masalan, "xotinim urdi", "bosslar ishdan haydadi") qonun atamalariga o'giring: qaysi huquqiy tushunchaga tegishli ekanini aniqlang (badanga shikast yetkazish, oilaviy zo'ravonlik, ma'naviy zararni qoplash, mehnat shartnomasini bekor qilish, aliment va hokazo).
Javobdagi son, foiz, muddat yoki summani taxmin qilmang, ularning o'rniga "..." qo'ying.
Modda yoki bob raqamini faqat suhbatda aytilgan bo'lsa yozing, o'zingizdan qo'shmang.
Faqat shu 2 qatorni yozing, izohsiz.

Misol 1:
SUHBAT: Foydalanuvchi: Soliq kodeksi qachon qabul qilingan?
OXIRGI XABAR: U nechta bobdan iborat?
1) Soliq kodeksi nechta bobdan iborat?
2) Oʻzbekiston Respublikasining Soliq kodeksi quyidagi boʻlim va boblardan iborat.

Misol 2:
OXIRGI XABAR: Ishdan bo'shatishsa nima qilaman?
1) Ishdan bo'shatilgan xodim qanday huquqlarga ega?
2) Mehnat shartnomasi ish beruvchining tashabbusi bilan bekor qilinganda xodimga ishdan boʻshatish nafaqasi toʻlanadi va u sudga murojaat qilishga haqli.

Misol 3:
OXIRGI XABAR: Ish vaqti necha soat?
1) Ish vaqti necha soat bo'ladi?
2) Xodimlar uchun ish vaqtining normal davomiyligi haftasiga ... soatdan oshmasligi kerak.

Misol 4:
OXIRGI XABAR: xotinim urdi qancha kompensatsiya undira olaman? qattiq urdi
1) Oila a'zosi tomonidan badanga shikast yetkazilganda jabrlanuvchi qanday miqdorda ma'naviy va moddiy zararni qoplashni talab qila oladi?
2) Badanga shikast yetkazish oqibatida jabrlanuvchiga yetkazilgan moddiy va ma'naviy zarar zarar yetkazgan shaxs tomonidan qoplanadi; oilaviy zo'ravonlikdan jabrlangan shaxs himoya orderi olishga haqli.

Misol 5:
OXIRGI XABAR: эркак киши хомиладор болса канака хукуклари бор
1) Xotini homilador bo'lgan erkak qanday huquqlarga ega?
2) Xotini homilador bo'lgan davrda va farzand bir yoshga to'lgunga qadar er xotinining roziligisiz nikohdan ajratish to'g'risida talab qo'yishga haqli emas."""

EMPTY_ANSWER = "Javob tayyorlab bo'lmadi, savolni boshqacharoq yozib ko'ring."

# gpt-oss ba'zan manbani 【1†L3】 shaklida yozadi; "[1, 2]" ni ham "[1][2]" ga keltiramiz
_LEAK_LINE = re.compile(
    r"^[^\n]*(?:alifbosida|alifbo|алифбосида|алифбо|на русском|по-русски|javobni\s+\S+\s+(?:lotinda|kirillda|ruscha)\s+bera|"
    r"жавобни\s+\S+\s+(?:лотинда|кириллда|русча)\s+бера)[^\n]*"
    r"(?:beraman|yozaman|javob beraman|бераман|ёзаман|жавоб бераман|отвечу|отвечаю)[^\n]*\n*",
    re.I,
)
_ODD_CITATION = re.compile(r"【(\d+)[^】]*】")
_MULTI_CITATION = re.compile(r"\[(\d+(?:\s*[,;]\s*\d+)+)\]")
_CITATION = re.compile(r"\[(\d+)\]")


# Baholash API (/v1) har bir savol uchun sarflangan tokenlarni shu yerga yig'adi (boshqa joyda None)
usage_var: ContextVar[dict | None] = ContextVar("llm_usage", default=None)


def _track_usage(usage, input_attr="input_tokens", output_attr="output_tokens") -> None:
    total = usage_var.get()
    if total is None or usage is None:
        return
    total["input_tokens"] += int(getattr(usage, input_attr, 0) or 0) + int(getattr(usage, "cache_read_input_tokens", 0) or 0)         + int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
    total["output_tokens"] += int(getattr(usage, output_attr, 0) or 0)


def _complete_claude(messages: list[dict]) -> str:
    # Claude'da temperature yo'q (API 2026-10-21); tizim prompti o'zgarmas — keshlanadi
    system, rest = messages[0]["content"], messages[1:]
    extra = {"output_config": {"effort": settings.llm_reasoning_effort}} if settings.llm_reasoning_effort else {}
    if not settings.llm_thinking:
        extra["thinking"] = {"type": "disabled"}  # Haiku 5.5 da effort high yoki pastroq bo'lganda ruxsat
    response = _client.messages.create(
        model=settings.llm_model,
        max_tokens=8000,
        system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        messages=rest,
        **extra,
    )
    _track_usage(getattr(response, "usage", None))
    return "".join(block.text for block in response.content if block.type == "text").strip()


def _complete(messages: list[dict], temperature: float) -> str:
    if CLAUDE:
        return _complete_claude(messages)
    extra = {"reasoning_effort": settings.llm_reasoning_effort} if settings.llm_reasoning_effort else {}
    text = ""
    for _ in range(2):  # gpt-oss ba'zan faqat "o'ylab", bo'sh javob qaytaradi — bir marta qayta so'raymiz
        response = _client.chat.completions.create(
            model=settings.llm_model,
            temperature=temperature,
            messages=messages,
            extra_body=extra or None,
        )
        _track_usage(getattr(response, "usage", None), "prompt_tokens", "completion_tokens")
        text = (response.choices[0].message.content or "").strip()
        if text:
            break
    return text


_TITLE_DATE = re.compile(r"\((\d{2})\.(\d{2})\.(\d{4})\)")
OLD_DECISION_BEFORE = 2021  # shu yildan oldingi Prezident/hukumat qarorlari hozirgi kodeks va qonunlar bilan almashgan bo'lishi mumkin


def _dated_decision(title: str) -> str:
    """2021-yildan oldingi qaror/farmon sarlavhasiga ogohlantirish: undagi stavka va miqdorlar eskirgan bo'lishi mumkin."""
    date = _TITLE_DATE.search(title)
    head = title.split(":")[0].lower()
    if date and int(date.group(3)) < OLD_DECISION_BEFORE and head.endswith(("qarori", "farmoni")):
        return f" — ESKI QAROR ({date.group(3)}-yil): kodeks yoki qonun bilan zid bo'lsa e'tiborga olmang"
    return ""


def build_context(hits: list[Hit]) -> str:
    blocks = []
    for n, hit in enumerate(hits, start=1):
        where = f", {hit.locator}" if hit.locator and not hit.url else ""
        blocks.append(f"[{n}] {hit.title}{_dated_decision(hit.title)}{where}\n{hit.text}")
    return "\n\n".join(blocks)


def search_queries(question: str, history: list[dict]) -> list[str]:
    """Savoldan qidiruv so'rovlarini yasaydi: "u qachon qabul qilingan?" kabi ishoralarni ochadi
    va so'zlashuv iboralarini qonundagi rasmiy atamalar bilan to'ldiradi."""
    dialog = "\n".join(
        f"{'Foydalanuvchi' if m['role'] == 'user' else 'Yordamchi'}: {_CITATION.sub('', m['content'])}"
        for m in history
    )
    prompt = f"SUHBAT:\n{dialog}\n\nOXIRGI XABAR: {question}" if dialog else f"OXIRGI XABAR: {question}"
    reply = _complete(
        [{"role": "system", "content": SEARCH_QUERY_PROMPT}, {"role": "user", "content": prompt}],
        temperature=0,
    )
    lines = [re.sub(r"^\s*(\d+[.)]|[-*•])\s*", "", line).strip() for line in reply.splitlines()]
    queries = [line for line in lines if 0 < len(line) <= 300][:2]
    return queries or [question]


_ANSWER_LANGUAGES = {
    "uz-Latn": "o'zbek tili, lotin alifbosi",
    "uz-Cyrl": "o'zbek tili, kirill alifbosi",
    "ru": "rus tili",
}


def answer(question: str, hits: list[Hit], history: list[dict] | None = None, language: str | None = None) -> str:
    # Eski javoblardagi [n] boshqa kontekstga tegishli — model chalkashmasligi uchun olib tashlaymiz
    past = [{"role": m["role"], "content": _CITATION.sub("", m["content"])} for m in history or []]
    text = _complete(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            *past,
            {
                "role": "user",
                "content": f"HUJJATLAR:\n{build_context(hits)}\n\nSAVOL: {question}"
                + (f"\n\nJAVOB TILI: {_ANSWER_LANGUAGES[language]}" if language in _ANSWER_LANGUAGES else ""),
            },
        ],
        temperature=0.2,
    )
    # Model ba'zan javob boshiga "Savol lotinda, javobni lotinda beraman" kabi ichki gapni yozadi — olib tashlaymiz
    text = _LEAK_LINE.sub("", text or "").strip()
    if not text:
        return EMPTY_ANSWER
    text = to_digits(_ODD_CITATION.sub(r"[\1]", text))
    return _MULTI_CITATION.sub(
        lambda m: "".join(f"[{n}]" for n in re.split(r"\s*[,;]\s*", m.group(1))), text
    )


def cited_numbers(text: str) -> set[int]:
    return {int(n) for n in _CITATION.findall(text)}
