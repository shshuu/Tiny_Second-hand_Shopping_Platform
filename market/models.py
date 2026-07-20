import os
import uuid
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q

class User(AbstractUser):
    class Role(models.TextChoices): USER="USER"; MODERATOR="MODERATOR"; ADMIN="ADMIN"; SUPERADMIN="SUPERADMIN"
    class Status(models.TextChoices): ACTIVE="ACTIVE"; RESTRICTED="RESTRICTED"; SUSPENDED="SUSPENDED"; DORMANT="DORMANT"; DELETED="DELETED"
    public_id=models.UUIDField(default=uuid.uuid4,unique=True,editable=False); display_name=models.CharField(max_length=30)
    role=models.CharField(max_length=12,choices=Role.choices,default=Role.USER)
    status=models.CharField(max_length=12,choices=Status.choices,default=Status.ACTIVE)
    def can_manage(self): return self.role in {self.Role.MODERATOR,self.Role.ADMIN,self.Role.SUPERADMIN}
    def can_transfer(self): return self.status == self.Status.ACTIVE

class Profile(models.Model):
    user=models.OneToOneField(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="profile")
    bio=models.CharField(max_length=500,blank=True)

class Block(models.Model):
    blocker=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="blocks")
    blocked=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="blocked_by")
    class Meta: constraints=[models.UniqueConstraint(fields=["blocker","blocked"],name="unique_block")]

class Category(models.Model):
    name=models.CharField(max_length=50,unique=True); slug=models.SlugField(unique=True); is_active=models.BooleanField(default=True)
    def __str__(self): return self.name

class Product(models.Model):
    class Status(models.TextChoices): DRAFT="DRAFT"; ACTIVE="ACTIVE"; RESERVED="RESERVED"; SOLD="SOLD"; HIDDEN="HIDDEN"; DELETED="DELETED"
    public_id=models.UUIDField(default=uuid.uuid4,unique=True,editable=False)
    seller=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="products")
    category=models.ForeignKey(Category,on_delete=models.PROTECT)
    title=models.CharField(max_length=100); description=models.TextField(max_length=5000); price=models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    condition=models.CharField(max_length=20,choices=[(x,x) for x in ("NEW","LIKE_NEW","USED","NEEDS_REPAIR")])
    status=models.CharField(max_length=10,choices=Status.choices,default=Status.DRAFT); created_at=models.DateTimeField(auto_now_add=True); updated_at=models.DateTimeField(auto_now=True)
    class Meta: indexes=[models.Index(fields=["status","created_at"],name="market_prod_status_created_idx"),models.Index(fields=["category","price"],name="market_prod_category_price_idx"),models.Index(fields=["seller","status"],name="market_prod_seller_status_idx")]

def product_image_path(instance, filename): return f"products/{instance.product.public_id}/{uuid.uuid4()}{os.path.splitext(filename)[1].lower()}"
class ProductImage(models.Model):
    product=models.ForeignKey(Product,on_delete=models.CASCADE,related_name="images"); image=models.ImageField(upload_to=product_image_path)
    original_name=models.CharField(max_length=255); mime_type=models.CharField(max_length=50); size=models.PositiveIntegerField(); display_order=models.PositiveSmallIntegerField(default=0); created_at=models.DateTimeField(auto_now_add=True)
    class Meta: ordering=("display_order","id")

class ChatRoom(models.Model):
    class Type(models.TextChoices): GLOBAL="GLOBAL"; DIRECT="DIRECT"
    public_id=models.UUIDField(default=uuid.uuid4,unique=True,editable=False); room_type=models.CharField(max_length=10,choices=Type.choices); related_product=models.ForeignKey(Product,on_delete=models.SET_NULL,null=True,blank=True); created_at=models.DateTimeField(auto_now_add=True)
class ChatParticipant(models.Model):
    room=models.ForeignKey(ChatRoom,on_delete=models.CASCADE,related_name="participants"); user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE); joined_at=models.DateTimeField(auto_now_add=True)
    class Meta: constraints=[models.UniqueConstraint(fields=["room","user"],name="unique_chat_participant")]
class ChatMessage(models.Model):
    class Status(models.TextChoices): VISIBLE="VISIBLE"; HIDDEN="HIDDEN"; DELETED="DELETED"
    public_id=models.UUIDField(default=uuid.uuid4,unique=True,editable=False); room=models.ForeignKey(ChatRoom,on_delete=models.CASCADE,related_name="messages"); sender=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT); content=models.CharField(max_length=1000); status=models.CharField(max_length=10,choices=Status.choices,default=Status.VISIBLE); created_at=models.DateTimeField(auto_now_add=True)

class Report(models.Model):
    class Target(models.TextChoices): USER="USER"; PRODUCT="PRODUCT"; MESSAGE="MESSAGE"
    class Status(models.TextChoices): PENDING="PENDING"; REVIEWING="REVIEWING"; ACCEPTED="ACCEPTED"; REJECTED="REJECTED"; RESOLVED="RESOLVED"
    public_id=models.UUIDField(default=uuid.uuid4,unique=True,editable=False); reporter=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="reports"); target_type=models.CharField(max_length=10,choices=Target.choices); target_id=models.UUIDField(); reason=models.CharField(max_length=30); description=models.CharField(max_length=1000,blank=True); status=models.CharField(max_length=12,choices=Status.choices,default=Status.PENDING); assigned_to=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True,related_name="assigned_reports"); assignment_version=models.PositiveIntegerField(default=0); created_at=models.DateTimeField(auto_now_add=True)
    class Meta: constraints=[models.UniqueConstraint(fields=["reporter","target_type","target_id"],name="unique_report_target")]

class Wallet(models.Model):
    public_id=models.UUIDField(default=uuid.uuid4,unique=True,editable=False); user=models.OneToOneField(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name="wallet"); balance=models.PositiveBigIntegerField(default=0)
    class Meta: constraints=[models.CheckConstraint(condition=Q(balance__gte=0),name="wallet_non_negative_balance")]

class WalletTransaction(models.Model):
    class Type(models.TextChoices): WELCOME="WELCOME_BONUS"; TEST="TEST_CREDIT"; GRANT="ADMIN_GRANT"; DEBIT="ADMIN_DEBIT"; TRANSFER="USER_TRANSFER"; REVERSAL="REVERSAL"
    public_id=models.UUIDField(default=uuid.uuid4,unique=True,editable=False); transaction_type=models.CharField(max_length=20,choices=Type.choices)
    source=models.ForeignKey(Wallet,on_delete=models.PROTECT,null=True,blank=True,related_name="outgoing"); destination=models.ForeignKey(Wallet,on_delete=models.PROTECT,null=True,blank=True,related_name="incoming")
    amount=models.PositiveBigIntegerField(validators=[MinValueValidator(1)]); idempotency_key=models.UUIDField(unique=True); grant_key=models.CharField(max_length=100,null=True,blank=True)
    memo=models.CharField(max_length=200,blank=True); original_transaction=models.OneToOneField("self",on_delete=models.PROTECT,null=True,blank=True,related_name="reversal"); created_by=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name="created_wallet_transactions"); created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints=[models.CheckConstraint(condition=Q(amount__gt=0),name="transaction_positive_amount"),models.CheckConstraint(condition=Q(source__isnull=True)|Q(destination__isnull=True)|~Q(source=F("destination")),name="transaction_distinct_wallets"),models.UniqueConstraint(fields=["grant_key"],condition=Q(grant_key__isnull=False),name="unique_non_null_grant_key")]

class LedgerEntry(models.Model):
    transaction=models.ForeignKey(WalletTransaction,on_delete=models.PROTECT,related_name="entries"); wallet=models.ForeignKey(Wallet,on_delete=models.PROTECT); entry_type=models.CharField(max_length=8,choices=[("CREDIT","CREDIT"),("DEBIT","DEBIT")]); amount=models.PositiveBigIntegerField(); balance_before=models.PositiveBigIntegerField(); balance_after=models.PositiveBigIntegerField(); created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=["transaction","wallet"],name="one_ledger_per_wallet_transaction"),models.CheckConstraint(condition=Q(amount__gt=0),name="ledger_positive_amount"),models.CheckConstraint(condition=Q(balance_before__gte=0),name="ledger_non_negative_before"),models.CheckConstraint(condition=Q(balance_after__gte=0),name="ledger_non_negative_after")]

class Notification(models.Model):
    user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.CASCADE,related_name="notifications"); notification_type=models.CharField(max_length=40); title=models.CharField(max_length=120); content=models.CharField(max_length=500); is_read=models.BooleanField(default=False); created_at=models.DateTimeField(auto_now_add=True)
class SecurityEvent(models.Model):
    event_type=models.CharField(max_length=80); user=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True); detail=models.CharField(max_length=500); created_at=models.DateTimeField(auto_now_add=True)
class AuditLog(models.Model):
    actor=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.SET_NULL,null=True,blank=True); action=models.CharField(max_length=80); target=models.CharField(max_length=100); reason=models.CharField(max_length=300,blank=True); created_at=models.DateTimeField(auto_now_add=True)
