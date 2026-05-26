import re

from django import template
from django.utils.html import escape, format_html
from django.utils.safestring import mark_safe

register = template.Library()

_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{3,8}$")


@register.filter(name='highlight_term', needs_autoescape=True)
def highlight_term(value, term, autoescape=True):
    """يُبرز أول ظهور لكل جزء متطابق (بدون حساسية لحالة الأحرف) ضمن نص مُحمّى."""
    if value is None:
        return ''
    text = escape(str(value))
    term_clean = escape(str(term or '').strip())
    if not term_clean:
        return mark_safe(text)
    pattern = re.compile(re.escape(term_clean), re.IGNORECASE)

    def repl(match):
        return '<mark class="search-hit">{0}</mark>'.format(match.group(0))

    return mark_safe(pattern.sub(repl, text))


@register.filter
def variant_swatch_style_attr(color_hex):
    """يُرجع سمة style=\"background-color: …\" آمنة؛ فارغ إذا لم يكن لوناً hex صالحاً."""
    if not color_hex:
        return ""
    s = str(color_hex).strip()
    if not _HEX_COLOR.match(s):
        return ""
    return format_html('style="background-color: {}"', s)
