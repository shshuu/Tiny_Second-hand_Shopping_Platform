from django.test import TestCase, override_settings
import importlib
from market.models import Category, Product, User
from market.services import register_user

class LocalMediaAndStatusTests(TestCase):
    def setUp(self):
        self.owner=register_user(username="mediaowner",password="very-secure-password",display_name="Owner")
        self.other=register_user(username="mediaother",password="very-secure-password",display_name="Other")
        category=Category.objects.create(name="Media",slug="media")
        self.product=Product.objects.create(seller=self.owner,category=category,title="Status",description="x",price=1,condition="USED",status=Product.Status.SOLD)

    def test_sold_and_reserved_are_public_but_hidden_states_are_not(self):
        for status in (Product.Status.SOLD, Product.Status.RESERVED):
            self.product.status=status; self.product.save(update_fields=["status"])
            self.assertEqual(self.client.get(f"/products/{self.product.public_id}/").status_code,200)
        for status in (Product.Status.HIDDEN,Product.Status.DELETED,Product.Status.DRAFT):
            self.product.status=status; self.product.save(update_fields=["status"])
            self.assertEqual(self.client.get(f"/products/{self.product.public_id}/").status_code,404)

    @override_settings(DEBUG=False,SERVE_MEDIA_LOCALLY=True)
    def test_local_media_route_is_explicitly_registered_only_when_enabled(self):
        import config.urls
        urls=importlib.reload(config.urls)
        self.assertTrue(any("media/" in str(pattern.pattern) for pattern in urls.urlpatterns))

    @override_settings(DEBUG=False,SERVE_MEDIA_LOCALLY=False)
    def test_production_media_route_is_not_registered(self):
        self.assertEqual(self.client.get("/media/missing.jpg").status_code,404)
