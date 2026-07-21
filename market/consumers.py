import json
from django.contrib.auth.models import AnonymousUser
from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from .models import ChatRoom
from .services import send_message

class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        if not self.scope.get("user",AnonymousUser()).is_authenticated: await self.close(code=4401); return
        self.room_id=str(self.scope.get("url_route",{}).get("kwargs",{}).get("public_id") or self.scope["path"].rstrip("/").split("/")[-1])
        if not await self.allowed(): await self.close(code=4403); return
        self.group=f"chat.{self.room_id}"; await self.channel_layer.group_add(self.group,self.channel_name); await self.accept()
    async def disconnect(self, code):
        if hasattr(self,"group"): await self.channel_layer.group_discard(self.group,self.channel_name)
    async def receive(self, text_data=None, bytes_data=None):
        if bytes_data or not text_data or len(text_data)>4096: await self.close(code=4400); return
        try: content=json.loads(text_data).get("content",""); message=await self.persist(content)
        except Exception: await self.send_json({"error":"message_rejected"}); return
        await self.channel_layer.group_send(self.group,{"type":"chat.message","id":str(message.public_id),"content":message.content,"sender":message.sender.display_name})
    async def chat_message(self,event): await self.send_json({"id":event["id"],"content":event["content"],"sender":event["sender"]})
    async def send_json(self,data): await self.send(text_data=json.dumps(data))
    @database_sync_to_async
    def allowed(self):
        room=ChatRoom.objects.filter(public_id=self.room_id).first()
        return bool(room and room.room_type == ChatRoom.Type.DIRECT and self.scope["user"].can_transfer() and room.participants.filter(user=self.scope["user"]).exists())
    @database_sync_to_async
    def persist(self,content):
        room=ChatRoom.objects.get(public_id=self.room_id)
        return send_message(sender=self.scope["user"],room=room,content=content)
