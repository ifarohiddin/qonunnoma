"""Berilgan lex.uz hujjatlarini ishlab turgan serverning /ingest/lex endpointi orqali bazaga qo'shadi.

Serverning o'zida ishga tushiriladi (lex.uz'dan matnni server oladi va o'zi indekslaydi). Admin token .env dan olinadi.
Hujjat ID'lari manfiy bo'lishi mumkin (masalan -2414114), shuning uchun vergul bilan beriladi:

    .venv/bin/python scripts/ingest_ids.py --ids=-2414114,-2307248
    .venv/bin/python scripts/ingest_ids.py --file scripts/topic_ids.txt     # har qatorda bitta ID, # — izoh

Bazada bor hujjat almashtiriladi (dublikat bo'lmaydi). Yangi hujjatlar qidiruvga servis qayta ishga tushgandan keyin
tushadi (CORPUS_REBUILD_SECONDS katta bo'lgani uchun qidiruv indeksi o'z-o'zidan qayta qurilmaydi).
"""
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SERVER = "http://127.0.0.1:8000"
DELAY = 2  # lex.uz ga yuk tushmasligi uchun hujjatlar orasida pauza


def admin_token() -> str:
    match = re.search(r"^ADMIN_TOKEN=(.*)$", (ROOT / ".env").read_text(encoding="utf-8"), re.M)
    if not match or not match.group(1).strip():
        sys.exit(".env da ADMIN_TOKEN yo'q")
    return match.group(1).strip()


def ingest(doc_id: str, token: str) -> dict:
    body = json.dumps({"urls": [f"https://lex.uz/uz/docs/{doc_id}"]}).encode()
    request = urllib.request.Request(SERVER + "/ingest/lex", body, {"Content-Type": "application/json", "X-Admin-Token": token})
    return json.load(urllib.request.urlopen(request, timeout=1800))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", default="", help="vergul bilan ajratilgan lex.uz ID'lari")
    parser.add_argument("--file", help="har qatorda bitta ID (# bilan izoh)")
    args = parser.parse_args()
    ids = [i.strip() for i in args.ids.split(",") if i.strip()]
    if args.file:
        for line in Path(args.file).read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                ids.append(line)
    ids = list(dict.fromkeys(ids))
    if not ids:
        sys.exit("ID berilmadi")
    token, added, failed = admin_token(), 0, []
    for n, doc_id in enumerate(ids, 1):
        started = time.time()
        try:
            result = ingest(doc_id, token)
            if result["indexed"]:
                info = result["indexed"][0]
                added += 1
                print(f"{n}/{len(ids)} OK   {doc_id}  {info['chunks']} bo'lak  {info['title'][:80]}  ({time.time() - started:.0f}s)", flush=True)
            else:
                reason = next(iter(result["errors"].values()), "?")
                failed.append(doc_id)
                print(f"{n}/{len(ids)} XATO {doc_id}  {reason[:120]}", flush=True)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            failed.append(doc_id)
            print(f"{n}/{len(ids)} XATO {doc_id}  server: {exc}", flush=True)
            time.sleep(30)
        time.sleep(DELAY)
    print(f"\nTAYYOR: {added} ta qo'shildi, {len(failed)} ta xato {failed if failed else ''}", flush=True)


if __name__ == "__main__":
    main()
