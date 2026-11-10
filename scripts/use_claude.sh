#!/usr/bin/env bash
# Serverda LLM'ni Claude Haiku'ga o'tkazadi: Anthropic API kalitini yashirin so'raydi (ekranda va tarixda ko'rinmaydi),
# .env ga yozadi va servisni qayta ishga tushiradi. Groq sozlamalari o'chirilmaydi — qaytish uchun:
#   LLM_PROVIDER=openai, LLM_MODEL=openai/gpt-oss-20b
set -euo pipefail
ENV=/opt/qonunnoma/.env

read -r -s -p "Anthropic API kaliti (sk-ant-...): " KEY; echo
KEY=$(printf '%s' "$KEY" | tr -d '[:space:]')  # joylashda qo'shilgan bo'sh joy va qator oxirlari
echo "Kiritildi: ${KEY:0:10}… (${#KEY} belgi)"
case "$KEY" in
  sk-ant-*) ;;
  *) echo "Bu Anthropic kalitiga o'xshamaydi (sk-ant- bilan boshlanishi kerak). Hech narsa o'zgarmadi."; exit 1 ;;
esac
# Kalitni bepul /v1/models so'rovi bilan tekshiramiz — noto'g'ri kalit bilan servis buzilmasin
code=$(printf 'header = "x-api-key: %s"\nheader = "anthropic-version: 2023-06-01"\n' "$KEY" \
  | curl -s -o /tmp/claude_check.json -w '%{http_code}' -K - https://api.anthropic.com/v1/models)
if [ "$code" != 200 ]; then
  echo "Anthropic kalitni qabul qilmadi (HTTP $code): $(python3 -c 'import json;print(json.load(open("/tmp/claude_check.json"))["error"]["message"])' 2>/dev/null)"
  echo "Hech narsa o'zgarmadi."; rm -f /tmp/claude_check.json; exit 1
fi
rm -f /tmp/claude_check.json

cp -p "$ENV" "$ENV.bak"
sed -i '/^\(LLM_PROVIDER\|LLM_MODEL\|LLM_REASONING_EFFORT\|ANTHROPIC_API_KEY\)=/d' "$ENV"
[ -z "$(tail -c1 "$ENV")" ] || echo >> "$ENV"
printf 'LLM_PROVIDER=anthropic\nLLM_MODEL=claude-haiku-5-5\nLLM_REASONING_EFFORT=low\nANTHROPIC_API_KEY=%s\n' "$KEY" >> "$ENV"
chmod 600 "$ENV"; chown qonunnoma:qonunnoma "$ENV"
unset KEY

systemctl restart qonunnoma
echo "Tayyor: Claude Haiku yoqildi, servis qayta ishga tushdi (indeks ~3 daqiqa yuklanadi). Eski .env: $ENV.bak"
