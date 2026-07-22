from .models import User
from .services import unread_chat_count

def navigation_counts(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {"unread_chat_count": 0, "operations_navigation": False, "operations_can_view_transactions": False}
    roles = {User.Role.MODERATOR, User.Role.ADMIN, User.Role.SUPERADMIN}
    return {
        "unread_chat_count": unread_chat_count(request.user),
        "operations_navigation": request.user.status == User.Status.ACTIVE and request.user.role in roles,
        "operations_can_view_transactions": request.user.role in {User.Role.ADMIN, User.Role.SUPERADMIN},
    }
