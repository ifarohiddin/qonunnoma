"""Admin panel API (/admin/api/*): sayt faolligi, foydalanuvchilar va ularni boshqarish.

Kirish — oddiy sessiya tokeni bilan (chatdagi kabi), ruxsat roli bo'yicha:
admin — hammasini ko'rish va oddiy foydalanuvchini bloklash; superadmin — qo'shimcha ravishda rol berish va
hisobni o'chirish. Super adminlar .env dagi SUPER_ADMINS dan olinadi, ularni paneldan o'zgartirib bo'lmaydi.
"""
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from . import accounts, vectorstore
from .accounts import role_of
from .config import settings

# Sxema faqat adminlarga beriladi (/admin/api/openapi.json), shuning uchun panel endpointlari ham unda ko'rinadi
router = APIRouter(prefix="/admin/api", tags=["Admin panel"])
TZ = timezone(timedelta(hours=5))  # "bugun" Toshkent vaqti bo'yicha
DAYS = 14  # grafikdagi kunlar soni
PROVIDER = "CASE WHEN telegram_id IS NOT NULL THEN 'telegram' WHEN google_sub IS NOT NULL THEN 'google' ELSE 'parol' END"
# Savol berishga hali ruxsat olmagan oddiy foydalanuvchilar (bloklanganlar kirolmaydi, ularni sanamaymiz)
PENDING_WHERE = "u.approved = 0 AND u.role = 'user' AND u.blocked = 0"
PENDING_COUNT = "SELECT COUNT(*) FROM users u WHERE " + PENDING_WHERE


def staff(user: sqlite3.Row = Depends(accounts.current_user)) -> sqlite3.Row:
    if role_of(user) not in ("admin", "superadmin"):
        raise HTTPException(403, "Bu bo‘lim faqat administratorlar uchun.")
    return user


def superadmin(user: sqlite3.Row = Depends(staff)) -> sqlite3.Row:
    if role_of(user) != "superadmin":
        raise HTTPException(403, "Bu amal faqat super admin uchun.")
    return user


def _sql(query: str, params: tuple = ()) -> list[sqlite3.Row]:
    return accounts._sql(query, params)


def _one(query: str, params: tuple = ()):
    return _sql(query, params)[0][0]


def _day_start(days_ago: int = 0) -> int:
    midnight = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    return int((midnight - timedelta(days=days_ago)).timestamp())


@router.get("/me")
def me(user: sqlite3.Row = Depends(staff)):
    return {"name": user["name"], "email": user["email"], "role": role_of(user)}


@router.get("/openapi.json", include_in_schema=False)
def openapi_schema(request: Request, user: sqlite3.Row = Depends(staff)):
    """FastAPI hujjatlari (Swagger) uchun sxema. Ommaviy /openapi.json yopiq, bu esa faqat adminlarga."""
    return request.app.openapi()


class SettingsIn(BaseModel):
    require_approval: bool


@router.get("/settings")
def get_settings(user: sqlite3.Row = Depends(staff)):
    return {"require_approval": accounts.approval_required()}


@router.put("/settings")
def put_settings(body: SettingsIn, actor: sqlite3.Row = Depends(superadmin)):
    """Yangi ro'yxatdan o'tganlar savol berishdan oldin admin ruxsatini kutsinmi. Mavjud foydalanuvchilarga tegmaydi."""
    accounts.set_setting("require_approval", "1" if body.require_approval else "0")
    accounts.log_event("admin", actor["id"], "Sozlama: yangi foydalanuvchilar uchun ruxsat " + ("talab qilinadi" if body.require_approval else "talab qilinmaydi"))
    return {"require_approval": body.require_approval}


@router.get("/stats")
def stats(user: sqlite3.Row = Depends(staff)):
    today, week, start = _day_start(), _day_start(6), _day_start(DAYS - 1)
    questions = "SELECT COUNT(*) FROM events WHERE kind = 'question' AND ts >= ?"
    visitors = "SELECT COUNT(DISTINCT visitor) FROM events WHERE kind = 'visit' AND ts >= ?"

    # Kunlar bo'yicha: savollar, ro'yxatdan o'tganlar, noyob tashrifchilar (O'zbekistonda yozgi vaqt yo'q — kun 86400 s)
    per_day = {(r["d"], r["kind"]): (r["n"], r["v"]) for r in _sql(
        "SELECT (ts - ?) / 86400 AS d, kind, COUNT(*) AS n, COUNT(DISTINCT visitor) AS v FROM events"
        " WHERE ts >= ? AND kind IN ('question', 'register', 'visit') GROUP BY d, kind", (start, start))}
    first = datetime.fromtimestamp(start, TZ)
    daily = [{
        "date": (first + timedelta(days=d)).strftime("%d.%m"),
        "questions": per_day.get((d, "question"), (0, 0))[0],
        "registrations": per_day.get((d, "register"), (0, 0))[0],
        "visitors": per_day.get((d, "visit"), (0, 0))[1],
    } for d in range(DAYS)]

    docs = vectorstore.list_documents()
    return {
        "users": {
            "total": _one("SELECT COUNT(*) FROM users"),
            "new_7d": _one("SELECT COUNT(*) FROM users WHERE created >= ?", (week,)),
            "active_7d": _one("SELECT COUNT(DISTINCT user_id) FROM events WHERE user_id IS NOT NULL AND ts >= ?"
                              " AND kind IN ('question', 'login', 'register')", (week,)),
            "blocked": _one("SELECT COUNT(*) FROM users WHERE blocked = 1"),
            "pending": _one(PENDING_COUNT),
            "require_approval": accounts.approval_required(),
            "providers": {r["p"]: r["n"] for r in _sql(f"SELECT {PROVIDER} AS p, COUNT(*) AS n FROM users GROUP BY p")},
        },
        "questions": {
            "today": _one(questions, (today,)),
            "week": _one(questions, (week,)),
            "total": _one("SELECT COUNT(*) FROM events WHERE kind = 'question'"),
            "avg_ms_7d": _one("SELECT CAST(AVG(ms) AS INTEGER) FROM events WHERE kind = 'question' AND ok = 1 AND ts >= ?", (week,)),
            "errors_7d": _one("SELECT COUNT(*) FROM events WHERE kind = 'question' AND ok = 0 AND ts >= ?", (week,)),
        },
        "visitors": {"today": _one(visitors, (today,)), "week": _one(visitors, (week,))},
        "feedback": {
            "up": _one("SELECT COUNT(*) FROM feedback WHERE value = 1"),
            "down": _one("SELECT COUNT(*) FROM feedback WHERE value = -1"),
        },
        "system": {
            "llm_model": settings.llm_model,
            "documents": len(docs),
            "chunks": sum(d["chunks"] for d in docs),
            "google_login": bool(settings.google_client_id),
            "telegram_login": bool(settings.telegram_bot_token),
        },
        "daily": daily,
    }


@router.get("/users")
def users(q: str = "", status: Literal["all", "pending"] = "all", offset: int = Query(0, ge=0),
          limit: int = Query(50, ge=1, le=200), user: sqlite3.Row = Depends(staff)):
    """status=pending — savol berishga ruxsat kutayotganlar (eng eskisi birinchi)."""
    conditions, params = [], []
    if q.strip():
        conditions.append("(u.name LIKE ? OR u.email LIKE ?)")
        params += [f"%{q.strip()}%"] * 2
    if status == "pending":
        conditions.append(PENDING_WHERE)
    where, params = ("WHERE " + " AND ".join(conditions) if conditions else ""), tuple(params)
    order = "u.id ASC" if status == "pending" else "u.id DESC"
    rows = _sql(
        f"SELECT u.id, u.name, u.email, u.created, u.last_seen, u.role, u.blocked, u.approved, {PROVIDER} AS provider,"
        " (SELECT COUNT(*) FROM events e WHERE e.user_id = u.id AND e.kind = 'question') AS questions,"
        " (SELECT COUNT(*) FROM chats c WHERE c.user_id = u.id) AS chats"
        f" FROM users u {where} ORDER BY {order} LIMIT ? OFFSET ?", (*params, limit, offset))
    return {
        "total": _one(f"SELECT COUNT(*) FROM users u {where}", params),
        "pending": _one(PENDING_COUNT),
        "items": [{**dict(r), "role": role_of(r), "blocked": bool(r["blocked"]), "approved": accounts.is_approved(r)} for r in rows],
    }


class UserPatch(BaseModel):
    role: Literal["user", "admin"] | None = None
    blocked: bool | None = None
    approved: bool | None = None  # savol berishga ruxsat (admin ham, super admin ham bera oladi)


def _target(user_id: int, actor: sqlite3.Row) -> sqlite3.Row:
    rows = _sql("SELECT * FROM users WHERE id = ?", (user_id,))
    if not rows:
        raise HTTPException(404, "Foydalanuvchi topilmadi.")
    if rows[0]["id"] == actor["id"]:
        raise HTTPException(400, "O‘z hisobingizni bu yerda o‘zgartira olmaysiz.")
    if role_of(rows[0]) == "superadmin":
        raise HTTPException(403, "Super adminni paneldan o‘zgartirib bo‘lmaydi.")
    return rows[0]


@router.patch("/users/{user_id}")
def update_user(user_id: int, patch: UserPatch, actor: sqlite3.Row = Depends(staff)):
    target, super_actor = _target(user_id, actor), role_of(actor) == "superadmin"
    if patch.role is not None:
        if not super_actor:
            raise HTTPException(403, "Rolni faqat super admin o‘zgartira oladi.")
        _sql("UPDATE users SET role = ? WHERE id = ?", (patch.role, user_id))
        if patch.role == "admin":
            _sql("UPDATE users SET approved = 1 WHERE id = ?", (user_id,))  # adminlar doim ruxsatli
    if patch.approved is not None:
        if role_of(target) == "admin" and not super_actor:
            raise HTTPException(403, "Adminning ruxsatini faqat super admin o‘zgartira oladi.")
        _sql("UPDATE users SET approved = ? WHERE id = ?", (int(patch.approved), user_id))
    if patch.blocked is not None:
        if role_of(target) == "admin" and not super_actor:
            raise HTTPException(403, "Adminni faqat super admin bloklay oladi.")
        _sql("UPDATE users SET blocked = ? WHERE id = ?", (int(patch.blocked), user_id))
        if patch.blocked:
            _sql("DELETE FROM sessions WHERE user_id = ?", (user_id,))  # ochiq sessiyalari darhol yopiladi
    done = [*([{"admin": "admin qilindi", "user": "adminlikdan olindi"}[patch.role]] if patch.role else []),
            *(["savol berishga ruxsat berildi" if patch.approved else "savol berish ruxsati olindi"] if patch.approved is not None else []),
            *(["bloklandi" if patch.blocked else "blokdan chiqarildi"] if patch.blocked is not None else [])]
    accounts.log_event("admin", actor["id"], f"{target['name']} ({target['email']}): {', '.join(done)}")
    return {"ok": True}


@router.post("/users/approve-pending")
def approve_pending(actor: sqlite3.Row = Depends(staff)):
    """Hozir kutayotgan hamma oddiy foydalanuvchiga savol berishga ruxsat beradi."""
    n = _one(PENDING_COUNT)
    _sql(f"UPDATE users SET approved = 1 WHERE id IN (SELECT u.id FROM users u WHERE {PENDING_WHERE})")
    accounts.log_event("admin", actor["id"], f"Kutayotgan {n} ta foydalanuvchiga savol berishga ruxsat berildi")
    return {"approved": n}


@router.delete("/users/{user_id}")
def delete_user(user_id: int, actor: sqlite3.Row = Depends(superadmin)):
    target = _target(user_id, actor)
    _sql("DELETE FROM users WHERE id = ?", (user_id,))  # sessiyalar, suhbatlar va saqlanganlar ham (CASCADE)
    accounts.log_event("admin", actor["id"], f"{target['name']} ({target['email']}): hisobi o‘chirildi")
    return {"ok": True}


@router.get("/questions")
def questions(limit: int = Query(100, ge=1, le=500), user_id: int | None = None, user: sqlite3.Row = Depends(staff)):
    where, params = ("AND e.user_id = ?", (user_id,)) if user_id else ("", ())
    rows = _sql(
        "SELECT e.ts, e.detail AS question, e.ms, e.ok, e.user_id, u.name, u.email FROM events e"
        f" LEFT JOIN users u ON u.id = e.user_id WHERE e.kind = 'question' {where} ORDER BY e.id DESC LIMIT ?",
        (*params, limit))
    return [dict(r) for r in rows]


@router.get("/feedback")
def feedback(limit: int = Query(100, ge=1, le=500), user: sqlite3.Row = Depends(staff)):
    rows = _sql(
        "SELECT f.ts, f.question, f.answer, f.value, f.user_id, u.name, u.email FROM feedback f"
        " LEFT JOIN users u ON u.id = f.user_id ORDER BY f.id DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]


@router.get("/activity")
def activity(limit: int = Query(100, ge=1, le=500), user: sqlite3.Row = Depends(staff)):
    """Kirishlar, ro'yxatdan o'tishlar va administrator amallari."""
    rows = _sql(
        "SELECT e.ts, e.kind, e.detail, e.user_id, u.name, u.email FROM events e LEFT JOIN users u ON u.id = e.user_id"
        " WHERE e.kind IN ('login', 'register', 'admin') ORDER BY e.id DESC LIMIT ?", (limit,))
    return [dict(r) for r in rows]
