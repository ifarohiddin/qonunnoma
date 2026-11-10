"""Foydalanuvchilar: ro'yxatdan o'tish, kirish (parol, Google, Telegram), sessiyalar va har bir foydalanuvchining
suhbatlari, saqlangan javoblari va javoblarga bahosi. Hammasi bitta SQLite faylda (data/app.db).

Parol scrypt bilan (har biriga alohida tuz) saqlanadi; sessiya tokenining o'zi emas, sha256 xeshi saqlanadi.
"""
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
import time

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from . import limits
from .config import settings

SESSION_DAYS = 30
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]{2,}$")

_lock = threading.Lock()
_db = sqlite3.connect(settings.data_dir / "app.db", check_same_thread=False)
_db.row_factory = sqlite3.Row
_db.executescript(
    """
    PRAGMA foreign_keys = ON;
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT NOT NULL UNIQUE COLLATE NOCASE,
        salt BLOB NOT NULL, pw_hash BLOB NOT NULL, created INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS sessions (
        token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        expires INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS chats (
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, id TEXT NOT NULL,
        title TEXT NOT NULL, ts INTEGER NOT NULL, msgs TEXT NOT NULL, PRIMARY KEY (user_id, id));
    CREATE TABLE IF NOT EXISTS saved (
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, id TEXT NOT NULL,
        ts INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY (user_id, id));
    CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY, user_id INTEGER, ts INTEGER NOT NULL,
        question TEXT NOT NULL, answer TEXT NOT NULL, value INTEGER NOT NULL);
    -- Sayt faolligi (admin panel uchun): visit, register, login, question
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY, ts INTEGER NOT NULL, kind TEXT NOT NULL, user_id INTEGER,
        detail TEXT, ms INTEGER, ok INTEGER, visitor TEXT);
    CREATE INDEX IF NOT EXISTS events_kind_ts ON events(kind, ts);
    -- Panel orqali o'zgartiriladigan sozlamalar (masalan, yangi foydalanuvchiga ruxsat talabi)
    CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """
)
# Keyin qo'shilgan ustunlar (eski bazaga ham qo'shiladi): Google/Telegram, rol, bloklash, oxirgi faollik,
# savol berishga ruxsat (eski foydalanuvchilar uchun DEFAULT 1 — ularning ruxsati o'zgarmaydi)
for _column in ("google_sub TEXT", "telegram_id INTEGER", "role TEXT NOT NULL DEFAULT 'user'",
                "blocked INTEGER NOT NULL DEFAULT 0", "last_seen INTEGER", "approved INTEGER NOT NULL DEFAULT 1"):
    try:
        _db.execute(f"ALTER TABLE users ADD COLUMN {_column}")
    except sqlite3.OperationalError:
        pass  # ustun allaqachon bor
_db.executescript(
    """
    CREATE UNIQUE INDEX IF NOT EXISTS users_google ON users(google_sub) WHERE google_sub IS NOT NULL;
    CREATE UNIQUE INDEX IF NOT EXISTS users_telegram ON users(telegram_id) WHERE telegram_id IS NOT NULL;
    """
)

router = APIRouter(tags=["Hisob va suhbatlar"])


def _sql(query: str, params: tuple = ()) -> list[sqlite3.Row]:
    with _lock:
        rows = _db.execute(query, params).fetchall()
        _db.commit()
        return rows


def _hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _new_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    _sql("DELETE FROM sessions WHERE expires < ?", (int(time.time()),))
    _sql("INSERT INTO sessions VALUES (?, ?, ?)", (_token_hash(token), user_id, int(time.time()) + SESSION_DAYS * 86400))
    return token


def role_of(user: sqlite3.Row) -> str:
    """user / admin / superadmin. Super adminlar .env dagi SUPER_ADMINS ro'yxatidan: ularni paneldan o'zgartirib bo'lmaydi."""
    supers = {e.strip().lower() for e in settings.super_admins.split(",") if e.strip()}
    return "superadmin" if user["email"].lower() in supers else user["role"]


def get_setting(key: str, default: str) -> str:
    rows = _sql("SELECT value FROM app_settings WHERE key = ?", (key,))
    return rows[0]["value"] if rows else default


def set_setting(key: str, value: str) -> None:
    _sql("INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))


def approval_required() -> bool:
    """Yangi ro'yxatdan o'tganlar savol berishdan oldin admin ruxsatini kutadimi (panel sozlamasi, bo'lmasa .env)."""
    return get_setting("require_approval", "1" if settings.require_approval else "0") == "1"


def is_approved(user: sqlite3.Row) -> bool:
    """Adminlar va super adminlar doim ruxsatli; oddiy foydalanuvchiga admin ruxsat bergan bo'lishi kerak."""
    return role_of(user) in ("admin", "superadmin") or bool(user["approved"])


def visitor_id(request: Request) -> str:
    # Noyob tashrifchilarni sanash uchun: IP ning o'zi emas, kunlik tuzli xeshi saqlanadi
    day = time.strftime("%Y-%m-%d", time.gmtime())
    return hashlib.sha256(f"{settings.admin_token}|{day}|{limits.client_ip(request)}".encode()).hexdigest()[:16]


def log_event(kind: str, user_id: int | None = None, detail: str | None = None,
              ms: int | None = None, ok: bool | None = None, visitor: str | None = None) -> None:
    try:
        _sql("INSERT INTO events (ts, kind, user_id, detail, ms, ok, visitor) VALUES (?, ?, ?, ?, ?, ?, ?)",
             (int(time.time()), kind, user_id, (detail or "")[:2000] or None, ms, None if ok is None else int(ok), visitor))
    except sqlite3.Error:
        pass  # jurnal yozilmasa ham asosiy ish to'xtamasin


def optional_user(authorization: str | None = Header(default=None)) -> sqlite3.Row | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    now = int(time.time())
    rows = _sql(
        "SELECT users.* FROM sessions JOIN users ON users.id = sessions.user_id"
        " WHERE token_hash = ? AND expires > ? AND users.blocked = 0",
        (_token_hash(authorization[7:]), now),
    )
    if rows and now - (rows[0]["last_seen"] or 0) > 300:  # oxirgi faollik — har so'rovda emas, 5 daqiqada bir
        _sql("UPDATE users SET last_seen = ? WHERE id = ?", (now, rows[0]["id"]))
    return rows[0] if rows else None


def current_user(user: sqlite3.Row | None = Depends(optional_user)) -> sqlite3.Row:
    if user is None:
        raise HTTPException(401, "Avval tizimga kiring.")
    return user


# ---------- ro'yxatdan o'tish / kirish ----------
class RegisterRequest(BaseModel):
    name: str = Field(max_length=60)
    email: str = Field(max_length=120)
    password: str = Field(max_length=200)


class LoginRequest(BaseModel):
    email: str = Field(max_length=120)
    password: str = Field(max_length=200)


class UserOut(BaseModel):
    name: str
    email: str
    role: str = "user"
    approved: bool = True  # False — admin ruxsat bermaguncha savol bera olmaydi


class AuthResponse(BaseModel):
    token: str
    user: UserOut


def _user_out(user: sqlite3.Row) -> UserOut:
    return UserOut(name=user["name"], email=user["email"], role=role_of(user), approved=is_approved(user))


def _signed_in(user: sqlite3.Row, kind: str, provider: str) -> AuthResponse:
    if user["blocked"]:
        raise HTTPException(403, "Hisobingiz bloklangan. Administratorga murojaat qiling.")
    log_event(kind, user["id"], provider)
    if role_of(user) == "superadmin" and not user["approved"]:
        _sql("UPDATE users SET approved = 1 WHERE id = ?", (user["id"],))  # panelda "kutayotgan" bo'lib ko'rinmasin
    return AuthResponse(token=_new_session(user["id"]), user=_user_out(user))


@router.post("/auth/register", response_model=AuthResponse)
def register(request: RegisterRequest, http: Request):
    limits.check(f"register:{limits.client_ip(http)}", 3, 20, "ro‘yxatdan o‘tish")
    name, email = request.name.strip(), request.email.strip()
    if len(name) < 2:
        raise HTTPException(422, "Ismingizni kiriting.")
    if not _EMAIL.match(email):
        raise HTTPException(422, "Elektron pochta manzilini to‘g‘ri kiriting.")
    if len(request.password) < 6:
        raise HTTPException(422, "Parol kamida 6 ta belgidan iborat bo‘lsin.")
    if _sql("SELECT 1 FROM users WHERE email = ?", (email,)):
        raise HTTPException(409, "Bu pochta bilan hisob allaqachon bor. Kirish bo‘limidan foydalaning.")
    salt = secrets.token_bytes(16)
    _sql(
        "INSERT INTO users (name, email, salt, pw_hash, created, approved) VALUES (?, ?, ?, ?, ?, ?)",
        (name, email, salt, _hash_password(request.password, salt), int(time.time()), int(not approval_required())),
    )
    return _signed_in(_sql("SELECT * FROM users WHERE email = ?", (email,))[0], "register", "parol")


@router.post("/auth/login", response_model=AuthResponse)
def login(request: LoginRequest, http: Request):
    limits.check(f"login:{limits.client_ip(http)}", 10, 100, "kirishga urinish")  # parolni taxmin qilishga qarshi
    rows = _sql("SELECT * FROM users WHERE email = ?", (request.email.strip(),))
    if not rows or not hmac.compare_digest(rows[0]["pw_hash"], _hash_password(request.password, rows[0]["salt"])):
        raise HTTPException(401, "Elektron pochta yoki parol noto‘g‘ri.")
    return _signed_in(rows[0], "login", "parol")


# ---------- Google va Telegram orqali kirish ----------
@router.get("/auth/config")
def auth_config():
    """Sahifa qaysi kirish tugmalarini ko'rsatishini biladi (sozlanmaganlari "ulanmagan" bo'lib qoladi)."""
    return {
        "google_client_id": settings.google_client_id or None,
        "telegram_bot": settings.telegram_bot_username if settings.telegram_bot_token else None,
        # Bot raqami (tokenning ":" gacha qismi) maxfiy emas: u Telegram kirish oynasining manzilida ham ko'rinadi
        "telegram_bot_id": int(settings.telegram_bot_token.split(":")[0]) if settings.telegram_bot_token else None,
    }


def _social_sign_in(column: str, value: str | int, name: str, email: str) -> AuthResponse:
    """Shu Google/Telegram hisobi bilan bog'langan foydalanuvchi; yo'q bo'lsa — yaratiladi.
    Google tasdiqlagan pochta bilan avval parol orqali ochilgan hisob bo'lsa, o'sha hisobga bog'lanadi."""
    assert column in ("google_sub", "telegram_id")
    provider = "google" if column == "google_sub" else "telegram"
    rows = _sql(f"SELECT * FROM users WHERE {column} = ?", (value,))
    if not rows and column == "google_sub":
        rows = _sql("SELECT * FROM users WHERE email = ?", (email,))
        if rows:
            _sql("UPDATE users SET google_sub = ? WHERE id = ?", (value, rows[0]["id"]))
    if rows:
        return _signed_in(rows[0], "login", provider)
    # Parol yo'q: tasodifiy xesh — bu hisobga parol bilan kirib bo'lmaydi
    _sql(
        f"INSERT INTO users (name, email, salt, pw_hash, created, approved, {column}) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (name.strip()[:60] or "Foydalanuvchi", email, secrets.token_bytes(16), secrets.token_bytes(32), int(time.time()),
         int(not approval_required()), value),
    )
    return _signed_in(_sql(f"SELECT * FROM users WHERE {column} = ?", (value,))[0], "register", provider)


class GoogleRequest(BaseModel):
    credential: str = Field(max_length=4096)  # Google Identity Services bergan ID token


def _verify_google(credential: str) -> dict:
    # Imzo va muddatni Google o'zi tekshiradi; biz — token aynan shu sayt uchun berilgani va pochta tasdiqlanganini
    try:
        response = httpx.get("https://oauth2.googleapis.com/tokeninfo", params={"id_token": credential}, timeout=10)
    except httpx.HTTPError as exc:
        raise HTTPException(502, "Google bilan bog‘lanib bo‘lmadi. Birozdan so‘ng urinib ko‘ring.") from exc
    info = response.json() if response.status_code == 200 else {}
    if (
        info.get("aud") != settings.google_client_id
        or info.get("iss") not in ("accounts.google.com", "https://accounts.google.com")
        or str(info.get("email_verified")).lower() != "true"
        or not info.get("email")
    ):
        raise HTTPException(401, "Google orqali kirib bo‘lmadi. Qayta urinib ko‘ring.")
    return info


@router.post("/auth/google", response_model=AuthResponse)
def google_login(request: GoogleRequest, http: Request):
    limits.check(f"login:{limits.client_ip(http)}", 10, 100, "kirishga urinish")
    if not settings.google_client_id:
        raise HTTPException(404, "Google orqali kirish hali ulanmagan.")
    info = _verify_google(request.credential)
    return _social_sign_in("google_sub", info["sub"], info.get("name") or info["email"].split("@")[0], info["email"])


def _verify_telegram(data: dict) -> None:
    """Telegram Login Widget ma'lumoti haqiqiyligi: bot tokenidan olingan kalit bilan HMAC (core.telegram.org/widgets/login)."""
    fields = {k: str(v) for k, v in data.items() if k != "hash" and v is not None}
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    secret = hashlib.sha256(settings.telegram_bot_token.encode()).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    fresh = fields.get("auth_date", "").isdigit() and time.time() - int(fields["auth_date"]) < 86400
    if not hmac.compare_digest(expected, str(data.get("hash", ""))) or not fresh:
        raise HTTPException(401, "Telegram orqali kirib bo‘lmadi. Qayta urinib ko‘ring.")


@router.post("/auth/telegram", response_model=AuthResponse)
def telegram_login(data: dict, http: Request):
    limits.check(f"login:{limits.client_ip(http)}", 10, 100, "kirishga urinish")
    if not settings.telegram_bot_token:
        raise HTTPException(404, "Telegram orqali kirish hali ulanmagan.")
    _verify_telegram(data)
    name = " ".join(str(data.get(k) or "") for k in ("first_name", "last_name")).strip() or str(data.get("username") or "")
    # Telegram pochta bermaydi: email ustuni majburiy va noyob — o'rniga ichki belgi
    return _social_sign_in("telegram_id", int(data["id"]), name, f"telegram:{int(data['id'])}")


@router.get("/auth/me", response_model=UserOut)
def me(user: sqlite3.Row = Depends(current_user)):
    return _user_out(user)


@router.post("/auth/logout")
def logout(authorization: str | None = Header(default=None)):
    if authorization and authorization.startswith("Bearer "):
        _sql("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(authorization[7:]),))
    return {"ok": True}


# ---------- suhbatlar ----------
class ChatIn(BaseModel):
    title: str = Field(max_length=200)
    ts: int
    msgs: list[dict] = Field(max_length=400)


@router.get("/me/chats")
def list_chats(user: sqlite3.Row = Depends(current_user)):
    rows = _sql("SELECT id, title, ts, msgs FROM chats WHERE user_id = ? ORDER BY ts DESC LIMIT 200", (user["id"],))
    return [{"id": r["id"], "title": r["title"], "ts": r["ts"], "msgs": json.loads(r["msgs"])} for r in rows]


@router.put("/me/chats/{chat_id}")
def put_chat(chat_id: str, chat: ChatIn, user: sqlite3.Row = Depends(current_user)):
    _sql(
        "INSERT OR REPLACE INTO chats VALUES (?, ?, ?, ?, ?)",
        (user["id"], chat_id[:64], chat.title, chat.ts, json.dumps(chat.msgs, ensure_ascii=False)),
    )
    return {"ok": True}


@router.delete("/me/chats/{chat_id}")
def delete_chat(chat_id: str, user: sqlite3.Row = Depends(current_user)):
    _sql("DELETE FROM chats WHERE user_id = ? AND id = ?", (user["id"], chat_id))
    return {"ok": True}


# ---------- saqlangan javoblar ----------
class SavedIn(BaseModel):
    ts: int
    data: dict  # {question, answer, sources, chat}


@router.get("/me/saved")
def list_saved(user: sqlite3.Row = Depends(current_user)):
    rows = _sql("SELECT id, ts, data FROM saved WHERE user_id = ? ORDER BY ts DESC", (user["id"],))
    return [{"id": r["id"], "ts": r["ts"], **json.loads(r["data"])} for r in rows]


@router.put("/me/saved/{saved_id}")
def put_saved(saved_id: str, item: SavedIn, user: sqlite3.Row = Depends(current_user)):
    _sql(
        "INSERT OR REPLACE INTO saved VALUES (?, ?, ?, ?)",
        (user["id"], saved_id[:64], item.ts, json.dumps(item.data, ensure_ascii=False)),
    )
    return {"ok": True}


@router.delete("/me/saved/{saved_id}")
def delete_saved(saved_id: str, user: sqlite3.Row = Depends(current_user)):
    _sql("DELETE FROM saved WHERE user_id = ? AND id = ?", (user["id"], saved_id))
    return {"ok": True}


# ---------- javobga baho (foydali / foydasiz) ----------
class FeedbackIn(BaseModel):
    question: str = Field(max_length=2000)
    answer: str = Field(max_length=8000)
    value: int = Field(ge=-1, le=1)


@router.post("/feedback")
def feedback(item: FeedbackIn, user: sqlite3.Row | None = Depends(optional_user)):
    _sql(
        "INSERT INTO feedback (user_id, ts, question, answer, value) VALUES (?, ?, ?, ?, ?)",
        (user["id"] if user else None, int(time.time()), item.question, item.answer, item.value),
    )
    return {"ok": True}
