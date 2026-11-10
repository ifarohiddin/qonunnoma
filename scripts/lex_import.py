"""lex.uz dan hujjatlarni ommaviy yuklash: ro'yxatni lex.uz qidiruvidan oladi va har birini ishlab turgan
serverning /ingest/lex endpointi orqali indekslaydi.

Guruhlar muhimlik tartibida: 2015-yildan beri qonunlar -> advokaturaga oid hujjatlar -> 2015-yilgacha qabul
qilingan amaldagi qonunlar -> 2015-yildan beri Prezident farmon va qarorlari -> Hukumat qarorlari. Faqat amaldagi hujjatlar; "o'zgartirish kiritish" va ratifikatsiya hujjatlari
tashlab ketiladi (o'zgarishlar asosiy hujjat matnida bor).

Istalgan payt Ctrl+C bilan to'xtatish mumkin: qayta ishga tushirilsa, qolgan joyidan davom etadi
(holat data/lex_import/ papkasida). lex.uz ga yuk tushmasligi uchun so'rovlar orasida pauza bor.

    .venv/Scripts/python scripts/lex_import.py                # hamma guruh
    .venv/Scripts/python scripts/lex_import.py qonun advokat  # faqat shu guruhlar
"""
import json
import math
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import settings  # noqa: E402  (.env dagi ADMIN_TOKEN uchun)

SERVER = "http://127.0.0.1:8000"
STATE_DIR = Path(__file__).resolve().parent.parent / "data" / "lex_import"
TODAY = date.today().strftime("%d.%m.%Y")
GROUPS = {
    "qonun": f"https://lex.uz/uz/search/nat?lang=4&form_id=3968&from=01.01.2015&to={TODAY}",
    # Nom bo'yicha qidiruv so'z shakliga sezgir: "advokat" so'rovi "Advokatura toʻgʻrisida"gi qonunni topmaydi
    "advokat": [
        "https://lex.uz/uz/search/all?searchtitle=advokat",
        "https://lex.uz/uz/search/all?searchtitle=Advokatura",
        "https://lex.uz/uz/search/all?searchtitle=advokatlik",
        "https://lex.uz/uz/search/all?searchtitle=advokatlar",
    ],
    # 2015-yilgacha qabul qilingan, lekin hozir ham amaldagi qonunlar (masalan, "Advokatura toʻgʻrisida", 1996)
    "qonun_eski": "https://lex.uz/uz/search/nat?lang=4&form_id=3968&from=01.01.1991&to=31.12.2014",
    "prezident": f"https://lex.uz/uz/search/all?act_type=3&from=01.01.2015&to={TODAY}&lang=4",
    "hukumat": f"https://lex.uz/uz/search/all?act_type=4&from=01.01.2015&to={TODAY}&lang=4",
}
PAGE_DELAY, DOC_DELAY = 3, 2
_AP = "[ʻ‘'’`]"
# O'zgartirish, ratifikatsiya, kuchini yo'qotgan deb topish — mustaqil matni yo'q yoki eskirgan hujjatlar
_SKIP_TITLE = re.compile(
    rf"o{_AP}zgartish|o{_AP}zgartirish|qo{_AP}shimcha(lar)? kiritish|ratifikatsiya|kuchini yo{_AP}qotgan deb", re.I
)
_HTTP = httpx.Client(headers={"User-Agent": "Mozilla/5.0 (compatible; RAG-study-bot)"}, follow_redirects=True, timeout=90)


def log(message: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {message}"
    print(line, flush=True)
    with open(STATE_DIR / "import.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _get(url: str, data: dict | None = None) -> str:
    for attempt in range(5):  # lex.uz ba'zan ulanishni uzadi — kutib qayta urinamiz
        try:
            response = _HTTP.post(url, data=data) if data else _HTTP.get(url)
            response.raise_for_status()
            return response.text
        except httpx.HTTPError as exc:
            wait = 30 * (attempt + 1)
            log(f"  lex.uz xatosi ({exc.__class__.__name__}), {wait}s kutiladi")
            time.sleep(wait)
    raise RuntimeError(f"lex.uz javob bermadi: {url}")


def _rows(soup: BeautifulSoup) -> list[dict]:
    rows = []
    for tr in soup.select("tr.dd-table__main-item"):
        link = tr.find("a", href=re.compile(r"^/uz/docs/-?\d+$"))
        if not link:
            continue
        state = tr.select_one(".lx_act_state i")
        badge = tr.select_one(".badge")
        rows.append({
            "id": link["href"].rsplit("/", 1)[1],
            "title": re.sub(r"\s+", " ", link.get_text(" ", strip=True)),
            "in_force": bool(state and "status_code_y" in state.get("class", [])),
            "kind": re.sub(r"\s+", " ", badge.get_text(" ", strip=True)) if badge else "",
        })
    return rows


def collect(group: str) -> list[dict]:
    """Qidiruvning barcha sahifalari (ASP.NET postback bilan sahifalanadi). Natija keshlanadi."""
    cache = STATE_DIR / f"list_{group}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    urls = GROUPS[group] if isinstance(GROUPS[group], list) else [GROUPS[group]]
    rows = []
    for url in urls:
        rows += _collect_search(group, url)
        time.sleep(PAGE_DELAY)
    unique = list({r["id"]: r for r in rows}.values())
    cache.write_text(json.dumps(unique, ensure_ascii=False, indent=0), encoding="utf-8")
    log(f"[{group}] ro'yxat tayyor: {len(unique)} hujjat")
    return unique


def _collect_search(group: str, url: str) -> list[dict]:
    soup = BeautifulSoup(_get(url), "lxml")
    total = re.search(r"([\d\s  ]+) hujjat topildi", soup.get_text(" "))
    pages = math.ceil(int(re.sub(r"\D", "", total.group(1))) / 20) if total else 1
    log(f"[{group}] {pages} sahifa ro'yxat yig'ilmoqda")
    rows, page = _rows(soup), 1
    while page < pages:
        links = {a.get_text(strip=True): a["href"] for a in soup.find_all("a", href=re.compile("rptPaging"))}
        href = links.get(str(page + 1)) or links.get("...") or links.get("»")
        if not href:
            break
        form = {i["name"]: i.get("value", "") for i in soup.find_all("input", attrs={"name": True}) if i.get("type") in (None, "hidden")}
        form.update({"__EVENTTARGET": re.search(r"__doPostBack\('([^']+)'", href).group(1), "__EVENTARGUMENT": ""})
        time.sleep(PAGE_DELAY)
        soup = BeautifulSoup(_get(url, form), "lxml")
        current = soup.select_one(".pagination .active, [class*=paging] .active")
        page = int(current.get_text(strip=True)) if current and current.get_text(strip=True).isdigit() else page + 1
        rows += _rows(soup)
        if page % 20 == 0:
            log(f"[{group}] {page}/{pages} sahifa, {len(rows)} hujjat")
    return rows


def ingest(doc_id: str) -> dict:
    body = json.dumps({"urls": [f"https://lex.uz/uz/docs/{doc_id}"]}).encode()
    headers = {"Content-Type": "application/json", "X-Admin-Token": settings.admin_token}
    request = urllib.request.Request(SERVER + "/ingest/lex", body, headers)
    return json.load(urllib.request.urlopen(request, timeout=1800))


def main(groups: list[str]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file = STATE_DIR / "state.json"
    # Holat faylini o'chirib qayta ishga tushirilsa, hammasi qaytadan yuklanadi (hujjat almashtiriladi, dublikat bo'lmaydi)
    state: dict[str, str] = json.loads(state_file.read_text(encoding="utf-8")) if state_file.exists() else {}

    for group in groups:
        rows = collect(group)
        todo = [r for r in rows if r["in_force"] and not _SKIP_TITLE.search(r["title"]) and "Farmoyish" not in r["kind"]]
        log(f"[{group}] {len(rows)} ta topildi, {len(todo)} tasi amalda va mustaqil hujjat")
        done = chunks = 0
        for n, row in enumerate(todo, 1):
            if state.get(row["id"], "").startswith(("ok", "skip")):
                continue
            started = time.time()
            try:
                result = ingest(row["id"])
                if result["indexed"]:
                    state[row["id"]] = f"ok:{result['indexed'][0]['chunks']}"
                    chunks += result["indexed"][0]["chunks"]
                    done += 1
                else:
                    error = next(iter(result["errors"].values()), "?")
                    state[row["id"]] = ("skip:" if "eskirgan" in error or "topilmadi" in error else "fail:") + error[:200]
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                state[row["id"]] = f"fail:server {exc}"
                log(f"  server bilan aloqa yo'q ({exc}); 60s kutiladi")
                time.sleep(60)
            state_file.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            if n % 10 == 0 or not state[row["id"]].startswith("ok"):
                log(f"[{group}] {n}/{len(todo)} · {state[row['id']][:60]} · {row['title'][:60]} ({time.time() - started:.0f}s)")
            time.sleep(DOC_DELAY)
        log(f"[{group}] TAYYOR: {done} ta yangi hujjat, {chunks} bo'lak")


if __name__ == "__main__":
    main(sys.argv[1:] or list(GROUPS))
