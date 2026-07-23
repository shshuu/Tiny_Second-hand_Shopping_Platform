import uuid
import threading
import time
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import DatabaseError
from django.db import close_old_connections
from django.core.cache import cache
from django.test import Client, TransactionTestCase, override_settings
from django.urls import reverse

from market.models import AuditLog, AutoModerationCase, Category, ChatMessage, LedgerEntry, Product, Report, SecurityEvent, User, WalletTransaction
from market.services import (assign_report, change_user_role, change_user_status, create_report, create_user_by_admin,
    direct_room, grant, moderate_message, moderate_product, register_user, send_message, transfer)


class AdminOperationTests(TransactionTestCase):
    def setUp(self):
        self.user=register_user(username="ops_user",password="very-secure-password",display_name="User")
        self.mod=register_user(username="ops_mod",password="very-secure-password",display_name="Mod"); self.mod.role=User.Role.MODERATOR; self.mod.save()
        self.admin=register_user(username="ops_admin",password="very-secure-password",display_name="Admin"); self.admin.role=User.Role.ADMIN; self.admin.save()
        self.superadmin=register_user(username="ops_super",password="very-secure-password",display_name="Super"); self.superadmin.role=User.Role.SUPERADMIN; self.superadmin.save()
        self.category=Category.objects.create(name="Operations",slug="operations")
        self.product=Product.objects.create(seller=self.user,category=self.category,title="Item",description="x",price=1,condition="USED",status=Product.Status.ACTIVE)

    def test_role_urls_and_state_audit(self):
        self.client.force_login(self.user); self.assertEqual(self.client.get(reverse("ops_dashboard")).status_code,403)
        self.client.force_login(self.mod); self.assertEqual(self.client.get(reverse("ops_dashboard")).status_code,200); self.assertEqual(self.client.get(reverse("ops_users")).status_code,403)
        change_user_status(actor=self.admin,target=self.user,status=User.Status.RESTRICTED,reason="abuse")
        self.user.refresh_from_db(); self.assertEqual(self.user.status,User.Status.RESTRICTED)
        log=AuditLog.objects.filter(action="user.status",target=str(self.user.public_id)).latest("created_at"); self.assertEqual(log.actor,self.admin); self.assertIn("ACTIVE->RESTRICTED",log.reason)
        with self.assertRaises(ValidationError): change_user_status(actor=self.mod,target=self.user,status=User.Status.ACTIVE,reason="no")
        with self.assertRaises(ValidationError): change_user_status(actor=self.admin,target=self.superadmin,status=User.Status.SUSPENDED,reason="no")

    def test_superadmin_roles_admin_creation_and_product_message_actions(self):
        with self.assertRaises(ValidationError): create_user_by_admin(actor=self.admin,username="no_super",password="very-secure-password",display_name="No",role=User.Role.SUPERADMIN)
        created=create_user_by_admin(actor=self.admin,username="new_mod",password="very-secure-password",display_name="New",role=User.Role.MODERATOR)
        self.assertEqual(created.role,User.Role.MODERATOR); self.assertTrue(hasattr(created,"wallet")); self.assertEqual(created.wallet.balance,0)
        with self.assertRaises(ValidationError): change_user_role(actor=self.admin,target=self.user,role=User.Role.MODERATOR,reason="no")
        change_user_role(actor=self.superadmin,target=self.user,role=User.Role.MODERATOR,reason="promotion")
        moderate_product(actor=self.mod,product=self.product,status=Product.Status.HIDDEN,reason="report")
        self.product.refresh_from_db(); self.assertEqual(self.product.status,Product.Status.HIDDEN)
        room=direct_room(sender=self.user,recipient=self.admin); message=send_message(sender=self.admin,room=room,content="reported")
        moderate_message(actor=self.mod,message=message,reason="abuse")
        message.refresh_from_db(); self.assertEqual(message.status,ChatMessage.Status.HIDDEN)

    @override_settings(ADMIN_GRANT_RATE_LIMIT_PER_MINUTE=50)
    def test_moderator_cannot_grant_and_admin_uses_existing_grant_service(self):
        with self.assertRaises(ValidationError): grant(actor=self.mod,recipient=self.user,amount=1,reason="no",idempotency_key=uuid.uuid4())
        grant(actor=self.admin,recipient=self.user,amount=1,reason="approved",idempotency_key=uuid.uuid4())
        self.assertTrue(AuditLog.objects.filter(action="wallet.grant",actor=self.admin).exists())

    def test_audit_log_is_append_only_in_postgresql(self):
        log=AuditLog.objects.create(actor=self.admin,action="test",target="target",reason="reason")
        with self.assertRaises(DatabaseError): AuditLog.objects.filter(pk=log.pk).update(reason="changed")
        with self.assertRaises(DatabaseError): AuditLog.objects.filter(pk=log.pk).delete()

    def test_report_assignment_is_role_checked_and_optimistic(self):
        report=Report.objects.create(reporter=self.user,target_type=Report.Target.PRODUCT,target_id=self.product.public_id,reason="SPAM")
        assigned=assign_report(actor=self.mod,report=report,assignee=self.mod,reason="triage",expected_version=0)
        self.assertEqual(assigned.assigned_to,self.mod); self.assertEqual(assigned.assignment_version,1)
        with self.assertRaises(ValidationError): assign_report(actor=self.mod,report=assigned,assignee=self.admin,reason="stale",expected_version=0)
        with self.assertRaises(ValidationError): assign_report(actor=self.user,report=assigned,assignee=self.admin,reason="no",expected_version=1)
        self.admin.status=User.Status.SUSPENDED; self.admin.save()
        with self.assertRaises(ValidationError): assign_report(actor=self.mod,report=assigned,assignee=self.admin,reason="bad",expected_version=1)
        self.assertTrue(AuditLog.objects.filter(action="report.assign",target=str(report.public_id)).exists())

    def test_operations_category_and_product_detail_permissions(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("ops_categories")).status_code,403)
        self.assertEqual(self.client.get(reverse("ops_product_detail",args=[self.product.public_id])).status_code,403)
        self.client.force_login(self.admin)
        response=self.client.post(reverse("ops_categories"),{"name":"Games","slug":"games","is_active":"on"})
        self.assertEqual(response.status_code,200)
        category=Category.objects.get(slug="games")
        self.client.post(reverse("ops_categories"),{"id":category.pk,"name":"Video Games","slug":"video-games"})
        category.refresh_from_db(); self.assertFalse(category.is_active); self.assertEqual(category.name,"Video Games")
        self.assertEqual(self.client.get(reverse("ops_product_detail",args=[self.product.public_id])).status_code,200)
        self.assertTrue(AuditLog.objects.filter(action="category.update",target=str(category.pk)).exists())

    def test_auto_case_operations_forms_are_pending_only_and_audit_is_human_readable(self):
        reporters=[register_user(username=f"case_rep{i}",password="very-secure-password",display_name=f"R{i}") for i in range(3)]
        for reporter in reporters: create_report(reporter=reporter,target_type=Report.Target.PRODUCT,target_id=self.product.public_id,reason="SPAM")
        case=AutoModerationCase.objects.get(target_type=AutoModerationCase.Target.PRODUCT)
        self.client.force_login(self.mod)
        response=self.client.post(reverse("ops_auto_case_action",args=[case.public_id]),{"action":"start"})
        self.assertEqual(response.status_code,302); case.refresh_from_db(); self.assertEqual(case.assigned_to,self.mod)
        response=self.client.post(reverse("ops_auto_case_action",args=[case.public_id]),{"action":"REJECTED","reason":"insufficient evidence"})
        self.assertEqual(response.status_code,302); case.refresh_from_db(); self.assertEqual(case.review_status,AutoModerationCase.Review.REJECTED)
        response=self.client.get(reverse("ops_auto_cases"))
        self.assertContains(response,"처리 결과")
        self.assertNotContains(response,'name="action"')
        self.client.force_login(self.admin)
        response=self.client.get(reverse("ops_audit"))
        self.assertContains(response,"자동 조치")

    def test_report_transition_ui_acceptance_hides_product_and_rejection_keeps_public(self):
        report=Report.objects.create(reporter=self.user,target_type=Report.Target.PRODUCT,target_id=self.product.public_id,reason="SPAM")
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(reverse("ops_report_action",args=[report.public_id]),{"status":"REVIEWING","reason":"no"}).status_code,403)
        self.client.force_login(self.mod)
        self.assertEqual(self.client.post(reverse("ops_report_action",args=[report.public_id]),{"status":"REVIEWING","reason":"triage"}).status_code,302)
        self.assertEqual(self.client.post(reverse("ops_report_action",args=[report.public_id]),{"status":"ACCEPTED","reason":"policy violation"}).status_code,302)
        report.refresh_from_db(); self.product.refresh_from_db()
        self.assertEqual((report.status,self.product.status),(Report.Status.ACCEPTED,Product.Status.HIDDEN))
        self.assertTrue(AuditLog.objects.filter(action="report.accept_hide_product",target=str(self.product.public_id)).exists())
        rejected_product=Product.objects.create(seller=self.user,category=self.category,title="Keep",description="x",price=1,condition="USED",status=Product.Status.ACTIVE)
        rejected=Report.objects.create(reporter=self.admin,target_type=Report.Target.PRODUCT,target_id=rejected_product.public_id,reason="SPAM")
        self.assertEqual(self.client.post(reverse("ops_report_action",args=[rejected.public_id]),{"status":"REJECTED","reason":"not a violation"}).status_code,302)
        rejected_product.refresh_from_db(); self.assertEqual(rejected_product.status,Product.Status.ACTIVE)

    def test_report_and_audit_lists_render_human_readable_details_and_closed_reports_are_readonly(self):
        report=Report.objects.create(reporter=self.user,target_type=Report.Target.PRODUCT,target_id=self.product.public_id,reason="SPAM",description="misleading listing")
        self.client.force_login(self.mod)
        response=self.client.get(reverse("ops_reports"))
        self.assertContains(response,"상품 신고"); self.assertContains(response,self.product.title); self.assertContains(response,"misleading listing")
        self.client.post(reverse("ops_report_action",args=[report.public_id]),{"status":"REJECTED","reason":"insufficient evidence"})
        response=self.client.get(reverse("ops_reports"))
        self.assertContains(response,"처리 결과: 기각"); self.assertNotContains(response,'name="status"')
        # 신고 처리는 MODERATOR에게 허용되지만 감사 로그 열람은 ADMIN 이상 전용이다.
        self.assertEqual(self.client.get(reverse("ops_audit")).status_code,403)
        self.client.force_login(self.admin)
        response=self.client.get(reverse("ops_audit"))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,"신고 상태 변경")

    @override_settings(ADMIN_LOGIN_RATE_LIMIT_PER_MINUTE=2)
    def test_admin_login_rate_limit_is_hashed_and_fail_closed_policy(self):
        from market.admin_views import _login_key
        login_url=reverse("admin_login")
        cache.delete(_login_key(self.admin.username,"10.0.0.1")); cache.delete(_login_key(self.admin.username,"10.0.0.2"))
        self.assertEqual(self.client.post(login_url,{"username":self.admin.username,"password":"wrong"},REMOTE_ADDR="10.0.0.1").status_code,200)
        self.assertEqual(self.client.post(login_url,{"username":self.admin.username,"password":"wrong"},REMOTE_ADDR="10.0.0.1").status_code,200)
        self.assertEqual(self.client.post(login_url,{"username":self.admin.username,"password":"very-secure-password"},REMOTE_ADDR="10.0.0.1").status_code,403)
        response=self.client.post(login_url,{"username":self.admin.username,"password":"very-secure-password"},REMOTE_ADDR="10.0.0.2")
        self.assertEqual(response.status_code,302)
        events=SecurityEvent.objects.filter(event_type__startswith="ADMIN_LOGIN")
        self.assertTrue(events.filter(event_type="ADMIN_LOGIN_RATE_LIMIT").exists())
        self.assertFalse(any(self.admin.username in event.detail or "very-secure-password" in event.detail for event in events))
        cache.delete(_login_key(self.admin.username,"10.0.0.1")); cache.delete(_login_key(self.admin.username,"10.0.0.2"))

    def test_admin_session_idle_absolute_and_role_revocation(self):
        login_url=reverse("admin_login")
        with patch("market.admin_views.time.time",return_value=1000):
            self.assertEqual(self.client.post(login_url,{"username":self.admin.username,"password":"very-secure-password"}).status_code,302)
        session=self.client.session; session["ops_started"]=1000; session["ops_last"]=1000; session.save()
        with patch("market.middleware.time.time",return_value=1899): self.assertEqual(self.client.get(reverse("ops_dashboard")).status_code,200)
        session=self.client.session; session["ops_started"]=1; session["ops_last"]=28800; session.save()
        with patch("market.middleware.time.time",return_value=28800): self.assertEqual(self.client.get(reverse("ops_dashboard")).status_code,200)
        with patch("market.middleware.time.time",return_value=28802): self.assertEqual(self.client.get(reverse("ops_dashboard")).status_code,403)
        self.assertEqual(SecurityEvent.objects.filter(event_type="ADMIN_SESSION_EXPIRED").count(),1)
        self.client.force_login(self.admin); self.admin.role=User.Role.USER; self.admin.save(update_fields=["role"])
        self.assertEqual(self.client.get(reverse("ops_dashboard")).status_code,403)

    @override_settings(TRANSFER_RATE_LIMIT_PER_MINUTE=50, CHAT_RATE_LIMIT_PER_MINUTE=100)
    def test_reversal_detail_uses_existing_service_and_reported_chat_is_linked(self):
        self.user.wallet.balance=10; self.user.wallet.save(update_fields=["balance"])
        original=transfer(sender=self.user,recipient=self.superadmin,amount=1,idempotency_key=uuid.uuid4())
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("ops_transaction_detail",args=[original.public_id])).status_code,200)
        self.assertEqual(self.client.get(reverse("ops_reverse",args=[original.public_id])).status_code,403)
        self.assertEqual(self.client.post(reverse("ops_reverse",args=[original.public_id]),{"reason":"review","current_password":"very-secure-password"}).status_code,302)
        self.assertTrue(AuditLog.objects.filter(action="wallet.reverse",actor=self.admin).exists())
        room=direct_room(sender=self.user,recipient=self.admin); message=send_message(sender=self.admin,room=room,content="reported")
        report=create_report(reporter=self.user,target_type=Report.Target.MESSAGE,target_id=message.public_id,reason="ABUSE")
        self.client.force_login(self.mod)
        self.assertEqual(self.client.get(reverse("ops_reported_chat",args=[report.public_id])).status_code,403)
        self.assertEqual(self.client.post(reverse("ops_reported_chat",args=[report.public_id]),{"reason":"investigation"}).status_code,200)
        self.assertTrue(AuditLog.objects.filter(action="chat.direct_view",actor=self.mod,target=str(room.public_id)).exists())

    @override_settings(ADMIN_LOGIN_RATE_LIMIT_PER_MINUTE=1, ADMIN_LOGIN_RATE_LIMIT_TTL_SECONDS=1)
    def test_real_redis_login_ttl_and_key_privacy(self):
        from market.admin_views import _login_key
        key=_login_key(self.admin.username,"10.0.0.9"); cache.delete(key)
        url=reverse("admin_login")
        self.assertEqual(self.client.post(url,{"username":self.admin.username,"password":"wrong"},REMOTE_ADDR="10.0.0.9").status_code,200)
        self.assertEqual(self.client.post(url,{"username":self.admin.username,"password":"very-secure-password"},REMOTE_ADDR="10.0.0.9").status_code,403)
        self.assertNotIn(self.admin.username,key); self.assertNotIn("10.0.0.9",key)
        time.sleep(1.1)
        self.assertEqual(self.client.post(url,{"username":self.admin.username,"password":"very-secure-password"},REMOTE_ADDR="10.0.0.9").status_code,302)
        cache.delete(key)

    def test_postgresql_concurrent_report_assignment_has_one_winner(self):
        report=Report.objects.create(reporter=self.user,target_type=Report.Target.PRODUCT,target_id=self.product.public_id,reason="SPAM")
        barrier=threading.Barrier(2); results=[]; lock=threading.Lock()
        def assign(assignee_id):
            close_old_connections()
            try:
                actor=User.objects.get(pk=self.superadmin.pk); assignee=User.objects.get(pk=assignee_id); target=Report.objects.get(pk=report.pk)
                barrier.wait(); assign_report(actor=actor,report=target,assignee=assignee,reason="concurrent",expected_version=0); outcome="ok"
            except ValidationError: outcome="conflict"
            finally:
                close_old_connections()
            with lock: results.append(outcome)
        threads=[threading.Thread(target=assign,args=(self.mod.pk,)),threading.Thread(target=assign,args=(self.admin.pk,))]
        [thread.start() for thread in threads]; [thread.join() for thread in threads]
        report.refresh_from_db(); self.assertEqual(sorted(results),["conflict","ok"]); self.assertEqual(report.assignment_version,1)
        self.assertEqual(AuditLog.objects.filter(action="report.assign",target=str(report.public_id)).count(),1)

    @override_settings(TRANSFER_RATE_LIMIT_PER_MINUTE=50, ADMIN_GRANT_RATE_LIMIT_PER_MINUTE=50)
    def test_reauthentication_299_300_301_boundaries_on_important_post(self):
        self.user.wallet.balance=10; self.user.wallet.save(update_fields=["balance"])
        self.client.force_login(self.admin)
        url=reverse("ops_grant")
        base={"recipient":str(self.user.public_id),"amount":"1","reason":"test","idempotency_key":str(uuid.uuid4()),"current_password":"very-secure-password"}
        session=self.client.session; session["ops_reauth_at"]=1000; session.save()
        with patch("market.admin_views.time.time",return_value=1299): self.assertEqual(self.client.post(url,base).status_code,302)
        base["idempotency_key"]=str(uuid.uuid4()); base["current_password"]="wrong"
        with patch("market.admin_views.time.time",return_value=1300): self.assertEqual(self.client.post(url,base).status_code,403)
        with patch("market.admin_views.time.time",return_value=1301): self.assertEqual(self.client.post(url,base).status_code,403)
        events=SecurityEvent.objects.filter(event_type__startswith="ADMIN_REAUTH")
        self.assertTrue(events.filter(event_type="ADMIN_REAUTH_FAILURE").exists())
        self.assertFalse(any("very-secure-password" in event.detail for event in events))

    def test_admin_login_redis_error_is_fail_closed_without_sensitive_event(self):
        from redis.exceptions import RedisError
        url=reverse("admin_login")
        with patch("market.admin_views.cache.add",side_effect=RedisError("offline")):
            response=self.client.post(url,{"username":self.admin.username,"password":"very-secure-password"},REMOTE_ADDR="10.0.0.8")
        self.assertEqual(response.status_code,403)
        event=SecurityEvent.objects.filter(event_type="ADMIN_LOGIN_RATE_LIMIT_BACKEND_ERROR").latest("created_at")
        self.assertNotIn(self.admin.username,event.detail); self.assertNotIn("very-secure-password",event.detail)

    @override_settings(TRANSFER_RATE_LIMIT_PER_MINUTE=50, CHAT_RATE_LIMIT_PER_MINUTE=100)
    def test_reversal_and_reported_chat_csrf_authorization_and_visibility(self):
        self.user.wallet.balance=20; self.user.wallet.save(update_fields=["balance"])
        original=transfer(sender=self.user,recipient=self.superadmin,amount=2,idempotency_key=uuid.uuid4())
        secure=Client(enforce_csrf_checks=True); secure.force_login(self.admin)
        detail=reverse("ops_transaction_detail",args=[original.public_id]); reverse_url=reverse("ops_reverse",args=[original.public_id])
        secure.get(detail)
        self.assertEqual(secure.post(reverse_url,{"reason":"x","current_password":"very-secure-password"}).status_code,403)
        self.client.force_login(self.mod); self.assertEqual(self.client.post(reverse_url,{"reason":"x","current_password":"very-secure-password"}).status_code,403)
        before=(WalletTransaction.objects.count(),LedgerEntry.objects.count(),AuditLog.objects.filter(action="wallet.reverse").count())
        self.client.force_login(self.admin); self.assertEqual(self.client.post(reverse_url,{"reason":"","current_password":"very-secure-password"}).status_code,302)
        self.assertEqual(before,(WalletTransaction.objects.count(),LedgerEntry.objects.count(),AuditLog.objects.filter(action="wallet.reverse").count()))
        room=direct_room(sender=self.user,recipient=self.admin)
        for i in range(55): send_message(sender=self.admin,room=room,content=f"m{i}")
        hidden=send_message(sender=self.admin,room=room,content="hidden"); moderate_message(actor=self.mod,message=hidden,reason="hide")
        message=room.messages.filter(status=ChatMessage.Status.VISIBLE).first(); report=create_report(reporter=self.user,target_type=Report.Target.MESSAGE,target_id=message.public_id,reason="ABUSE")
        chat_url=reverse("ops_reported_chat",args=[report.public_id]); secure.force_login(self.mod); secure.get(chat_url)
        self.assertEqual(secure.post(chat_url,{"reason":"review"}).status_code,403)
        self.client.force_login(self.mod); self.assertEqual(self.client.get(chat_url).status_code,403)
        before_logs=AuditLog.objects.filter(action="chat.direct_view").count(); response=self.client.post(chat_url,{"reason":"review"})
        self.assertEqual(response.status_code,200); self.assertLessEqual(len(response.context["messages"]),50); self.assertNotIn(hidden.pk,[item.pk for item in response.context["messages"]])
        self.assertEqual(AuditLog.objects.filter(action="chat.direct_view").count(),before_logs+1)
