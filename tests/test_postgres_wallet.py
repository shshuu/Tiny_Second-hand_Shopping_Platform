import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from unittest.mock import patch
from redis.exceptions import RedisError
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import DatabaseError, connection, close_old_connections, transaction
from django.db.models import Sum
from django.test import TransactionTestCase, override_settings, skipUnlessDBFeature
from django.utils import timezone
from market.models import AuditLog, LedgerEntry, Notification, Profile, SecurityEvent, User, WalletTransaction
from market.services import _daily_total, award_welcome_bonus, grant, register_user, reverse_transfer, transfer, verify_wallet

@skipUnlessDBFeature("has_select_for_update")
class PostgreSQLWalletConcurrencyTests(TransactionTestCase):
    reset_sequences=True
    def setUp(self):
        cache.clear()
        self.a=register_user(username="posta",password="very-secure-password",display_name="A")
        self.b=register_user(username="postb",password="very-secure-password",display_name="B")
        self.admin=register_user(username="postaadmin",password="very-secure-password",display_name="Admin")
        self.admin.role=User.Role.ADMIN; self.admin.save(update_fields=["role"])
        grant(actor=self.admin,recipient=self.a,amount=100,reason="test",idempotency_key=uuid.uuid4())
        grant(actor=self.admin,recipient=self.b,amount=100,reason="test",idempotency_key=uuid.uuid4())
    def _transfer(self, sender_id, recipient_id, amount, key, barrier):
        close_old_connections(); barrier.wait()
        try:
            sender=User.objects.get(pk=sender_id); recipient=User.objects.get(pk=recipient_id)
            return transfer(sender=sender,recipient=recipient,amount=amount,idempotency_key=key).pk
        finally: connection.close()
    def _grant(self, recipient_id, key, barrier):
        close_old_connections(); barrier.wait()
        try:
            actor=User.objects.get(pk=self.admin.pk); recipient=User.objects.get(pk=recipient_id)
            return grant(actor=actor,recipient=recipient,amount=10,reason="concurrent",idempotency_key=key).pk
        finally: connection.close()
    def _grant_amount(self, actor_id, recipient_id, amount, key, barrier):
        close_old_connections(); barrier.wait()
        try:
            actor=User.objects.get(pk=actor_id); recipient=User.objects.get(pk=recipient_id)
            return grant(actor=actor,recipient=recipient,amount=amount,reason="concurrent limit",idempotency_key=key).pk
        finally: connection.close()
    def _reverse(self, original_id, barrier):
        close_old_connections(); barrier.wait()
        try:
            actor=User.objects.get(pk=self.admin.pk)
            return reverse_transfer(actor=actor,original_id=original_id,password="very-secure-password",reason="concurrent").pk
        finally: connection.close()
    def _welcome(self, user_id, barrier):
        close_old_connections(); barrier.wait()
        try: return award_welcome_bonus(User.objects.get(pk=user_id)).pk
        finally: connection.close()
    def test_same_idempotency_key_concurrently_returns_one_transaction(self):
        key=uuid.uuid4(); barrier=threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self._transfer(self.a.pk,self.b.pk,10,key,barrier), range(2)))
        self.assertEqual(results[0],results[1]); self.assertEqual(WalletTransaction.objects.filter(idempotency_key=key).count(),1)
    def test_opposite_direction_transfers_do_not_deadlock(self):
        barrier=threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(self._transfer,self.a.pk,self.b.pk,10,uuid.uuid4(),barrier)
            second=pool.submit(self._transfer,self.b.pk,self.a.pk,10,uuid.uuid4(),barrier)
            first.result(timeout=15); second.result(timeout=15)
        self.a.wallet.refresh_from_db(); self.b.wallet.refresh_from_db(); self.assertEqual((self.a.wallet.balance,self.b.wallet.balance),(100,100))
    def test_completed_history_cannot_be_updated_or_deleted(self):
        tx=transfer(sender=self.a,recipient=self.b,amount=10,idempotency_key=uuid.uuid4())
        with self.assertRaises(DatabaseError): WalletTransaction.objects.filter(pk=tx.pk).update(memo="tamper")
        with self.assertRaises(DatabaseError): LedgerEntry.objects.filter(transaction=tx).delete()
    def test_same_sender_concurrent_transfers_never_create_negative_balance(self):
        c=register_user(username="postc",password="very-secure-password",display_name="C")
        barrier=threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first=pool.submit(self._transfer,self.a.pk,self.b.pk,80,uuid.uuid4(),barrier)
            second=pool.submit(self._transfer,self.a.pk,c.pk,80,uuid.uuid4(),barrier)
            outcomes=[]
            for future in (first,second):
                try: outcomes.append(future.result(timeout=15))
                except ValidationError: outcomes.append(None)
        self.a.wallet.refresh_from_db(); self.assertEqual(sum(x is not None for x in outcomes),1); self.assertGreaterEqual(self.a.wallet.balance,0)
    def test_admin_grant_duplicate_request_is_idempotent(self):
        key=uuid.uuid4(); barrier=threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(lambda _:self._grant(self.b.pk,key,barrier),range(2)))
        self.assertEqual(results[0],results[1]); self.assertEqual(WalletTransaction.objects.filter(idempotency_key=key).count(),1)
    def test_concurrent_reversal_returns_same_result(self):
        original=transfer(sender=self.a,recipient=self.b,amount=10,idempotency_key=uuid.uuid4()); barrier=threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool: results=list(pool.map(lambda _:self._reverse(original.pk,barrier),range(2)))
        self.assertEqual(results[0],results[1]); self.assertEqual(WalletTransaction.objects.filter(original_transaction=original).count(),1)
    @override_settings(WELCOME_BONUS_ENABLED=True,WELCOME_BONUS_AMOUNT=10)
    def test_welcome_bonus_is_idempotent(self):
        user=register_user(username="bonus",password="very-secure-password",display_name="Bonus")
        first=award_welcome_bonus(user); second=award_welcome_bonus(user)
        self.assertEqual(first.pk,second.pk); self.assertEqual(WalletTransaction.objects.filter(grant_key=f"WELCOME_BONUS:{user.pk}").count(),1)
    @override_settings(WELCOME_BONUS_ENABLED=False,WELCOME_BONUS_AMOUNT=10)
    def test_welcome_bonus_concurrent_requests_create_once(self):
        user=register_user(username="bonusrace",password="very-secure-password",display_name="Bonus race"); barrier=threading.Barrier(2)
        with override_settings(WELCOME_BONUS_ENABLED=True,WELCOME_BONUS_AMOUNT=10), ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:self._welcome(user.pk,barrier),range(2)))
        user.wallet.refresh_from_db(); self.assertEqual(results[0],results[1]); self.assertEqual(user.wallet.balance,10)
        txs=WalletTransaction.objects.filter(grant_key=f"WELCOME_BONUS:{user.pk}"); self.assertEqual(txs.count(),1); self.assertEqual(LedgerEntry.objects.filter(transaction=txs.get(),entry_type="CREDIT").count(),1)
    def test_ledger_mismatch_creates_security_event_without_auto_repair(self):
        self.a.wallet.balance=99; self.a.wallet.save(update_fields=["balance"])
        self.assertFalse(verify_wallet(self.a.wallet)); self.a.wallet.refresh_from_db()
        self.assertEqual(self.a.wallet.balance,99); self.assertTrue(SecurityEvent.objects.filter(event_type="LEDGER_MISMATCH",user=self.a).exists())
    def test_registration_rolls_back_when_profile_creation_fails(self):
        with patch("market.services.Profile.objects.create",side_effect=RuntimeError("forced failure")):
            with self.assertRaises(RuntimeError): register_user(username="rollback",password="very-secure-password",display_name="Rollback")
        self.assertFalse(User.objects.filter(username="rollback").exists())

    @override_settings(TRANSFER_MAX_AMOUNT=100,TRANSFER_DAILY_LIMIT=200,TRANSFER_RATE_LIMIT_PER_MINUTE=50)
    def test_transfer_limit_boundaries_and_failed_requests(self):
        grant(actor=self.admin,recipient=self.a,amount=200,reason="limits",idempotency_key=uuid.uuid4())
        transfer(sender=self.a,recipient=self.b,amount=99,idempotency_key=uuid.uuid4())
        transfer(sender=self.a,recipient=self.b,amount=100,idempotency_key=uuid.uuid4())
        with self.assertRaises(ValidationError): transfer(sender=self.a,recipient=self.b,amount=101,idempotency_key=uuid.uuid4())
        self.assertEqual(WalletTransaction.objects.filter(source=self.a.wallet,transaction_type="USER_TRANSFER").aggregate(total=Sum("amount"))["total"],199)
        transfer(sender=self.a,recipient=self.b,amount=1,idempotency_key=uuid.uuid4())
        with self.assertRaises(ValidationError): transfer(sender=self.a,recipient=self.b,amount=1,idempotency_key=uuid.uuid4())
    @override_settings(TRANSFER_MAX_AMOUNT=200,TRANSFER_DAILY_LIMIT=200,TRANSFER_RATE_LIMIT_PER_MINUTE=50)
    def test_concurrent_transfer_daily_limit(self):
        grant(actor=self.admin,recipient=self.a,amount=200,reason="limits",idempotency_key=uuid.uuid4()); c=register_user(username="limitc",password="very-secure-password",display_name="C")
        barrier=threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(self._transfer,self.a.pk,target.pk,150,uuid.uuid4(),barrier) for target in (self.b,c)]
            outcomes=[]
            for future in futures:
                try: outcomes.append(future.result(timeout=15))
                except ValidationError: outcomes.append(None)
        total=WalletTransaction.objects.filter(source=self.a.wallet,transaction_type="USER_TRANSFER").aggregate(total=Sum("amount"))["total"] or 0
        self.assertEqual(sum(x is not None for x in outcomes),1); self.assertLessEqual(total,200)
    @override_settings(ADMIN_GRANT_MAX_AMOUNT=100,ADMIN_GRANT_DAILY_LIMIT=200,ADMIN_GRANT_RATE_LIMIT_PER_MINUTE=50)
    def test_admin_grant_limits_and_roles(self):
        recipient=register_user(username="grantuser",password="very-secure-password",display_name="Recipient")
        limit_admin=register_user(username="limitadmin",password="very-secure-password",display_name="Limit admin")
        limit_admin.role=User.Role.ADMIN; limit_admin.save(update_fields=["role"])
        grant(actor=limit_admin,recipient=recipient,amount=100,reason="limit",idempotency_key=uuid.uuid4())
        grant(actor=limit_admin,recipient=recipient,amount=100,reason="limit",idempotency_key=uuid.uuid4())
        with self.assertRaises(ValidationError): grant(actor=limit_admin,recipient=recipient,amount=1,reason="limit",idempotency_key=uuid.uuid4())
        with self.assertRaises(ValidationError): grant(actor=self.a,recipient=recipient,amount=1,reason="no",idempotency_key=uuid.uuid4())
    def test_notifications_are_post_commit_and_not_duplicated(self):
        before=Notification.objects.count(); key=uuid.uuid4(); transfer(sender=self.a,recipient=self.b,amount=10,idempotency_key=key)
        self.assertEqual(Notification.objects.count(),before+1); transfer(sender=self.a,recipient=self.b,amount=10,idempotency_key=key); self.assertEqual(Notification.objects.count(),before+1)
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                transfer(sender=self.a,recipient=self.b,amount=10,idempotency_key=uuid.uuid4()); raise RuntimeError("rollback")
        self.assertEqual(Notification.objects.count(),before+1)

    @override_settings(TRANSFER_MAX_AMOUNT=100,TRANSFER_DAILY_LIMIT=200,TRANSFER_RATE_LIMIT_PER_MINUTE=50)
    def test_transfer_limits_leave_no_partial_records(self):
        grant(actor=self.admin,recipient=self.a,amount=200,reason="limit funds",idempotency_key=uuid.uuid4())
        transfer(sender=self.a,recipient=self.b,amount=99,idempotency_key=uuid.uuid4())
        transfer(sender=self.a,recipient=self.b,amount=100,idempotency_key=uuid.uuid4())
        self.a.wallet.refresh_from_db(); self.b.wallet.refresh_from_db()
        before=(WalletTransaction.objects.count(),LedgerEntry.objects.count(),self.a.wallet.balance,self.b.wallet.balance)
        with self.assertRaises(ValidationError): transfer(sender=self.a,recipient=self.b,amount=101,idempotency_key=uuid.uuid4())
        self.a.wallet.refresh_from_db(); self.b.wallet.refresh_from_db()
        self.assertEqual((WalletTransaction.objects.count(),LedgerEntry.objects.count(),self.a.wallet.balance,self.b.wallet.balance),before)
        transfer(sender=self.a,recipient=self.b,amount=1,idempotency_key=uuid.uuid4())
        with self.assertRaises(ValidationError): transfer(sender=self.a,recipient=self.b,amount=1,idempotency_key=uuid.uuid4())
        self.assertEqual(_daily_total(self.a.wallet,WalletTransaction.Type.TRANSFER),200)

    @override_settings(TRANSFER_MAX_AMOUNT=200,TRANSFER_DAILY_LIMIT=200,TRANSFER_RATE_LIMIT_PER_MINUTE=50)
    def test_daily_total_only_counts_user_transfers_and_ledgers_match(self):
        grant(actor=self.admin,recipient=self.a,amount=200,reason="daily funds",idempotency_key=uuid.uuid4())
        original=transfer(sender=self.a,recipient=self.b,amount=100,idempotency_key=uuid.uuid4())
        reverse_transfer(actor=self.admin,original_id=original.pk,password="very-secure-password",reason="test")
        self.assertEqual(_daily_total(self.a.wallet,WalletTransaction.Type.TRANSFER),100)
        self.a.wallet.refresh_from_db(); self.b.wallet.refresh_from_db()
        self.assertTrue(verify_wallet(self.a.wallet)); self.assertTrue(verify_wallet(self.b.wallet))

    @override_settings(TRANSFER_MAX_AMOUNT=100,TRANSFER_DAILY_LIMIT=1000,TRANSFER_RATE_LIMIT_PER_MINUTE=2)
    def test_redis_rate_limit_is_per_user_and_fail_closed(self):
        grant(actor=self.admin,recipient=self.a,amount=20,reason="rate funds",idempotency_key=uuid.uuid4())
        transfer(sender=self.a,recipient=self.b,amount=1,idempotency_key=uuid.uuid4())
        transfer(sender=self.a,recipient=self.b,amount=1,idempotency_key=uuid.uuid4())
        with self.assertRaises(ValidationError): transfer(sender=self.a,recipient=self.b,amount=1,idempotency_key=uuid.uuid4())
        transfer(sender=self.b,recipient=self.a,amount=1,idempotency_key=uuid.uuid4())
        with patch("market.services.cache.add",side_effect=RedisError("unavailable")):
            with self.assertRaises(ValidationError): transfer(sender=self.b,recipient=self.a,amount=1,idempotency_key=uuid.uuid4())

    @override_settings(ADMIN_GRANT_MAX_AMOUNT=100,ADMIN_GRANT_DAILY_LIMIT=200,ADMIN_GRANT_RATE_LIMIT_PER_MINUTE=50)
    def test_admin_grant_boundaries_leave_no_partial_records(self):
        recipient=register_user(username="grantboundary",password="very-secure-password",display_name="Recipient")
        admin=register_user(username="grantboundaryadmin",password="very-secure-password",display_name="Admin")
        admin.role=User.Role.SUPERADMIN; admin.save(update_fields=["role"])
        grant(actor=admin,recipient=recipient,amount=99,reason="limit",idempotency_key=uuid.uuid4())
        grant(actor=admin,recipient=recipient,amount=100,reason="limit",idempotency_key=uuid.uuid4())
        before=(WalletTransaction.objects.count(),LedgerEntry.objects.count(),Notification.objects.count(),AuditLog.objects.count())
        with self.assertRaises(ValidationError): grant(actor=admin,recipient=recipient,amount=101,reason="limit",idempotency_key=uuid.uuid4())
        with self.assertRaises(ValidationError): grant(actor=admin,recipient=recipient,amount=2,reason="limit",idempotency_key=uuid.uuid4())
        self.assertEqual((WalletTransaction.objects.count(),LedgerEntry.objects.count(),Notification.objects.count(),AuditLog.objects.count()),before)

    @override_settings(ADMIN_GRANT_MAX_AMOUNT=200,ADMIN_GRANT_DAILY_LIMIT=200,ADMIN_GRANT_RATE_LIMIT_PER_MINUTE=50)
    def test_concurrent_admin_grants_do_not_exceed_daily_limit(self):
        admin=register_user(username="concurrentgrantadmin",password="very-secure-password",display_name="Admin")
        admin.role=User.Role.ADMIN; admin.save(update_fields=["role"])
        first=register_user(username="concurrentgranta",password="very-secure-password",display_name="A")
        second=register_user(username="concurrentgrantb",password="very-secure-password",display_name="B")
        barrier=threading.Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures=[pool.submit(self._grant_amount,admin.pk,target.pk,150,uuid.uuid4(),barrier) for target in (first,second)]
            outcomes=[]
            for future in futures:
                try: outcomes.append(future.result(timeout=15))
                except ValidationError: outcomes.append(None)
        total=WalletTransaction.objects.filter(created_by=admin,transaction_type=WalletTransaction.Type.GRANT).aggregate(total=Sum("amount"))["total"] or 0
        self.assertEqual(sum(x is not None for x in outcomes),1); self.assertLessEqual(total,200)

    def test_grant_and_reversal_notifications_are_post_commit(self):
        recipient=register_user(username="notificationrecipient",password="very-secure-password",display_name="Recipient")
        before=Notification.objects.count()
        grant(actor=self.admin,recipient=recipient,amount=10,reason="notification",idempotency_key=uuid.uuid4())
        self.assertEqual(Notification.objects.count(),before+1)
        original=transfer(sender=self.a,recipient=self.b,amount=10,idempotency_key=uuid.uuid4())
        reverse_transfer(actor=self.admin,original_id=original.pk,password="very-secure-password",reason="notification")
        self.assertEqual(Notification.objects.count(),before+3)
        with self.assertRaises(RuntimeError):
            with transaction.atomic():
                grant(actor=self.admin,recipient=recipient,amount=10,reason="rollback",idempotency_key=uuid.uuid4()); raise RuntimeError("rollback")
        self.assertEqual(Notification.objects.count(),before+3)

    @override_settings(TRANSFER_MAX_AMOUNT=100,TRANSFER_DAILY_LIMIT=100,TRANSFER_RATE_LIMIT_PER_MINUTE=50,ADMIN_GRANT_MAX_AMOUNT=100,ADMIN_GRANT_DAILY_LIMIT=100,ADMIN_GRANT_RATE_LIMIT_PER_MINUTE=50)
    def test_daily_limits_reset_at_seoul_midnight(self):
        tz=timezone.get_current_timezone()
        before_midnight=timezone.make_aware(datetime(2026,7,20,23,59,30),tz)
        after_midnight=timezone.make_aware(datetime(2026,7,21,0,0,30),tz)
        with patch("market.services.timezone.now",return_value=before_midnight):
            transfer(sender=self.a,recipient=self.b,amount=100,idempotency_key=uuid.uuid4())
        funder=register_user(username="midnightfunder",password="very-secure-password",display_name="Funder")
        funder.role=User.Role.ADMIN; funder.save(update_fields=["role"])
        with patch("market.services.timezone.now",return_value=after_midnight):
            grant(actor=funder,recipient=self.a,amount=100,reason="midnight funds",idempotency_key=uuid.uuid4())
            transfer(sender=self.a,recipient=self.b,amount=100,idempotency_key=uuid.uuid4())
            self.assertEqual(_daily_total(self.a.wallet,WalletTransaction.Type.TRANSFER),100)
        midnight_admin=register_user(username="midnightadmin",password="very-secure-password",display_name="Admin")
        midnight_admin.role=User.Role.ADMIN; midnight_admin.save(update_fields=["role"])
        recipient=register_user(username="midnightrecipient",password="very-secure-password",display_name="Recipient")
        with patch("market.services.timezone.now",return_value=before_midnight):
            grant(actor=midnight_admin,recipient=recipient,amount=100,reason="midnight",idempotency_key=uuid.uuid4())
        with patch("market.services.timezone.now",return_value=after_midnight):
            grant(actor=midnight_admin,recipient=recipient,amount=100,reason="midnight",idempotency_key=uuid.uuid4())
        self.assertEqual(WalletTransaction.objects.filter(source=self.a.wallet,transaction_type=WalletTransaction.Type.TRANSFER).count(),2)
        self.assertEqual(WalletTransaction.objects.filter(created_by=midnight_admin,transaction_type=WalletTransaction.Type.GRANT).count(),2)

    @override_settings(TRANSFER_MAX_AMOUNT=100,TRANSFER_DAILY_LIMIT=1000,TRANSFER_RATE_LIMIT_PER_MINUTE=2,RATE_LIMIT_TTL_SECONDS=1)
    def test_redis_rate_limit_allows_again_after_real_ttl_expiry(self):
        grant(actor=self.admin,recipient=self.a,amount=10,reason="ttl funds",idempotency_key=uuid.uuid4())
        transfer(sender=self.a,recipient=self.b,amount=1,idempotency_key=uuid.uuid4())
        transfer(sender=self.a,recipient=self.b,amount=1,idempotency_key=uuid.uuid4())
        key=f"rate:transfer:{self.a.pk}:{timezone.now().strftime('%Y%m%d%H%M')}"
        self.assertEqual(cache.get(key),2)
        with self.assertRaises(ValidationError): transfer(sender=self.a,recipient=self.b,amount=1,idempotency_key=uuid.uuid4())
        transfer(sender=self.b,recipient=self.a,amount=1,idempotency_key=uuid.uuid4())
        time.sleep(1.2)
        self.assertIsNone(cache.get(key))
        transfer(sender=self.a,recipient=self.b,amount=1,idempotency_key=uuid.uuid4())
