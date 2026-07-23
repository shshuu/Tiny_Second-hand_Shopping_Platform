from django.core.exceptions import ValidationError
from django.test import TransactionTestCase, override_settings
from django.test import Client
from django.conf import settings
from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from config.asgi import application
from market.models import AuditLog, AutoModerationCase, Category, ChatMessage, Product, Report, User
from market.services import (assign_auto_case, community_room, create_report, register_user,
    review_auto_case, send_community_message, start_auto_case_review, unread_chat_summary)


@override_settings(CHAT_RATE_LIMIT_PER_MINUTE=100)
class CommunityAndAutoModerationTests(TransactionTestCase):
    def setUp(self):
        self.seller=register_user(username="auto_seller",password="very-secure-password",display_name="Seller")
        self.reporters=[register_user(username=f"auto_r{i}",password="very-secure-password",display_name=f"R{i}") for i in range(5)]
        category=Category.objects.create(name="Auto",slug="auto")
        self.product=Product.objects.create(seller=self.seller,category=category,title="Visible",description="description",price=1,condition="USED",status=Product.Status.ACTIVE)

    def test_community_persists_without_unread_and_restricted_cannot_send(self):
        message=send_community_message(sender=self.reporters[0],content="<b>hello</b>")
        self.assertEqual(message.room,community_room())
        self.assertEqual(unread_chat_summary(self.reporters[1]),(0,{}))
        self.reporters[1].status=User.Status.RESTRICTED; self.reporters[1].save(update_fields=["status"])
        with self.assertRaises(ValidationError): send_community_message(sender=self.reporters[1],content="no")

    def test_product_three_active_reporters_hide_once_and_user_five_restrict(self):
        for reporter in self.reporters[:2]: create_report(reporter=reporter,target_type=Report.Target.PRODUCT,target_id=self.product.public_id,reason="SPAM")
        self.product.refresh_from_db(); self.assertEqual(self.product.status,Product.Status.ACTIVE)
        create_report(reporter=self.reporters[2],target_type=Report.Target.PRODUCT,target_id=self.product.public_id,reason="SPAM")
        self.product.refresh_from_db(); self.assertEqual(self.product.status,Product.Status.HIDDEN)
        self.assertEqual(AutoModerationCase.objects.filter(target_type="PRODUCT").count(),1)
        target=register_user(username="reported_target",password="very-secure-password",display_name="Target")
        for reporter in self.reporters: create_report(reporter=reporter,target_type=Report.Target.USER,target_id=target.public_id,reason="ABUSE")
        target.refresh_from_db(); self.assertEqual(target.status,User.Status.RESTRICTED)
        self.assertEqual(AutoModerationCase.objects.filter(target_type="USER").count(),1)

    def test_hidden_community_message_is_not_returned_to_public_history(self):
        message=send_community_message(sender=self.reporters[0],content="hidden")
        message.status=ChatMessage.Status.HIDDEN; message.save(update_fields=["status"])
        self.assertFalse(community_room().messages.filter(status=ChatMessage.Status.VISIBLE,pk=message.pk).exists())

    def test_auto_case_rejection_restores_only_unchanged_automatic_state_and_is_single_use(self):
        for reporter in self.reporters[:3]: create_report(reporter=reporter,target_type=Report.Target.PRODUCT,target_id=self.product.public_id,reason="SPAM")
        case=AutoModerationCase.objects.get(target_type="PRODUCT")
        moderator=register_user(username="auto_mod",password="very-secure-password",display_name="Mod"); moderator.role=User.Role.MODERATOR; moderator.save(update_fields=["role"])
        review_auto_case(actor=moderator,case=case,accepted=False,reason="not enough evidence")
        self.product.refresh_from_db(); case.refresh_from_db()
        self.assertEqual(self.product.status,Product.Status.ACTIVE); self.assertEqual(case.review_status,AutoModerationCase.Review.REJECTED)
        self.assertTrue(AuditLog.objects.filter(action="moderation.auto_case_reject",actor=moderator).exists())
        with self.assertRaises(ValidationError): review_auto_case(actor=moderator,case=case,accepted=False,reason="again")

    def test_manual_state_change_after_auto_action_is_not_overwritten_on_rejection(self):
        for reporter in self.reporters[:3]: create_report(reporter=reporter,target_type=Report.Target.PRODUCT,target_id=self.product.public_id,reason="SPAM")
        case=AutoModerationCase.objects.get(target_type="PRODUCT")
        self.product.status=Product.Status.DELETED; self.product.save(update_fields=["status"])
        moderator=register_user(username="auto_mod_two",password="very-secure-password",display_name="Mod"); moderator.role=User.Role.MODERATOR; moderator.save(update_fields=["role"])
        review_auto_case(actor=moderator,case=case,accepted=False,reason="manual action retained")
        self.product.refresh_from_db(); self.assertEqual(self.product.status,Product.Status.DELETED)

    def test_auto_case_assignment_review_and_readonly_completion_are_optimistic(self):
        for reporter in self.reporters[:3]: create_report(reporter=reporter,target_type=Report.Target.PRODUCT,target_id=self.product.public_id,reason="SPAM")
        case=AutoModerationCase.objects.get(target_type="PRODUCT")
        moderator=register_user(username="case_mod",password="very-secure-password",display_name="Mod"); moderator.role=User.Role.MODERATOR; moderator.save(update_fields=["role"])
        other=register_user(username="case_other",password="very-secure-password",display_name="Other"); other.role=User.Role.ADMIN; other.save(update_fields=["role"])
        assigned=assign_auto_case(actor=moderator,case=case,assignee=other,expected_version=0)
        self.assertEqual((assigned.assigned_to,assigned.assignment_version),(other,1))
        with self.assertRaises(ValidationError): assign_auto_case(actor=moderator,case=assigned,assignee=moderator,expected_version=0)
        started=start_auto_case_review(actor=other,case=assigned)
        self.assertIsNotNone(started.started_at); self.assertEqual(started.review_status,AutoModerationCase.Review.REVIEWING)
        reviewed=review_auto_case(actor=other,case=started,accepted=True,reason="policy confirmed")
        self.assertEqual(reviewed.review_status,AutoModerationCase.Review.ACCEPTED)
        with self.assertRaises(ValidationError): start_auto_case_review(actor=other,case=reviewed)
        self.assertTrue(AuditLog.objects.filter(action="moderation.auto_case_assign",target=str(case.public_id)).exists())

    def test_community_report_hide_flow_preserves_audit_and_hides_content(self):
        message=send_community_message(sender=self.seller,content="reportable community message")
        report=create_report(reporter=self.reporters[0],target_type=Report.Target.MESSAGE,target_id=message.public_id,reason="ABUSE")
        moderator=register_user(username="community_mod",password="very-secure-password",display_name="Mod"); moderator.role=User.Role.MODERATOR; moderator.save(update_fields=["role"])
        from market.services import moderate_message
        moderate_message(actor=moderator,message=message,reason="policy breach")
        message.refresh_from_db()
        self.assertEqual(message.status,ChatMessage.Status.HIDDEN)
        self.assertFalse(community_room().messages.filter(pk=message.pk,status=ChatMessage.Status.VISIBLE).exists())
        self.assertTrue(AuditLog.objects.filter(action="chat.message_hide",target=str(message.public_id)).exists())
        self.assertEqual(report.target_id,message.public_id)

    def test_community_websocket_rejects_anonymous_and_persists_active_message(self):
        anonymous=WebsocketCommunicator(application,"/ws/community/")
        client=Client(); client.force_login(self.reporters[0]); cookie=client.cookies[settings.SESSION_COOKIE_NAME].value
        active=WebsocketCommunicator(application,"/ws/community/",headers=[(b"cookie",f"{settings.SESSION_COOKIE_NAME}={cookie}".encode())])
        async def run():
            self.assertFalse((await anonymous.connect())[0]); self.assertTrue((await active.connect())[0])
            await active.send_to(text_data='{"content":"hello community"}')
            self.assertEqual((await active.receive_json_from())["content"],"hello community")
            await active.disconnect()
        async_to_sync(run)()
        self.assertTrue(ChatMessage.objects.filter(content="hello community",room__room_type="GLOBAL").exists())
