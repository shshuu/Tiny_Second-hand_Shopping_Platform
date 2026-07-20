import os
from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
application=ProtocolTypeRouter({"http":get_asgi_application(),"websocket":AuthMiddlewareStack(URLRouter(__import__("market.routing",fromlist=["websocket_urlpatterns"]).websocket_urlpatterns))})
