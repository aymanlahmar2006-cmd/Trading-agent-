# إعداد تنبيهات Telegram

مجاني تماماً، مفيش API مدفوع. 5 دقايق.

## 1. اعمل bot

افتح Telegram ودوّر على **@BotFather** → ابعتله:

```
/newbot
```

هيسألك على اسم واسم مستخدم (لازم ينتهي بـ `bot`). هيرد عليك بـ **token** شكله كده:

```
1234567890:XXXXXXXX-EXAMPLE-NOT-A-REAL-TOKEN-XXXX
```

**الـ token ده زي الباسورد.** ما تحطهوش في أي ملف داخل المشروع — الريبو ده public.

## 2. هات الـ chat ID بتاعك

ابعت أي رسالة للبوت اللي عملته (مثلاً `مرحبا`)، وبعدين افتح اللينك ده في المتصفح
بعد ما تحط الـ token مكان `<TOKEN>`:

```
https://api.telegram.org/bot<TOKEN>/getUpdates
```

دوّر على `"chat":{"id":123456789` — الرقم ده هو `TELEGRAM_CHAT_ID`.

> لو رجعلك `{"ok":true,"result":[]}` يبقى البوت لسه ما استقبلش رسالة منك. ابعتله
> رسالة الأول وبعدين افتح اللينك تاني.

## 3. حطهم في البيئة

**Linux / macOS** — ضيفهم في `~/.bashrc` أو `~/.zshrc`:

```bash
export TELEGRAM_BOT_TOKEN="1234567890:XXXXXXXX-EXAMPLE..."
export TELEGRAM_CHAT_ID="123456789"
```

بعدين `source ~/.bashrc`.

**Windows (PowerShell)** — دايمين:

```powershell
setx TELEGRAM_BOT_TOKEN "1234567890:XXXXXXXX-EXAMPLE..."
setx TELEGRAM_CHAT_ID "123456789"
```

بعدين اقفل الـ terminal وافتحه تاني.

## 4. اختبر

```bash
python3 -c "from crypto_agent.notify import notify; print(notify('اختبار من الأيجنت'))"
```

لو ظهر `Delivery(channel='telegram', ok=True)` يبقى تمام.

## لو مش شغال

| الرسالة | المعنى |
|---|---|
| `not configured` | المتغيرات مش موجودة في الـ terminal ده — اقفله وافتحه تاني |
| `HTTP 401: Unauthorized` | الـ token غلط أو ناقص |
| `HTTP 400: chat not found` | الـ chat ID غلط، أو ما بعتّش للبوت رسالة قبل كده |

**في كل الحالات الرسالة بتتكتب في `journal/outbox.log`** — مفيش تنبيه بيضيع
حتى لو الإرسال فشل.
