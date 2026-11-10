#!/usr/bin/env bash
# Google va Telegram orqali kirishni yoqadi: sozlamalarni so'raydi (bot tokeni yashirin), .env ga yozadi
# va servisni qayta ishga tushiradi. Bo'sh qoldirilgani o'zgarmaydi.
set -euo pipefail
ENV=/opt/qonunnoma/.env

set_var() {  # $1 — nom, $2 — qiymat
  sed -i "/^$1=/d" "$ENV"
  [ -z "$(tail -c1 "$ENV")" ] || echo >> "$ENV"
  printf '%s=%s\n' "$1" "$2" >> "$ENV"
}

read -r -p "Google Client ID (…apps.googleusercontent.com, bo'sh — o'tkazib yuborish): " GID
read -r -p "Telegram bot nomi (@ siz, masalan qonunnoma_bot; bo'sh — o'tkazib yuborish): " TBOT
TTOKEN=""
if [ -n "$TBOT" ]; then read -r -s -p "Telegram bot tokeni (@BotFather bergan): " TTOKEN; echo; fi

GID=$(printf '%s' "$GID" | tr -d '[:space:]'); TBOT=$(printf '%s' "$TBOT" | tr -d '[:space:]@'); TTOKEN=$(printf '%s' "$TTOKEN" | tr -d '[:space:]')
# Nom o'rniga token yozilsa — qaytarib ko'rsatmaymiz (ekranda va loglarda qolmasin)
if [[ "$TBOT" =~ ^[0-9]+: ]]; then echo "Bot nomi o'rniga token yozildi. Nom — masalan qonunnoma_bot; token keyingi so'rovda yashirin kiritiladi. Hech narsa o'zgarmadi."; exit 1; fi
if [ -n "$GID" ] && [[ "$GID" != *.apps.googleusercontent.com ]]; then echo "Google Client ID …apps.googleusercontent.com bilan tugashi kerak. Hech narsa o'zgarmadi."; exit 1; fi
if [ -n "$TBOT" ]; then
  ok=$(curl -s "https://api.telegram.org/bot$TTOKEN/getMe" | python3 -c 'import json,sys;d=json.load(sys.stdin);print(d.get("result",{}).get("username","") if d.get("ok") else "")' 2>/dev/null || true)
  if [ -z "$ok" ]; then echo "Telegram tokeni ishlamadi. Hech narsa o'zgarmadi."; exit 1; fi
  if [ "${ok,,}" != "${TBOT,,}" ]; then echo "Token @$ok botiga tegishli, siz @$TBOT yozdingiz. Hech narsa o'zgarmadi."; exit 1; fi
fi
[ -n "$GID$TBOT" ] || { echo "Hech narsa kiritilmadi."; exit 0; }

cp -p "$ENV" "$ENV.bak"
[ -z "$GID" ] || set_var GOOGLE_CLIENT_ID "$GID"
if [ -n "$TBOT" ]; then set_var TELEGRAM_BOT_USERNAME "$TBOT"; set_var TELEGRAM_BOT_TOKEN "$TTOKEN"; fi
chmod 600 "$ENV"; chown qonunnoma:qonunnoma "$ENV"; unset TTOKEN

systemctl restart qonunnoma
echo "Tayyor: ${GID:+Google }${TBOT:+Telegram }kirish yoqildi, servis qayta ishga tushdi (indeks ~3 daqiqa yuklanadi)."
