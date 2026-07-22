import os
import uuid
from io import BytesIO
from tempfile import TemporaryDirectory

from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from market.models import AuditLog, Category, ChatMessage, ChatRoom, LedgerEntry, Product, ProductImage, User, WalletTransaction
from market.services import register_user


def image_upload():
    content = BytesIO()
    Image.new("RGB", (12, 12), "blue").save(content, "PNG")
    return SimpleUploadedFile("product.png", content.getvalue(), content_type="image/png")


class FreshDataCommandsTests(TestCase):
    def test_seed_categories_is_idempotent_and_active(self):
        self.assertEqual(Category.objects.count(), 0)
        call_command("seed_categories")
        first = list(Category.objects.order_by("slug").values_list("name", "slug", "is_active"))
        call_command("seed_categories")
        self.assertEqual(list(Category.objects.order_by("slug").values_list("name", "slug", "is_active")), first)
        self.assertEqual(Category.objects.filter(is_active=True).count(), 6)

    def test_promote_and_list_operations_users(self):
        user = register_user(username="localoperator", password="very-secure-password", display_name="Operator")
        call_command("promote_user", user.username, "--role", "SUPERADMIN")
        user.refresh_from_db()
        self.assertEqual(user.role, User.Role.SUPERADMIN)
        self.assertTrue(AuditLog.objects.filter(action="user.role", target=str(user.public_id)).exists())


@override_settings(WELCOME_BONUS_ENABLED=True, WELCOME_BONUS_AMOUNT=100)
class UserFacingFlowTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="전자기기", slug="electronics")
        self.seller = register_user(username="sellerflow", password="very-secure-password", display_name="판매자")
        self.buyer = register_user(username="buyerflow", password="very-secure-password", display_name="구매자")
        self.product = Product.objects.create(seller=self.seller, category=self.category, title="한국어 상품", description="한국어 설명", price=100, condition="USED", status=Product.Status.ACTIVE)

    def test_signup_bonus_is_transaction_and_ledger_based(self):
        response = self.client.post(reverse("signup"), {"username":"newbonus", "display_name":"새 사용자", "password1":"very-secure-password", "password2":"very-secure-password"})
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="newbonus")
        self.assertEqual(user.wallet.balance, 100)
        tx = WalletTransaction.objects.get(destination=user.wallet, transaction_type=WalletTransaction.Type.WELCOME)
        self.assertEqual(tx.amount, 100)
        self.assertTrue(LedgerEntry.objects.filter(transaction=tx, wallet=user.wallet, entry_type="CREDIT").exists())

    @override_settings(WELCOME_BONUS_ENABLED=False)
    def test_signup_without_demo_bonus_keeps_wallet_at_zero(self):
        user = register_user(username="zerobonus", password="very-secure-password", display_name="Zero")
        self.assertEqual(user.wallet.balance, 0)
        self.assertFalse(WalletTransaction.objects.filter(destination=user.wallet, transaction_type=WalletTransaction.Type.WELCOME).exists())

    def test_wallet_legacy_get_and_post_cannot_execute_arbitrary_user_transfer(self):
        self.client.force_login(self.buyer)
        self.buyer.wallet.refresh_from_db()
        before = (WalletTransaction.objects.count(), LedgerEntry.objects.count(), self.buyer.wallet.balance)
        get_response = self.client.get(reverse("wallet"), {"recipient": self.seller.public_id, "amount": 1})
        self.assertEqual(get_response.status_code, 200)
        response = self.client.post(reverse("wallet"), {"recipient":"not-a-user", "amount":1, "memo":"", "idempotency_key":uuid.uuid4()})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "송금")
        self.buyer.wallet.refresh_from_db()
        self.assertEqual((WalletTransaction.objects.count(), LedgerEntry.objects.count(), self.buyer.wallet.balance), before)

    def test_product_chat_is_reused_listed_to_both_users_and_protected(self):
        self.client.force_login(self.buyer)
        response = self.client.post(reverse("start_product_chat", args=[self.product.public_id]))
        self.assertEqual(response.status_code, 302)
        room = ChatRoom.objects.get(related_product=self.product)
        self.assertEqual(self.client.post(reverse("start_product_chat", args=[self.product.public_id])).url, reverse("chat_room", args=[room.public_id]))
        self.assertContains(self.client.get(reverse("chat_list")), self.product.title)
        self.client.force_login(self.seller)
        self.assertContains(self.client.get(reverse("chat_list")), self.product.title)
        outsider = register_user(username="outsiderflow", password="very-secure-password", display_name="외부")
        self.client.force_login(outsider)
        self.assertEqual(self.client.get(reverse("chat_room", args=[room.public_id])).status_code, 404)

    def test_http_chat_post_does_not_render_model_object_text(self):
        self.client.force_login(self.buyer)
        self.client.post(reverse("start_product_chat", args=[self.product.public_id]))
        room=ChatRoom.objects.get(related_product=self.product)
        response=self.client.post(reverse("chat_room", args=[room.public_id]), {"content":"plain HTTP fallback"})
        self.assertEqual(response.status_code, 302)
        response=self.client.get(reverse("chat_room", args=[room.public_id]))
        self.assertNotContains(response, "ChatMessage Object")
        self.assertContains(response, "plain HTTP fallback")

    def test_new_product_chat_is_blocked_after_sold_but_existing_room_remains(self):
        self.client.force_login(self.buyer)
        self.client.post(reverse("start_product_chat", args=[self.product.public_id]))
        room = ChatRoom.objects.get(related_product=self.product)
        self.product.status = Product.Status.SOLD
        self.product.save(update_fields=["status"])
        self.assertEqual(self.client.get(reverse("chat_room", args=[room.public_id])).status_code, 200)
        second_buyer = register_user(username="secondbuyer", password="very-secure-password", display_name="둘째")
        self.client.force_login(second_buyer)
        self.assertEqual(self.client.post(reverse("start_product_chat", args=[self.product.public_id])).status_code, 302)
        self.assertEqual(ChatRoom.objects.filter(related_product=self.product).count(), 1)

    def test_my_store_is_private_and_image_upload_uses_temporary_media_root(self):
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            self.client.force_login(self.seller)
            response = self.client.post(reverse("product_create"), {"category":self.category.pk, "title":"사진 상품", "description":"설명", "price":3, "condition":"USED", "images":image_upload()})
            self.assertEqual(response.status_code, 302)
            image = ProductImage.objects.get(product__title="사진 상품")
            self.assertTrue(os.path.exists(image.image.path))
            self.assertContains(self.client.get(reverse("my_store")), "사진 상품")
        self.client.force_login(self.buyer)
        self.assertNotContains(self.client.get(reverse("my_store")), "사진 상품")

    def test_only_five_images_are_accepted_server_side(self):
        self.client.force_login(self.seller)
        with TemporaryDirectory() as media_root, override_settings(MEDIA_ROOT=media_root):
            response = self.client.post(reverse("product_create"), {"category":self.category.pk, "title":"too many", "description":"x", "price":3, "condition":"USED", "images":[image_upload() for _ in range(6)]})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Product.objects.filter(title="too many").exists())
