#!/usr/bin/env bash
# Anthropic kaliti/tokenini tekshiradi: bepul /v1/models so'rovi bilan, ikki usulda.
# Kalit yashirin so'raladi, ekranga, tarixga va jarayonlar ro'yxatiga (ps) chiqmaydi.
set -uo pipefail
read -r -s -p "Anthropic kaliti yoki tokeni: " KEY; echo
URL=https://api.anthropic.com/v1/models

ask() {  # $1 — sarlavhalar (curl config qatorlari), stdin orqali beriladi
  printf '%b' "$1" | curl -s -o /tmp/key_test.json -w '%{http_code}' -K - "$URL"
}
reason() { python3 -c 'import json;d=json.load(open("/tmp/key_test.json"));e=d.get("error") or {};print(" ", e.get("type",""), "-", e.get("message","OK"))' 2>/dev/null; }

code=$(ask "header = \"x-api-key: $KEY\"\nheader = \"anthropic-version: 2023-06-01\"\n")
echo "API kaliti sifatida (x-api-key):     HTTP $code"; reason
code=$(ask "header = \"Authorization: Bearer $KEY\"\nheader = \"anthropic-version: 2023-06-01\"\nheader = \"anthropic-beta: oauth-2025-04-20\"\n")
echo "OAuth token sifatida (Bearer):       HTTP $code"; reason
rm -f /tmp/key_test.json; unset KEY
echo "200 — ishlaydi; 401 — bu usulda qabul qilinmaydi; 403 — ruxsat yo'q."
