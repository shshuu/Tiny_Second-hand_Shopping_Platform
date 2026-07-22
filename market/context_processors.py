from .services import unread_chat_count

def navigation_counts(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {"unread_chat_count": 0}
    return {"unread_chat_count": unread_chat_count(request.user)}
