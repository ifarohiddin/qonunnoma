"""Test to'plamini /v1/rag/batch ga 10 ta batch qilib ketma-ket yuboradi va har bir javobni saqlaydi.

Ishlatish:  python run_eval.py [run_id] [--base https://qonunnoma.uz]
API kalit: ../../qoidalar/eval_api_key.txt yoki EVAL_API_KEY muhit o'zgaruvchisi.
Natija: runs/<run_id>/b01.json ... b10.json
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
BASE = "https://qonunnoma.uz"
if "--base" in sys.argv:
    BASE = sys.argv[sys.argv.index("--base") + 1]
args = [a for a in sys.argv[1:] if not a.startswith("--") and a != BASE]
RUN_ID = args[0] if args else time.strftime("eval-%Y-%m-%d-%H%M")
KEY = os.environ.get("EVAL_API_KEY") or (HERE.parent.parent / "qoidalar" / "eval_api_key.txt").read_text().strip()
HEADERS = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json; charset=utf-8", "User-Agent": "rag-eval-client/1.0"}


def call(method: str, path: str, body: dict | None = None, timeout: int = 150) -> tuple[int, dict]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(BASE + path, data=data, headers=HEADERS, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except ValueError:
            return exc.code, {"error": {"code": "HTTP", "message": raw[:200].decode("utf-8", "replace")}}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 599, {"error": {"code": "NETWORK", "message": str(exc)}}


def send(batch: dict) -> dict:
    """Spetsifikatsiya 5-bo'lim: 5xx va timeout bo'lsa 3 martagacha (5, 15, 45 s) o'sha batch_id bilan qayta."""
    for wait in (5, 15, 45, None):
        status, data = call("POST", "/v1/rag/batch", batch)
        if status == 202:  # async: tayyor bo'lguncha so'raymiz
            while status == 202:
                time.sleep(5)
                status, data = call("GET", f"/v1/rag/batch/{batch['batch_id']}")
        if status == 200:
            return data
        if status == 429:
            time.sleep(2)
            continue
        if status < 500 and status != 599 or wait is None:
            raise SystemExit(f"{batch['batch_id']}: HTTP {status} {data}")
        print(f"  {batch['batch_id']}: HTTP {status}, {wait} s dan keyin qayta...")
        time.sleep(wait)
    raise SystemExit("qayta urinishlar tugadi")


def main() -> None:
    testset = json.loads((HERE / "testset.json").read_text(encoding="utf-8"))
    out = HERE / "runs" / RUN_ID
    out.mkdir(parents=True, exist_ok=True)
    status, meta = call("GET", "/v1/meta")
    if status != 200:
        raise SystemExit(f"/v1/meta: HTTP {status} {meta}")
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    print("tizim:", meta["system"])
    for number in range(1, 11):
        name = f"b{number:02d}"
        items = [{"id": t["id"], "question": t["question"], "language": t["language"]} for t in testset if t["batch"] == name]
        batch = {
            "run_id": RUN_ID, "batch_id": f"{RUN_ID}-{name}", "batch_index": number, "total_batches": 10,
            "options": {"top_k": 5, "return_contexts": True, "return_debug": True, "answer_language": "auto"},
            "items": items,
        }
        started = time.time()
        result = send(batch)  # oldingi batch javobi kelgandan keyin keyingisi
        (out / f"{name}.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        s = result["summary"]
        print(f"{name}: {time.time() - started:5.1f} s  ok={s['ok']} no_answer={s['no_answer']} error={s['error']}")


if __name__ == "__main__":
    main()
