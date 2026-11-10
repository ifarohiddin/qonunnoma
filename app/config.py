from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore")

    # "openai" — OpenAI-mos API (Groq, Ollama: LLM_BASE_URL/LLM_API_KEY); "anthropic" — Claude
    # (kalit ANTHROPIC_API_KEY dan olinadi, LLM_MODEL=claude-haiku-5-5)
    llm_provider: str = "openai"
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = "ollama"
    llm_model: str = "gpt-oss:20b"
    # "O'ylaydigan" modellar uchun: low / medium / high (bo'sh — yuborilmaydi). Claude'da output_config.effort
    llm_reasoning_effort: str = ""
    anthropic_api_key: str = ""
    # Claude'ning o'ylash bosqichi: o'chiq — eng arzon va tez (faqat javob tokenlari to'lanadi)
    llm_thinking: bool = False
    # Chatbot oxirgi nechta xabarni eslab qoladi
    chat_history_messages: int = 6

    # Internetga chiqarilganda (qonunnoma.uz) albatta qo'ying: hujjat yuklash/o'chirish, /ask va /docs faqat
    # "X-Admin-Token" sarlavhasi bilan ishlaydi. Bo'sh — lokal rejim, hamma narsa ochiq
    admin_token: str = ""
    # Admin panel (/admin): bu pochtalar (vergul bilan) — super admin; ularni paneldan o'zgartirib bo'lmaydi
    super_admins: str = ""
    # Yangi ro'yxatdan o'tganlar savol berishdan oldin admin ruxsatini kutadi. Bu boshlang'ich qiymat: paneldan
    # (Umumiy ko'rinish → Ruxsat sozlamasi) o'zgartirilsa, bazadagi qiymat ishlatiladi. Eski foydalanuvchilar ruxsatli
    require_approval: bool = True
    # Bitta foydalanuvchi (yoki mehmon uchun IP) bo'yicha chat limiti — Groq tokenlari bir kishiga tugab qolmasin
    chat_per_minute: int = 5
    chat_per_day: int = 40
    # Savol berish faqat tizimga kirganlarga (mehmon — avval kirish/ro'yxatdan o'tish)
    chat_requires_login: bool = True

    # Google orqali kirish: Google Cloud Console → OAuth client ID (Web), origin — https://qonunnoma.uz
    google_client_id: str = ""
    # Telegram orqali kirish: @BotFather dagi bot (/setdomain qonunnoma.uz); token — maxfiy
    telegram_bot_username: str = ""
    telegram_bot_token: str = ""

    # Modellar qurilmasi: bo'sh — GPU bo'lsa GPU; "cpu" — video xotirani band qilmaslik uchun (masalan, o'yin paytida)
    device: str = ""
    embed_model: str = "BAAI/bge-m3"
    # bge-m3 prefikssiz ishlaydi; e5 modellari uchun "query: " va "passage: " kerak
    embed_query_prefix: str = ""
    embed_passage_prefix: str = ""
    # Topilgan bo'laklarni savol bilan birga o'qib qayta tartiblaydigan model (bo'sh — o'chirilgan).
    # GPU'da bir savolga ~0.3 s, CPU'da ~10 s qo'shadi
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_candidates: int = 30

    chunk_chars: int = 1200
    chunk_overlap: int = 200
    # LLM'ga beriladigan parchalar soni: 5 da reranker umumiy qoidani (masalan, 21 kunlik ta'til) ba'zan 6-7-o'ringa
    # qo'yib, kontekstdan chiqarib yuborardi
    top_k: int = 8
    deep_top_k: int = 12  # "Chuqur qidiruv" yoqilganda
    # Har bir savolni qidirishdan oldin LLM qonun tiliga o'giradi: kirill/ruscha va og'zaki savollar ("xotinim urdi")
    # lotincha rasmiy matn bilan mos kelishi uchun. Bir savolga ~900 token (Claude Haiku'da ~$0.0001)
    rewrite_always: bool = True
    # Qidiruv indeksi (BM25 + vektorlar) baza o'zgargandan keyin eng ko'pi bilan shuncha soniyada bir qayta quriladi.
    # Katta bazada qayta qurish bir necha daqiqa va ko'p xotira oladi: serverda juda katta qiymat qo'yiladi
    # (yangi hujjatlar servis qayta ishga tushirilgach qidiruvga tushadi)
    corpus_rebuild_seconds: int = 600

    # Tashqi baholash API (/v1): Bearer kalitlar (vergul bilan; bo'sh — /v1 yopiq) va lex.uz ma'lumoti olingan sana
    eval_api_keys: str = ""
    lex_snapshot_date: str = "2026-11-03"

    data_dir: Path = ROOT / "data"
    lex_delay_seconds: float = 1.0


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
(settings.data_dir / "uploads").mkdir(exist_ok=True)
