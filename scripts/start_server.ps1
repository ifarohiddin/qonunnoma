# Qonunnoma serverini ishga tushiradi (qonunnoma.uz uchun). Faqat 127.0.0.1 da tinglaydi —
# internetdan kirish Cloudflare Tunnel orqali bo'ladi, kompyuterning porti tashqariga ochilmaydi.
Set-Location (Join-Path $PSScriptRoot "..")
.\.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
