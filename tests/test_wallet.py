import uuid
from django.core.exceptions import ValidationError
from django.core.cache import cache
from django.test import TestCase
from market.models import LedgerEntry, User, WalletTransaction
from market.services import grant, register_user, reverse_transfer, transfer, verify_wallet

class WalletTests(TestCase):
    def setUp(self):
        cache.clear()
        self.a=register_user(username="alice",password="very-secure-password",display_name="Alice")
        self.b=register_user(username="bob1",password="very-secure-password",display_name="Bob")
        self.admin=register_user(username="admin1",password="very-secure-password",display_name="Admin")
        self.admin.role=User.Role.ADMIN; self.admin.save(update_fields=["role"])
        grant(actor=self.admin,recipient=self.a,amount=100,reason="테스트 자금",idempotency_key=uuid.uuid4())
    def test_transfer_creates_balanced_ledger(self):
        tx=transfer(sender=self.a,recipient=self.b,amount=30,idempotency_key=uuid.uuid4())
        self.a.wallet.refresh_from_db(); self.b.wallet.refresh_from_db()
        self.assertEqual((self.a.wallet.balance,self.b.wallet.balance),(70,30)); self.assertEqual(LedgerEntry.objects.filter(transaction=tx).count(),2)
    def test_duplicate_key_is_idempotent(self):
        key=uuid.uuid4(); first=transfer(sender=self.a,recipient=self.b,amount=30,idempotency_key=key); second=transfer(sender=self.a,recipient=self.b,amount=30,idempotency_key=key)
        self.assertEqual(first.pk,second.pk)
    def test_same_key_different_request_is_rejected(self):
        key=uuid.uuid4(); transfer(sender=self.a,recipient=self.b,amount=30,idempotency_key=key)
        with self.assertRaises(ValidationError): transfer(sender=self.a,recipient=self.b,amount=31,idempotency_key=key)
    def test_insufficient_balance_is_rejected(self):
        with self.assertRaises(ValidationError): transfer(sender=self.a,recipient=self.b,amount=101,idempotency_key=uuid.uuid4())
    def test_admin_reversal_restores_balances_once(self):
        tx=transfer(sender=self.a,recipient=self.b,amount=30,idempotency_key=uuid.uuid4())
        reverse_transfer(actor=self.admin,original_id=tx.pk,password="very-secure-password",reason="운영 복구")
        self.a.wallet.refresh_from_db(); self.b.wallet.refresh_from_db(); self.assertEqual((self.a.wallet.balance,self.b.wallet.balance),(100,0)); self.assertTrue(verify_wallet(self.a.wallet))
        self.assertEqual(reverse_transfer(actor=self.admin,original_id=tx.pk,password="very-secure-password",reason="중복").original_transaction_id,tx.pk)
