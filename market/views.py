import hashlib
import logging
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import OperationalError
from django.db.models import OuterRef, Q, Subquery
from django.core.paginator import Paginator
from django.http import Http404, HttpResponseForbidden
from redis.exceptions import RedisError
from django.shortcuts import get_object_or_404, redirect, render
from .forms import ChatMessageForm, ProductForm, ProductImageForm, ProfileForm, ReportForm, SafePasswordChangeForm, SignUpForm
from .models import Block, Category, ChatMessage, ChatRoom, Notification, Product, ProductImage, Report, SecurityEvent, User, WalletTransaction
from .services import change_product_status, community_room, create_report, direct_room, mark_room_read, purchase_product, register_user, send_message, unread_chat_count, unread_chat_summary

logger = logging.getLogger(__name__)

RATE_LIMIT_ERROR = "Request cannot be processed. Please try again later."

def _client_ip(request): return request.META.get("REMOTE_ADDR", "unknown")[:64]
def _rate_key(scope, value): return f"public-rate:{scope}:{hashlib.sha256(value.encode()).hexdigest()}"
def _rate_backend_event(event_type, key):
    SecurityEvent.objects.create(event_type=event_type, detail=f"rate_key_digest={hashlib.sha256(key.encode()).hexdigest()[:16]}")
def _counter_limited(key, limit):
    try: return (cache.get(key) or 0) >= limit
    except (RedisError, ConnectionError, OSError):
        _rate_backend_event("PUBLIC_RATE_LIMIT_BACKEND_ERROR", key); return True
def _increment_counter(key, limit, window, event_type):
    try:
        if cache.add(key, 1, timeout=window): return False
        return cache.incr(key) > limit
    except (RedisError, ConnectionError, OSError):
        _rate_backend_event(event_type, key); return True
def _login_rate_keys(request):
    username=request.POST.get("username", "")[:150].casefold()
    ip=_client_ip(request)
    return _rate_key("login-account-ip", f"{username}\0{ip}"), _rate_key("login-ip", ip)

def product_list(request):
    q=request.GET.get("q", "").strip()[:100]
    # Drafts are private to their seller; hidden/deleted listings are never public.
    products=Product.objects.filter(status__in=[Product.Status.ACTIVE, Product.Status.RESERVED, Product.Status.SOLD]).select_related("seller", "category").prefetch_related("images")
    if q: products=products.filter(Q(title__icontains=q)|Q(description__icontains=q)|Q(category__name__icontains=q)|Q(seller__display_name__icontains=q))
    if request.GET.get("category", "").isdigit(): products=products.filter(category_id=request.GET["category"])
    if request.GET.get("condition") in {x[0] for x in Product._meta.get_field("condition").choices}: products=products.filter(condition=request.GET["condition"])
    if request.GET.get("status") in {Product.Status.ACTIVE,Product.Status.RESERVED,Product.Status.SOLD}: products=products.filter(status=request.GET["status"])
    min_price=int(request.GET["min_price"]) if request.GET.get("min_price", "").isdigit() else None
    max_price=int(request.GET["max_price"]) if request.GET.get("max_price", "").isdigit() else None
    if min_price is not None: products=products.filter(price__gte=min_price)
    if max_price is not None: products=products.filter(price__lte=max_price)
    if min_price is not None and max_price is not None and min_price > max_price: products=products.none()
    products=products.order_by({"new":"-created_at", "old":"created_at", "price_low":"price", "price_high":"-price"}.get(request.GET.get("sort"), "-created_at"))
    page=Paginator(products,20).get_page(request.GET.get("page"))
    query_params=request.GET.copy(); query_params.pop("page", None)
    return render(request, "market/product_list.html", {"products":page, "page_obj":page, "q":q, "query_params":query_params.urlencode()})

def signup(request):
    form=SignUpForm(request.POST or None)
    if request.method == "POST":
        key=_rate_key("signup-ip", _client_ip(request))
        if _increment_counter(key, settings.SIGNUP_RATE_LIMIT, settings.SIGNUP_RATE_LIMIT_WINDOW_SECONDS, "SIGNUP_RATE_LIMIT_BACKEND_ERROR"):
            form.add_error(None, RATE_LIMIT_ERROR)
            return render(request, "market/form.html", {"form":form, "title":"Sign up"}, status=429)
    if request.method == "POST" and form.is_valid():
        user=register_user(username=form.cleaned_data["username"],password=form.cleaned_data["password1"],display_name=form.cleaned_data["display_name"])
        login(request,user)
        return redirect("product_list")
    return render(request, "market/form.html", {"form":form, "title":"회원가입"})

class SafeLoginView(LoginView):
    template_name="market/form.html"

    def _error_response(self, status=200):
        form=self.get_form_class()(request=self.request)
        form.full_clean()
        form.cleaned_data={}
        form.add_error(None, RATE_LIMIT_ERROR)
        return self.render_to_response(self.get_context_data(form=form), status=status)

    def post(self, request, *args, **kwargs):
        account_key, ip_key=_login_rate_keys(request)
        if _counter_limited(account_key, settings.LOGIN_FAILURE_RATE_LIMIT) or _counter_limited(ip_key, settings.LOGIN_FAILURE_IP_RATE_LIMIT):
            return self._error_response(status=429)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        account_key, ip_key=_login_rate_keys(self.request)
        blocked=_increment_counter(account_key, settings.LOGIN_FAILURE_RATE_LIMIT, settings.LOGIN_FAILURE_RATE_LIMIT_WINDOW_SECONDS, "LOGIN_RATE_LIMIT_BACKEND_ERROR")
        blocked=_increment_counter(ip_key, settings.LOGIN_FAILURE_IP_RATE_LIMIT, settings.LOGIN_FAILURE_RATE_LIMIT_WINDOW_SECONDS, "LOGIN_RATE_LIMIT_BACKEND_ERROR") or blocked
        return self._error_response(status=429 if blocked else 200)

    def form_valid(self, form):
        account_key, ip_key=_login_rate_keys(self.request)
        try: cache.delete_many([account_key, ip_key])
        except (RedisError, ConnectionError, OSError):
            _rate_backend_event("LOGIN_RATE_LIMIT_BACKEND_ERROR", account_key)
            return self._error_response(status=429)
        return super().form_valid(form)
    extra_context={"title":"로그인"}

@login_required
def product_create(request):
    if not request.user.can_transfer(): return HttpResponseForbidden("제한된 계정입니다.")
    form=ProductForm(request.POST or None); image_form=ProductImageForm(request.POST or None, request.FILES or None)
    category_available = Category.objects.filter(is_active=True).exists()
    if request.method == "POST" and form.is_valid() and image_form.is_valid():
        product=form.save(commit=False); product.seller=request.user
        product.status=Product.Status.ACTIVE if form.cleaned_data["start_selling"] else Product.Status.DRAFT
        product.save()
        for index, image in enumerate(image_form.cleaned_data["images"]): ProductImage.objects.create(product=product, image=image, original_name=image.name[:255], mime_type=image.content_type, size=image.size, display_order=index)
        return redirect("product_detail", public_id=product.public_id)
    return render(request, "market/form.html", {"form":form, "image_form":image_form, "title":"상품 등록", "multipart":True, "category_available":category_available})

def product_detail(request, public_id):
    product=get_object_or_404(Product.objects.select_related("seller", "category").prefetch_related("images"), public_id=public_id)
    if product.status in {Product.Status.HIDDEN, Product.Status.DELETED, Product.Status.DRAFT} and product.seller_id != getattr(request.user, "id", None): raise Http404
    return render(request, "market/product_detail.html", {"product":product})

@login_required
def product_purchase(request, public_id):
    if request.method != "POST": return HttpResponseForbidden("Invalid request")
    if not request.user.can_transfer(): return HttpResponseForbidden("제한된 계정입니다.")
    product=get_object_or_404(Product,public_id=public_id)
    try: purchase_product(buyer=request.user,product_id=product.pk); messages.success(request,"Purchase completed.")
    except ValidationError as exc: messages.error(request,exc.message)
    return redirect("product_detail",public_id=product.public_id)

@login_required
def product_edit(request, public_id):
    product=get_object_or_404(Product, public_id=public_id, seller=request.user)
    if not request.user.can_transfer(): return HttpResponseForbidden("제한된 계정입니다.")
    if product.status == Product.Status.SOLD: return HttpResponseForbidden("판매 완료 상품은 수정할 수 없습니다.")
    form=ProductForm(request.POST or None, instance=product)
    if request.method == "POST" and form.is_valid(): form.save(); messages.success(request, "상품을 수정했습니다."); return redirect("product_detail", public_id=product.public_id)
    return render(request, "market/form.html", {"form":form, "title":"상품 수정"})

@login_required
def product_delete(request, public_id):
    product=get_object_or_404(Product, public_id=public_id, seller=request.user)
    if request.method == "POST": product.status=Product.Status.DELETED; product.save(update_fields=["status", "updated_at"]); return redirect("product_list")
    return render(request, "market/confirm.html", {"title":"상품 삭제", "object":product})

@login_required
def product_status(request, public_id):
    product=get_object_or_404(Product,public_id=public_id,seller=request.user)
    if request.method != "POST": return HttpResponseForbidden("Invalid request")
    try: change_product_status(seller=request.user,product=product,status=request.POST.get("status"))
    except ValidationError as exc: return HttpResponseForbidden(exc.message)
    return redirect("product_detail",public_id=product.public_id)

@login_required
def profile_view(request):
    form=ProfileForm(request.POST or None, initial={"display_name":request.user.display_name,"bio":request.user.profile.bio})
    if request.method == "POST" and form.is_valid():
        request.user.display_name=form.cleaned_data["display_name"].strip(); request.user.save(update_fields=["display_name"])
        request.user.profile.bio=form.cleaned_data["bio"].strip(); request.user.profile.save(update_fields=["bio"])
        messages.success(request, "프로필이 저장되었습니다.")
        return redirect("my_page")
    return render(request, "market/form.html", {"form":form,"title":"프로필"})

@login_required
def my_page(request):
    products = request.user.products.exclude(status=Product.Status.DELETED)
    return render(request, "market/my_page.html", {
        "product_count": products.count(),
        "sold_count": products.filter(status=Product.Status.SOLD).count(),
        "notification_count": Notification.objects.filter(user=request.user, is_read=False).count(),
        "recent_notifications": Notification.objects.filter(user=request.user).order_by("-created_at")[:10],
        "recent_reports": Report.objects.filter(reporter=request.user).order_by("-created_at")[:10],
        "blocked_users": Block.objects.filter(blocker=request.user).select_related("blocked").order_by("blocked__display_name")[:20],
    })

@login_required
def my_store(request):
    products = request.user.products.select_related("category").prefetch_related("images").order_by("-created_at")
    page = Paginator(products, 20).get_page(request.GET.get("page"))
    return render(request, "market/my_store.html", {"products": page, "page_obj": page})

@login_required
def password_change(request):
    form=SafePasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid(): user=form.save(); update_session_auth_hash(request, user); return redirect("profile")
    return render(request, "market/form.html", {"form":form,"title":"비밀번호 변경"})

@login_required
def toggle_block(request, username):
    target=get_object_or_404(User, username=username)
    if request.method != "POST" or target == request.user: return HttpResponseForbidden("잘못된 요청입니다.")
    block, created=Block.objects.get_or_create(blocker=request.user, blocked=target)
    if not created: block.delete()
    return redirect("product_list")

@login_required
def start_product_chat(request, product_id):
    if request.method != "POST":
        return HttpResponseForbidden("채팅 시작은 POST 요청으로만 가능합니다.")
    product=get_object_or_404(Product.objects.select_related("seller"), public_id=product_id)
    recipient=product.seller
    try: room=direct_room(sender=request.user, recipient=recipient, product=product)
    except ValidationError as exc:
        messages.error(request, exc.message)
        return redirect("product_detail", public_id=product.public_id) if product.status == Product.Status.ACTIVE else redirect("product_list")
    return redirect("chat_room", public_id=room.public_id)

@login_required
def chat_list(request):
    last_messages = ChatMessage.objects.filter(room=OuterRef("pk"), status=ChatMessage.Status.VISIBLE).order_by("-created_at", "-id")
    rooms = (
        ChatRoom.objects.filter(room_type=ChatRoom.Type.DIRECT, participants__user=request.user)
        .select_related("related_product", "related_product__seller")
        .prefetch_related("related_product__images", "participants__user")
        .annotate(last_message_at=Subquery(last_messages.values("created_at")[:1]), last_message_text=Subquery(last_messages.values("content")[:1]))
        .order_by("-last_message_at", "-created_at")
        .distinct()
    )
    _total_unread, unread_rooms=unread_chat_summary(request.user)
    for room in rooms:
        room.counterparty = next((participant.user for participant in room.participants.all() if participant.user_id != request.user.pk), None)
        room.viewer_role = "판매자" if room.related_product and room.related_product.seller_id == request.user.pk else "구매자"
        room.unread_count = unread_rooms.get(str(room.public_id), 0)
    return render(request, "market/chat_list.html", {"rooms": rooms})

@login_required
def community(request):
    if request.user.status == User.Status.SUSPENDED or not request.user.is_active: raise Http404
    room=community_room()
    page=Paginator(room.messages.filter(status=ChatMessage.Status.VISIBLE).select_related("sender").order_by("-created_at","-id"),50).get_page(request.GET.get("page"))
    return render(request,"market/community.html",{"room":room,"chat_messages":list(reversed(page.object_list)),"page_obj":page,"can_post":request.user.status == User.Status.ACTIVE})

@login_required
def chat_room(request, public_id):
    room=get_object_or_404(ChatRoom.objects.prefetch_related("participants", "messages__sender"), public_id=public_id)
    if not room.participants.filter(user=request.user).exists(): raise Http404
    mark_room_read(room=room,user=request.user)
    form=ChatMessageForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try: send_message(sender=request.user, room=room, content=form.cleaned_data["content"]); return redirect("chat_room", public_id=room.public_id)
        except ValidationError as exc: form.add_error(None, exc.message)
    messages_qs=room.messages.filter(status="VISIBLE").select_related("sender").order_by("-created_at","-id")
    page=Paginator(messages_qs,50).get_page(request.GET.get("page"))
    return render(request, "market/chat_room.html", {"room":room,"form":form,"chat_messages":list(reversed(page.object_list)),"page_obj":page})

@login_required
def submit_report(request, target_type, target_id):
    # UI links are hidden for restricted accounts, but this protects direct URLs too.
    if request.user.status != User.Status.ACTIVE or not request.user.is_active:
        return HttpResponseForbidden("New report submission is unavailable for this account.")
    form=ReportForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try: create_report(reporter=request.user,target_type=target_type,target_id=target_id,reason=form.cleaned_data["reason"],description=form.cleaned_data["description"]); messages.success(request,"신고가 접수되었습니다."); return redirect("product_list")
        except ValidationError as exc: form.add_error(None, exc.message)
    return render(request,"market/form.html",{"form":form,"title":"신고"})

@login_required
def wallet_view(request):
    transactions=WalletTransaction.objects.filter(Q(source=request.user.wallet)|Q(destination=request.user.wallet)).select_related("source__user","destination__user","created_by").order_by("-created_at")
    return render(request, "market/wallet.html", {"wallet":request.user.wallet, "transactions":transactions[:100]})

def _error_page(request, status):
    return render(request, f"{status}.html", status=status)

def error_400(request, exception=None): return _error_page(request, 400)
def error_403(request, exception=None): return _error_page(request, 403)
def error_404(request, exception=None): return _error_page(request, 404)
def error_500(request): return _error_page(request, 500)
