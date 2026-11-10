# RAG tizimi (FastAPI)

lex.uz hujjatlari va PDF/DOCX/TXT fayllar asosida savol-javob beruvchi tizim.

- **Embedding:** `BAAI/bge-m3` (lokal, bepul, ko'p tilli; o'zbekcha savollarda `multilingual-e5` dan aniqroq)
- **Vektor baza:** ChromaDB (`data/chroma`, diskda saqlanadi)
- **Bo'laklash:** qonunlarda har bir modda alohida bo'lak, boshiga bo'lim va bob sarlavhasi qo'shiladi; qidiruvda hujjat
  nomi ham hisobga olinadi ("Mehnat kodeksi bo'yicha ..." savoli o'sha kodeksdan qidiradi)
- **lex.uz:** kuchini yo'qotgan hujjatlar qo'shilmaydi (chatbot eskirgan qonun bo'yicha javob bermasligi uchun)
- **Qidiruv:** gibrid — vektor (ma'no) + BM25 (so'z), Reciprocal Rank Fusion bilan birlashtiriladi.
  Vektor o'xshashligi xotirada aniq hisoblanadi (ChromaDB'ning taxminiy HNSW qidiruvi ba'zi moddalarni o'tkazib yuborardi).
  BM25 o'zbekcha uchun moslangan (apostrof normalizatsiyasi, so'z boshi va qo'shimchasiz o'zak: "kunni" → "kun").
  Savolda "106-modda" kabi havola bo'lsa, o'sha modda birinchi o'ringa qo'yiladi.
  Suhbatdagi davomiy savol ("u qachon qabul qilingan?") avval LLM orqali mustaqil savolga aylantiriladi
- **Qayta tartiblash:** `BAAI/bge-reranker-v2-m3` — gibrid qidiruvning eng yaxshi 30 ta nomzodini savol bilan birga
  o'qib, eng moslarini tanlaydi (o'xshash moddalar ko'p bo'lganda kerakligini yuqoriga chiqaradi)
- **LLM:** OpenAI'ning ochiq modeli `gpt-oss-20b` — Ollama (lokal), Groq yoki OpenRouter orqali

## Ishga tushirish

```bash
.venv/Scripts/python -m pip install -r requirements.txt   # bir marta
cp .env.example .env                                        # LLM sozlamalarini tahrirlang
.venv/Scripts/python -m uvicorn app.main:app --port 8000
```

- **Chatbot ("Qonunnoma"):** http://localhost:8000 — qisqa javob, o'ngda manbalar (modda, parcha, moslik bahosi,
  lex.uz havolasi). "Chuqur qidiruv" ko'proq parcha oladi, ro'yxatdan bitta hujjatni tanlab faqat u bo'yicha so'rash,
  "Fayl" bilan PDF/DOCX/TXT ni bazaga qo'shib u bo'yicha so'rash mumkin. Javobni saqlash, baholash (foydali/foydasiz),
  "Saqlangan javoblar" va "Qidiruv tarixi" bo'limlari bor
- **Hisoblar:** ro'yxatdan o'tgan foydalanuvchining suhbatlari va saqlangan javoblari serverda (`data/app.db`, SQLite)
  saqlanadi va istalgan brauzerdan ko'rinadi; mehmonniki — faqat shu brauzerda, kirganda hisobga ko'chiriladi.
  Parollar scrypt bilan xeshlanadi. Google/Telegram orqali kirish va parolni tiklash hozircha ulanmagan.
  Server faqat lokal ishlatish uchun: internetga ochishdan oldin HTTPS kerak
- **Swagger UI:** http://localhost:8000/docs — hujjat qo'shish va boshqa endpointlar (ommaviy rejimda yopiq)
- **qonunnoma.uz ga chiqarish:** [DEPLOY.md](DEPLOY.md) — Cloudflare Tunnel, ommaviy rejim, avtomatik ishga tushirish

## LLM tanlash (`.env`)

| Variant | Narx | Izoh |
|---|---|---|
| Ollama + `gpt-oss:20b` | bepul, lokal | ~14 GB xotira kerak; 16 GB RAM / 6 GB VRAM da sekin bo'ladi |
| Groq + `openai/gpt-oss-20b` | bepul tarif (limit bilan) | tez, API kalit kerak |
| OpenRouter + `openai/gpt-oss-20b:free` | bepul tarif | API kalit kerak |

## GPU (tavsiya etiladi)

NVIDIA GPU bo'lsa, PyTorch'ning CUDA versiyasini o'rnating (`pip install -r requirements.txt` CPU versiyasini qo'yadi):

```bash
.venv/Scripts/python -m pip install "torch==2.15.0+cu132" --index-url https://download.pytorch.org/whl/cu132
```

`cu132` — CUDA 13.2: u `nvidia-smi` ko'rsatgan CUDA versiyasidan katta bo'lmasin. Server ishlab turganda o'rnatmang
(Windows ishlatilayotgan fayllarni almashtira olmaydi). RTX 3060 (6 GB) da o'lchangan:

| | CPU | GPU |
|---|---|---|
| Bo'lakni vektorlash (`bge-m3`) | ~530 ms | ~11 ms |
| 20 ta kodeks + Konstitutsiya (11 ming bo'lak) | ~2.5 soat | ~6 daqiqa (lex.uz'dan yuklash bilan) |
| Reranker, bitta savol (30 nomzod) | ~10 s | ~0.3 s |

GPU'da ikkala model yarim aniqlikda (fp16) ishlaydi va server ishlab turgan butun vaqt davomida ~2.5–3.7 GB video
xotirani band qiladi. GPU o'yin yoki boshqa dastur bilan band bo'lsa, serverni CPU'da ishga tushiring (`.env` da
`DEVICE=cpu` yoki bir martalik):

```powershell
$env:DEVICE = "cpu"; .\.venv\Scripts\python -m uvicorn app.main:app --port 8000
```

GPU bo'lmasa, reranker'ni `.env` da `RERANK_MODEL=` bilan o'chiring.

## Embedding modeli

`bge-m3` ~2.3 GB xotira oladi. Yengilroq variant — `intfloat/multilingual-e5-base` (~4 baravar tez, sifati biroz past),
sozlamasi `.env.example` da. Har bir model o'z kolleksiyasida saqlanadi, shuning uchun modelni almashtirgandan keyin
hujjatlarni qayta yuklang.

## Endpointlar

```bash
# lex.uz dan hujjat qo'shish (havola yoki ID)
curl -X POST localhost:8000/ingest/lex -H "Content-Type: application/json" \
  -d '{"urls": ["https://lex.uz/uz/docs/-6445145"]}'

# Fayl yuklash
curl -X POST localhost:8000/ingest/files -F "files=@hujjat.pdf" -F "files=@matn.txt"

# Chatbot: qisqa javob + faqat javobda tilga olingan manbalar (modda nomi, qisqa parcha, moslik bahosi, havola).
# history — oldingi xabarlar, davomiy savollar ("bu qaysi moddada?") uchun; deep — chuqur qidiruv;
# source — faqat shu hujjatdan qidirish (/documents dagi "source")
curl -X POST localhost:8000/chat -H "Content-Type: application/json" \
  -d '{"message": "Davlat tili qaysi til?", "history": [], "deep": false, "source": null}'

# Javob + topilgan bo'laklarning to'liq matni (qidiruvni tekshirish uchun)
curl -X POST localhost:8000/ask -H "Content-Type: application/json" \
  -d '{"question": "Inson huquqlari qanday kafolatlanadi?"}'

# Faqat qidiruv (LLM'siz), hujjatlar ro'yxati, o'chirish
curl -X POST localhost:8000/search -H "Content-Type: application/json" -d '{"question": "..."}'
curl localhost:8000/documents
curl -X DELETE "localhost:8000/documents?source=hujjat.pdf"
```

`/ask` javobida `sources` bor: har bir manba uchun hujjat nomi, nisbiy ball (reranker bali; faqat tartiblash uchun), matn va
(lex.uz uchun) aynan o'sha moddaga havola.

Groq bepul tarifi: daqiqasiga 8 000 va kuniga 200 000 token. Bitta savol ~2 800 token sarflaydi (LLM'ga 8 ta parcha
beriladi, `TOP_K`), ya'ni kuniga taxminan 70 ta savol; "Chuqur qidiruv" 12 ta parcha va qo'shimcha so'rov bilan qimmatroq. Limit tugasa, chatda qancha kutish kerakligi ko'rsatiladi. Birinchi savol LLM'ga 1 marta,
suhbatdagi davomiy savol 2 marta murojaat qiladi (mustaqil savolga aylantirish + javob).
