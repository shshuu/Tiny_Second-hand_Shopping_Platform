class SecurityHeadersMiddleware:
    def __init__(self, get_response): self.get_response=get_response
    def __call__(self, request):
        response=self.get_response(request)
        response["Content-Security-Policy"]="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
        response["Permissions-Policy"]="camera=(), microphone=(), geolocation=()"
        return response
import time
from django.conf import settings
from django.contrib.auth import logout
from django.http import HttpResponseForbidden
from .models import SecurityEvent, User


class AdminSessionMiddleware:
    def __init__(self, get_response): self.get_response=get_response
    def __call__(self, request):
        user=getattr(request,"user",None)
        if request.path.startswith("/operations/") and user and user.is_authenticated and user.role in {User.Role.MODERATOR,User.Role.ADMIN,User.Role.SUPERADMIN}:
            now=int(time.time()); started=request.session.get("ops_started",now); last=request.session.get("ops_last",now)
            if now-started > settings.ADMIN_SESSION_ABSOLUTE_SECONDS or now-last > settings.ADMIN_SESSION_IDLE_SECONDS:
                SecurityEvent.objects.create(event_type="ADMIN_SESSION_EXPIRED",user=user,detail="administrator session expired")
                logout(request); return HttpResponseForbidden("Administrator session expired.")
            request.session["ops_last"]=now
        return self.get_response(request)
