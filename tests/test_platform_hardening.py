import uuid
from io import BytesIO
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from PIL import Image
from market.models import AuditLog, Category, ChatMessage, Product, Report, User
from market.services import change_product_status, create_report, create_user_by_admin, direct_room, register_user, send_message

class PlatformHardeningTests(TestCase):
    def setUp(self):
        self.admin=register_user(username="hardadmin",password="very-secure-password",display_name="Admin"); self.admin.role=User.Role.ADMIN; self.admin.save()
        self.a=register_user(username="harda",password="very-secure-password",display_name="A")
        self.b=register_user(username="hardb",password="very-secure-password",display_name="B")
        self.c=register_user(username="hardc",password="very-secure-password",display_name="C")
        self.d=register_user(username="hardd",password="very-secure-password",display_name="D")
        self.category=Category.objects.create(name="Hardening",slug="hardening")
        self.product=Product.objects.create(seller=self.b,category=self.category,title="Product",description="Description",price=10,condition="USED")
    def test_admin_creation_uses_registration_and_role_is_enforced(self):
        with self.assertRaises(ValidationError): create_user_by_admin(actor=self.a,username="noadmin",password="very-secure-password",display_name="No")
        user=create_user_by_admin(actor=self.admin,username="createdadmin",password="very-secure-password",display_name="Created")
        self.assertTrue(hasattr(user,"profile")); self.assertEqual(user.wallet.balance,0)
    def test_product_status_transitions_are_server_controlled(self):
        change_product_status(seller=self.b,product=self.product,status=Product.Status.ACTIVE)
        change_product_status(seller=self.b,product=self.product,status=Product.Status.RESERVED)
        change_product_status(seller=self.b,product=self.product,status=Product.Status.SOLD)
        with self.assertRaises(ValidationError): change_product_status(seller=self.b,product=self.product,status=Product.Status.ACTIVE)
        with self.assertRaises(ValidationError): change_product_status(seller=self.a,product=self.product,status=Product.Status.RESERVED)
    def test_reports_target_types_and_auto_actions(self):
        for reporter in (self.a,self.c,self.d): create_report(reporter=reporter,target_type=Report.Target.PRODUCT,target_id=self.product.public_id,reason="SPAM")
        self.product.refresh_from_db(); self.assertEqual(self.product.status,Product.Status.HIDDEN)
        with self.assertRaises(ValidationError): create_report(reporter=self.b,target_type=Report.Target.PRODUCT,target_id=self.product.public_id,reason="SPAM")
        for reporter in (self.b,self.c,self.d): create_report(reporter=reporter,target_type=Report.Target.USER,target_id=self.a.public_id,reason="ABUSE")
        self.a.refresh_from_db(); self.assertEqual(self.a.status,User.Status.RESTRICTED); self.assertTrue(AuditLog.objects.filter(action="report.auto_restrict").exists())
    def test_message_self_report_and_duplicate_are_rejected(self):
        room=direct_room(sender=self.a,recipient=self.b); message=send_message(sender=self.a,room=room,content="hello")
        with self.assertRaises(ValidationError): create_report(reporter=self.a,target_type=Report.Target.MESSAGE,target_id=message.public_id,reason="ABUSE")
        create_report(reporter=self.b,target_type=Report.Target.MESSAGE,target_id=message.public_id,reason="ABUSE")
        with self.assertRaises(Exception): create_report(reporter=self.b,target_type=Report.Target.MESSAGE,target_id=message.public_id,reason="ABUSE")
    def test_search_paginates_and_excludes_hidden(self):
        for i in range(25): Product.objects.create(seller=self.b,category=self.category,title=f"Search {i}",description="x",price=i+1,condition="USED",status=Product.Status.ACTIVE)
        hidden=Product.objects.create(seller=self.b,category=self.category,title="Search hidden",description="x",price=1,condition="USED",status=Product.Status.HIDDEN)
        response=self.client.get(reverse("product_list"),{"q":"Search","page":"2","sort":"price_low"})
        self.assertEqual(response.status_code,200); self.assertEqual(response.context["page_obj"].number,2); self.assertNotContains(response,hidden.title)
