from django.test import TestCase, override_settings
from django.urls import reverse

from market.models import Category, User
from market.services import register_user


@override_settings(DEBUG=False, ALLOWED_HOSTS=["testserver"])
class UserErrorPageTests(TestCase):
    def test_missing_url_and_django_admin_are_safe_404_pages(self):
        response = self.client.get("/missing-page/")
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "페이지를 찾을 수 없습니다", status_code=404)
        self.assertNotContains(response, "URLconf", status_code=404)
        self.assertEqual(self.client.get("/admin/").status_code, 404)

    def test_logout_redirects_to_public_login(self):
        user = register_user(username="logoutuser", password="very-secure-password", display_name="Logout")
        self.client.force_login(user)
        response = self.client.post(reverse("logout"))
        self.assertRedirects(response, reverse("login"))

    def test_category_free_product_form_explains_the_problem(self):
        user = register_user(username="categoryfree", password="very-secure-password", display_name="Category")
        self.client.force_login(user)
        response = self.client.get(reverse("product_create"))
        self.assertContains(response, "등록 가능한 카테고리가 없습니다")
