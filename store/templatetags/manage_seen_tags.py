from django import template

register = template.Library()


@register.simple_tag
def manage_is_new(user, obj, kind):
    from ..manage_seen_utils import should_show_new_flag

    return should_show_new_flag(user, obj, kind)


@register.simple_tag
def manage_row_state(user, obj, kind):
    from ..manage_seen_utils import get_row_alert_state

    return get_row_alert_state(user, obj, kind)
