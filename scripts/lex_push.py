"""lex.uz hujjatlarini SHU kompyuterda (GPU) yuklab, bo'laklab, embedding hisoblaydi va tayyor holda serverning
/ingest/precomputed endpointiga yuboradi. Serverning CPU'sida embedding bitta hujjatga ~30 soniya oladi va foydalanuvchilar
savoliga halaqit beradi; GPU'da esa soniyalar.

    .venv/Scripts/python scripts/lex_push.py --file scripts/topic_ids.txt
    .venv/Scripts/python scripts/lex_push.py --ids=-2414114,-2307248
    SERVER_URL=http://127.0.0.1:8000 ...   # boshqa server (standart: https://qonunnoma.uz)

Holat data/lex_import/push_state.json da: to'xtatilsa, qayta ishga tushirilganda qolgan joyidan davom etadi.
Yangi hujjatlar serverda qidiruv indeksiga servis qayta ishga tushgandan keyin tushadi.
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import embeddings  # noqa: E402
from app.chunking import make_chunks  # noqa: E402
from app.config import settings  # noqa: E402
from app.loaders import fetch_many_lex  # noqa: E402

SERVER = os.environ.get("SERVER_URL", "https://qonunnoma.uz").rstrip("/")
STATE_FILE = ROOT / "data" / "lex_import" / "push_state.json"
DELAY = 1.5  # lex.uz ga yuk tushmasligi uchun hujjatlar orasida pauza


def load_ids(args: argparse.Namespace) -> list[str]:
    ids = [i.strip() for i in args.ids.split(",") if i.strip()]
    if args.file:
        for line in Path(args.file).read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                ids.append(line)
    return list(dict.fromkeys(ids))


def push(client: httpx.Client, doc, chunks, vectors) -> None:
    body = {
        "source": doc.source, "title": doc.title, "url": doc.url,
        "chunks": [{"text": c.text, "locator": c.locator} for c in chunks],
        "embeddings": [[round(x, 5) for x in v] for v in vectors],  # 5 xona yetarli, so'rov hajmi ~3 baravar kichrayadi
    }
    for attempt in range(6):
        try:
            response = client.post(f"{SERVER}/ingest/precomputed", json=body, headers={"X-Admin-Token": settings.admin_token})
            if response.status_code == 200:
                return
            if response.status_code in (400, 401, 403, 404, 422):  # qayta urinish foydasiz
                raise RuntimeError(f"server rad etdi: {response.status_code} {response.text[:200]}")
        except httpx.HTTPError as exc:
            print(f"  server bilan aloqa xatosi ({exc.__class__.__name__}), {10 * (attempt + 1)}s kutiladi", flush=True)
        time.sleep(10 * (attempt + 1))
    raise RuntimeError("server javob bermadi")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", default="")
    parser.add_argument("--file")
    parser.add_argument("--max-chunks", type=int, default=400, help="bundan katta hujjat o'tkazib yuboriladi (server xotirasi)")
    parser.add_argument("--budget", type=int, default=0, help="jami bo'laklar shu sondan oshganda to'xtaydi (0 — cheklovsiz)")
    args = parser.parse_args()
    ids = load_ids(args)
    if not ids:
        sys.exit("ID berilmadi")
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    state: dict[str, str] = json.loads(STATE_FILE.read_text(encoding="utf-8")) if STATE_FILE.exists() else {}
    todo = [i for i in ids if not state.get(i, "").startswith(("ok", "skip"))]
    print(f"{len(ids)} ta ID, {len(todo)} tasi qoldi. Server: {SERVER}", flush=True)
    done = chunks_total = 0
    started = time.time()
    with httpx.Client(timeout=300) as client:
        for n, doc_id in enumerate(todo, 1):
            if args.budget and chunks_total >= args.budget:
                print(f"Byudjet tugadi ({chunks_total} bo'lak): to'xtatildi, qolganlari keyingi safar.", flush=True)
                break
            t = time.time()
            try:
                docs, errors = fetch_many_lex([f"https://lex.uz/uz/docs/{doc_id}"])
                if not docs:
                    reason = next(iter(errors.values()), "?")
                    state[doc_id] = ("skip:" if "eskirgan" in reason or "topilmadi" in reason else "fail:") + reason[:160]
                    print(f"{n}/{len(todo)} {state[doc_id][:100]}  ({doc_id})", flush=True)
                else:
                    doc = docs[0]
                    chunks = make_chunks(doc.segments, settings.chunk_chars, settings.chunk_overlap)
                    if len(chunks) > args.max_chunks:
                        state[doc_id] = f"skip:juda katta ({len(chunks)} bo'lak)"
                        print(f"{n}/{len(todo)} o'tkazildi: {len(chunks)} bo'lak  {doc.title[:70]}", flush=True)
                        time.sleep(DELAY)
                        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
                        continue
                    # Serverdagi _index bilan bir xil: hujjat nomi ham vektorga kiradi
                    vectors = embeddings.embed_passages([f"{doc.title}\n{c.text}" for c in chunks])
                    push(client, doc, chunks, vectors)
                    state[doc_id] = f"ok:{len(chunks)}"
                    done += 1
                    chunks_total += len(chunks)
                    print(f"{n}/{len(todo)} OK {len(chunks):>3} bo'lak  {doc.title[:80]}  ({time.time() - t:.0f}s)", flush=True)
            except Exception as exc:
                state[doc_id] = f"fail:{exc}"[:200]
                print(f"{n}/{len(todo)} XATO {doc_id}: {str(exc)[:150]}", flush=True)
            STATE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
            time.sleep(DELAY)
    failed = [i for i in todo if state.get(i, "").startswith("fail")]
    print(f"\nTAYYOR: {done} ta hujjat, {chunks_total} bo'lak, {(time.time() - started) / 60:.0f} daqiqa. Xato: {len(failed)} {failed[:20]}", flush=True)


if __name__ == "__main__":
    main()
