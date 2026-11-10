"""100 savollik test to'plami (spetsifikatsiya 6-bo'lim). Kutilgan modda raqamlari bazadagi matndan tekshirilgan.
Chiqish: testset.json (tester tomonida; API ga faqat id, question, language yuboriladi)."""
import json
import random
from pathlib import Path

DOC = {"M": "lex:-6257288", "J": "lex:-111453", "FK1": "lex:-111189", "FK2": "lex:-180552", "OK": "lex:-104720",
       "S": "lex:-4674902", "FPK": "lex:-3517337", "UJ": "lex:-106136"}
LAT, CYR, RU = "uz-Latn", "uz-Cyrl", "ru"
T = []


def add(cat, q, exp, pairs, kw=None, lang=LAT):
    """pairs: [("M", 217), ...] — kutilgan (hujjat, modda); kw: har biri alohida tekshiriladigan regex guruhlari."""
    T.append({"category": cat, "question": q, "language": lang, "expected_answer": exp,
              "expected": [{"doc_id": DOC[d], "article": f"{n}-modda"} for d, n in pairs],
              "keywords": kw or [], "answerable": bool(pairs)})


# --- faktik, bitta modda (35)
F = "faktik"
add(F, "Har yilgi asosiy eng kam mehnat ta'tilining davomiyligi qancha?", "21 kalendar kun", [("M", 217)], [r"21|yigirma bir"])
add(F, "Mehnat shartnomasida dastlabki sinov muddati necha oydan oshmasligi kerak?", "3 oy (rahbarlar uchun 6 oy)", [("M", 130)], [r"\b3 oy|uch oy"])
add(F, "Haftasiga ish vaqtining normal davomiyligi necha soatdan oshmasligi kerak?", "40 soat", [("M", 182)], [r"40|qirq"])
add(F, "Homiladorlik va tug'ish ta'tili necha kalendar kun beriladi?", "tug'ruqqacha 70 va keyin 56 kun", [("M", 404)], [r"70|yetmish", r"56|ellik olti"])
add(F, "Tungi vaqtdagi mehnat uchun haq qanday miqdorda to'lanadi?", "kamida bir yarim baravar", [("M", 264)], [r"1,5|bir yarim"])
add(F, "Jinoiy javobgarlik necha yoshdan boshlanadi?", "16 yosh", [("J", 17)], [r"16|o'n olti"])
add(F, "Umumiy da'vo muddati necha yil?", "3 yil", [("FK1", 150)], [r"\b3 yil|uch yil"])
add(F, "Fuqaroning muomala layoqati necha yoshdan to'liq hajmda vujudga keladi?", "18 yosh", [("FK1", 22)], [r"18|o'n sakkiz"])
add(F, "Oila kodeksiga ko'ra nikoh yoshi necha yosh?", "18 yosh", [("OK", 15)], [r"18|o'n sakkiz"])
add(F, "Voyaga yetmagan bir bola uchun aliment ota-ona daromadining qancha qismi miqdorida undiriladi?", "to'rtdan bir qismi", [("OK", 99)], [r"to'rtdan bir|1/4|25 foiz"])
add(F, "Qo'shilgan qiymat solig'i stavkasi necha foiz?", "12 foiz", [("S", 258)], [r"12"])
add(F, "Sud nikohdan ajratishda er-xotinga yarashish uchun necha oygacha muhlat tayinlashga haqli?", "6 oygacha", [("OK", 40)], [r"\b6 oy|olti oy"])
add(F, "Rezident jismoniy shaxslarning daromadiga qanday soliq stavkasi qo'llanadi?", "12 foiz", [("S", 381)], [r"12"])
add(F, "Jismoniy shaxslardan olinadigan mol-mulk solig'ini kimlar to'laydi?", "soliq solish obyekti bo'lgan mol-mulki bor jismoniy shaxslar", [("S", 418)], [r"jismoniy shaxs"])
add(F, "Zaruriy mudofaa holatida sodir etilgan harakat jinoyat hisoblanadimi?", "yo'q, chegaradan chiqilmagan bo'lsa jinoyat deb topilmaydi", [("J", 37)], [r"jinoyat (deb topilmaydi|hisoblanmaydi|emas)|topilmaydi"])
add(F, "Yuridik shaxs deb qanday tashkilot hisoblanadi?", "alohida mol-mulkka ega, o'z nomidan huquqlarga ega bo'lgan, sudda da'vogar va javobgar bo'la oladigan tashkilot", [("FK1", 39)], [r"mol-mulk"])
add(F, "Qaysi bitimlar oddiy yozma shaklda tuziladi?", "yuridik shaxslarning bitimlari va fuqarolar o'rtasida BHM 10 baravaridan ortiq bitimlar", [("FK1", 108)], [r"yuridik shaxs", r"\b10\b|o'n baravar"])
add(F, "Mulk ijarasi shartnomasi qaysi hollarda yozma shaklda tuzilishi shart?", "1 yildan ortiq muddatga yoki taraflardan biri yuridik shaxs bo'lsa", [("FK2", 539)], [r"yozma", r"1 yil|bir yil|yuridik shaxs"])
add(F, "Qarz shartnomasi nima?", "qarz beruvchi pul yoki ashyolarni mulk qilib beradi, qarz oluvchi shuncha summani qaytaradi", [("FK2", 732)], [r"qarz beruvchi"])
add(F, "Chakana oldi-sotdi shartnomasi qanday shartnoma hisoblanadi?", "ommaviy shartnoma", [("FK2", 425)], [r"ommaviy"])
add(F, "Qanday hollarda ota-ona ota-onalik huquqidan mahrum qilinadi?", "majburiyatlarni bajarishdan bosh tortsa, aliment to'lashdan bo'yin tovlasa va hokazo", [("OK", 79)], [r"aliment|bosh tort|suiiste"])
add(F, "Nikoh yoshiga yetmagan shaxs bilan tuzilgan nikoh haqiqiy emas deb topilishi mumkinmi?", "ha, manfaatlari talab qilgan hollarda", [("OK", 51)], [r"haqiqiy emas"])
add(F, "O'n sakkiz yoshgacha bo'lgan xodim qanday hollarda to'liq moddiy javobgar bo'ladi?", "faqat qasddan zarar yetkazganda", [("M", 341)], [r"qasd"])
add(F, "Mehnat kodeksida ta'tillarning qanday turlari nazarda tutilgan?", "har yilgi, ijtimoiy, ish haqi qisman saqlanadigan va saqlanmaydigan ta'til", [("M", 213)], [r"yillik|har yilgi", r"ijtimoiy"])
add(F, "Qaysi ijtimoiy ta'tillar mavjud?", "homiladorlik va tug'ish, bola parvarishlash, o'quv, ijodiy ta'tillar", [("M", 237)], [r"homiladorlik", r"bola parvarish"])
add(F, "Voyaga yetmagan bolani moddiy ta'minlashdan bo'yin tovlash qachon jinoyat bo'ladi?", "sud qarori bo'yicha undiriladigan mablag'ni ikki oydan ortiq to'lamaslik va ma'muriy jazodan keyin", [("J", 122)], [r"2 oy|ikki oy"])
add(F, "16 yoshga to'lmagan shaxs bilan jinsiy aloqa qilish uchun qanday jazo belgilangan?", "3 yildan 5 yilgacha ozodlikni cheklash yoki ozodlikdan mahrum qilish", [("J", 128)], [r"\b3\b|uch", r"\b5\b|besh"])
add(F, "Takroran yoki xavfli retsidivist tomonidan qasddan odam o'ldirilsa qanday jazo beriladi?", "15 yildan 25 yilgacha yoki umrbod ozodlikdan mahrum qilish", [("J", 97)], [r"\b15\b|o'n besh", r"\b25\b|yigirma besh|umrbod"])
add(F, "Pora olishning eng og'ir holatida (juda ko'p miqdorda yoki uyushgan guruh manfaatlarini ko'zlab) qanday jazo beriladi?", "10 yildan 15 yilgacha ozodlikdan mahrum qilish", [("J", 210)], [r"\b10\b|o'n yil", r"\b15\b|o'n besh"])
add(F, "Juda ko'p miqdorda firibgarlik uchun qanday jazo nazarda tutilgan?", "8 yildan 10 yilgacha ozodlikdan mahrum qilish (yoki BHM 400-600 baravari jarima)", [("J", 168)], [r"\b8\b|sakkiz", r"\b10\b|o'n yil"])
add(F, "Ish beruvchi tashabbusi bilan mehnat shartnomasini qaysi asoslarda bekor qilish mumkin?", "malakasi yetarli emasligi, mehnat majburiyatlarini muntazam buzishi va boshqalar", [("M", 161)], [r"malaka|muntazam"])
add(F, "Dam olish kunlarida va bayram kunlarida ishlashga qaysi hollarda yo'l qo'yiladi?", "uzluksiz ishlaydigan tashkilotlar, kechiktirib bo'lmaydigan ta'mirlash va boshqa ishlar", [("M", 209)], [r"uzluksiz|kechiktirib|ta'mirlash"])
add(F, "Mehnat shartnomasini bekor qilish asoslari qaysilar?", "taraflarning kelishuvi, muddat tugashi, xodim yoki ish beruvchi tashabbusi va boshqalar", [("M", 155)], [r"kelishuv"])
add(F, "Turar joy mulkdori o'z turar joyini ayirboshlashga haqlimi?", "ha, Fuqarolik kodeksi qoidalariga binoan", [("UJ", 115)], [r"haqli|ha"])
add(F, "Sud buyrug'i berish haqidagi arizadan davlat boji undiriladimi?", "ha, da'vo ishi uchun belgilangan tartib va miqdorda", [("FPK", 174)], [r"davlat boji"])

# --- raqamlar (15)
N = "raqamlar"
add(N, "Tug'ruqdan keyin necha kalendar kun ta'til beriladi?", "56 kun", [("M", 404)], [r"56|ellik olti"])
add(N, "Homiladorlik va tug'ish ta'tilida nafaqa o'rtacha oylik ish haqining kamida necha foizi?", "75 foiz", [("M", 404)], [r"75|yetmish besh"])
add(N, "Dividendlar tarzidagi daromadga jismoniy shaxslar uchun soliq stavkasi qancha?", "5 foiz", [("S", 381)], [r"\b5\b|besh"])
add(N, "Ikki bola uchun aliment ota-ona daromadining qancha qismini tashkil etadi?", "uchdan bir qismi", [("OK", 99)], [r"uchdan bir|1/3|33"])
add(N, "Uch va undan ortiq bola uchun aliment miqdori qancha?", "yarmi", [("OK", 99)], [r"yarmi|1/2|50"])
add(N, "Fuqarolar o'rtasidagi bitim bazaviy hisoblash miqdorining necha baravaridan ortiq bo'lsa oddiy yozma shaklda tuziladi?", "10 baravar", [("FK1", 108)], [r"\b10\b|o'n"])
add(N, "Tashkilot rahbarlari va bosh buxgalterlar uchun dastlabki sinov muddati necha oygacha bo'lishi mumkin?", "6 oy", [("M", 130)], [r"\b6\b|olti"])
add(N, "Mulk ijarasi shartnomasi necha yildan ortiq muddatga mo'ljallangan bo'lsa yozma shaklda tuziladi?", "1 yildan ortiq", [("FK2", 539)], [r"\b1 yil|bir yil"])
add(N, "Hokim nikoh yoshini ko'pi bilan necha yilga kamaytirishi mumkin?", "1 yil", [("OK", 15)], [r"\b1 yil|bir yil"])
add(N, "Qaysi jinoyatlar uchun javobgarlik 14 yoshdan boshlanadi?", "14 yoshdan o'ldirish (97), shikast (104-106), o'g'rilik (169) kabi", [("J", 17)], [r"\b14\b|o'n to'rt", r"97|odam o'ldirish"])
add(N, "Soliq stavkasi 36-bobda nazarda tutilgan hollarda qancha foiz bo'ladi?", "0 foiz", [("S", 258)], [r"\b0\b|nol"])
add(N, "Tungi vaqtda ishbay ish haqi soatlik tarif stavkasining kamida necha foizi miqdorida to'lanadi?", "50 foiz yoki undan ortiq", [("M", 264)], [r"50|ellik"])
add(N, "Pora olishning oddiy holatida (a, b bandlarsiz) jazo necha yildan necha yilgacha?", "5 yildan 10 yilgacha ozodlikdan mahrum qilish", [("J", 210)], [r"\b5\b|besh", r"\b10\b|o'n"])
add(N, "Voyaga yetmagan bolani ta'minlashdan bo'yin tovlash uchun jazo sifatida necha yilgacha axloq tuzatish ishlari belgilangan?", "2 yilgacha", [("J", 122)], [r"\b2\b|ikki"])
add(N, "Qolgan soliq to'lovchilar uchun foyda solig'i stavkasi qancha?", "15 foiz", [("S", 337)], [r"15|o'n besh"])

# --- bir nechta modda / hujjat (15)
MU = "ko'p manba"
add(MU, "Homiladorlik ta'tili necha kun va nafaqa qancha, boshqa qanday ijtimoiy ta'tillar bor?", "70+56 kun, 75% nafaqa, bola parvarishlash va boshqalar", [("M", 404), ("M", 237)], [r"70|yetmish"])
add(MU, "Ish beruvchi tashabbusi bilan ishdan bo'shatishda qanday asoslar bor va ishdan bo'shatish nafaqasi to'lanadimi?", "asoslar 161-modda; nafaqa 173-modda", [("M", 161), ("M", 173)], [r"nafaqa"])
add(MU, "Ajrashganda umumiy mol-mulk qanday bo'linadi va bolalarga aliment qancha?", "27-modda va 99-modda", [("OK", 27), ("OK", 99)], [r"aliment"])
add(MU, "Nikoh yoshi necha yosh va yoshiga yetmagan shaxs bilan tuzilgan nikoh qanday oqibatga olib keladi?", "18 yosh; nikoh haqiqiy emas deb topilishi mumkin", [("OK", 15), ("OK", 51)], [r"18|o'n sakkiz", r"haqiqiy emas"])
add(MU, "Qasddan odam o'ldirish va zaruriy mudofaa chegarasidan chetga chiqib odam o'ldirish nima bilan farqlanadi?", "97 va 100-moddalar", [("J", 97), ("J", 100), ("J", 37)], [r"zaruriy mudofaa"])
add(MU, "O'g'rilik va firibgarlik uchun jinoiy javobgarlik qanday?", "169 va 168-moddalar", [("J", 169), ("J", 168)], [r"o'g'rilik", r"firibgarlik"])
add(MU, "Umumiy va maxsus da'vo muddatlari qanday?", "150 va 151-moddalar", [("FK1", 150), ("FK1", 151)], [r"\b3 yil|uch yil", r"maxsus"])
add(MU, "Oldi-sotdi shartnomasi va chakana oldi-sotdi shartnomasi nima?", "386 va 425-moddalar", [("FK2", 386), ("FK2", 425)], [r"chakana"])
add(MU, "Mulk ijarasi shartnomasining shakli va muddati qanday?", "539 va 540-moddalar", [("FK2", 539), ("FK2", 540)], [r"yozma"])
add(MU, "Ish vaqtining normal davomiyligi, tungi ishning davomiyligi va tungi ishga haq to'lash qanday?", "182, 188, 264-moddalar", [("M", 182), ("M", 188), ("M", 264)], [r"40|qirq"])
add(MU, "Dam olish kunlarida ishlash va bayram kunlarida ishlash qanday cheklanadi?", "209 va 211-moddalar", [("M", 209), ("M", 211)], [r"dam olish"])
add(MU, "Dastlabki sinov muddati va uning natijasi qanday belgilanadi?", "130 va 132-moddalar", [("M", 130), ("M", 132)], [r"sinov"])
add(MU, "Yuridik shaxs nima va uning ta'sis hujjatlari qaysilar?", "39 va 43-moddalar", [("FK1", 39), ("FK1", 43)], [r"ta'sis"])
add(MU, "Aliment to'lamaslik uchun qanday javobgarlik bor va aliment miqdori qanday aniqlanadi?", "122-modda (JK) va 99-modda (OK)", [("J", 122), ("OK", 99)], [r"aliment"])
add(MU, "Ota-onalik huquqidan mahrum qilish tartibi va oqibatlari qanday?", "79, 80, 81-moddalar", [("OK", 79), ("OK", 80), ("OK", 81)], [r"mahrum"])

# --- o'zgargan norma (10): eski qoidaga tayanilmasligini tekshiradi
C = "o'zgargan norma"
add(C, "QQS stavkasi 20 foizmi?", "yo'q, amaldagi stavka 12 foiz", [("S", 258)], [r"12"])
add(C, "Yillik asosiy mehnat ta'tili 15 ish kuni emasmi?", "amaldagi qoida: 21 kalendar kun", [("M", 217)], [r"21|yigirma bir"])
add(C, "Dividendlarga jismoniy shaxslar uchun 10 foiz soliq solinadimi?", "5 foiz", [("S", 381)], [r"\b5\b|besh"])
add(C, "Ayollar uchun nikoh yoshi 17 yoshmi?", "yo'q, erkak va ayollar uchun 18 yosh", [("OK", 15)], [r"18|o'n sakkiz"])
add(C, "Haftalik ish vaqti 41 soatgacha bo'lishi mumkinmi?", "yo'q, 40 soatdan ortiq bo'la olmaydi", [("M", 182)], [r"40|qirq"])
add(C, "Tug'ruq ta'tili jami 60 kun emasmi?", "amaldagi: 70 + 56 kalendar kun", [("M", 404)], [r"70|yetmish", r"56|ellik olti"])
add(C, "Da'vo muddati 5 yilmi?", "yo'q, umumiy da'vo muddati 3 yil", [("FK1", 150)], [r"\b3 yil|uch yil"])
add(C, "Dastlabki sinov muddati olti oygacha bo'lishi mumkinmi (oddiy xodim uchun)?", "oddiy xodim uchun 3 oydan oshmaydi", [("M", 130)], [r"\b3 oy|uch oy"])
add(C, "Hokim nikoh yoshini 3 yilga kamaytirishi mumkinmi?", "yo'q, ko'pi bilan 1 yil", [("OK", 15)], [r"\b1 yil|bir yil"])
add(C, "Foyda solig'ining umumiy stavkasi 20 foizmi?", "qolgan soliq to'lovchilar uchun 15 foiz", [("S", 337)], [r"15|o'n besh"])

# --- rus va kirill (10)
R = "rus/kirill"
add(R, "Какой срок исковой давности установлен Гражданским кодексом?", "3 года", [("FK1", 150)], [r"три|\b3\b"], RU)
add(R, "С какого возраста наступает уголовная ответственность в Узбекистане?", "16 лет", [("J", 17)], [r"16|шестнадцат"], RU)
add(R, "Какова минимальная продолжительность ежегодного основного трудового отпуска?", "21 календарный день", [("M", 217)], [r"21|двадцат"], RU)
add(R, "Какой брачный возраст установлен в Узбекистане?", "18 лет", [("OK", 15)], [r"18|восемнадцат"], RU)
add(R, "Какова ставка НДС в Узбекистане?", "12 процентов", [("S", 258)], [r"12|двенадцат"], RU)
add(R, "Сколько календарных дней длится отпуск по беременности и родам?", "70 до и 56 после родов", [("M", 404)], [r"70|семьдесят", r"56|пятьдесят шесть"], RU)
add(R, "Меҳнат таътилининг энг кам муддати қанча?", "21 календарь кун", [("M", 217)], [r"21|йигирма бир"], CYR)
add(R, "Никоҳ ёши неча ёш?", "18 ёш", [("OK", 15)], [r"18|ўн саккиз"], CYR)
add(R, "Даъво муддати неча йил?", "3 йил", [("FK1", 150)], [r"\b3\b|уч"], CYR)
add(R, "Ишдан бўшатиш нафақаси қачон тўланади?", "баъзи асосларда бекор қилинганда", [("M", 173)], [r"нафақа"], CYR)

# --- javobsiz (10)
Z = "javobsiz"
for q in ["Mars sayyorasida yer sotib olish tartibi qanday?", "2022-yilda futbol bo'yicha jahon chempionati g'olibi kim bo'ldi?",
          "Pizza tayyorlash retsepti qanday?", "Eng yaxshi dasturlash tili qaysi?", "Quyosh tizimidagi eng katta sayyora qaysi?",
          "Bugun Toshkentda ob-havo qanday bo'ladi?", "Yangi iPhone ning narxi qancha?",
          "Amerika Qo'shma Shtatlari Konstitutsiyasiga kiritilgan birinchi tuzatish nima haqida?",
          "Rossiya Federatsiyasi Mehnat kodeksida yillik ta'til necha kun?", "Hayotning ma'nosi nima?"]:
    add(Z, q, "", [])

# --- og'zaki, noaniq (5)
O = "og'zaki"
add(O, "ishdan sababsiz haydashdi nima qilaman", "ish beruvchi tashabbusi bilan bekor qilish asoslari (161) yoki bekor qilish asoslari (155)", [("M", 161), ("M", 155)], [])
add(O, "tug'ruq ta'tiliga chiqsam pul berishadimi", "ha, nafaqa to'lanadi (404-modda)", [("M", 404)], [r"nafaqa"])
add(O, "ajrashsam bolaga qancha pul to'layman", "aliment: 1 bola 1/4, 2 bola 1/3, 3+ bola 1/2 (99-modda)", [("OK", 99)], [r"to'rtdan bir|1/4|25"])
add(O, "yigit o'g'rilik qilib qo'lga tushsa nima bo'ladi", "o'g'rilik uchun jinoiy javobgarlik (169-modda)", [("J", 169)], [r"o'g'rilik"])
add(O, "bayram kuni ishlashga majburlashsa bo'ladimi", "ishlanmaydigan bayram kunlarida ishlash taqiqlanadi, istisnolar bor (208-209)", [("M", 209), ("M", 208)], [])

if __name__ == "__main__":
    assert len(T) == 100, len(T)
    random.seed(7)
    cats = {}
    for t in T:
        cats.setdefault(t["category"], []).append(t)
    batches = [[] for _ in range(10)]
    i = 0
    for items in cats.values():  # har bir kategoriyadan aralashtirib: bitta batch ham kichik namuna bo'ladi
        random.shuffle(items)
        for t in items:
            batches[i % 10].append(t)
            i += 1
    out = []
    for b, items in enumerate(batches, 1):
        random.shuffle(items)
        for t in items:
            out.append({"id": f"q{len(out) + 1:03d}", "batch": f"b{b:02d}", **t})
    Path(__file__).with_name("testset.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(len(out), {c: len(v) for c, v in cats.items()}, [len(b) for b in batches])
