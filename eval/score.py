"""run_id papkasidagi b01..b10.json ni testset.json bilan solishtirib, spetsifikatsiya 6-bo'limidagi metrikalarni hisoblaydi.

Ishlatish:  python score.py runs/<run_id>
Avtomatik hisoblanadigan metrikalar to'liq LLM-hakam o'rniga PROKSI hisoblanadi (qo'lda tekshirish tavsiya etiladi):
  - correctness: kutilgan javobdagi kalit so'z/raqamlar javobda bormi (0/1/2)
  - faithfulness: javobdagi raqamlar keltirilgan kontekstlarda bormi
  - citation accuracy: keltirilgan modda kutilgan moddaga mos keladimi
"""
import json
import re
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "app"))
from numwords import to_digits  # noqa: E402

HERE = Path(__file__).parent
run_dir = Path(sys.argv[1])
testset = {t["id"]: t for t in json.loads((HERE / "testset.json").read_text(encoding="utf-8"))}
results = {}
for path in sorted(run_dir.glob("b[0-9][0-9].json")):
    for r in json.loads(path.read_text(encoding="utf-8"))["results"]:
        results[r["id"]] = r
meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8")) if (run_dir / "meta.json").exists() else {}


def norm(text: str) -> str:
    return re.sub(r"[ʻʼ’‘`]", "'", (text or "").lower())


def pair(c: dict) -> tuple:
    return (c["doc_id"], c.get("article"))


rows = []
for qid, t in testset.items():
    r = results.get(qid)
    if r is None:
        rows.append({"id": qid, "t": t, "missing": True})
        continue
    expected = {(e["doc_id"], e["article"]) for e in t["expected"]}
    exp_docs = {e["doc_id"] for e in t["expected"]}
    ctx = r.get("contexts") or []
    top5 = [c for c in ctx if c["rank"] <= 5]
    row = {"id": qid, "t": t, "r": r, "status": r["status"]}
    if t["answerable"]:
        row["doc_hit"] = any(c["doc_id"] in exp_docs for c in top5)
        row["art_hit"] = any(pair(c) in expected for c in top5)
        ranks = [c["rank"] for c in ctx if pair(c) in expected]
        row["rr"] = 1 / min(ranks) if ranks else 0.0
        row["recall"] = len({pair(c) for c in top5} & expected) / len(expected)
        row["precision"] = sum(pair(c) in expected for c in top5) / max(1, len(top5))
        row["doc_precision"] = sum(c["doc_id"] in exp_docs for c in top5) / max(1, len(top5))
    if t["answerable"] and t["keywords"] and r["status"] in ("ok", "no_answer") and r.get("answer"):
        answer = norm(r["answer"])
        hit = sum(bool(re.search(norm(k), answer)) for k in t["keywords"])
        row["score"] = 2 if hit == len(t["keywords"]) else 1 if hit >= len(t["keywords"]) / 2 else 0
        if r["no_answer"]:
            row["score"] = 0
    elif t["answerable"] and t["keywords"]:
        row["score"] = 0
    cites = r.get("citations") or []
    if cites:
        cited_ctx = [c for c in ctx if c["chunk_id"] in {x["chunk_id"] for x in cites}]
        row["cite_in_ctx"] = all(x["chunk_id"] in {c["chunk_id"] for c in ctx} for x in cites)
        if t["answerable"]:
            row["cite_match"] = sum(pair(x) in expected for x in cites) / len(cites)
            row["cite_any"] = any(pair(x) in expected for x in cites)
        text = to_digits(norm(" ".join(c.get("text") or "" for c in cited_ctx)))
        text = re.sub(r"\s+", " ", text)
        numbers = set(re.findall(r"\d+(?:[.,]\d+)?", re.sub(r"\[\d+\]", "", r["answer"])))
        flat = text.replace(" ", "")
        row["numbers_ok"] = all(n in text or n.replace(",", ".") in text or n in flat for n in numbers) if numbers else None
    rows.append(row)


def mean(values):
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else float("nan")


def pct(x):
    return f"{x * 100:5.1f}%"


answerable = [x for x in rows if x["t"]["answerable"] and "r" in x]
unanswerable = [x for x in rows if not x["t"]["answerable"] and "r" in x]
done = [x for x in rows if "r" in x]
print(f"# Baholash natijasi: {run_dir.name}")
if meta:
    s = meta["system"]
    print(f"Tizim: {s['llm_model']} | {s['embedding_model']} | reranker={s['reranker']} | {s['index_version']}")
print(f"Savollar: {len(done)}/{len(rows)} javob keldi; javobi bor: {len(answerable)}, javobsiz: {len(unanswerable)}\n")

print("## Retrieval (javobi bor savollar)")
print(f"Hit@5 (hujjat)      : {pct(mean(x['doc_hit'] for x in answerable))}   maqsad >= 90%")
print(f"Hit@5 (modda)       : {pct(mean(x['art_hit'] for x in answerable))}   maqsad >= 80%")
print(f"MRR (modda)         : {mean(x['rr'] for x in answerable):.3f}   maqsad >= 0.70")
print(f"Recall@5 (modda)    : {pct(mean(x['recall'] for x in answerable))}")
print(f"Context precision   : {pct(mean(x['precision'] for x in answerable))}   maqsad >= 60% (qat'iy: aynan kutilgan modda)")
print(f"Context precision*  : {pct(mean(x['doc_precision'] for x in answerable))}   (yumshoq: kutilgan hujjat)\n")

print("## Generatsiya va manba (proksi)")
scored = [x for x in answerable if "score" in x]
print(f"Answer correctness  : {mean(x['score'] for x in scored):.2f} / 2   maqsad >= 1.6   (n={len(scored)}, kalit so'z bo'yicha)")
num = [x["numbers_ok"] for x in done if x.get("numbers_ok") is not None]
print(f"Faithfulness (raqam): {pct(mean(num))}   maqsad >= 95%   (n={len(num)}; javobdagi raqamlar keltirilgan kontekstda bormi)")
cm = [x["cite_any"] for x in answerable if "cite_any" in x]
cp = [x["cite_match"] for x in answerable if "cite_match" in x]
print(f"Citation accuracy   : {pct(mean(cp))}   maqsad >= 90%   (keltirilgan modda kutilganga mos; kamida bittasi mos: {pct(mean(cm))})")
bad = [x for x in done if x.get("cite_in_ctx") is False]
print(f"To'qilgan manba     : {len(bad)} ta   maqsad 0   (citation chunk_id contexts da yo'q)")
old = [c for x in done for c in (x['r'].get('citations') or []) if c.get("doc_status") != "amalda"]
print(f"Eskirgan norma      : {len(old)} ta   maqsad 0\n")

print("## Xavfsizlik (javobsiz savollar)")
ok = [x for x in unanswerable if x["r"]["no_answer"]]
print(f"No-answer aniqligi  : {len(ok)} / {len(unanswerable)}   maqsad >= 9/10")
for x in unanswerable:
    if not x["r"]["no_answer"]:
        print(f"   to'qigan javob: {x['id']} {x['t']['question'][:60]} -> {x['r']['answer'][:100]!r}")
false_refusals = [x for x in answerable if x["r"]["no_answer"]]
print(f"Noto'g'ri rad etish : {len(false_refusals)} / {len(answerable)} (javobi bor savolga no_answer)\n")

print("## Operatsion")
times = sorted(x["r"]["timing"]["total_ms"] for x in done if x["r"].get("timing") and x["r"]["timing"].get("total_ms"))
if times:
    p = lambda q: times[min(len(times) - 1, int(q * len(times)))] / 1000  # noqa: E731
    print(f"Latency p50 / p95   : {p(0.5):.1f} s / {p(0.95):.1f} s   maqsad <= 5 s / <= 12 s")
errs = [x for x in done if x["status"] in ("error", "timeout")]
print(f"Xato ulushi         : {pct(len(errs) / max(1, len(done)))}   maqsad <= 2%   ({len(errs)} ta)")
usage_in = sum((x["r"].get("usage") or {}).get("input_tokens", 0) for x in done)
usage_out = sum((x["r"].get("usage") or {}).get("output_tokens", 0) for x in done)
print(f"Tokenlar            : kirish {usage_in}, chiqish {usage_out} (100 savol)\n")

print("## Kategoriya bo'yicha")
by = defaultdict(list)
for x in answerable:
    by[x["t"]["category"]].append(x)
print(f"{'kategoriya':18} {'n':>3} {'Hit@5 doc':>10} {'Hit@5 art':>10} {'MRR':>6} {'javob 0-2':>10}")
for cat, xs in by.items():
    sc = [x["score"] for x in xs if "score" in x]
    print(f"{cat:18} {len(xs):3d} {pct(mean(x['doc_hit'] for x in xs)):>10} {pct(mean(x['art_hit'] for x in xs)):>10} {mean(x['rr'] for x in xs):6.2f} {mean(sc):10.2f}")

print("\n## Xatolar tahlili (har biri bitta sababga)")
causes = defaultdict(list)
for x in answerable:
    if x["status"] in ("error", "timeout"):
        causes["xato (API)"].append(x)
    elif not x["art_hit"]:
        causes["retrieval: to'g'ri modda top-5 da yo'q"].append(x)
    elif x["r"]["no_answer"] or x.get("score", 2) < 2:
        causes["generatsiya: modda topilgan, javob noto'g'ri/to'liq emas"].append(x)
    elif x.get("cite_any") is False:
        causes["manba: javob to'g'ri, havola kutilgan moddaga mos emas"].append(x)
for cause, xs in causes.items():
    print(f"\n{cause}: {len(xs)} ta")
    for x in xs:
        got = [f"{c['article']}" for c in (x['r'].get('contexts') or [])[:5]]
        exp = [e["article"] for e in x["t"]["expected"]]
        print(f"  {x['id']} [{x['t']['category']}] {x['t']['question'][:70]}")
        print(f"      kutilgan: {exp} | top-5: {got}")
        if x["r"].get("answer"):
            print(f"      javob: {x['r']['answer'][:140]!r}")

(run_dir / "rows.json").write_text(json.dumps([{k: v for k, v in x.items() if k not in ("t", "r")} | {"question": x["t"]["question"], "category": x["t"]["category"]} for x in rows], ensure_ascii=False, indent=1, default=str), encoding="utf-8")
