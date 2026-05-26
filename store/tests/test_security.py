"""اختبارات أساسية لخدمات الأمان."""
from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from store.security_services import (
    clear_login_failure,
    is_login_locked,
    record_login_failure,
    turnstile_configured,
)


class LoginRateLimitTests(TestCase):
    def setUp(self):
        cache.clear()
        self.client = Client()

    def tearDown(self):
        cache.clear()

    @override_settings(LOGIN_FAILURE_MAX=2, LOGIN_FAILURE_LOCK_SECONDS=60, LOGIN_FAILURE_WINDOW_SEC=3600)
    def test_lock_after_failures(self):
        portal = 'store'
        from django.test import RequestFactory

        rf = RequestFactory()
        req = rf.post('/login/')
        req.META['REMOTE_ADDR'] = '203.0.113.50'

        self.assertFalse(is_login_locked(portal, req, 'tuser'))
        record_login_failure(portal, req, 'tuser')
        record_login_failure(portal, req, 'tuser')
        self.assertTrue(is_login_locked(portal, req, 'tuser'))

        clear_login_failure(portal, req, 'tuser')
        self.assertFalse(is_login_locked(portal, req, 'tuser'))


class TurnstileConfiguredTests(TestCase):
    @override_settings(TURNSTILE_SITE_KEY='', TURNSTILE_SECRET_KEY='')
    def test_not_configured_when_empty(self):
        self.assertFalse(turnstile_configured())

    @override_settings(TURNSTILE_SITE_KEY='x', TURNSTILE_SECRET_KEY='y')
    def test_configured_when_both_set(self):
        self.assertTrue(turnstile_configured())
