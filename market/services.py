import uuid
import logging
from datetime import timedelta
from django.conf import settings
from django.contrib.auth import authenticate
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import DateTimeField, F, OuterRef, Q, Subquery, Sum
from django.utils import timezone
from redis.exceptions import RedisError
from .models import AuditLog, ChatMessage, ChatParticipant, ChatReadState, ChatRoom, LedgerEntry, Notification, Product, Profile, Purchase, Report, SecurityEvent, User, Wallet, WalletTransaction

logger = logging.getLogger(__name__)

def _blocked(a,b): return a.blocks.filter(blocked=b).exists() or b.blocks.filter(blocked=a).exists()
def _notify(user, kind, title, content): transaction.on_commit(lambda: Notification.objects.create(user=user,notification_type=kind,title=title,content=content))
def _rate_limit(user, action, limit):
    key=f"rate:{action}:{user.pk}:{timezone.now().strftime('%Y%m%d%H%M')}"
    try:
        if cache.add(key, 1, timeout=settings.RATE_LIMIT_TTL_SECONDS):
            return
        count=cache.incr(key)
    except (RedisError, ConnectionError, OSError) as exc:
        logger.exception("Rate-limit backend unavailable for %s", action)
        raise ValidationError("요청 처리 보안 확인에 실패했습니다. 잠시 후 다시 시도하세요.") from exc
    if count > limit:
        raise ValidationError("요청 횟수 제한을 초과했습니다. 잠시 후 다시 시도하세요.")
def _lock_wallets(*wallet_ids):
    locked=Wallet.objects.select_for_update().filter(pk__in=sorted(wallet_ids)).order_by("pk")
    return {wallet.pk:wallet for wallet in locked}
def _daily_total(wallet, transaction_type):
    start=timezone.now().replace(hour=0,minute=0,second=0,microsecond=0)
    return WalletTransaction.objects.filter(source=wallet,transaction_type=transaction_type,created_at__gte=start).aggregate(total=Sum("amount"))["total"] or 0
def _entry(tx,wallet,kind,amount):
    before=wallet.balance; after=before + amount if kind == "CREDIT" else before - amount
    if after < 0: raise ValidationError("잔액이 부족합니다.")
    LedgerEntry.objects.create(transaction=tx,wallet=wallet,entry_type=kind,amount=amount,balance_before=before,balance_after=after)
    wallet.balance=after

@transaction.atomic
def register_user(*, username, password, display_name):
    user=User.objects.create_user(username=username,password=password,display_name=display_name)
    Profile.objects.create(user=user)
    wallet=Wallet.objects.create(user=user,balance=0)
    if settings.WELCOME_BONUS_ENABLED: award_welcome_bonus(user)
    return user

def create_user_by_admin(*, actor, username, password, display_name, role=User.Role.USER):
    if actor.role not in {User.Role.ADMIN,User.Role.SUPERADMIN}: raise ValidationError("사용자 생성 권한이 없습니다.")
    if role not in User.Role.values or (role == User.Role.SUPERADMIN and actor.role != User.Role.SUPERADMIN): raise ValidationError("The requested account role is not permitted.")
    user=register_user(username=username,password=password,display_name=display_name)
    user.role=role; user.save(update_fields=["role"])
    AuditLog.objects.create(actor=actor,action="user.create",target=str(user.public_id),reason=f"role={role}")
    return user

@transaction.atomic
def award_welcome_bonus(user):
    wallet=_lock_wallets(user.wallet.pk)[user.wallet.pk]
    key=f"WELCOME_BONUS:{user.pk}"
    existing=WalletTransaction.objects.filter(grant_key=key).first()
    if existing: return existing
    try:
        with transaction.atomic(): tx=WalletTransaction.objects.create(transaction_type=WalletTransaction.Type.WELCOME,destination=wallet,amount=settings.WELCOME_BONUS_AMOUNT,idempotency_key=uuid.uuid4(),grant_key=key,memo="Welcome bonus")
    except IntegrityError:
        return WalletTransaction.objects.get(grant_key=key)
    _entry(tx,wallet,"CREDIT",tx.amount); wallet.save(update_fields=["balance"]); _notify(user,"WELCOME_BONUS","가입 포인트","가입 포인트가 지급되었습니다.")
    return tx

def _existing_idempotent(key, source_id, destination_id, amount):
    existing=WalletTransaction.objects.filter(idempotency_key=key).first()
    if existing and existing.source_id == source_id and existing.destination_id == destination_id and existing.amount == amount: return existing
    if existing: raise ValidationError("같은 요청 키가 다른 거래에 사용되었습니다.")
    return None

@transaction.atomic
def transfer(*, sender, recipient, amount, idempotency_key, memo=""):
    if sender == recipient or not sender.can_transfer() or not recipient.can_transfer() or _blocked(sender,recipient): raise ValidationError("송금할 수 없는 사용자입니다.")
    if amount <= 0 or amount > settings.TRANSFER_MAX_AMOUNT: raise ValidationError("송금 금액 한도를 확인하세요.")
    _rate_limit(sender,"transfer",settings.TRANSFER_RATE_LIMIT_PER_MINUTE)
    source_id,destination_id=sender.wallet.pk,recipient.wallet.pk
    found=_existing_idempotent(idempotency_key,source_id,destination_id,amount)
    if found: return found
    wallets=_lock_wallets(source_id,destination_id); source,destination=wallets[source_id],wallets[destination_id]
    if _daily_total(source,WalletTransaction.Type.TRANSFER)+amount > settings.TRANSFER_DAILY_LIMIT: raise ValidationError("일일 송금 한도를 초과했습니다.")
    if source.balance < amount: raise ValidationError("포인트 잔액이 부족합니다.")
    try:
        with transaction.atomic():
            tx=WalletTransaction.objects.create(transaction_type=WalletTransaction.Type.TRANSFER,source=source,destination=destination,amount=amount,idempotency_key=idempotency_key,memo=memo,created_by=sender)
    except IntegrityError:
        found=_existing_idempotent(idempotency_key,source_id,destination_id,amount)
        if found: return found
        raise
    _entry(tx,source,"DEBIT",amount); _entry(tx,destination,"CREDIT",amount); source.save(update_fields=["balance"]); destination.save(update_fields=["balance"])
    AuditLog.objects.create(actor=sender,action="wallet.transfer",target=str(tx.public_id)); _notify(recipient,"TRANSFER_RECEIVED","포인트 수신",f"{amount}P를 받았습니다.")
    return tx

@transaction.atomic
def grant(*, actor, recipient, amount, reason, idempotency_key):
    if actor.role not in {actor.Role.ADMIN,actor.Role.SUPERADMIN} or amount <= 0 or amount > settings.ADMIN_GRANT_MAX_AMOUNT or not reason.strip(): raise ValidationError("관리자 지급 요청이 올바르지 않습니다.")
    _rate_limit(actor,"admin_grant",settings.ADMIN_GRANT_RATE_LIMIT_PER_MINUTE)
    wallets=_lock_wallets(actor.wallet.pk,recipient.wallet.pk)
    wallet=wallets[recipient.wallet.pk]
    found=_existing_idempotent(idempotency_key,None,wallet.pk,amount)
    if found: return found
    daily=WalletTransaction.objects.filter(created_by=actor,transaction_type=WalletTransaction.Type.GRANT,created_at__gte=timezone.now().replace(hour=0,minute=0,second=0,microsecond=0)).aggregate(total=Sum("amount"))["total"] or 0
    if daily + amount > settings.ADMIN_GRANT_DAILY_LIMIT: raise ValidationError("관리자 일일 지급 한도를 초과했습니다.")
    try:
        with transaction.atomic(): tx=WalletTransaction.objects.create(transaction_type=WalletTransaction.Type.GRANT,destination=wallet,amount=amount,idempotency_key=idempotency_key,memo=reason,created_by=actor)
    except IntegrityError:
        found=_existing_idempotent(idempotency_key,None,wallet.pk,amount)
        if found: return found
        raise
    _entry(tx,wallet,"CREDIT",amount); wallet.save(update_fields=["balance"]); AuditLog.objects.create(actor=actor,action="wallet.grant",target=str(tx.public_id),reason=reason); _notify(recipient,"ADMIN_GRANT","포인트 지급",f"관리자가 {amount}P를 지급했습니다.")
    return tx

@transaction.atomic
def reverse_transfer(*, actor, original_id, password, reason):
    if actor.role not in {actor.Role.ADMIN,actor.Role.SUPERADMIN} or not actor.check_password(password) or not reason.strip(): raise ValidationError("복구 권한 또는 재인증 정보를 확인하세요.")
    original=WalletTransaction.objects.select_for_update().get(pk=original_id)
    if original.transaction_type != WalletTransaction.Type.TRANSFER: raise ValidationError("송금 거래만 복구할 수 있습니다.")
    existing=WalletTransaction.objects.filter(original_transaction=original).first()
    if existing: return existing
    wallets=_lock_wallets(original.source_id,original.destination_id); source,destination=wallets[original.source_id],wallets[original.destination_id]
    if destination.balance < original.amount: raise ValidationError("수신 지갑 잔액이 부족합니다.")
    tx=WalletTransaction.objects.create(transaction_type=WalletTransaction.Type.REVERSAL,source=destination,destination=source,amount=original.amount,idempotency_key=uuid.uuid4(),memo=reason,original_transaction=original,created_by=actor)
    _entry(tx,destination,"DEBIT",tx.amount); _entry(tx,source,"CREDIT",tx.amount); destination.save(update_fields=["balance"]); source.save(update_fields=["balance"])
    AuditLog.objects.create(actor=actor,action="wallet.reverse",target=str(tx.public_id),reason=reason); _notify(source.user,"REVERSAL","거래 복구","포인트 거래가 복구되었습니다."); return tx

def verify_wallet(wallet):
    computed=sum(e.amount if e.entry_type == "CREDIT" else -e.amount for e in LedgerEntry.objects.filter(wallet=wallet).order_by("created_at","id"))
    if computed != wallet.balance: SecurityEvent.objects.create(event_type="LEDGER_MISMATCH",user=wallet.user,detail=f"wallet={wallet.pk}, balance={wallet.balance}, ledger={computed}")
    return computed == wallet.balance

@transaction.atomic
def direct_room(*,sender,recipient,product=None):
    if sender == recipient or _blocked(sender,recipient) or not sender.can_transfer() or not recipient.can_transfer(): raise ValidationError("채팅을 시작할 수 없습니다.")
    # Public room creation always supplies a product.  Keeping product-less
    # direct rooms readable preserves historic moderator evidence, but no
    # public URL can create one.
    if product is not None and (product.seller_id != recipient.pk or product.status != Product.Status.ACTIVE):
        raise ValidationError("현재 이 상품으로 새 채팅을 시작할 수 없습니다.")
    for room in ChatRoom.objects.filter(room_type=ChatRoom.Type.DIRECT,related_product=product).prefetch_related("participants"):
        if {p.user_id for p in room.participants.all()} == {sender.pk,recipient.pk}: return room
    room=ChatRoom.objects.create(room_type=ChatRoom.Type.DIRECT,related_product=product)
    ChatParticipant.objects.bulk_create([ChatParticipant(room=room,user=sender),ChatParticipant(room=room,user=recipient)])
    # A null marker means "never read". Existing rooms without a row are
    # handled the same way by unread_chat_count().
    ChatReadState.objects.bulk_create([ChatReadState(room=room,user=sender),ChatReadState(room=room,user=recipient)])
    return room

@transaction.atomic
def change_product_status(*, seller, product, status):
    allowed={Product.Status.DRAFT:{Product.Status.ACTIVE},Product.Status.ACTIVE:{Product.Status.RESERVED,Product.Status.SOLD},Product.Status.RESERVED:{Product.Status.ACTIVE,Product.Status.SOLD}}
    if not seller.can_transfer(): raise ValidationError("Restricted users cannot change product status.")
    if product.seller_id != seller.pk or status not in allowed.get(product.status,set()): raise ValidationError("허용되지 않은 판매 상태 전이입니다.")
    product.status=status; product.save(update_fields=["status","updated_at"]); AuditLog.objects.create(actor=seller,action="product.status",target=str(product.public_id),reason=status); return product
def send_message(*,sender,room,content):
    if room.room_type != ChatRoom.Type.DIRECT or not sender.can_transfer() or not room.participants.filter(user=sender).exists(): raise ValidationError("채팅 권한이 없습니다.")
    other=room.participants.exclude(user=sender).select_related("user").first()
    if not other or _blocked(sender,other.user): raise ValidationError("차단 관계에서는 메시지를 전송할 수 없습니다.")
    content=content.strip()
    if not content or len(content)>1000: raise ValidationError("메시지 길이가 올바르지 않습니다.")
    _rate_limit(sender,"chat",settings.CHAT_RATE_LIMIT_PER_MINUTE)
    message=ChatMessage.objects.create(room=room,sender=sender,content=content)
    return message

@transaction.atomic
def purchase_product(*, buyer, product_id):
    product=Product.objects.select_for_update().select_related("seller").get(pk=product_id)
    if product.status != Product.Status.ACTIVE or product.seller_id == buyer.pk:
        raise ValidationError("This product is not available for purchase.")
    wallets=_lock_wallets(buyer.wallet.pk, product.seller.wallet.pk)
    source,destination=wallets[buyer.wallet.pk],wallets[product.seller.wallet.pk]
    if source.balance < product.price: raise ValidationError("Insufficient point balance.")
    if Purchase.objects.filter(product=product).exists(): raise ValidationError("This product has already been purchased.")
    tx=WalletTransaction.objects.create(transaction_type=WalletTransaction.Type.TRANSFER,source=source,destination=destination,amount=product.price,idempotency_key=uuid.uuid4(),memo=f"Product purchase: {product.title}",product=product,created_by=buyer)
    _entry(tx,source,"DEBIT",tx.amount); _entry(tx,destination,"CREDIT",tx.amount)
    source.save(update_fields=["balance"]); destination.save(update_fields=["balance"])
    product.status=Product.Status.SOLD; product.save(update_fields=["status","updated_at"])
    purchase=Purchase.objects.create(product=product,buyer=buyer,seller=product.seller,amount=tx.amount,transaction=tx)
    AuditLog.objects.create(actor=buyer,action="product.purchase",target=str(product.public_id),reason=str(purchase.public_id))
    _notify(product.seller,"PRODUCT_SOLD","Product sold",f"{product.title} was purchased.")
    return purchase

def unread_chat_count(user):
    last_read = ChatReadState.objects.filter(room_id=OuterRef("room_id"), user_id=user.pk).values("last_read_at")[:1]
    return (
        ChatMessage.objects.filter(room__participants__user=user, status=ChatMessage.Status.VISIBLE)
        .exclude(sender=user)
        .annotate(_last_read_at=Subquery(last_read, output_field=DateTimeField()))
        .filter(Q(_last_read_at__isnull=True) | Q(created_at__gt=F("_last_read_at")))
        .distinct()
        .count()
    )

def unread_chat_count_for_room(*, room, user):
    last_read = ChatReadState.objects.filter(room_id=room.pk, user_id=user.pk).values("last_read_at")[:1]
    return (
        ChatMessage.objects.filter(room=room, status=ChatMessage.Status.VISIBLE)
        .exclude(sender=user)
        .annotate(_last_read_at=Subquery(last_read, output_field=DateTimeField()))
        .filter(Q(_last_read_at__isnull=True) | Q(created_at__gt=F("_last_read_at")))
        .count()
    )

@transaction.atomic
def mark_room_read(*, room, user):
    if not room.participants.filter(user=user).exists(): raise ValidationError("Chat permission is required.")
    ChatReadState.objects.update_or_create(room=room,user=user,defaults={"last_read_at":timezone.now()})
def create_report(*,reporter,target_type,target_id,reason,description=""):
    targets={Report.Target.USER:User,Report.Target.PRODUCT:Product,Report.Target.MESSAGE:ChatMessage}; target=targets[target_type].objects.filter(public_id=target_id).first()
    if not target: raise ValidationError("신고 대상을 찾을 수 없습니다.")
    if target_type == Report.Target.USER and target.pk == reporter.pk: raise ValidationError("자기 자신은 신고할 수 없습니다.")
    if target_type == Report.Target.PRODUCT and target.seller_id == reporter.pk: raise ValidationError("자신의 상품은 신고할 수 없습니다.")
    if target_type == Report.Target.MESSAGE and target.sender_id == reporter.pk: raise ValidationError("자신의 메시지는 신고할 수 없습니다.")
    _rate_limit(reporter,"report",10)
    report=Report.objects.create(reporter=reporter,target_type=target_type,target_id=target_id,reason=reason,description=description.strip())
    count=Report.objects.filter(target_type=target_type,target_id=target_id,status__in=[Report.Status.PENDING,Report.Status.REVIEWING]).values("reporter").distinct().count()
    if target_type == Report.Target.PRODUCT and count >= 3:
        target.status=Product.Status.HIDDEN; target.save(update_fields=["status","updated_at"]); AuditLog.objects.create(actor=None,action="report.auto_hide",target=str(target.public_id))
    if target_type == Report.Target.USER and count >= 3 and target.status == User.Status.ACTIVE:
        target.status=User.Status.RESTRICTED; target.save(update_fields=["status"]); AuditLog.objects.create(actor=None,action="report.auto_restrict",target=str(target.public_id))
    return report

@transaction.atomic
def transition_report(*, actor, report, status, reason):
    allowed={Report.Status.PENDING:{Report.Status.REVIEWING,Report.Status.REJECTED},Report.Status.REVIEWING:{Report.Status.ACCEPTED,Report.Status.REJECTED,Report.Status.RESOLVED},Report.Status.ACCEPTED:{Report.Status.RESOLVED}}
    if actor.role not in {User.Role.MODERATOR,User.Role.ADMIN,User.Role.SUPERADMIN} or not reason.strip() or status not in allowed.get(report.status,set()): raise ValidationError("허용되지 않은 신고 상태 전이입니다.")
    before=report.status; report.status=status; report.save(update_fields=["status"])
    AuditLog.objects.create(actor=actor,action="report.transition",target=str(report.public_id),reason=f"{before}->{status}: {reason.strip()}")
    # A moderator's accepted product report is an explicit temporary content
    # action. Rejection deliberately leaves the listing state untouched.
    if status == Report.Status.ACCEPTED and report.target_type == Report.Target.PRODUCT:
        product=Product.objects.filter(public_id=report.target_id).first()
        if product and product.status not in {Product.Status.HIDDEN, Product.Status.DELETED}:
            before_product=product.status
            product.status=Product.Status.HIDDEN; product.save(update_fields=["status","updated_at"])
            AuditLog.objects.create(actor=actor,action="report.accept_hide_product",target=str(product.public_id),reason=f"{before_product}->HIDDEN: {reason.strip()}")
    return report


def _require_role(actor, roles):
    if actor.role not in roles:
        raise ValidationError("Administrator permission is required.")


@transaction.atomic
def change_user_status(*, actor, target, status, reason):
    _require_role(actor, {User.Role.ADMIN, User.Role.SUPERADMIN})
    if not reason.strip() or status not in {User.Status.ACTIVE, User.Status.RESTRICTED, User.Status.SUSPENDED, User.Status.DORMANT, User.Status.DELETED}:
        raise ValidationError("A valid status and reason are required.")
    if target.role == User.Role.SUPERADMIN and actor.role != User.Role.SUPERADMIN:
        raise ValidationError("Only a super administrator may manage a super administrator.")
    before=target.status
    if before == status:
        raise ValidationError("The requested status is already set.")
    target.status=status; target.save(update_fields=["status"])
    AuditLog.objects.create(actor=actor, action="user.status", target=str(target.public_id), reason=f"{before}->{status}: {reason.strip()}")
    return target


@transaction.atomic
def change_user_role(*, actor, target, role, reason):
    _require_role(actor, {User.Role.SUPERADMIN})
    if not reason.strip() or role not in User.Role.values:
        raise ValidationError("A valid role and reason are required.")
    before=target.role
    if before == role:
        raise ValidationError("The requested role is already set.")
    target.role=role; target.save(update_fields=["role"])
    AuditLog.objects.create(actor=actor, action="user.role", target=str(target.public_id), reason=f"{before}->{role}: {reason.strip()}")
    return target


@transaction.atomic
def moderate_product(*, actor, product, status, reason):
    _require_role(actor, {User.Role.MODERATOR, User.Role.ADMIN, User.Role.SUPERADMIN})
    if not reason.strip() or status not in {Product.Status.HIDDEN, Product.Status.ACTIVE, Product.Status.DELETED}:
        raise ValidationError("A valid product action and reason are required.")
    before=product.status
    if before == status:
        raise ValidationError("The requested product status is already set.")
    product.status=status; product.save(update_fields=["status", "updated_at"])
    AuditLog.objects.create(actor=actor, action="product.moderate", target=str(product.public_id), reason=f"{before}->{status}: {reason.strip()}")
    return product


@transaction.atomic
def moderate_message(*, actor, message, reason):
    _require_role(actor, {User.Role.MODERATOR, User.Role.ADMIN, User.Role.SUPERADMIN})
    if not reason.strip() or message.status != ChatMessage.Status.VISIBLE:
        raise ValidationError("A visible message and reason are required.")
    message.status=ChatMessage.Status.HIDDEN; message.save(update_fields=["status"])
    AuditLog.objects.create(actor=actor, action="chat.message_hide", target=str(message.public_id), reason=reason.strip())
    return message


def view_direct_chat_for_moderation(*, actor, room, report, reason):
    _require_role(actor, {User.Role.MODERATOR, User.Role.ADMIN, User.Role.SUPERADMIN})
    if room.room_type != ChatRoom.Type.DIRECT or not reason.strip() or not report or report.target_type != Report.Target.MESSAGE:
        raise ValidationError("A linked message report and reason are required.")
    if not room.messages.filter(public_id=report.target_id).exists():
        raise ValidationError("The report is not linked to this direct chat.")
    AuditLog.objects.create(actor=actor, action="chat.direct_view", target=str(room.public_id), reason=reason.strip())
    return room.messages.filter(status=ChatMessage.Status.VISIBLE).select_related("sender").order_by("-created_at", "-id")[:50]


@transaction.atomic
def assign_report(*, actor, report, assignee, reason, expected_version):
    _require_role(actor, {User.Role.MODERATOR, User.Role.ADMIN, User.Role.SUPERADMIN})
    if report.status not in {Report.Status.PENDING, Report.Status.REVIEWING} or not reason.strip():
        raise ValidationError("Only open reports with a reason can be assigned.")
    if assignee.role not in {User.Role.MODERATOR, User.Role.ADMIN, User.Role.SUPERADMIN} or assignee.status != User.Status.ACTIVE:
        raise ValidationError("Assignee must be an active administrator.")
    updated=Report.objects.filter(pk=report.pk, assignment_version=expected_version).update(assigned_to=assignee, assignment_version=expected_version+1)
    if not updated: raise ValidationError("This report assignment was changed by another administrator.")
    AuditLog.objects.create(actor=actor, action="report.assign", target=str(report.public_id), reason=f"assignee={assignee.public_id}: {reason.strip()}")
    report.refresh_from_db(); return report
