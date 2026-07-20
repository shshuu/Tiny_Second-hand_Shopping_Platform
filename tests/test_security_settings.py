from django.test import Client, TestCase, override_settings
from django.urls import clear_url_caches
from django.urls import reverse

from market.models import AuditLog, Category, Product, User
from market.services import register_user


class SecurityResponseTests(TestCase):
    def test_public_and_operations_responses_have_restrictive_headers(self):
        response=self.client.get("/")
        csp=response["Content-Security-Policy"]
        self.assertIn("default-src 'self'",csp); self.assertIn("object-src 'none'",csp)
        self.assertIn("form-action 'self'",csp); self.assertIn("frame-ancestors 'none'",csp)
        self.assertIn("connect-src 'self'",csp); self.assertNotIn("wss:",csp); self.assertNotIn("unsafe-eval",csp)
        self.assertEqual(response["X-Content-Type-Options"],"nosniff")
        self.assertEqual(response["X-Frame-Options"],"DENY")
        self.assertIn("same-origin",response["Referrer-Policy"])
        self.assertIn("geolocation=()",response["Permissions-Policy"])

    @override_settings(ALLOWED_HOSTS=["allowed.example"])
    def test_host_allowlist_rejects_suffix_and_similar_domains(self):
        self.assertEqual(self.client.get("/",HTTP_HOST="allowed.example").status_code,200)
        self.assertEqual(self.client.get("/",HTTP_HOST="allowed.example:443").status_code,200)
        for host in ("untrusted.example","allowed.example.evil.test","allowed-example.test","bad host"):
            response=self.client.get("/",HTTP_HOST=host)
            self.assertEqual(response.status_code,400)
            self.assertNotIn("SECRET_KEY",response.content.decode())

    @override_settings(SESSION_COOKIE_SECURE=True,CSRF_COOKIE_SECURE=True,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE="Lax")
    def test_secure_cookie_policy_is_configured(self):
        self.client.get("/login/")
        self.assertTrue(self.client.cookies.get("csrftoken").get("secure"))

    @override_settings(SECURE_SSL_REDIRECT=True,SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO","https"),SECURE_HSTS_SECONDS=31536000,SECURE_HSTS_INCLUDE_SUBDOMAINS=True,SECURE_HSTS_PRELOAD=True,ALLOWED_HOSTS=["allowed.example"])
    def test_https_redirect_proxy_hsts_and_headers(self):
        http=self.client.get("/",HTTP_HOST="allowed.example",secure=False)
        self.assertEqual(http.status_code,301); self.assertTrue(http["Location"].startswith("https://allowed.example"))
        https=self.client.get("/",HTTP_HOST="allowed.example",HTTP_X_FORWARDED_PROTO="https",secure=False)
        self.assertEqual(https.status_code,200); self.assertIn("max-age=31536000",https["Strict-Transport-Security"])
        self.assertIn("includeSubDomains",https["Strict-Transport-Security"]); self.assertIn("preload",https["Strict-Transport-Security"])

    def test_debug_false_does_not_register_media_pattern(self):
        import importlib
        from config import urls
        with override_settings(DEBUG=False):
            clear_url_caches()
            production_urls=importlib.reload(urls)
            self.assertFalse(any(str(pattern.pattern).startswith("media/") for pattern in production_urls.urlpatterns))
        clear_url_caches()
        importlib.reload(urls)


class CsrfOriginTests(TestCase):
    def setUp(self):
        self.moderator=register_user(username="csrf_mod",password="very-secure-password",display_name="Moderator")
        self.moderator.role=User.Role.MODERATOR; self.moderator.save(update_fields=["role"])
        self.seller=register_user(username="csrf_seller",password="very-secure-password",display_name="Seller")
        category=Category.objects.create(name="CSRF",slug="csrf")
        self.product=Product.objects.create(seller=self.seller,category=category,title="CSRF product",description="x",price=1,condition="USED",status=Product.Status.ACTIVE)

    def _client_with_token(self):
        client=Client(enforce_csrf_checks=True)
        client.force_login(self.moderator)
        client.get("/login/",HTTP_HOST="allowed.example")
        return client, client.cookies["csrftoken"].value

    @override_settings(ALLOWED_HOSTS=["allowed.example"],CSRF_TRUSTED_ORIGINS=["https://allowed.example"])
    def test_csrf_origin_and_token_control_product_action_without_audit_side_effects(self):
        url=reverse("ops_product_action",args=[self.product.public_id])
        client, token=self._client_with_token()
        success=client.post(url,{"status":Product.Status.HIDDEN,"reason":"policy"},HTTP_HOST="allowed.example",HTTP_ORIGIN="https://allowed.example",HTTP_X_CSRFTOKEN=token,secure=True)
        self.assertEqual(success.status_code,302)
        self.product.refresh_from_db(); self.assertEqual(self.product.status,Product.Status.HIDDEN)

        for origin, supplied_token in (("https://allowed.example",None),("https://evil.example",token),("http://allowed.example",token),("https://allowed.example.evil.test",token)):
            product=Product.objects.create(seller=self.seller,category=self.product.category,title=f"Blocked {origin}",description="x",price=1,condition="USED",status=Product.Status.ACTIVE)
            before=AuditLog.objects.filter(action="product.moderate",target=str(product.public_id)).count()
            headers={"HTTP_HOST":"allowed.example","HTTP_ORIGIN":origin}
            if supplied_token:
                headers["HTTP_X_CSRFTOKEN"]=supplied_token
            response=client.post(reverse("ops_product_action",args=[product.public_id]),{"status":Product.Status.HIDDEN,"reason":"policy"},secure=True,**headers)
            self.assertEqual(response.status_code,403)
            self.assertNotIn("SECRET_KEY",response.content.decode())
            product.refresh_from_db(); self.assertEqual(product.status,Product.Status.ACTIVE)
            self.assertEqual(AuditLog.objects.filter(action="product.moderate",target=str(product.public_id)).count(),before)
