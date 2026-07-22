import uuid
import warnings
from django import forms
from django.contrib.auth.forms import PasswordChangeForm, UserCreationForm
from django.core.exceptions import ValidationError
from io import BytesIO
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageOps
from .models import Category, Product, User

class SignUpForm(UserCreationForm):
    class Meta:
        model=User; fields=("username","display_name","password1","password2")
    def clean_username(self):
        value=self.cleaned_data["username"].strip()
        if not value.replace("_","").isalnum() or not 4 <= len(value) <= 30: raise forms.ValidationError("아이디는 4~30자의 영문, 숫자, 밑줄만 사용할 수 있습니다.")
        return value

class ProductForm(forms.ModelForm):
    start_selling=forms.BooleanField(required=False, initial=True, label="등록 즉시 판매 시작")
    class Meta: model=Product; fields=("category","title","description","price","condition")
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.filter(is_active=True).order_by("name")
        if self.instance and self.instance.pk:
            self.fields.pop("start_selling")

class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected=True

class MultipleFileField(forms.FileField):
    widget=MultipleFileInput
    def clean(self, data, initial=None):
        if not data: return []
        files=data if isinstance(data, (list, tuple)) else [data]
        return [super(MultipleFileField, self).clean(file, initial) for file in files]

class ProductImageForm(forms.Form):
    images=MultipleFileField(widget=MultipleFileInput(attrs={"multiple":True, "data-image-input":"true"}), required=False)
    def clean_images(self):
        files=self.files.getlist("images")
        if len(files) > 5: raise ValidationError("한 상품에는 최대 5장만 업로드할 수 있습니다.")
        allowed={"image/jpeg":"JPEG", "image/png":"PNG", "image/webp":"WEBP"}
        sanitized=[]
        for image in files:
            if image.size > 5 * 1024 * 1024 or image.content_type not in allowed: raise ValidationError("JPEG, PNG, WebP 형식의 5MB 이하 이미지만 허용됩니다.")
            try:
                # Pillow normally only warns on a decompression bomb. Treat that
                # warning as an upload failure before decoding can continue.
                with warnings.catch_warnings():
                    warnings.simplefilter("error", Image.DecompressionBombWarning)
                    verified=Image.open(image); verified.load()
                fmt=allowed[image.content_type]
                if verified.format != fmt or getattr(verified,"is_animated",False) or verified.width > 4096 or verified.height > 4096 or verified.width * verified.height > 12_000_000: raise ValidationError("Invalid image dimensions or format")
                clean=ImageOps.exif_transpose(verified)
                output=BytesIO()
                if fmt == "JPEG":
                    clean.convert("RGB").save(output,"JPEG",quality=88,optimize=True); name,mime="image.jpg","image/jpeg"
                elif fmt == "WEBP":
                    clean.save(output,"WEBP",quality=88,method=6); name,mime="image.webp","image/webp"
                else:
                    clean.save(output,"PNG",optimize=True); name,mime="image.png","image/png"
                sanitized.append(SimpleUploadedFile(name,output.getvalue(),content_type=mime))
            except Exception as exc: raise ValidationError("유효한 이미지 파일이 아닙니다.") from exc
        return sanitized

class ProfileForm(forms.Form):
    display_name=forms.CharField(min_length=2, max_length=30)
    bio=forms.CharField(required=False, max_length=500, widget=forms.Textarea)

class SafePasswordChangeForm(PasswordChangeForm):
    pass

class ChatMessageForm(forms.Form):
    content=forms.CharField(max_length=1000, widget=forms.Textarea)

class ReportForm(forms.Form):
    reason=forms.ChoiceField(choices=[("FRAUD","사기 의심"),("ILLEGAL","불법 상품"),("SPAM","스팸"),("ABUSE","부적절한 콘텐츠"),("OTHER","기타")])
    description=forms.CharField(max_length=1000, required=False, widget=forms.Textarea)

class TransferForm(forms.Form):
    recipient=forms.CharField(max_length=30); amount=forms.IntegerField(min_value=1); memo=forms.CharField(max_length=200,required=False)
    idempotency_key=forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)
