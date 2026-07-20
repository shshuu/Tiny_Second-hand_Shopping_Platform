import time
from unittest.mock import patch

from django.core.cache import cache
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse
from redis.exceptions import RedisError

from market.models import Profile, SecurityEvent, User, Wallet, WalletTransaction
from market.services import register_user
from market.views import _login_rate_keys, _rate_key


@override_settings(
    SIGNUP_RATE_LIMIT=1,
    SIGNUP_RATE_LIMIT_WINDOW_SECONDS=1,
    LOGIN_FAILURE_RATE_LIMIT=1,
    LOGIN_FAILURE_IP_RATE_LIMIT=10,
    LOGIN_FAILURE_RATE_LIMIT_WINDOW_SECONDS=1,
)
class PublicAuthenticationRateLimitTests(TransactionTestCase):
    def setUp(self):
        cache.clear()
        self.signup_url=reverse("signup")
        self.login_url=reverse("login")
        self.user=register_user(username="rate_login_user", password="very-secure-password", display_name="Rate Login")

    def tearDown(self):
        cache.clear()

    def _signup(self, username, ip):
        return self.client.post(self.signup_url, {"username":username, "display_name":"New User", "password1":"very-secure-password", "password2":"very-secure-password"}, REMOTE_ADDR=ip)

    def _login(self, username, password, ip, client=None):
        return (client or self.client).post(self.login_url, {"username":username, "password":password}, REMOTE_ADDR=ip)

    def test_signup_post_limit_is_hashed_per_ip_preserves_db_and_get_is_free(self):
        ip="198.51.100.10"; key=_rate_key("signup-ip", ip)
        self.assertEqual(self.client.get(self.signup_url, REMOTE_ADDR=ip).status_code, 200)
        self.assertIsNone(cache.get(key))
        before=(User.objects.count(), Profile.objects.count(), Wallet.objects.count(), WalletTransaction.objects.count())
        self.assertEqual(self._signup("signup_one", ip).status_code, 302)
        self.assertEqual(self._signup("signup_blocked", ip).status_code, 429)
        self.assertEqual((User.objects.count(), Profile.objects.count(), Wallet.objects.count(), WalletTransaction.objects.count()), tuple(value + increment for value, increment in zip(before, (1, 1, 1, 0))))
        self.assertNotIn(ip, key)
        self.assertEqual(self._signup("signup_other_ip", "198.51.100.11").status_code, 302)

    def test_signup_real_redis_ttl_and_backend_failure_are_fail_closed(self):
        ip="198.51.100.12"; key=_rate_key("signup-ip", ip)
        self.assertEqual(self._signup("signup_ttl_one", ip).status_code, 302)
        self.assertGreater(cache._cache.get_client(write=True).ttl(cache.make_key(key)), 0)
        self.assertEqual(self._signup("signup_ttl_blocked", ip).status_code, 429)
        time.sleep(1.1)
        self.assertEqual(self._signup("signup_ttl_after", ip).status_code, 302)
        before=User.objects.count()
        with patch("market.views.cache.add", side_effect=RedisError("offline")):
            response=self._signup("signup_backend_blocked", "198.51.100.13")
        self.assertEqual(response.status_code, 429); self.assertEqual(User.objects.count(), before)
        event=SecurityEvent.objects.filter(event_type="SIGNUP_RATE_LIMIT_BACKEND_ERROR").latest("created_at")
        self.assertNotIn("198.51.100.13", event.detail); self.assertNotIn("signup_backend_blocked", event.detail)

    def test_login_failure_limit_is_generic_hashed_and_success_clears(self):
        ip="203.0.113.10"; account_key, ip_key=_login_rate_keys(type("Request", (), {"POST":{"username":self.user.username}, "META":{"REMOTE_ADDR":ip}})())
        first=self._login(self.user.username, "wrong-password", ip)
        self.assertEqual(first.status_code, 200)
        blocked=self._login(self.user.username, "wrong-password", ip)
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(self._login(self.user.username, "very-secure-password", ip).status_code, 429)
        self.assertNotIn(self.user.username, account_key); self.assertNotIn(ip, account_key); self.assertNotIn(ip, ip_key)

        other_ip="203.0.113.11"
        unknown_first=self._login("does_not_exist", "wrong-password", other_ip)
        known_first=self._login(self.user.username, "wrong-password", "203.0.113.12")
        self.assertEqual(unknown_first.status_code, known_first.status_code)
        self.assertIn("Request cannot be processed", unknown_first.content.decode())
        with override_settings(LOGIN_FAILURE_RATE_LIMIT=2):
            success_client=Client()
            self.assertEqual(self._login(self.user.username, "wrong-password", "203.0.113.13", success_client).status_code, 200)
            self.assertEqual(self._login(self.user.username, "very-secure-password", "203.0.113.13", success_client).status_code, 302)
            success_client.logout()
            self.assertEqual(self._login(self.user.username, "wrong-password", "203.0.113.13", success_client).status_code, 200)

    def test_login_real_ttl_get_free_and_backend_failure_fail_closed(self):
        ip="203.0.113.20"; account_key, _= _login_rate_keys(type("Request", (), {"POST":{"username":self.user.username}, "META":{"REMOTE_ADDR":ip}})())
        self.assertEqual(self.client.get(self.login_url, REMOTE_ADDR=ip).status_code, 200)
        self.assertIsNone(cache.get(account_key))
        self.assertEqual(self._login(self.user.username, "wrong-password", ip).status_code, 200)
        self.assertGreater(cache._cache.get_client(write=True).ttl(cache.make_key(account_key)), 0)
        self.assertEqual(self._login(self.user.username, "wrong-password", ip).status_code, 429)
        time.sleep(1.1)
        self.assertEqual(self._login(self.user.username, "very-secure-password", ip).status_code, 302)
        with patch("market.views.cache.get", side_effect=RedisError("offline")):
            response=self._login(self.user.username, "very-secure-password", "203.0.113.21")
        self.assertEqual(response.status_code, 429)
        event=SecurityEvent.objects.filter(event_type="PUBLIC_RATE_LIMIT_BACKEND_ERROR").latest("created_at")
        self.assertNotIn(self.user.username, event.detail); self.assertNotIn("203.0.113.21", event.detail)
