import uuid
import hashlib
import time

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.conf import settings
from django.core.cache import cache
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .models import AuditLog, AutoModerationCase, Category, ChatMessage, ChatRoom, Product, Report, SecurityEvent, User, WalletTransaction
from .services import (assign_auto_case, assign_report, change_user_role, change_user_status, create_user_by_admin, grant,
    moderate_message, moderate_product, reverse_transfer, review_auto_case, start_auto_case_review,
    transition_report, view_direct_chat_for_moderation)


def _allowed(request, roles):
    return request.user.is_authenticated and request.user.status == User.Status.ACTIVE and request.user.role in roles


def ops_required(roles):
    def decorator(view):
        @login_required
        def wrapped(request, *args, **kwargs):
            if not _allowed(request, roles):
                return HttpResponseForbidden("Administrator permission required.")
            return view(request, *args, **kwargs)
        return wrapped
    return decorator


def _page(request, queryset, size=30):
    return Paginator(queryset, size).get_page(request.GET.get("page"))


_REPORT_TYPES={"USER":"사용자 신고", "PRODUCT":"상품 신고", "MESSAGE":"채팅 메시지 신고"}
_REPORT_STATES={"PENDING":"접수", "REVIEWING":"검토 중", "ACCEPTED":"승인", "REJECTED":"기각", "RESOLVED":"처리 완료"}
_AUDIT_LABELS={
    "report.transition":"신고 상태 변경", "report.assign":"신고 담당자 배정", "report.accept_hide_product":"신고 승인에 따른 상품 숨김",
    "product.hide":"상품 숨김 처리", "product.restore":"상품 공개 복구", "product.moderate":"상품 운영 조치",
    "moderation.auto_hide":"자동 상품 숨김", "moderation.auto_restrict":"자동 사용자 임시 제한",
    "moderation.auto_case_assign":"자동 조치 담당자 배정", "moderation.auto_case_review_start":"자동 조치 검토 시작",
    "moderation.auto_case_accept":"자동 조치 승인", "moderation.auto_case_reject":"자동 조치 기각 및 복구",
    "chat.message_hide":"채팅 메시지 숨김", "category.update":"카테고리 관리", "user.status":"사용자 상태 변경", "user.role":"사용자 역할 변경",
}


def _decorate_reports(reports):
    product_ids=[report.target_id for report in reports if report.target_type == Report.Target.PRODUCT]
    message_ids=[report.target_id for report in reports if report.target_type == Report.Target.MESSAGE]
    products={str(obj.public_id):obj for obj in Product.objects.filter(public_id__in=product_ids)}
    chat_messages={str(obj.public_id):obj for obj in ChatMessage.objects.select_related("sender","room__related_product").filter(public_id__in=message_ids)}
    for report in reports:
        report.display_type=_REPORT_TYPES[report.target_type]; report.display_status=_REPORT_STATES[report.status]
        report.assignee_name=report.assigned_to.username if report.assigned_to else "미배정"
        report.target_label="삭제되었거나 확인할 수 없는 대상"
        report.target_url=""
        if report.target_type == Report.Target.PRODUCT:
            product=products.get(str(report.target_id))
            if product: report.target_label=product.title; report.target_url=reverse("ops_product_detail",args=[product.public_id])
        elif report.target_type == Report.Target.USER:
            user=User.objects.filter(public_id=report.target_id).first()
            if user: report.target_label=user.username; report.target_url=reverse("ops_users")+"?q="+str(user.public_id)
        else:
            message=chat_messages.get(str(report.target_id))
            if message:
                product=message.room.related_product
                kind="1:1 채팅" if message.room.room_type == ChatRoom.Type.DIRECT else "공용 채팅"
                product_hint=f" / {product.title}" if product else ""
                report.target_label=f"{kind}{product_hint} / {message.sender.username}: {message.content}"
        latest=AuditLog.objects.filter(target=str(report.public_id),action="report.transition").select_related("actor").order_by("-created_at").first()
        report.processed_by=latest.actor.username if latest and latest.actor else ""
        report.processed_at=latest.created_at if latest else None
        report.processed_reason=latest.reason if latest else ""
    return reports


def _decorate_audit_logs(logs):
    """Presentation-only resolver: immutable audit rows remain untouched."""
    # Audit targets are immutable free-form text; do not pass arbitrary values
    # into UUID predicates when a legacy/fallback target is not a UUID.
    import uuid as _uuid
    ids=[]
    for entry in logs:
        try: ids.append(str(_uuid.UUID(str(entry.target))))
        except (ValueError, TypeError, AttributeError): pass
    products={str(obj.public_id):obj for obj in Product.objects.filter(public_id__in=ids)}
    users={str(obj.public_id):obj for obj in User.objects.filter(public_id__in=ids)}
    reports={str(obj.public_id):obj for obj in Report.objects.select_related("reporter").filter(public_id__in=ids)}
    cases={str(obj.public_id):obj for obj in AutoModerationCase.objects.filter(public_id__in=ids)}
    messages={str(obj.public_id):obj for obj in ChatMessage.objects.select_related("sender","room__related_product").filter(public_id__in=ids)}
    numeric_targets=[entry.target for entry in logs if str(entry.target).isdigit()]
    categories={str(obj.pk):obj for obj in Category.objects.filter(pk__in=numeric_targets)}
    for entry in logs:
        entry.display_action=_AUDIT_LABELS.get(entry.action, entry.action.replace("_", " ").replace(".", " · "))
        entry.target_label="삭제되었거나 찾을 수 없는 대상"
        entry.target_url=""
        if product:=products.get(entry.target): entry.target_label=f"상품 · {product.title}"; entry.target_url=reverse("ops_product_detail",args=[product.public_id])
        elif user:=users.get(entry.target): entry.target_label=f"사용자 · {user.username}"; entry.target_url=reverse("ops_users")+"?q="+str(user.public_id)
        elif report:=reports.get(entry.target): entry.target_label=f"{_REPORT_TYPES[report.target_type]} · 신고자 {report.reporter.username}"; entry.target_url=reverse("ops_reports")+"?q="+str(report.public_id)
        elif case:=cases.get(entry.target): entry.target_label=f"자동 조치 · {case.target_type}"; entry.target_url=reverse("ops_auto_cases")+"?case="+str(case.public_id)
        elif message:=messages.get(entry.target): entry.target_label=f"채팅 메시지 · {message.sender.username}: {message.content[:60]}"
        elif category:=categories.get(entry.target): entry.target_label=f"카테고리 · {category.name}"
        entry.target_fallback=entry.target
    return logs


def _ip(request): return request.META.get("REMOTE_ADDR", "unknown")[:64]
def _login_key(username, ip): return "admin-login:"+hashlib.sha256(f"{username.casefold()}:{ip}".encode()).hexdigest()


def admin_login(request):
    if request.method == "POST":
        username=request.POST.get("username", "")[:150]; key=_login_key(username,_ip(request))
        try:
            if (cache.get(key) or 0) >= settings.ADMIN_LOGIN_RATE_LIMIT_PER_MINUTE:
                SecurityEvent.objects.create(event_type="ADMIN_LOGIN_RATE_LIMIT",detail=f"ip={_ip(request)}")
                return HttpResponseForbidden("Too many administrator login attempts. Try again later.")
            cache.add(key,0,timeout=settings.ADMIN_LOGIN_RATE_LIMIT_TTL_SECONDS); cache.incr(key)
        except Exception:
            SecurityEvent.objects.create(event_type="ADMIN_LOGIN_RATE_LIMIT_BACKEND_ERROR",detail=f"ip={_ip(request)}")
            return HttpResponseForbidden("Administrator login is temporarily unavailable.")
        user=authenticate(request,username=username,password=request.POST.get("password", ""))
        if not user or user.role not in {User.Role.MODERATOR,User.Role.ADMIN,User.Role.SUPERADMIN} or user.status != User.Status.ACTIVE:
            SecurityEvent.objects.create(event_type="ADMIN_LOGIN_FAILURE",user=user,detail=f"account={hashlib.sha256(username.casefold().encode()).hexdigest()[:16]} ip={_ip(request)}")
            messages.error(request,"Administrator login failed.")
        else:
            login(request,user); request.session["ops_started"]=int(time.time()); request.session["ops_last"]=int(time.time()); request.session["ops_reauth_at"]=0
            SecurityEvent.objects.create(event_type="ADMIN_LOGIN_SUCCESS",user=user,detail=f"ip={_ip(request)}")
            return redirect("ops_dashboard")
    return render(request,"market/ops_login.html")


@ops_required({User.Role.MODERATOR, User.Role.ADMIN, User.Role.SUPERADMIN})
def admin_logout(request):
    if request.method != "POST": return HttpResponseForbidden("POST required.")
    SecurityEvent.objects.create(event_type="ADMIN_LOGOUT",user=request.user,detail=f"ip={_ip(request)}")
    logout(request); return redirect("admin_login")


def _reauth(request):
    now=int(time.time())
    if now-int(request.session.get("ops_reauth_at", 0)) < settings.ADMIN_REAUTH_SECONDS:
        return True
    if request.user.check_password(request.POST.get("current_password", "")):
        request.session["ops_reauth_at"]=now; SecurityEvent.objects.create(event_type="ADMIN_REAUTH_SUCCESS",user=request.user,detail=f"ip={_ip(request)}"); return True
    SecurityEvent.objects.create(event_type="ADMIN_REAUTH_FAILURE",user=request.user,detail=f"ip={_ip(request)}"); return False


@ops_required({User.Role.MODERATOR, User.Role.ADMIN, User.Role.SUPERADMIN})
def dashboard(request):
    user_counts=User.objects.values("status").annotate(total=Count("id"))
    product_counts=Product.objects.values("status").annotate(total=Count("id"))
    context={"user_counts":{row["status"]:row["total"] for row in user_counts}, "product_counts":{row["status"]:row["total"] for row in product_counts},
        "users":User.objects.count(), "pending":Report.objects.filter(status=Report.Status.PENDING).count(), "reviewing":Report.objects.filter(status=Report.Status.REVIEWING).count(),
        "transfers":WalletTransaction.objects.filter(transaction_type=WalletTransaction.Type.TRANSFER).count(), "grants":WalletTransaction.objects.filter(transaction_type=WalletTransaction.Type.GRANT).count(),
        "reversals":WalletTransaction.objects.filter(transaction_type=WalletTransaction.Type.REVERSAL).count(), "mismatches":SecurityEvent.objects.filter(event_type="LEDGER_MISMATCH").count(),
        "recent_actions":AuditLog.objects.select_related("actor").order_by("-created_at")[:20]}
    return render(request, "market/ops_dashboard.html", context)


@ops_required({User.Role.ADMIN, User.Role.SUPERADMIN})
def users(request):
    q=request.GET.get("q", "").strip()[:100]
    qs=User.objects.all().order_by("username")
    if q: qs=qs.filter(Q(username__icontains=q)|Q(display_name__icontains=q)|Q(public_id__icontains=q))
    return render(request,"market/ops_list.html",{"title":"Users","page_obj":_page(request,qs),"q":q,"kind":"users"})


@ops_required({User.Role.ADMIN, User.Role.SUPERADMIN})
def user_action(request, public_id):
    target=get_object_or_404(User,public_id=public_id)
    if request.method != "POST": return HttpResponseForbidden("POST required.")
    try:
        if "role" in request.POST: change_user_role(actor=request.user,target=target,role=request.POST["role"],reason=request.POST.get("reason", ""))
        else: change_user_status(actor=request.user,target=target,status=request.POST.get("status"),reason=request.POST.get("reason", ""))
    except ValidationError as exc: messages.error(request,exc.message)
    else: messages.success(request,"User action completed.")
    return redirect("ops_users")


@ops_required({User.Role.ADMIN, User.Role.SUPERADMIN})
def create_user(request):
    if request.method == "POST":
        try: create_user_by_admin(actor=request.user,username=request.POST.get("username", ""),password=request.POST.get("password", ""),display_name=request.POST.get("display_name", ""),role=request.POST.get("role", User.Role.USER))
        except (ValidationError, ValueError) as exc: messages.error(request,str(exc))
        else: messages.success(request,"User created.")
    return render(request,"market/ops_create_user.html",{"roles":User.Role.choices})


@ops_required({User.Role.MODERATOR, User.Role.ADMIN, User.Role.SUPERADMIN})
def products(request):
    qs=Product.objects.select_related("seller","category").order_by("-created_at")
    if request.GET.get("status") in Product.Status.values: qs=qs.filter(status=request.GET["status"])
    return render(request,"market/ops_list.html",{"title":"Products","page_obj":_page(request,qs),"kind":"products"})

@ops_required({User.Role.MODERATOR, User.Role.ADMIN, User.Role.SUPERADMIN})
def product_detail(request, public_id):
    product=get_object_or_404(Product.objects.select_related("seller","category").prefetch_related("images"),public_id=public_id)
    return render(request,"market/ops_product_detail.html",{"product":product,"reports":Report.objects.filter(target_type=Report.Target.PRODUCT,target_id=product.public_id),"auto_cases":AutoModerationCase.objects.filter(target_type="PRODUCT",target_id=product.public_id),"transactions":WalletTransaction.objects.filter(product=product)})

@ops_required({User.Role.ADMIN, User.Role.SUPERADMIN})
def categories(request):
    if request.method == "POST":
        category=get_object_or_404(Category,pk=request.POST["id"]) if request.POST.get("id") else Category()
        category.name=request.POST.get("name","").strip(); category.slug=request.POST.get("slug","").strip(); category.is_active=request.POST.get("is_active") == "on"
        try: category.full_clean(); category.save(); AuditLog.objects.create(actor=request.user,action="category.update",target=str(category.pk),reason=category.name); messages.success(request,"Category saved.")
        except ValidationError as exc: messages.error(request,str(exc))
    return render(request,"market/ops_categories.html",{"categories":Category.objects.order_by("name")})

@ops_required({User.Role.MODERATOR, User.Role.ADMIN, User.Role.SUPERADMIN})
def auto_cases(request):
    cases=list(AutoModerationCase.objects.select_related("reviewed_by","assigned_to").order_by("-created_at"))
    product_ids=[case.target_id for case in cases if case.target_type == AutoModerationCase.Target.PRODUCT]
    user_ids=[case.target_id for case in cases if case.target_type == AutoModerationCase.Target.USER]
    products={str(obj.public_id):obj for obj in Product.objects.filter(public_id__in=product_ids)}
    users={str(obj.public_id):obj for obj in User.objects.filter(public_id__in=user_ids)}
    for case in cases:
        target=products.get(str(case.target_id)) if case.target_type == AutoModerationCase.Target.PRODUCT else users.get(str(case.target_id))
        case.target_label=(target.title if case.target_type == AutoModerationCase.Target.PRODUCT else target.username) if target else "삭제되었거나 찾을 수 없는 대상"
        case.target_url=reverse("ops_product_detail",args=[target.public_id]) if target and case.target_type == AutoModerationCase.Target.PRODUCT else ""
        case.related_reports=Report.objects.filter(target_type=Report.Target.PRODUCT if case.target_type == AutoModerationCase.Target.PRODUCT else Report.Target.USER,target_id=case.target_id).select_related("reporter").order_by("created_at")
    assignees=User.objects.filter(role__in=[User.Role.MODERATOR,User.Role.ADMIN,User.Role.SUPERADMIN],status=User.Status.ACTIVE,is_active=True).order_by("username")
    return render(request,"market/ops_auto_cases.html",{"cases":cases,"assignees":assignees})

@ops_required({User.Role.MODERATOR, User.Role.ADMIN, User.Role.SUPERADMIN})
def auto_case_action(request, public_id):
    case=get_object_or_404(AutoModerationCase,public_id=public_id)
    if request.method != "POST": return HttpResponseForbidden("POST required.")
    try:
        action=request.POST.get("action")
        if action == "assign":
            assignee=get_object_or_404(User,public_id=request.POST.get("assignee"))
            assign_auto_case(actor=request.user,case=case,assignee=assignee,expected_version=int(request.POST.get("version","-1")))
        elif action == "start": start_auto_case_review(actor=request.user,case=case)
        elif action in {"ACCEPTED","REJECTED"}: review_auto_case(actor=request.user,case=case,accepted=action=="ACCEPTED",reason=request.POST.get("reason",""))
        else: raise ValidationError("Unknown automatic moderation action.")
    except ValidationError as exc: messages.error(request,str(exc))
    else: messages.success(request,"Automatic moderation case updated.")
    return redirect("ops_auto_cases")

@ops_required({User.Role.MODERATOR, User.Role.ADMIN, User.Role.SUPERADMIN})
def community_messages(request):
    qs=ChatMessage.objects.filter(room__room_type=ChatRoom.Type.GLOBAL).select_related("sender").order_by("-created_at")
    page_obj=_page(request,qs)
    counts={str(row["target_id"]):row["total"] for row in Report.objects.filter(target_type=Report.Target.MESSAGE,target_id__in=[obj.public_id for obj in page_obj.object_list]).values("target_id").annotate(total=Count("id"))}
    for message in page_obj.object_list: message.report_count=counts.get(str(message.public_id),0)
    return render(request,"market/ops_list.html",{"title":"Community messages","page_obj":page_obj,"kind":"community_messages"})


@ops_required({User.Role.MODERATOR, User.Role.ADMIN, User.Role.SUPERADMIN})
def product_action(request, public_id):
    product=get_object_or_404(Product,public_id=public_id)
    if request.method != "POST": return HttpResponseForbidden("POST required.")
    try: moderate_product(actor=request.user,product=product,status=request.POST.get("status"),reason=request.POST.get("reason", ""))
    except ValidationError as exc: messages.error(request,exc.message)
    else: messages.success(request,"Product action completed.")
    return redirect("ops_products")


@ops_required({User.Role.MODERATOR, User.Role.ADMIN, User.Role.SUPERADMIN})
def reports(request):
    qs=Report.objects.select_related("reporter","assigned_to").order_by("-created_at")
    if request.GET.get("status") in Report.Status.values: qs=qs.filter(status=request.GET["status"])
    if request.GET.get("target_type") in Report.Target.values: qs=qs.filter(target_type=request.GET["target_type"])
    assignees=User.objects.filter(role__in=[User.Role.MODERATOR,User.Role.ADMIN,User.Role.SUPERADMIN],status=User.Status.ACTIVE).order_by("username")
    page_obj=_page(request,qs); _decorate_reports(list(page_obj.object_list))
    return render(request,"market/ops_list.html",{"title":"Reports","page_obj":page_obj,"kind":"reports","assignees":assignees})


@ops_required({User.Role.MODERATOR, User.Role.ADMIN, User.Role.SUPERADMIN})
def report_action(request, public_id):
    report=get_object_or_404(Report,public_id=public_id)
    if request.method != "POST": return HttpResponseForbidden("POST required.")
    try: transition_report(actor=request.user,report=report,status=request.POST.get("status"),reason=request.POST.get("reason", ""))
    except ValidationError as exc: messages.error(request,exc.message)
    else: messages.success(request,"Report transitioned.")
    return redirect("ops_reports")

@ops_required({User.Role.MODERATOR, User.Role.ADMIN, User.Role.SUPERADMIN})
def assign_report_view(request, public_id):
    report=get_object_or_404(Report,public_id=public_id)
    if request.method != "POST": return HttpResponseForbidden("POST required.")
    assignee=get_object_or_404(User,public_id=request.POST.get("assignee"))
    try: assign_report(actor=request.user,report=report,assignee=assignee,reason=request.POST.get("reason", ""),expected_version=int(request.POST.get("version", "-1")))
    except (ValidationError, ValueError) as exc: messages.error(request,str(exc))
    else: messages.success(request,"Report assignee updated.")
    return redirect("ops_reports")


@ops_required({User.Role.MODERATOR, User.Role.ADMIN, User.Role.SUPERADMIN})
def hide_message(request, public_id):
    message=get_object_or_404(ChatMessage,public_id=public_id)
    if request.method != "POST": return HttpResponseForbidden("POST required.")
    try: moderate_message(actor=request.user,message=message,reason=request.POST.get("reason", ""))
    except ValidationError as exc: messages.error(request,exc.message)
    else: messages.success(request,"Message hidden.")
    return redirect("ops_community_messages" if message.room.room_type == ChatRoom.Type.GLOBAL else "ops_reports")


@ops_required({User.Role.ADMIN, User.Role.SUPERADMIN})
def transactions(request):
    qs=WalletTransaction.objects.select_related("source__user","destination__user","created_by").order_by("-created_at")
    if request.GET.get("type") in WalletTransaction.Type.values: qs=qs.filter(transaction_type=request.GET["type"])
    return render(request,"market/ops_list.html",{"title":"Transactions","page_obj":_page(request,qs),"kind":"transactions"})


@ops_required({User.Role.ADMIN, User.Role.SUPERADMIN})
def grant_points(request):
    if request.method != "POST": return HttpResponseForbidden("POST required.")
    if not _reauth(request): return HttpResponseForbidden("Current password confirmation is required.")
    recipient=get_object_or_404(User,public_id=request.POST.get("recipient"))
    try: grant(actor=request.user,recipient=recipient,amount=int(request.POST.get("amount", "0")),reason=request.POST.get("reason", ""),idempotency_key=uuid.UUID(request.POST.get("idempotency_key", "")))
    except (ValidationError, ValueError) as exc: messages.error(request,str(exc))
    else: messages.success(request,"Grant completed.")
    return redirect("ops_transactions")

@ops_required({User.Role.ADMIN, User.Role.SUPERADMIN})
def reverse_transaction(request, public_id):
    original=get_object_or_404(WalletTransaction,public_id=public_id)
    if request.method != "POST": return HttpResponseForbidden("POST required.")
    if not _reauth(request): return HttpResponseForbidden("Current password confirmation is required.")
    try: reverse_transfer(actor=request.user,original_id=original.pk,password=request.POST.get("current_password", ""),reason=request.POST.get("reason", ""))
    except ValidationError as exc: messages.error(request,exc.message)
    else: messages.success(request,"Transaction reversal completed.")
    return redirect("ops_transactions")

@ops_required({User.Role.ADMIN, User.Role.SUPERADMIN})
def transaction_detail(request, public_id):
    transaction=get_object_or_404(WalletTransaction.objects.select_related("source__user","destination__user","original_transaction"),public_id=public_id)
    reversal=WalletTransaction.objects.filter(original_transaction=transaction).first()
    return render(request,"market/ops_transaction_detail.html",{"transaction":transaction,"reversal":reversal,"recoverable":transaction.transaction_type == WalletTransaction.Type.TRANSFER and not reversal})

@ops_required({User.Role.MODERATOR, User.Role.ADMIN, User.Role.SUPERADMIN})
def reported_direct_chat(request, report_id):
    report=get_object_or_404(Report,public_id=report_id,target_type=Report.Target.MESSAGE)
    message=get_object_or_404(ChatMessage.objects.select_related("room","sender"),public_id=report.target_id)
    if message.room.room_type != ChatRoom.Type.DIRECT or request.method != "POST": return HttpResponseForbidden("A reported direct chat POST is required.")
    try: messages_qs=view_direct_chat_for_moderation(actor=request.user,room=message.room,report=report,reason=request.POST.get("reason", ""))
    except ValidationError as exc: return HttpResponseForbidden(exc.message)
    return render(request,"market/ops_reported_chat.html",{"report":report,"message":message,"messages":list(reversed(messages_qs))})


@ops_required({User.Role.ADMIN, User.Role.SUPERADMIN})
def audit_logs(request):
    page_obj=_page(request,AuditLog.objects.select_related("actor").order_by("-created_at")); _decorate_audit_logs(list(page_obj.object_list))
    return render(request,"market/ops_list.html",{"title":"Audit logs","page_obj":page_obj,"kind":"audit"})
