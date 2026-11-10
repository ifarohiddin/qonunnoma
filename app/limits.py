"""Oddiy so'rov limitlari (xotirada): chat va kirish urinishlari uchun. Server qayta ishga tushsa, hisob nolga qaytadi."""
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

_lock = threading.Lock()
_hits: dict[str, deque] = defaultdict(deque)


def client_ip(request: Request) -> str:
    # Cloudflare Tunnel orqali kelganda haqiqiy manzil shu sarlavhada (server faqat 127.0.0.1 da tinglaydi)
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "?")


def check(key: str, per_minute: int, per_day: int, what: str) -> None:
    now = time.time()
    with _lock:
        hits = _hits[key]
        while hits and now - hits[0] > 86400:
            hits.popleft()
        last_minute = sum(1 for t in hits if now - t < 60)
        if last_minute >= per_minute:
            raise HTTPException(429, f"Juda tez: {what} daqiqasiga {per_minute} martagacha. Bir daqiqadan so‘ng urinib ko‘ring.")
        if len(hits) >= per_day:
            raise HTTPException(429, f"Bugungi limit tugadi: {what} kuniga {per_day} martagacha. Ertaga qayta urinib ko‘ring.")
        hits.append(now)
