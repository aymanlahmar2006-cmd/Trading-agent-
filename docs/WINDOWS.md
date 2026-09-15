# التشغيل على Windows

الأوامر في باقي المستندات مكتوبة بصيغة Linux. الفروق كلها هنا.

## 1. `python` مش `python3`

```powershell
python -m pytest tests/ -q
python -m crypto_agent analyze examples/snapshot_pullback.example.json
```

لو `python` مش متعرّف، نزّل Python من <https://www.python.org/downloads/>
و**علّم على `Add python.exe to PATH`** وإنت بتثبّت.

## 2. كل أمر في سطر واحد

الـ `\` في آخر السطر دي صيغة bash. PowerShell بتقسم الأمر لنصين:

```
fatal: repository '\' does not exist
```

❌ **غلط:**
```
git clone -b my-branch \
  https://github.com/user/repo
```

✅ **صح — سطر واحد:**
```powershell
git clone -b claude/crypto-spot-trading-agent-h0gfky https://github.com/aymanlahmar2006-cmd/Trading-agent-
```

لو الأمر طويل وعايز تكسره، PowerShell بتستخدم **backtick** (`` ` ``):

```powershell
python -m crypto_agent open `
  --symbol BINANCE:SOLUSDT --entry 112.6 --size 10 --stop 108.2
```

## 3. العربي بيظهر بالمقلوب — ده طبيعي

كونسول Windows (سواء PowerShell أو Windows Terminal) **مش بيدعم ترتيب الكتابة
من اليمين لليسار**. فالعربي بيطلع معكوس والحروف مش متصلة:

```
يلاع :ةقثلا          ← المفروض: الثقة: عالي
```

**مش مشكلة في الكود.** الحل: الأيجنت **بيكتشف Windows تلقائياً ويطلع إنجليزي**.
مش محتاج تعمل حاجة.

لو عايز تجبره:

```powershell
python -m crypto_agent analyze examples\snapshot_pullback.example.json --lang en
python -m crypto_agent watch snapshots\latest.json --lang ar   # لو بتستخدم طرفية بتدعم RTL
```

أو ثبّتها للجلسة كلها:

```powershell
$env:CRYPTO_AGENT_LANG = "en"
```

> **رسايل Telegram بتفضل بالعربي** مهما كان إعداد الكونسول — الموبايل بيعرض
> العربي صح. لو عايز تغيّرها، `alerts.language` في `config/watchlist.json`.

## 4. الاختبارات

```powershell
python -m pytest tests/ -q
```

المفروض **90 passed** على أي نظام. الاختبارات بتثبّت اللغة بنفسها
(`tests/conftest.py`)، فنتيجتها واحدة على Windows وLinux.

> لو شفت فشل في اختبارات بتقارن نص عربي، يبقى `CRYPTO_AGENT_LANG` متظبطة عندك
> بقيمة غريبة. امسحها: `Remove-Item Env:CRYPTO_AGENT_LANG`

## 5. متغيرات البيئة

`export` مش موجودة في PowerShell.

```powershell
# دائم — بعدها اقفل الـ terminal وافتحه تاني
setx TELEGRAM_BOT_TOKEN "..."
setx TELEGRAM_CHAT_ID "..."

# للجلسة الحالية بس
$env:TELEGRAM_BOT_TOKEN = "..."
```

> **`setx` مش بتأثر على الـ terminal المفتوح.** لازم تقفله وتفتحه تاني، وإلا
> هتفضل تشوف `not configured`.

للتأكد:
```powershell
echo $env:TELEGRAM_BOT_TOKEN
```

## 6. المسارات

الكود بيستخدم `pathlib`، فالمسارات بتشتغل عادي على Windows. بس لو بتكتب مسار
بنفسك في أمر، حطه بين علامتين تنصيص لو فيه مسافات:

```powershell
python -m crypto_agent analyze "C:\Users\Splendid\Desktop\snap.json"
```

## 7. أوامر شائعة — نسخة PowerShell

```powershell
# اختبار
python -m pytest tests/ -q

# تحليل
python -m crypto_agent analyze examples/snapshot_pullback.example.json

# scan كامل من غير إرسال
python -m crypto_agent watch snapshots/latest.json --no-notify

# سجّل صفقة
python -m crypto_agent open --symbol BINANCE:SOLUSDT --entry 112.6 --size 10 --stop 108.2 --target 120.3

# اقفل صفقة
python -m crypto_agent close --symbol SOLUSDT --price 120.3

# الحالة
python -m crypto_agent status --price SOLUSDT=118.4

# اختبار Telegram
python -c "from crypto_agent.notify import notify; print(notify('اختبار'))"
```
