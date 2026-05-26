"""
مساعد دردشة تلع للعملاء: إجابات جاهزة + أزرار سريعة (قواعد ثابتة).
يُحدّث بيانات التوصيل (الاسم/الجوال/العنوان) تلقائيًا عند السماح بحالة الطلب؛
لا يغيّر الدفع/الشحن الإداري ويحوّل للممثّل عند رفض التعديل التلقائي.
"""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any

from django.db.models import Q
from django.utils import timezone

from .discount_engine import normalize_phone
from .order_contact_edit_service import (
    apply_customer_name,
    apply_customer_phone,
    apply_delivery_address,
    build_address_text,
    can_edit_contact_info,
)
from .models import Order, SupportMessage, SupportThread

BOT_KIND = "support_bot"

# يُستخدم أيضًا كرسالة انتظار تلقائية للرسالة الأولى (ينبغي بقاء النص مطابقاً).
SUPPORT_AUTO_WAITING_REPLY = (
    'اهلاً بك في متجر دولابك 🌟 تم استلام رسالتك بنجاح، '
    'وسيتم الرد عليك من أحد ممثلي خدمة العملاء فور توفره. نشكرك على انتظارك.'
)

# أزرار القائمة الرئيسية (يجب أن تطابق label في الواجهة)
QR_ROOT: list[dict[str, str]] = [
    {"id": "track", "label": "تتبع الطلب"},
    {"id": "edit", "label": "تعديل بيانات الطلب"},
    {"id": "returns", "label": "الإرجاع والاستبدال"},
    {"id": "pay", "label": "الدفع والمشاكل المالية"},
    {"id": "ship", "label": "الشحن والتوصيل"},
    {"id": "coupon", "label": "الكوبونات والخصومات"},
]

BACK_HOME = "رجوع للقائمة الرئيسية"
LAST_ORDER = "عرض آخر طلب"
# ——— تدفق تعديل بيانات الطلب (دردشة) ———
EDIT_NAME = "تعديل الاسم"
EDIT_PHONE = "تعديل رقم الجوال"
EDIT_ADDRESS = "تعديل العنوان"
OTHER_ORDER_ID = "رقم طلب آخر"
# بعد تغيير رقم الطلب — للضيف: تذكير باستخدام الرقم الجديد عند فتح دردشة لاحقاً
GUEST_NEW_CHAT_PHONE_HINT = (
    "\n\nتذكير: عند **بدء محادثة جديدة** لاحقاً من صفحة خدمة العملاء، "
    "أدخل **رقم الجوال الجديد** المسجّل على طلبك وليس الرقم القديم، "
    "ليتوافق إدخالك مع بيانات الطلب في النظام."
)
# خطوات العنوان في الشات: الحقول المهمة فقط (لا نعرض حقولًا اختيارية داخل البوت)
ADDRESS_STEPS: list[tuple[str, str, bool]] = [
    ("country", "أدخل **البلد**:", True),
    ("city", "أدخل **المدينة**:", True),
    ("district", "أدخل **الحي أو المنطقة**:", True),
    ("street", "أدخل **الشارع** (مثال: حي — شارع):", True),
]
LABEL_MORE = "مساعدة أخرى (القائمة الكاملة)"
LABEL_END = "إنهاء المحادثة"
# نص المتابعة داخل نفس فقاعة إجابة المساعد؛ الأزرار السريعة توضح الخيارين.
FOLLOWUP_TEXT = "هل تحتاج إلى مساعدة في شيء آخر؟"
# عند الحاجة لمراجعة يدوية من الفريق (بدون زر «التحدث مع موظف»)
HINT_WRITE_TO_TEAM = "اكتب استفسارك أو رقم الطلب باختصار وسيصل طلبك لفريق خدمة العملاء."
# زرتان فقط في رسالة المتابعة (نفس تسمية إنهاء الزر اليدوي لاحقاً)
QR_FOLLOWUP: list[dict[str, str]] = [
    {"id": "more", "label": LABEL_MORE},
    {"id": "endchat", "label": LABEL_END},
]

ESCALATION_RE = re.compile(
    r"شكوى|محام|قضيّة|قضية|نصب|احتيال|دعوى|بلاغ|شرطة",
    re.IGNORECASE,
)

# طلب صريح للتحدث مع ممثل / خدمة العملاء (نص حر من العميل) — تطابق حرفي سريع
HUMAN_INTENT_RE = re.compile(
    r"التحدث\s*مع\s*(موظف|أحد|احد|شخص|ممثل)|"
    r"أتكلم\s*مع|اتكلم\s*مع|"
    r"موظف\s*خدمة|ممثل[يى]?\s*خدمة|"
    r"(اريد|أريد|ابغى|أبغى)\s*(موظف|شخص|حد|احد|أحد|اتكلم|التحدث)|"
    r"تواصل\s*مع\s*(موظف|خدمة|ممثل)|"
    r"خدمة\s*العملاء|"
    r"مساعدة\s*بشرية|شخص\s*حقيقي|"
    r"كلام\s*مع\s*(موظف|حد|أحد|احد)",
    re.IGNORECASE,
)

# مقاطع مرجعية (بعد _normalize_arabic_intent) + مطابقة تفاضلية تغطي أخطاء مثل: موضف/موظف، خدمه/خدمة
STAFF_FUZZY_REFS: tuple[str, ...] = (
    "التحدث مع موظف",
    "التحدث مع ممثل",
    "التحدث مع احد",
    "التحدث مع شخص",
    "اريد التحدث مع موظف",
    "ابغي موظف",
    "وين الموظف",
    "اتكلم مع موظف",
    "تكلم مع موظف",
    "كلام مع موظف",
    "تواصل مع موظف",
    "راسلوني ممثل",
    "ممثلي خدمه العملاء",
    "خدمه العملاء",
    "خدمه عملاء",
    "موظف خدمه",
    "ممثل خدمه",
    "اريد احد من الدعم",
    "رقم خدمه العملاء",
    "وصلني لممثل",
    "محد يرد",
)

# مفردات شائعة (بعد التطبيع) — تشابه نسبي يغطي حرفا زائدا أو مبدالا
STAFF_FUZZY_TOKENS: tuple[str, ...] = (
    "موظف",
    "ممثل",
    "العملاء",
    "خدمه",
    "ممثلين",
    "الدعم",
)

_AR_INTENT = re.compile(r"[\s\u200c\u200f\u202a\u202c\u2066\u2069]+")
_AR_STRIP = re.compile(r"[^\u0600-\u06ff0-9\s]")


def _normalize_arabic_intent(s: str) -> str:
    """
    تطبيع خفيف للمقارنة: ألف/همزات، ة/ه، ى/ي، إزالة تنسيق/رموز غير عربية.
    لا يستبدل تلقائياً ض/ظ/ط/ذ — يُرجَى للمقارنة التفاضلية.
    """
    t = (s or "").strip()
    t = unicodedata.normalize("NFKC", t)
    t = _AR_STRIP.sub(" ", t)
    t = t.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ٱ", "ا")
    t = t.replace("ى", "ي").replace("ة", "ه")
    t = t.replace("ؤ", "و").replace("ئ", "ي")
    t = _AR_INTENT.sub(" ", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip().casefold()


def _seq_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return float(SequenceMatcher(None, a, b).ratio())


def _fuzzy_wants_live_staff(n: str) -> bool:
    """
    يكتشف نية التحدث مع ممثل خدمة العملاء حتى مع خطأ في حرف أو حرفين في الجملة.
    """
    if not n or len(n) < 2:
        return False

    # 1) جمل كاملة مقابل مراجع (نص + نوافذ كلمات بنفس العدد)
    for ref in STAFF_FUZZY_REFS:
        refn = _normalize_arabic_intent(ref)
        if len(refn) < 3:
            continue
        if refn in n:
            return True
        if _seq_ratio(n, refn) >= 0.76:
            return True
        wn, rw = n.split(), refn.split()
        ln = len(rw)
        for i in range(0, max(0, len(wn) - ln + 1)):
            chunk = " ".join(wn[i : i + ln])
            if _seq_ratio(chunk, refn) >= 0.76:
                return True

    wn = n.split()

    # 2) كلمات شبه موظف / ممثل / … (موضف → موظف)
    for w in wn:
        if len(w) < 3:
            continue
        wnorm = w
        for tok in STAFF_FUZZY_TOKENS:
            tnorm = _normalize_arabic_intent(tok)
            r = _seq_ratio(wnorm, tnorm)
            if len(wnorm) >= 5:
                th = 0.81
            else:
                th = 0.72
            if r >= th:
                return True

    # 3) «خدمه» بمفردها كاختصار لطلب «خدمه العملاء»
    if len(wn) == 1 and 3 <= len(wn[0]) <= 6 and _seq_ratio(wn[0], "خدمه") >= 0.86:
        return True

    return False

WELCOME_TEXT = (
    "أهلًا بك 👋\n"
    "أنا المساعد التلقائي. اختر أحد الخيارات أدناه للحصول على إجابة سريعة،"
    " أو اكتب رقم الطلب عند طلب المتابعة."
)


def _session_key(thread_id: int) -> str:
    return f"support_bot_{int(thread_id)}"


def _get_ctx(request) -> dict[str, Any]:
    tid = request.session.get("support_thread_id")
    if not tid:
        return {"expect": None, "subflow": None}
    k = _session_key(int(tid))
    v = request.session.get(k)
    if not isinstance(v, dict):
        v = {"expect": None, "subflow": None}
    v.setdefault("expect", None)
    v.setdefault("subflow", None)
    return v


def _set_ctx(request, ctx: dict[str, Any]) -> None:
    tid = request.session.get("support_thread_id")
    if not tid:
        return
    request.session[_session_key(int(tid))] = ctx
    request.session.modified = True


def _merge_ctx(request, updates: dict[str, Any]) -> None:
    ctx = _get_ctx(request)
    ctx.update(updates)
    _set_ctx(request, ctx)


def _clear_subflow(request) -> None:
    _set_ctx(request, {"expect": None, "subflow": None})


def _order_contact_summary(order: Order) -> str:
    return (
        f"رقم الطلب: #{order.id}\n"
        f"الحالة: {order.get_status_display()}\n"
        f"الاسم: {order.customer_name}\n"
        f"الجوال: {order.customer_phone}\n"
        f"العنوان الحالي:\n{order.address}"
    )


def _get_ctx_order(identity, ctx: dict[str, Any]) -> Order | None:
    """طلب مرتبط بسياق التعديل ويتم التحقق من ملكية العميل."""
    raw_id = ctx.get("order_id")
    if not raw_id:
        return None
    try:
        oid = int(raw_id)
    except (TypeError, ValueError):
        return None
    return _resolve_order(identity, str(oid))


def _show_order_edit_menu(
    thread: SupportThread,
    order: Order,
    request,
    *,
    include_other_order: bool,
    prefix: str = "",
) -> None:
    block = _order_contact_summary(order)
    prefix_nl = (prefix + "\n\n") if prefix else ""
    body = f"{prefix_nl}{block}\n\nيمكنك اختيار ماذا تريد تعديله:"
    qrs: list[dict[str, str]] = [
        {"id": "en", "label": EDIT_NAME},
        {"id": "ep", "label": EDIT_PHONE},
        {"id": "ea", "label": EDIT_ADDRESS},
    ]
    if include_other_order:
        qrs.append({"id": "eoth", "label": OTHER_ORDER_ID})
    qrs.append({"id": "backh", "label": BACK_HOME})
    _create_bot(thread, body, qrs)
    _set_ctx(
        request,
        {
            "expect": "field_choice",
            "subflow": "edit_order",
            "order_id": order.id,
        },
    )


def _start_order_edit_flow(
    request, thread: SupportThread, identity
) -> dict[str, Any]:
    """تعديل بيانات الطلب: آخر طلب للمسجّل، أو رقم طلب للضيف."""
    if identity.get("customer_user"):
        order = _last_order(identity)
        if not order:
            _answer_then_followup(
                thread,
                "لا يوجد لديك طلبات سابقة مرتبطة بهذا الحساب. "
                f"للمساعدة اختر «تتبع الطلب» أو {HINT_WRITE_TO_TEAM}",
            )
            _clear_subflow(request)
            return {"skip_first_waiting": True}
        allowed, reason = can_edit_contact_info(order)
        if not allowed:
            _send_staff_waiting_message(thread)
            if reason:
                _create_bot(thread, reason, None)
            _clear_subflow(request)
            return {"skip_first_waiting": True}
        _show_order_edit_menu(thread, order, request, include_other_order=True)
        return {"skip_first_waiting": True}
    # ضيف: يدخل رقم الطلب
    _create_bot(
        thread,
        f"لكي نُظهر بيانات الطلب ونتحقق من ربطه برقم الجوال: اكتب **رقم الطلب** (أرقام فقط).\n"
        f"للعودة: {BACK_HOME}.",
        [{"id": "backh", "label": BACK_HOME}] + list(QR_ROOT),
    )
    _set_ctx(
        request,
        {
            "expect": "edit_order_id",
            "subflow": "edit_order",
            "order_id": None,
        },
    )
    return {"skip_first_waiting": True}


def _process_order_edit_subflow(
    request, thread: SupportThread, identity, text: str
) -> dict[str, Any] | None:
    """
    يعالج subflow=edit_order. إن لم يطابق يرجع None ليستمر باقي المساعد.
    """
    ctx = _get_ctx(request)
    if ctx.get("subflow") != "edit_order":
        return None
    sub_expect = (ctx.get("expect") or "").strip()
    is_guest = not identity.get("customer_user")

    if _is_escalation(text) or _wants_live_staff(text):
        _send_staff_waiting_message(thread)
        _clear_subflow(request)
        return {"skip_first_waiting": True}

    if text == BACK_HOME:
        _create_bot(thread, WELCOME_TEXT, QR_ROOT)
        _clear_subflow(request)
        return {"skip_first_waiting": True}

    # —— انتظار رقم الطلب (ضيف دائمًا؛ ومسجّل عند «رقم طلب آخر») ——
    if sub_expect == "edit_order_id":
        m = re.search(r"(\d+)", text)
        if not m:
            _create_bot(
                thread,
                "لم نفهم رقم الطلب. اكتب رقمًا صالحًا (مثل 12) أو " f"{BACK_HOME}.",
                [{"id": "backh", "label": BACK_HOME}] + list(QR_ROOT),
            )
            return {"skip_first_waiting": True}
        order = _resolve_order(identity, m.group(1))
        if not order:
            _answer_then_followup(
                thread,
                "لم نجد هذا الطلب أو أنه غير مرتبط برقم الجوال/الحساب الحالي. "
                f"راجع رقم الطلب. {HINT_WRITE_TO_TEAM}",
            )
            _clear_subflow(request)
            return {"skip_first_waiting": True}
        allowed, reason = can_edit_contact_info(order)
        if not allowed:
            _send_staff_waiting_message(thread)
            if reason:
                _create_bot(thread, reason, None)
            _clear_subflow(request)
            return {"skip_first_waiting": True}
        _show_order_edit_menu(
            thread,
            order,
            request,
            include_other_order=not is_guest,
        )
        return {"skip_first_waiting": True}

    order = _get_ctx_order(identity, ctx)
    if not order:
        _answer_then_followup(
            thread,
            "تعذّر تحميل بيانات الطلب للتعديل. ابدأ من «تعديل بيانات الطلب» مرة أخرى.",
        )
        _clear_subflow(request)
        return {"skip_first_waiting": True}
    # تحديث من القاعدة بعد تعديلات سابقة
    order.refresh_from_db()

    # —— اختيار حقل (اسم / جوال / عنوان / طلب آخر) ——
    if sub_expect == "field_choice":
        if text == OTHER_ORDER_ID and not is_guest:
            _create_bot(
                thread,
                f"اكتب **رقم الطلب** الذي تريد تعديل بياناته (مرتبط بحسابك فقط).\n{BACK_HOME} للخروج.",
                [{"id": "backh", "label": BACK_HOME}] + list(QR_ROOT),
            )
            _set_ctx(
                request,
                {
                    "expect": "edit_order_id",
                    "subflow": "edit_order",
                    "order_id": None,
                },
            )
            return {"skip_first_waiting": True}
        if text == EDIT_NAME:
            _create_bot(
                thread,
                f"اكتب **الاسم الجديد** كاملاً في رسالة واحدة.\n" f"أو {BACK_HOME}.",
                [{"id": "backh", "label": BACK_HOME}] + list(QR_ROOT),
            )
            _merge_ctx(request, {"expect": "edit_name_value"})
            return {"skip_first_waiting": True}
        if text == EDIT_PHONE:
            _create_bot(
                thread,
                f"اكتب **رقم الجوال الجديد** (مثال: 05xxxxxxxx).\n" f"أو {BACK_HOME}.",
                [{"id": "backh", "label": BACK_HOME}] + list(QR_ROOT),
            )
            _merge_ctx(request, {"expect": "edit_phone_value"})
            return {"skip_first_waiting": True}
        if text == EDIT_ADDRESS:
            _set_ctx(
                request,
                {
                    "subflow": "edit_order",
                    "expect": "edit_address_step",
                    "order_id": order.id,
                    "edit_addr_idx": 0,
                    "edit_addr_data": {},
                },
            )
            _label, prompt, _req = ADDRESS_STEPS[0]
            _create_bot(
                thread,
                "سنأخذ عنوان التوصيل في أربع خطوات (البلد، المدينة، الحي، الشارع).\n\n" + prompt,
                [{"id": "backh", "label": BACK_HOME}] + list(QR_ROOT),
            )
            return {"skip_first_waiting": True}
        _create_bot(
            thread,
            "اختر أحد الخيارات أدناه باستخدام الأزرار السريعة.",
            [
                {"id": "en", "label": EDIT_NAME},
                {"id": "ep", "label": EDIT_PHONE},
                {"id": "ea", "label": EDIT_ADDRESS},
            ]
            + (
                [{"id": "eoth", "label": OTHER_ORDER_ID}]
                if not is_guest
                else []
            )
            + [{"id": "backh", "label": BACK_HOME}],
        )
        return {"skip_first_waiting": True}

    if sub_expect == "edit_name_value":
        name = (text or "").strip()
        if len(name) < 2:
            _create_bot(
                thread,
                "الاسم قصير جدًا. اكتب الاسم كاملًا (حرفان على الأقل) أو " f"{BACK_HOME}.",
                [{"id": "backh", "label": BACK_HOME}] + list(QR_ROOT),
            )
            return {"skip_first_waiting": True}
        try:
            apply_customer_name(order=order, new_name=name)
        except ValueError as e:
            _create_bot(
                thread,
                f"{e}\n{BACK_HOME} للخروج.",
                [{"id": "backh", "label": BACK_HOME}] + list(QR_ROOT),
            )
            return {"skip_first_waiting": True}
        order.refresh_from_db()
        _show_order_edit_menu(
            thread,
            order,
            request,
            include_other_order=not is_guest,
            prefix="تم حفظ الاسم الجديد بنجاح.",
        )
        return {"skip_first_waiting": True}

    if sub_expect == "edit_phone_value":
        ph = normalize_phone(text)
        if not ph or len(ph) < 9:
            _create_bot(
                thread,
                "رقم الجوال غير واضح. جرّب مثل 05xxxxxxxx أو 9665xxxxxxxx. أو " f"{BACK_HOME}.",
                [{"id": "backh", "label": BACK_HOME}] + list(QR_ROOT),
            )
            return {"skip_first_waiting": True}
        if len(ph) > 20:
            ph = ph[:20]
        try:
            apply_customer_phone(order=order, new_phone=ph)
        except ValueError as e:
            _create_bot(
                thread,
                f"{e}\n{BACK_HOME}.",
                [{"id": "backh", "label": BACK_HOME}] + list(QR_ROOT),
            )
            return {"skip_first_waiting": True}
        order.refresh_from_db()
        phone_prefix = "تم حفظ رقم الجوال الجديد."
        if is_guest:
            phone_prefix = phone_prefix + GUEST_NEW_CHAT_PHONE_HINT
        _show_order_edit_menu(
            thread,
            order,
            request,
            include_other_order=not is_guest,
            prefix=phone_prefix,
        )
        return {"skip_first_waiting": True}

    if sub_expect == "edit_address_step":
        idx = int(ctx.get("edit_addr_idx") or 0)
        data: dict = dict(ctx.get("edit_addr_data") or {})
        if idx < 0 or idx >= len(ADDRESS_STEPS):
            _clear_subflow(request)
            return None
        _key, _label, required = ADDRESS_STEPS[idx]
        t = (text or "").strip()
        if required and (not t or t in {"-", "—"}):
            _create_bot(
                thread,
                "هذا الحقل إلزامي (*). يرجى إدخال قيمة واضحة.",
                [{"id": "backh", "label": BACK_HOME}] + list(QR_ROOT),
            )
            return {"skip_first_waiting": True}
        if not required and t in ("", "-", "—", "تخطي", "تخطي."):
            t = ""
        if not (not required and not t):
            data[_key] = t
        next_idx = idx + 1
        if next_idx < len(ADDRESS_STEPS):
            _merge_ctx(
                request,
                {
                    "edit_addr_idx": next_idx,
                    "edit_addr_data": data,
                    "expect": "edit_address_step",
                },
            )
            _nlabel, nprompt, _nr = ADDRESS_STEPS[next_idx]
            _create_bot(
                thread,
                nprompt,
                [{"id": "backh", "label": BACK_HOME}] + list(QR_ROOT),
            )
            return {"skip_first_waiting": True}
        try:
            address_text = build_address_text(
                {k: str(v) for k, v in data.items() if v is not None}
            )
        except ValueError as e:
            _create_bot(
                thread,
                f"{e}\nأعد من «تعديل العنوان».",
                [
                    {"id": "en", "label": EDIT_NAME},
                    {"id": "ep", "label": EDIT_PHONE},
                    {"id": "ea", "label": EDIT_ADDRESS},
                    {"id": "backh", "label": BACK_HOME},
                ],
            )
            return {"skip_first_waiting": True}
        try:
            apply_delivery_address(order=order, address_text=address_text)
        except ValueError as e:
            _create_bot(
                thread,
                str(e),
                [{"id": "backh", "label": BACK_HOME}] + list(QR_ROOT),
            )
            return {"skip_first_waiting": True}
        order.refresh_from_db()
        _show_order_edit_menu(
            thread,
            order,
            request,
            include_other_order=not is_guest,
            prefix="تم حفظ العنوان الجديد.",
        )
        return {"skip_first_waiting": True}

    return None


def _answer_then_followup(thread: SupportThread, answer_text: str) -> None:
    """إجابة المساعد + سؤال المتابعة وأزرارها داخل فقاعة واحدة."""
    body = f"{(answer_text or '').rstrip()}\n\n{FOLLOWUP_TEXT}"
    _create_bot(thread, body, QR_FOLLOWUP)


def _send_staff_waiting_message(thread: SupportThread) -> None:
    """رسالة الانتظار الكاملة (نظام) — كما تُعرض عند أول رسالة غير آليّة."""
    SupportMessage.objects.create(
        thread=thread,
        sender_type=SupportMessage.SENDER_SYSTEM,
        text=SUPPORT_AUTO_WAITING_REPLY,
        image=None,
        metadata={},
    )


def should_send_auto_waiting_reply(thread: SupportThread, *, skip_first_waiting: bool) -> bool:
    """أول رسالة عميل في جولة انتظار الموظف دون رد انتظار سابق في نفس الجولة."""
    if skip_first_waiting or thread.status == SupportThread.STATUS_ENDED:
        return False

    customers = SupportMessage.objects.filter(
        thread=thread,
        sender_type=SupportMessage.SENDER_CUSTOMER,
    )
    if thread.last_staff_message_at:
        customers = customers.filter(created_at__gt=thread.last_staff_message_at)

    first_in_episode = customers.order_by('created_at').first()
    if not first_in_episode:
        return False
    if customers.exclude(pk=first_in_episode.pk).exists():
        return False

    return not SupportMessage.objects.filter(
        thread=thread,
        sender_type=SupportMessage.SENDER_SYSTEM,
        text=SUPPORT_AUTO_WAITING_REPLY,
        created_at__gte=first_in_episode.created_at,
    ).exists()


def end_thread_by_customer(thread: SupportThread) -> bool:
    """إغلاق المحادثة من الطلب/الواجهة (نص نظامي غير مُعرّف كبوت)."""
    if thread.status == SupportThread.STATUS_ENDED:
        return False
    now = timezone.now()
    SupportMessage.objects.create(
        thread=thread,
        sender_type=SupportMessage.SENDER_SYSTEM,
        text="تم إنهاء الدردشة بناءً على طلبك. يمكنك بدء محادثة جديدة في أي وقت.",
    )
    thread.status = SupportThread.STATUS_ENDED
    thread.ended_at = now
    thread.ended_by_type = "customer"
    thread.warning_sent_at = None
    thread.updated_at = now
    thread.save(update_fields=["status", "ended_at", "ended_by_type", "warning_sent_at", "updated_at"])
    return True


def _create_bot(
    thread: SupportThread,
    text: str,
    quick_replies: list[dict[str, str]] | None = None,
) -> None:
    meta = {"kind": BOT_KIND, "quick_replies": quick_replies or []}
    SupportMessage.objects.create(
        thread=thread,
        sender_type=SupportMessage.SENDER_SYSTEM,
        text=text,
        image=None,
        metadata=meta,
    )


def ensure_bot_welcome_for_thread(thread: SupportThread) -> None:
    """رسالة ترحيب + أزرار عند بدء محادثة جديدة بدون رسائل."""
    if SupportMessage.objects.filter(thread=thread).exists():
        return
    _create_bot(thread, WELCOME_TEXT, QR_ROOT)


def welcome_messages_for_client() -> list[dict[str, Any]]:
    """ترحيب الشات بوت للعميل قبل إنشاء محادثة في قاعدة البيانات."""
    return [{
        'id': 0,
        'sender_type': 'system',
        'is_bot': True,
        'text': WELCOME_TEXT,
        'image_url': '',
        'quick_replies': list(QR_ROOT),
        'created_at': '',
    }]


def _resolve_order(identity, raw: str) -> Order | None:
    s = (raw or "").strip()
    s = s.lstrip("#").strip()
    if not s.isdigit():
        return None
    oid = int(s)
    qs = Order.objects.filter(pk=oid)
    if identity.get("customer_user"):
        return qs.filter(user_id=identity["customer_user"].id).first()
    phone = normalize_phone(identity.get("guest_phone") or "")
    if not phone:
        return None
    return (
        qs.filter(
            Q(customer_phone=phone)
            | Q(customer_phone__icontains=phone)
        )
        .first()
    )


def _last_order(identity) -> Order | None:
    if identity.get("customer_user"):
        return (
            Order.objects.filter(user_id=identity["customer_user"].id)
            .order_by("-id")
            .first()
        )
    phone = normalize_phone(identity.get("guest_phone") or "")
    if not phone:
        return None
    return (
        Order.objects.filter(
            Q(customer_phone=phone)
            | Q(customer_phone__icontains=phone)
        )
        .order_by("-id")
        .first()
    )


def _order_summary(order: Order) -> str:
    parts = [f"رقم الطلب: #{order.id}", f"الحالة: {order.get_status_display()}"]
    if getattr(order, "payment_status", None):
        parts.append(f"الدفع: {order.get_payment_status_display()}")
    try:
        sh = order.shipment
        if sh and (sh.tracking_number or "").strip():
            parts.append(f"رقم التتبع: {sh.tracking_number}")
    except Exception:
        pass
    return "\n".join(parts)


def _is_escalation(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return bool(ESCALATION_RE.search(t))


def _wants_live_staff(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if bool(HUMAN_INTENT_RE.search(t)):
        return True
    n = _normalize_arabic_intent(t)
    return _fuzzy_wants_live_staff(n)


def _static_returns() -> str:
    return (
        "الإرجاع والاستبدال:\n"
        "• تقدر تبدأ طلب إرجاع من صفحة طلباتك لأي طلب مؤهّل.\n"
        "• يجب أن يكون المنتج بحالته الأصلية وضمن فترة الإرجاع المعتمدة.\n"
        "• تفاصيل الاسترداد تختلف حسب طريقة الدفع (قد يتأخر الظهور في الحساب حسب البنك).\n"
        f"للمساعدة اليدوية: {HINT_WRITE_TO_TEAM}"
    )


def _static_pay() -> str:
    return (
        "الدفع:\n"
        "• جرّب إعادة عملية الدفع، وتأكد من بيانات البطاقة والرصيد.\n"
        "• الدفع عند الاستلام قد يكون متاحًا حسب منطقتك (يظهر لك عند إتمام الطلب).\n"
        f"للمساعدة اليدوية في الدفع/الاسترداد: {HINT_WRITE_TO_TEAM}"
    )


def _static_ship() -> str:
    return (
        "الشحن والتوصيل:\n"
        "• تختلف المدة حسب المدينة (غالبًا بضعة أيام عمل عدا الجمعة/العطل).\n"
        "• رسوم التوصيل تظهر قبل تأكيد الدفع.\n"
        f"لتتبع آخر: من «{QR_ROOT[0]['label']}»."
    )


def _static_coupon() -> str:
    return (
        "الكوبونات:\n"
        "• أدخل الكود في خانة الكوبون قبل الدفع.\n"
        "• قد يكون الكوبون غير مفعّل للمنتجات المختارة أو منتهي الصلاحية.\n"
        f"للمراجعة: {HINT_WRITE_TO_TEAM}"
    )


def process_support_bot_turn(request, thread: SupportThread, identity) -> dict[str, Any]:
    """
    يعالج آخر رسالة عميل (يجب أن تكون محفوظة مسبقًا).
    يعيد: skip_first_waiting لعدم إرسال رسالة الانتظار التلقائية عند الرسالة الأولى
    عند اختيار مسار البوت.
    """
    last = (
        SupportMessage.objects.filter(
            thread=thread,
            sender_type=SupportMessage.SENDER_CUSTOMER,
        )
        .order_by("-id")
        .first()
    )
    if not last or not (last.text or "").strip() or last.image:
        return {"skip_first_waiting": False}

    text = (last.text or "").strip()
    ctx = _get_ctx(request)

    # بانتظار رقم طلب (تتبع) — قبل الرجوع/المتابعة حتى يُعالج رقم الطلب أولاً
    if ctx.get("expect") == "order_id" and ctx.get("subflow") == "track":
        if _is_escalation(text) or _wants_live_staff(text):
            _send_staff_waiting_message(thread)
            _set_ctx(request, {"expect": None, "subflow": None})
            return {"skip_first_waiting": True}
        if text == LAST_ORDER:
            order = _last_order(identity)
        else:
            m = re.search(r"(\d+)", text)
            order = _resolve_order(identity, m.group(1)) if m else None
        if order:
            _answer_then_followup(
                thread,
                f"معلومات طلبك:\n{_order_summary(order)}",
            )
        else:
            _answer_then_followup(
                thread,
                "لم نتمكّن من إيجاد الطلب أو ليس مرتبطًا بهذا الحساب/الجوال. "
                f"تأكد من الرقم، أو {HINT_WRITE_TO_TEAM}",
            )
        _set_ctx(request, {"expect": None, "subflow": None})
        return {"skip_first_waiting": True}

    edit_h = _process_order_edit_subflow(request, thread, identity, text)
    if edit_h is not None:
        return edit_h

    if text == LABEL_END:
        end_thread_by_customer(thread)
        _set_ctx(request, {"expect": None, "subflow": None})
        return {"skip_first_waiting": True}

    if text in (LABEL_MORE, BACK_HOME):
        _create_bot(thread, WELCOME_TEXT, QR_ROOT)
        _set_ctx(request, {"expect": None, "subflow": None})
        return {"skip_first_waiting": True}

    if _is_escalation(text) or _wants_live_staff(text):
        _send_staff_waiting_message(thread)
        _set_ctx(request, {"expect": None, "subflow": None})
        return {"skip_first_waiting": True}

    if text == QR_ROOT[0]["label"]:  # تتبع الطلب
        _create_bot(
            thread,
            f"لتتبع الطلب: اكتب رقم الطلب (مثل 12) أو اختر {LAST_ORDER}.\n"
            f"للعودة: {BACK_HOME}.",
            [{"id": "last", "label": LAST_ORDER}, {"id": "backh", "label": BACK_HOME}] + list(QR_ROOT),
        )
        _set_ctx(request, {"expect": "order_id", "subflow": "track"})
        return {"skip_first_waiting": True}

    if text == QR_ROOT[1]["label"]:
        return _start_order_edit_flow(request, thread, identity)

    if text == QR_ROOT[2]["label"]:
        _answer_then_followup(thread, _static_returns())
        _set_ctx(request, {"expect": None, "subflow": None})
        return {"skip_first_waiting": True}

    if text == QR_ROOT[3]["label"]:
        _answer_then_followup(thread, _static_pay())
        _set_ctx(request, {"expect": None, "subflow": None})
        return {"skip_first_waiting": True}

    if text == QR_ROOT[4]["label"]:
        _answer_then_followup(thread, _static_ship())
        _set_ctx(request, {"expect": None, "subflow": None})
        return {"skip_first_waiting": True}

    if text == QR_ROOT[5]["label"]:
        _answer_then_followup(thread, _static_coupon())
        _set_ctx(request, {"expect": None, "subflow": None})
        return {"skip_first_waiting": True}

    if text == LAST_ORDER:
        order = _last_order(identity)
        if order:
            _answer_then_followup(
                thread,
                f"آخر طلب لك:\n{_order_summary(order)}",
            )
        else:
            _answer_then_followup(
                thread,
                f"لا يوجد طلب سابق مرتبط بهذا الحساب/الرقم. اكتب رقم طلب صريح. {HINT_WRITE_TO_TEAM}",
            )
        _set_ctx(request, {"expect": None, "subflow": None})
        return {"skip_first_waiting": True}

    return {"skip_first_waiting": False}
