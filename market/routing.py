from django.urls import path
from .consumers import ChatConsumer, CommunityConsumer, UnreadConsumer
websocket_urlpatterns=[path("ws/chat/<uuid:public_id>/",ChatConsumer.as_asgi()),path("ws/unread/",UnreadConsumer.as_asgi()),path("ws/community/",CommunityConsumer.as_asgi())]
