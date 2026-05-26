"""واجهة المتجر — تجميع من الوحدات الفرعية للتوافق مع store.urls."""
from .views_storefront import *  # noqa: F401,F403
from .views_support import (
    support_chat,
    support_end,
    support_new_conversation,
    support_poll,
    support_send,
)
from .views_webhooks import fake_gateway_webhook, fake_shipping_webhook
