import threading
from unittest.mock import patch
from django.core.exceptions import ValidationError
from django.db import close_old_connections
from django.test import TransactionTestCase, override_settings
from market.models import AuditLog, Category, ChatReadState, ChatRoom, LedgerEntry, Product, Purchase, User, WalletTransaction
from market.services import direct_room, mark_room_read, purchase_product, register_user, send_message, unread_chat_count


@override_settings(CHAT_RATE_LIMIT_PER_MINUTE=100, TRANSFER_RATE_LIMIT_PER_MINUTE=100)
class PurchaseAndUnreadTests(TransactionTestCase):
    def setUp(self):
        self.seller=register_user(username="purchase_seller",password="very-secure-password",display_name="Seller")
        self.buyer=register_user(username="purchase_buyer",password="very-secure-password",display_name="Buyer")
        self.other=register_user(username="purchase_other",password="very-secure-password",display_name="Other")
        self.buyer.wallet.balance=100; self.buyer.wallet.save(update_fields=["balance"])
        self.other.wallet.balance=100; self.other.wallet.save(update_fields=["balance"])
        category=Category.objects.create(name="Purchase",slug="purchase")
        self.product=Product.objects.create(seller=self.seller,category=category,title="Item",description="x",price=30,condition="USED",status=Product.Status.ACTIVE)

    def test_purchase_is_atomic_and_single_product_record(self):
        purchase=purchase_product(buyer=self.buyer,product_id=self.product.pk)
        self.product.refresh_from_db(); self.buyer.wallet.refresh_from_db(); self.seller.wallet.refresh_from_db()
        self.assertEqual(self.product.status,Product.Status.SOLD); self.assertEqual(purchase.amount,30)
        self.assertEqual(self.buyer.wallet.balance,70); self.assertEqual(self.seller.wallet.balance,30)
        self.assertEqual(Purchase.objects.filter(product=self.product).count(),1)
        self.assertEqual(WalletTransaction.objects.filter(product=self.product).count(),1)
        with self.assertRaises(ValidationError): purchase_product(buyer=self.other,product_id=self.product.pk)

    def test_purchase_retransmission_and_sold_or_reserved_products_do_not_charge_twice(self):
        purchase_product(buyer=self.buyer, product_id=self.product.pk)
        with self.assertRaises(ValidationError):
            purchase_product(buyer=self.buyer, product_id=self.product.pk)
        self.buyer.wallet.refresh_from_db(); self.seller.wallet.refresh_from_db()
        self.assertEqual((self.buyer.wallet.balance, self.seller.wallet.balance), (70, 30))
        self.assertEqual(Purchase.objects.count(), 1)
        reserved = Product.objects.create(seller=self.seller, category=self.product.category, title="Reserved", description="x", price=20, condition="USED", status=Product.Status.RESERVED)
        with self.assertRaises(ValidationError):
            purchase_product(buyer=self.other, product_id=reserved.pk)
        self.assertFalse(Purchase.objects.filter(product=reserved).exists())

    def test_purchase_rolls_back_every_record_when_purchase_creation_fails(self):
        before = {
            "transactions": WalletTransaction.objects.count(),
            "ledger": LedgerEntry.objects.count(),
            "purchases": Purchase.objects.count(),
            "audit": AuditLog.objects.count(),
            "buyer": self.buyer.wallet.balance,
            "seller": self.seller.wallet.balance,
        }
        with patch("market.services.Purchase.objects.create", side_effect=RuntimeError("forced failure")):
            with self.assertRaises(RuntimeError):
                purchase_product(buyer=self.buyer, product_id=self.product.pk)
        self.product.refresh_from_db(); self.buyer.wallet.refresh_from_db(); self.seller.wallet.refresh_from_db()
        self.assertEqual(self.product.status, Product.Status.ACTIVE)
        self.assertEqual((self.buyer.wallet.balance, self.seller.wallet.balance), (before["buyer"], before["seller"]))
        self.assertEqual(WalletTransaction.objects.count(), before["transactions"])
        self.assertEqual(LedgerEntry.objects.count(), before["ledger"])
        self.assertEqual(Purchase.objects.count(), before["purchases"])
        self.assertEqual(AuditLog.objects.count(), before["audit"])

    def test_purchase_rejects_self_and_insufficient_without_mutation(self):
        with self.assertRaises(ValidationError): purchase_product(buyer=self.seller,product_id=self.product.pk)
        self.buyer.wallet.balance=0; self.buyer.wallet.save(update_fields=["balance"])
        with self.assertRaises(ValidationError): purchase_product(buyer=self.buyer,product_id=self.product.pk)
        self.product.refresh_from_db(); self.assertEqual(self.product.status,Product.Status.ACTIVE); self.assertFalse(Purchase.objects.exists())

    def test_room_read_state_counts_only_received_messages(self):
        room=direct_room(sender=self.buyer,recipient=self.seller,product=self.product)
        send_message(sender=self.seller,room=room,content="incoming")
        self.assertEqual(unread_chat_count(self.buyer),1); self.assertEqual(unread_chat_count(self.seller),0)
        mark_room_read(room=room,user=self.buyer)
        self.assertEqual(unread_chat_count(self.buyer),0); self.assertTrue(ChatReadState.objects.filter(room=room,user=self.buyer).exists())

    def test_concurrent_purchase_has_one_winner(self):
        barrier=threading.Barrier(2); outcomes=[]
        def run(user_id):
            close_old_connections()
            try:
                user=User.objects.get(pk=user_id); barrier.wait(); purchase_product(buyer=user,product_id=self.product.pk); outcomes.append("ok")
            except ValidationError: outcomes.append("blocked")
            finally: close_old_connections()
        threads=[threading.Thread(target=run,args=(self.buyer.pk,)),threading.Thread(target=run,args=(self.other.pk,))]
        [thread.start() for thread in threads]; [thread.join() for thread in threads]
        self.assertEqual(sorted(outcomes),["blocked","ok"]); self.assertEqual(Purchase.objects.filter(product=self.product).count(),1)
