# qonunnoma.uz ga chiqarish (o'z kompyuterida + Cloudflare Tunnel)

Sayt shu kompyuterda ishlaydi. Cloudflare Tunnel kompyuterdan Cloudflare'ga chiquvchi ulanish ochadi, shuning uchun
routerda port ochish, "oq" IP olish shart emas; HTTPS sertifikatini Cloudflare o'zi beradi. Kompyuter yoqiq va
internetga ulangan bo'lishi kerak.

## 1. Domenni Cloudflare'ga ulash (bir marta)

1. https://dash.cloudflare.com da bepul akkaunt oching.
2. **Add a domain** → `qonunnoma.uz` → **Free** tarif.
3. Cloudflare ikkita nameserver beradi (masalan, `ada.ns.cloudflare.com`, `bob.ns.cloudflare.com`).
4. Domenni sotib olgan joyingiz (ahost.uz, webname.uz va h.k.) panelida `qonunnoma.uz` ning NS yozuvlarini shu
   ikkitasiga almashtiring. `.uz` da bu bir necha soatdan 24 soatgacha olishi mumkin; tayyor bo'lganda Cloudflare
   xat yuboradi ("Active").

## 2. Tunnel yaratish (bir marta)

`cloudflared` allaqachon o'rnatilgan: `C:\Program Files (x86)\cloudflared\cloudflared.exe`.

1. Cloudflare panelida **Zero Trust** → **Networks** → **Tunnels** → **Create a tunnel** → **Cloudflared**,
   nomi: `qonunnoma`.
2. **Windows** ni tanlang va ko'rsatilgan `cloudflared.exe service install <token>` buyrug'ini nusxalang.
   PowerShell'ni **administrator sifatida** ochib, shu buyruqni ishga tushiring — tunnel Windows xizmati bo'lib
   o'rnatiladi va kompyuter yonganda o'zi ishga tushadi. (Tokenni hech kimga bermang.)
3. **Public hostname** qo'shing:
   - Subdomain: bo'sh, Domain: `qonunnoma.uz`, Service: `HTTP`, URL: `localhost:8000`
   - yana biri: Subdomain `www`, qolgani xuddi shunday
4. https://qonunnoma.uz ni oching.

## 3. Serverni avtomatik ishga tushirish

Server `scripts/start_server.ps1` bilan ishga tushadi (faqat `127.0.0.1:8000` da tinglaydi). Kompyuterga kirganda
o'zi ishga tushishi uchun PowerShell'da bir marta:

```powershell
$a = New-ScheduledTaskAction -Execute "powershell.exe" -Argument '-ExecutionPolicy Bypass -WindowStyle Hidden -File "C:\Users\Hikari\Desktop\PDP University\rag\scripts\start_server.ps1"'
Register-ScheduledTask -TaskName "Qonunnoma server" -Action $a -Trigger (New-ScheduledTaskTrigger -AtLogOn)
```

Windows sozlamalarida kompyuterning uxlash (Sleep) rejimini o'chiring, aks holda sayt ham "uxlaydi".

## 4. Ommaviy rejim (allaqachon yoqilgan)

`.env` da `ADMIN_TOKEN` bor — server shuni ko'rib ommaviy rejimga o'tadi:

- hujjat yuklash/o'chirish (`/ingest/*`, `DELETE /documents`), `/search`, `/ask` faqat `X-Admin-Token` sarlavhasi
  bilan; `/docs` (Swagger) yopiq; sahifadagi "Fayl" tugmasi yashiringan;
- chat limiti: mehmon (IP bo'yicha) daqiqasiga 5, kuniga 40 savol; kirgan foydalanuvchiga ikki baravar
  (`CHAT_PER_MINUTE`, `CHAT_PER_DAY`); kirish urinishlari daqiqasiga 10 ta.

`scripts/lex_import.py` tokenni `.env` dan o'zi oladi. Lokal, ochiq rejimga qaytish uchun `ADMIN_TOKEN` qatorini
o'chirib, serverni qayta ishga tushiring.

## Muhim: Groq limiti

Groq bepul tarifi butun sayt uchun kuniga 200 000 token beradi — bu kuniga taxminan 70 ta savol. Saytdan bir necha
kishi foydalansa, limit tez tugaydi va hamma "limit tugadi" xabarini oladi. Ommaga ochishdan oldin Groq'ning pullik
tarifiga (https://console.groq.com/settings/billing) o'ting yoki `CHAT_PER_DAY` ni kamaytiring.
