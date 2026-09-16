"""Labels in Arabic and English.

The Windows console does not reorder right-to-left text, so Arabic output there
arrives reversed and with unjoined letters -- unreadable. Terminal output
therefore defaults to English on Windows and Arabic everywhere else, while
Telegram always gets Arabic because phone clients render it correctly.
"""

from __future__ import annotations

import os
import sys

AR = "ar"
EN = "en"


def resolve(lang: str = "auto") -> str:
    """Pick a language. ``auto`` means Arabic unless the console cannot show it.

    Precedence is explicit choice, then CRYPTO_AGENT_LANG, then detection. The
    environment variable outranks detection because it is a stated preference,
    and because it is what lets a test suite behave the same on every OS.
    """
    if lang in (AR, EN):
        return lang

    from_env = os.environ.get("CRYPTO_AGENT_LANG", "").strip().lower()
    if from_env in (AR, EN):
        return from_env

    if sys.platform.startswith("win"):
        # Windows Terminal and conhost both lack bidirectional reordering.
        return EN
    encoding = (getattr(sys.stdout, "encoding", "") or "").lower()
    if encoding and "utf" not in encoding:
        return EN
    return AR


T: dict[str, dict[str, str]] = {
    # Report scaffolding
    "market_context": {AR: "=== Market Context ===", EN: "=== Market Context ==="},
    "top_opportunities": {AR: "=== Top Opportunities ===", EN: "=== Top Opportunities ==="},
    "watching": {
        AR: "=== Watching (لسه معندهاش إشارة واضحة) ===",
        EN: "=== Watching (no clear signal yet) ===",
    },
    "alerts_header": {AR: "=== تنبيهات ===", EN: "=== Alerts ==="},
    "no_opportunities": {
        AR: "لا توجد فرص مستوفية للشروط في هذه الجولة.",
        EN: "No setup met the criteria on this pass.",
    },
    "nothing": {AR: "لا شيء.", EN: "Nothing."},
    "no_alerts": {AR: "لا جديد يستدعي التنبيه.", EN: "Nothing new worth an alert."},
    "safety_note": {
        AR: "— إشارات فقط. لم يتم ولن يتم تنفيذ أي صفقة تلقائياً. —",
        EN: "— Signals only. No trade is or will be executed automatically. —",
    },
    "context_unavailable": {
        AR: ("غير متاح — طبقة تقييم السوق مش متوصلة في الجولة دي. "
             "التحليل تحت ده بدون سياق BTC."),
        EN: ("Unavailable — the market context layer did not run on this pass. "
             "The analysis below has no BTC context."),
    },
    "load_failures": {AR: "=== رموز فشل تحميلها ===", EN: "=== Symbols that failed to load ==="},
    "no_symbol_analysed": {
        AR: "لم يتم تحليل أي رمز. أخطاء البيانات:",
        EN: "No symbol could be analysed. Data errors:",
    },

    # Per-opportunity lines
    "price_now": {AR: "السعر الحالي", EN: "Price"},
    "setup_quality": {AR: "جودة الإعداد", EN: "Setup quality"},
    "reason": {AR: "السبب:", EN: "Reasoning:"},
    "confidence": {AR: "الثقة", EN: "Confidence"},
    "data_gaps": {AR: "⚠ نواقص في البيانات:", EN: "⚠ Data gaps:"},
    "notes": {AR: "ℹ ملاحظات:", EN: "ℹ Notes:"},
    "rr_net": {AR: "صافي", EN: "net"},
    "rr_gross_note": {
        AR: "قبل التكاليف — الرسوم والانزلاق بياخدوا",
        EN: "gross — fees and slippage take",
    },
    "no_clear_signal": {AR: "لا توجد إشارة واضحة.", EN: "No clear signal."},

    # Trend and confidence values
    "bullish": {AR: "صاعد", EN: "bullish"},
    "bearish": {AR: "هابط", EN: "bearish"},
    "neutral": {AR: "عرضي", EN: "sideways"},
    "strong": {AR: "قوي", EN: "strong"},
    "moderate": {AR: "متوسط", EN: "moderate"},
    "weak": {AR: "ضعيف", EN: "weak"},
    "sideways": {AR: "عرضي", EN: "sideways"},
    "unknown": {AR: "غير محدد", EN: "unknown"},
    "high": {AR: "عالي", EN: "high"},
    "medium": {AR: "متوسط", EN: "medium"},
    "low": {AR: "منخفض", EN: "low"},

    # Regime
    "risk_on": {AR: "مُقبل على المخاطرة (risk-on)", EN: "risk-on"},
    "risk_off": {AR: "متجنب للمخاطرة (risk-off)", EN: "risk-off"},
    "mixed": {AR: "مختلط", EN: "mixed"},
    "regime_unknown": {AR: "غير معروف", EN: "unknown"},
    "breadth": {
        AR: "اتساع السوق: {bullish} من {total} رمز صاعد ({pct:.0f}%)",
        EN: "Breadth: {bullish} of {total} symbols bullish ({pct:.0f}%)",
    },
    "btc_not_analysed": {
        AR: "BTC لم يتم تحليله في هذه الجولة — تقييم السوق مبني على الاتساع فقط.",
        EN: "BTC was not analysed this pass — the regime read rests on breadth alone.",
    },
    "no_peers": {
        AR: "لا توجد رموز أخرى للمقارنة، فمفيش حكم على اتساع السوق.",
        EN: "No other symbols to compare against, so breadth is not judged.",
    },
    "rotation_into_btc": {
        AR: ("BTC صاعد لكن باقي السوق مش تابع — ده دوران نحو BTC، مش risk-on. "
             "الألت كوينز أضعف من المعتاد في الوضع ده."),
        EN: ("BTC is rising while the rest is not following — that is rotation into "
             "BTC, not risk-on. Alts are weaker than usual in this state."),
    },
    "btc_down_alts_up": {
        AR: "BTC هابط بينما الألت صاعدة — وضع غير مستقر، عادةً بيتحل لصالح BTC.",
        EN: ("BTC is falling while alts rise — an unstable state that usually "
             "resolves in BTC's favour."),
    },
    "regime_changed": {
        AR: "حالة السوق اتغيرت من {before} إلى {after}",
        EN: "Market regime changed from {before} to {after}",
    },
    "regime_change_title": {AR: "تغيّر في حالة السوق", EN: "Market regime changed"},

    # Alerts
    "stop_breached_title": {AR: "{sym}: السعر اخترق الستوب", EN: "{sym}: price broke the stop"},
    "stop_breached_detail": {
        AR: ("السعر {price} تحت الستوب {stop}. الخسارة الحالية {r}. "
             "قرار الخروج قرارك — الأيجنت ما بينفذش."),
        EN: ("Price {price} is below the stop {stop}. Currently {r}. "
             "Exiting is your call — the agent does not execute."),
    },
    "target_reached_title": {AR: "{sym}: وصل الهدف {target}", EN: "{sym}: target {target} reached"},
    "target_reached_detail": {
        AR: "السعر {price} عند/فوق الهدف. الربح الحالي {r}.",
        EN: "Price {price} is at or above the target. Currently {r}.",
    },
    "stop_near_title": {AR: "{sym}: السعر قرّب من الستوب", EN: "{sym}: price is nearing the stop"},
    "stop_near_detail": {
        AR: ("فاضل {pct:.0f}% بس من مسافة المخاطرة الأصلية (السعر {price}، "
             "الستوب {stop}). الوضع الحالي {r}."),
        EN: ("Only {pct:.0f}% of the original risk distance is left (price {price}, "
             "stop {stop}). Currently {r}."),
    },
    "no_price_title": {AR: "{sym}: مفيش سعر لحظي", EN: "{sym}: no live price"},
    "no_price_detail": {
        AR: ("الصفقة مفتوحة لكن ما قدرناش نجيب سعرها في الجولة دي، فمفيش متابعة "
             "للستوب أو الهدف."),
        EN: ("The position is open but no price was collected this pass, so the "
             "stop and target are not being tracked."),
    },
    "new_setup_title": {AR: "{sym}: إعداد جديد ({q:.0f}/100)", EN: "{sym}: new setup ({q:.0f}/100)"},
    "new_setup_detail": {
        AR: "دخول {entry} | ستوب {stop} | هدف {target} | R:R {rr:.2f} صافي",
        EN: "Entry {entry} | stop {stop} | target {target} | R:R {rr:.2f} net",
    },
    "r_not_computed": {AR: "R غير محسوب", EN: "R not computed"},
    "alerts_telegram_header": {AR: "🔔 تنبيهات", EN: "🔔 Alerts"},

    # Journal / CLI
    "open_positions": {AR: "=== صفقات مفتوحة ===", EN: "=== Open positions ==="},
    "closed_summary": {AR: "=== ملخص الصفقات المقفولة ===", EN: "=== Closed trade summary ==="},
    "no_closed": {AR: "لسه مفيش صفقات مقفولة.", EN: "No closed trades yet."},
    "recorded": {AR: "✅ اتسجلت", EN: "✅ Recorded"},
    "closed": {AR: "✅ اتقفلت", EN: "✅ Closed"},
    "entry": {AR: "دخول", EN: "entry"},
    "stop": {AR: "ستوب", EN: "stop"},
    "target": {AR: "هدف", EN: "target"},
    "exit": {AR: "خروج", EN: "exit"},
    "risk_1r": {AR: "المخاطرة {risk} (= 1R)", EN: "Risk {risk} (= 1R)"},
    "entry_fee": {AR: "رسوم الدخول", EN: "entry fee"},
    "result": {AR: "النتيجة", EN: "result"},
    "max_adverse": {AR: "أقصى تراجع", EN: "max adverse"},
    "max_favourable": {AR: "أقصى ربح غير محقق", EN: "max favourable"},
    "no_live_price": {AR: "(مفيش سعر لحظي — مرر --price)", EN: "(no live price — pass --price)"},
    "count": {AR: "العدد", EN: "Trades"},
    "win_rate": {AR: "نسبة الربح", EN: "win rate"},
    "expectancy": {AR: "التوقع", EN: "Expectancy"},
    "per_trade": {AR: "لكل صفقة", EN: "per trade"},
    "total": {AR: "الإجمالي", EN: "total"},
    "net": {AR: "صافي", EN: "net"},
    "best": {AR: "أفضل", EN: "best"},
    "worst": {AR: "أسوأ", EN: "worst"},
    "pf_undefined": {
        AR: "غير محسوب (مفيش صفقة خاسرة لسه)",
        EN: "undefined (no losing trade yet)",
    },
    "negative_expectancy": {
        AR: "\n⚠ التوقع سالب — الإشارات دي مش رابحة على بياناتك الفعلية حتى الآن.",
        EN: "\n⚠ Expectancy is negative — on your own data these signals are not profitable so far.",
    },
    "already_open": {
        AR: "في صفقة مفتوحة بالفعل على {sym} ({id}). اقفلها الأول أو استخدم رمز مختلف.",
        EN: "A position is already open on {sym} ({id}). Close it first, or use a different symbol.",
    },
    "rejected": {AR: "الصفقة مترفضة: {err}", EN: "Position rejected: {err}"},
    "no_open_position": {AR: "مفيش صفقة مفتوحة على {sym}.", EN: "No open position on {sym}."},
    "bad_price_format": {
        AR: "صيغة غلط: {item} — المفروض SYMBOL=PRICE",
        EN: "Bad format: {item} — expected SYMBOL=PRICE",
    },
    "error": {AR: "خطأ", EN: "Error"},
}


def t(key: str, lang: str, **kwargs) -> str:
    """Look up ``key`` in ``lang``, formatting any placeholders."""
    entry = T.get(key)
    if entry is None:
        return key
    text = entry.get(lang, entry.get(EN, key))
    return text.format(**kwargs) if kwargs else text
