import uuid

from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from market.models import AuditLog, Category, ChatMessage, ChatRoom, Product, Report, User
from market.services import (
    change_product_status, create_report, direct_room,
    register_user, send_message, transfer, transition_report,
)


class ReportAndRestrictionGateTests(TestCase):
    def setUp(self):
        self.moderator=register_user(username="gate_mod",password="very-secure-password",display_name="Moderator")
        self.moderator.role=User.Role.MODERATOR; self.moderator.save(update_fields=["role"])
        self.a=register_user(username="gate_a",password="very-secure-password",display_name="A")
        self.b=register_user(username="gate_b",password="very-secure-password",display_name="B")
        self.c=register_user(username="gate_c",password="very-secure-password",display_name="C")
        self.category=Category.objects.create(name="Gate",slug="gate")
        self.product=Product.objects.create(seller=self.a,category=self.category,title="Gate product",description="x",price=10,condition="USED")
        self.direct=direct_room(sender=self.a,recipient=self.b)

    def test_report_transitions_are_authorized_and_audited(self):
        report=create_report(reporter=self.a,target_type=Report.Target.USER,target_id=self.b.public_id,reason="ABUSE")
        transition_report(actor=self.moderator,report=report,status=Report.Status.REVIEWING,reason="triage")
        transition_report(actor=self.moderator,report=report,status=Report.Status.ACCEPTED,reason="confirmed")
        transition_report(actor=self.moderator,report=report,status=Report.Status.RESOLVED,reason="action complete")
        log=AuditLog.objects.filter(action="report.transition",target=str(report.public_id)).order_by("-created_at").first()
        self.assertEqual(log.actor,self.moderator); self.assertIn("ACCEPTED->RESOLVED",log.reason); self.assertIn("action complete",log.reason); self.assertIsNotNone(log.created_at)
        with self.assertRaises(ValidationError): transition_report(actor=self.moderator,report=report,status=Report.Status.PENDING,reason="bad")
        with self.assertRaises(ValidationError): transition_report(actor=self.a,report=report,status=Report.Status.REVIEWING,reason="unauthorized")
        rejected=create_report(reporter=self.c,target_type=Report.Target.PRODUCT,target_id=self.product.public_id,reason="SPAM")
        transition_report(actor=self.moderator,report=rejected,status=Report.Status.REJECTED,reason="not supported")
        with self.assertRaises(ValidationError): transition_report(actor=self.moderator,report=rejected,status=Report.Status.RESOLVED,reason="terminal")
        fresh=create_report(reporter=self.a,target_type=Report.Target.MESSAGE,target_id=send_message(sender=self.b,room=self.direct,content="report target").public_id,reason="ABUSE")
        # Triage begins without a disposition reason; accept/reject requires one.
        transition_report(actor=self.moderator,report=fresh,status=Report.Status.REVIEWING,reason="")
        with self.assertRaises(ValidationError): transition_report(actor=self.moderator,report=fresh,status=Report.Status.ACCEPTED,reason="")

    @override_settings(TRANSFER_RATE_LIMIT_PER_MINUTE=50, CHAT_RATE_LIMIT_PER_MINUTE=50)
    def test_restricted_and_suspended_are_blocked_and_active_recovers(self):
        self.a.wallet.balance=100; self.a.wallet.save(update_fields=["balance"])
        for status, report_target in ((User.Status.RESTRICTED,self.b),(User.Status.SUSPENDED,self.c)):
            self.a.status=status; self.a.save(update_fields=["status"])
            self.client.force_login(self.a)
            response=self.client.post(reverse("product_create"),{"category":self.category.pk,"title":"blocked","description":"x","price":1,"condition":"USED"})
            self.assertEqual(response.status_code,403)
            with self.assertRaises(ValidationError): change_product_status(seller=self.a,product=self.product,status=Product.Status.ACTIVE)
            with self.assertRaises(ValidationError): send_message(sender=self.a,room=self.direct,content="direct blocked")
            with self.assertRaises(ValidationError): send_message(sender=self.a,room=self.direct,content="direct blocked")
            with self.assertRaises(ValidationError): transfer(sender=self.a,recipient=self.b,amount=1,idempotency_key=uuid.uuid4())
            # Restricted and suspended accounts cannot create new reports; they
            # may still sign in to see their existing state and notices.
            with self.assertRaises(ValidationError): create_report(reporter=self.a,target_type=Report.Target.USER,target_id=report_target.public_id,reason="ABUSE")
        self.a.status=User.Status.ACTIVE; self.a.save(update_fields=["status"])
        change_product_status(seller=self.a,product=self.product,status=Product.Status.ACTIVE)
        self.assertEqual(send_message(sender=self.a,room=self.direct,content="restored").sender,self.a)
        self.assertEqual(transfer(sender=self.a,recipient=self.b,amount=1,idempotency_key=uuid.uuid4()).transaction_type,"USER_TRANSFER")

    def test_all_report_targets_require_an_active_reporter_and_keep_existing_reports(self):
        community=ChatRoom.objects.create(room_type=ChatRoom.Type.GLOBAL)
        direct_message=send_message(sender=self.b,room=self.direct,content="direct target")
        community_message=ChatMessage.objects.create(room=community,sender=self.b,content="community target")
        targets=[(Report.Target.PRODUCT,self.product.public_id),(Report.Target.USER,self.b.public_id),(Report.Target.MESSAGE,direct_message.public_id),(Report.Target.MESSAGE,community_message.public_id)]
        reporter=self.c
        for kind,target in targets: self.assertIsNotNone(create_report(reporter=reporter,target_type=kind,target_id=target,reason="ABUSE"))
        before=Report.objects.filter(reporter=reporter).count()
        for status in (User.Status.RESTRICTED,User.Status.SUSPENDED):
            reporter.status=status; reporter.save(update_fields=["status"])
            for kind,target in targets:
                with self.assertRaises(ValidationError): create_report(reporter=reporter,target_type=kind,target_id=target,reason="ABUSE")
            self.assertEqual(Report.objects.filter(reporter=reporter).count(),before)
        reporter.status=User.Status.ACTIVE; reporter.is_active=False; reporter.save(update_fields=["status","is_active"])
        with self.assertRaises(ValidationError): create_report(reporter=reporter,target_type=Report.Target.USER,target_id=self.b.public_id,reason="ABUSE")
