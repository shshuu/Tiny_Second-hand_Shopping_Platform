from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.exceptions import ValidationError
from django.db import OperationalError
from django.db.models import Q
from django.core.paginator import Paginator
import logging
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from .forms import ChatMessageForm, ProductForm, ProductImageForm, ProfileForm, ReportForm, SafePasswordChangeForm, SignUpForm, TransferForm
from .models import Block, ChatRoom, Product, ProductImage, Report, User, WalletTransaction
from .services import change_product_status, create_report, direct_room, register_user, send_message, transfer

logger = logging.getLogger(__name__)

def product_list(request):
    q=request.GET.get("q", "").strip()[:100]
    # Drafts are private to their seller; hidden/deleted listings are never public.
    products=Product.objects.filter(status__in=[Product.Status.ACTIVE, Product.Status.RESERVED, Product.Status.SOLD]).select_related("seller", "category")
    if q: products=products.filter(Q(title__icontains=q)|Q(description__icontains=q)|Q(seller__display_name__icontains=q))
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
    if request.method == "POST" and form.is_valid():
        user=register_user(username=form.cleaned_data["username"],password=form.cleaned_data["password1"],display_name=form.cleaned_data["display_name"])
        login(request,user)
        return redirect("product_list")
    return render(request, "market/form.html", {"form":form, "title":"회원가입"})

class SafeLoginView(LoginView):
    template_name="market/form.html"
    extra_context={"title":"로그인"}

@login_required
def product_create(request):
    if not request.user.can_transfer(): return HttpResponseForbidden("제한된 계정입니다.")
    form=ProductForm(request.POST or None); image_form=ProductImageForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid() and image_form.is_valid():
        product=form.save(commit=False); product.seller=request.user; product.save()
        for index, image in enumerate(image_form.cleaned_data["images"]): ProductImage.objects.create(product=product, image=image, original_name=image.name[:255], mime_type=image.content_type, size=image.size, display_order=index)
        return redirect("product_detail", public_id=product.public_id)
    return render(request, "market/form.html", {"form":form, "image_form":image_form, "title":"상품 등록", "multipart":True})

def product_detail(request, public_id):
    product=get_object_or_404(Product.objects.select_related("seller", "category").prefetch_related("images"), public_id=public_id)
    if product.status != Product.Status.ACTIVE and product.seller_id != getattr(request.user, "id", None): raise Http404
    return render(request, "market/product_detail.html", {"product":product})

@login_required
def product_edit(request, public_id):
    product=get_object_or_404(Product, public_id=public_id, seller=request.user)
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
        return redirect("profile")
    return render(request, "market/form.html", {"form":form,"title":"프로필"})

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
def start_direct_chat(request, username, product_id=None):
    recipient=get_object_or_404(User, username=username)
    product=get_object_or_404(Product, public_id=product_id) if product_id else None
    try: room=direct_room(sender=request.user, recipient=recipient, product=product)
    except ValidationError as exc: return HttpResponseForbidden(exc.message)
    return redirect("chat_room", public_id=room.public_id)

@login_required
def chat_room(request, public_id):
    room=get_object_or_404(ChatRoom.objects.prefetch_related("participants", "messages__sender"), public_id=public_id)
    if not room.participants.filter(user=request.user).exists(): raise Http404
    form=ChatMessageForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try: send_message(sender=request.user, room=room, content=form.cleaned_data["content"]); return redirect("chat_room", public_id=room.public_id)
        except ValidationError as exc: form.add_error(None, exc.message)
    messages_qs=room.messages.filter(status="VISIBLE").select_related("sender").order_by("-created_at","-id")
    page=Paginator(messages_qs,50).get_page(request.GET.get("page"))
    return render(request, "market/chat_room.html", {"room":room,"form":form,"messages":list(reversed(page.object_list)),"page_obj":page})

@login_required
def submit_report(request, target_type, target_id):
    form=ReportForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try: create_report(reporter=request.user,target_type=target_type,target_id=target_id,reason=form.cleaned_data["reason"],description=form.cleaned_data["description"]); messages.success(request,"신고가 접수되었습니다."); return redirect("product_list")
        except ValidationError as exc: form.add_error(None, exc.message)
    return render(request,"market/form.html",{"form":form,"title":"신고"})

@login_required
def wallet_view(request):
    form=TransferForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        recipient=get_object_or_404(User, username=form.cleaned_data["recipient"])
        try: transfer(sender=request.user, recipient=recipient, amount=form.cleaned_data["amount"], idempotency_key=form.cleaned_data["idempotency_key"], memo=form.cleaned_data["memo"]); messages.success(request, "송금이 완료되었습니다."); return redirect("wallet")
        except ValidationError as exc: form.add_error(None, exc.message)
        except OperationalError:
            logger.exception("Transfer transaction conflict")
            form.add_error(None, "거래 처리 중 충돌이 발생했습니다. 동일한 요청 키로 다시 시도해 주세요.")
    transactions=WalletTransaction.objects.filter(Q(source=request.user.wallet)|Q(destination=request.user.wallet)).select_related("source__user","destination__user","created_by").order_by("-created_at")
    return render(request, "market/wallet.html", {"form":form, "wallet":request.user.wallet, "transactions":transactions[:100]})
