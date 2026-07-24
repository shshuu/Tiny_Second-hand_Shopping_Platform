from io import BytesIO
from tempfile import TemporaryDirectory
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image
from market.models import Category, Product, User

def image_file():
    stream=BytesIO(); Image.new("RGB", (10, 10), "red").save(stream, "PNG")
    return SimpleUploadedFile("sample.png", stream.getvalue(), content_type="image/png")

class ProductSecurityTests(TestCase):
    def setUp(self):
        self.owner=User.objects.create_user(username="owner",password="very-secure-password",display_name="Owner")
        self.other=User.objects.create_user(username="other",password="very-secure-password",display_name="Other")
        self.category=Category.objects.create(name="전자기기",slug="electronics")
        self.product=Product.objects.create(seller=self.owner,category=self.category,title="상품",description="설명",price=100,condition="USED",status="ACTIVE")
    def test_other_user_cannot_edit_product(self):
        self.client.login(username="other",password="very-secure-password")
        response=self.client.post(reverse("product_edit",args=[self.product.public_id]), {"category":self.category.id,"title":"변조","description":"x","price":1,"condition":"USED","status":"ACTIVE"})
        self.assertEqual(response.status_code, 404)
        self.product.refresh_from_db(); self.assertEqual(self.product.title,"상품")
    def test_valid_image_is_accepted(self):
        self.client.login(username="owner",password="very-secure-password")
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            response=self.client.post(reverse("product_create"), {"category":self.category.id,"title":"새 상품","description":"설명","price":100,"condition":"USED","status":"ACTIVE","images":image_file()})
            self.assertEqual(response.status_code,302)
            self.assertEqual(Product.objects.get(title="새 상품").images.count(),1)
    def test_non_image_is_rejected(self):
        self.client.login(username="owner",password="very-secure-password")
        bad=SimpleUploadedFile("attack.svg",b"<svg/>",content_type="image/svg+xml")
        response=self.client.post(reverse("product_create"), {"category":self.category.id,"title":"악성","description":"설명","price":100,"condition":"USED","status":"ACTIVE","images":bad})
        self.assertEqual(response.status_code,200)
        self.assertFalse(Product.objects.filter(title="악성").exists())
