import importlib
from pathlib import Path
from tempfile import TemporaryDirectory

from django.contrib.staticfiles import finders
from django.test import TestCase, override_settings
from django.urls import clear_url_caches, set_urlconf

from market.models import Category, Product
from market.services import register_user


class LocalMediaAndStatusTests(TestCase):
    def setUp(self):
        self.owner=register_user(username="mediaowner",password="very-secure-password",display_name="Owner")
        self.other=register_user(username="mediaother",password="very-secure-password",display_name="Other")
        self.category=Category.objects.create(name="Media",slug="media")
        self.product=Product.objects.create(seller=self.owner,category=self.category,title="Status",description="x",price=1,condition="USED",status=Product.Status.SOLD)

    def _reload_urls(self):
        import config.urls
        clear_url_caches(); set_urlconf(None)
        return importlib.reload(config.urls)

    def test_sold_and_reserved_are_public_but_hidden_states_are_not(self):
        for status in (Product.Status.SOLD, Product.Status.RESERVED):
            self.product.status=status; self.product.save(update_fields=["status"])
            self.assertEqual(self.client.get(f"/products/{self.product.public_id}/").status_code,200)
        for status in (Product.Status.HIDDEN,Product.Status.DELETED,Product.Status.DRAFT):
            self.product.status=status; self.product.save(update_fields=["status"])
            self.assertEqual(self.client.get(f"/products/{self.product.public_id}/").status_code,404)

    def test_local_demo_media_serves_image_and_blocks_traversal(self):
        with TemporaryDirectory() as media_root:
            image_path=Path(media_root, "products", "pixel.png")
            image_path.parent.mkdir(parents=True)
            image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
            with override_settings(DEBUG=False, SERVE_MEDIA_LOCALLY=True, MEDIA_ROOT=media_root):
                self._reload_urls()
                response=self.client.get("/media/products/pixel.png")
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response["Content-Type"].startswith("image/png"))
                for path in ("/media/../manage.py", "/media/%2e%2e/manage.py"):
                    blocked=self.client.get(path)
                    self.assertNotEqual(blocked.status_code, 200)
                    self.assertNotIn(b"django", b"".join(blocked.streaming_content) if getattr(blocked,"streaming",False) else blocked.content.lower())
            self._reload_urls()

    def test_production_media_route_is_not_registered(self):
        with override_settings(DEBUG=False, SERVE_MEDIA_LOCALLY=False):
            self._reload_urls()
            self.assertEqual(self.client.get("/media/missing.jpg").status_code,404)
        self._reload_urls()

    def test_csp_uses_external_scripts_and_static_assets_exist(self):
        response=self.client.get("/")
        self.assertIn("script-src 'self'", response["Content-Security-Policy"])
        for path in ("market/js/chat_room.js", "market/js/unread_badge.js", "market/js/product_image_selection.js"):
            self.assertTrue(finders.find(path), path)
        static_response=self.client.get("/static/market/js/chat_room.js")
        self.assertEqual(static_response.status_code, 200)
        self.assertIn("javascript", static_response["Content-Type"])
        for name in ("base.html", "chat_room.html", "form.html"):
            template=Path(__file__).parents[1] / "market" / "templates" / "market" / name
            content=template.read_text(encoding="utf-8")
            self.assertNotRegex(content, r"<script(?![^>]*\bsrc=)[^>]*>")

    def test_default_product_create_is_active_and_draft_is_explicit(self):
        self.client.force_login(self.owner)
        base={"category":self.category.pk,"title":"Default active","description":"x","price":1,"condition":"USED","start_selling":"on"}
        self.assertEqual(self.client.post("/products/new/",base).status_code,302)
        self.assertEqual(Product.objects.get(title="Default active").status,Product.Status.ACTIVE)
        base.update({"title":"Explicit draft","start_selling":""})
        self.assertEqual(self.client.post("/products/new/",base).status_code,302)
        self.assertEqual(Product.objects.get(title="Explicit draft").status,Product.Status.DRAFT)
