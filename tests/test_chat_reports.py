from django.core.exceptions import ValidationError
from django.test import TestCase
from market.models import Block, Category, Product, Report, User
from market.services import create_report, direct_room, send_message

class ChatAndReportTests(TestCase):
    def setUp(self):
        self.a=User.objects.create_user(username="alpha",password="very-secure-password",display_name="Alpha")
        self.b=User.objects.create_user(username="bravo",password="very-secure-password",display_name="Bravo")
        self.c=User.objects.create_user(username="charlie",password="very-secure-password",display_name="Charlie")
        self.d=User.objects.create_user(username="delta",password="very-secure-password",display_name="Delta")
        category=Category.objects.create(name="도서",slug="books")
        self.product=Product.objects.create(seller=self.b,category=category,title="책",description="책",price=100,condition="USED",status="ACTIVE")
    def test_direct_chat_only_participants_can_send(self):
        room=direct_room(sender=self.a,recipient=self.b,product=self.product)
        self.assertEqual(direct_room(sender=self.a,recipient=self.b,product=self.product).id,room.id)
        send_message(sender=self.a,room=room,content="안녕하세요")
        with self.assertRaises(ValidationError): send_message(sender=self.c,room=room,content="침입")
    def test_block_prevents_direct_chat(self):
        Block.objects.create(blocker=self.b,blocked=self.a)
        with self.assertRaises(ValidationError): direct_room(sender=self.a,recipient=self.b)
    def test_three_distinct_reports_hide_product(self):
        for reporter in (self.a,self.c,self.d): create_report(reporter=reporter,target_type=Report.Target.PRODUCT,target_id=self.product.public_id,reason="SPAM")
        self.product.refresh_from_db(); self.assertEqual(self.product.status,Product.Status.HIDDEN)
    def test_duplicate_report_is_rejected(self):
        create_report(reporter=self.a,target_type=Report.Target.PRODUCT,target_id=self.product.public_id,reason="SPAM")
        with self.assertRaises(Exception): create_report(reporter=self.a,target_type=Report.Target.PRODUCT,target_id=self.product.public_id,reason="SPAM")
