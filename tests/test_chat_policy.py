from django.core.exceptions import ValidationError
from django.test import TestCase
from market.models import Block, Report, User
from market.services import create_report, direct_room, register_user, send_message, transition_report

class ChatPolicyTests(TestCase):
    def setUp(self):
        self.a=register_user(username="cpa",password="very-secure-password",display_name="A")
        self.b=register_user(username="cpb",password="very-secure-password",display_name="B")
        self.c=register_user(username="cpc",password="very-secure-password",display_name="C")
        self.admin=register_user(username="cpadmin",password="very-secure-password",display_name="Admin"); self.admin.role=User.Role.MODERATOR; self.admin.save()
    def test_restricted_users_cannot_send_direct_messages(self):
        room=direct_room(sender=self.a, recipient=self.b)
        self.assertEqual(send_message(sender=self.a,room=room,content="direct").sender,self.a)
        self.a.status=User.Status.RESTRICTED; self.a.save()
        with self.assertRaises(ValidationError): send_message(sender=self.a,room=room,content="blocked")
    def test_direct_block_and_suspension_are_shared_service_policy(self):
        room=direct_room(sender=self.a,recipient=self.b); Block.objects.create(blocker=self.b,blocked=self.a)
        with self.assertRaises(ValidationError): send_message(sender=self.a,room=room,content="blocked")
        Block.objects.all().delete(); self.a.status=User.Status.SUSPENDED; self.a.save()
        with self.assertRaises(ValidationError): send_message(sender=self.a,room=room,content="suspended")
    def test_report_transition_requires_authority_reason_and_is_audited(self):
        report=create_report(reporter=self.a,target_type=Report.Target.USER,target_id=self.b.public_id,reason="ABUSE")
        with self.assertRaises(ValidationError): transition_report(actor=self.a,report=report,status=Report.Status.REVIEWING,reason="x")
        transition_report(actor=self.admin,report=report,status=Report.Status.REVIEWING,reason="review")
        transition_report(actor=self.admin,report=report,status=Report.Status.ACCEPTED,reason="valid")
        transition_report(actor=self.admin,report=report,status=Report.Status.RESOLVED,reason="done")
        with self.assertRaises(ValidationError): transition_report(actor=self.admin,report=report,status=Report.Status.PENDING,reason="no")
