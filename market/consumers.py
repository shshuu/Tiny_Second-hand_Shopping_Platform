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
        try:
            payload=json.loads(text_data)
            if payload.get("action") == "mark_read":
                await self.mark_read()
                await self.channel_layer.group_send(f"user.unread.{self.scope['user'].pk}", {"type":"unread.update", "room_id":self.room_id})
                return
            content=payload.get("content",""); message, recipient_id=await self.persist(content)
        except Exception: await self.send_json({"error":"message_rejected"}); return
        await self.channel_layer.group_send(self.group,{"type":"chat.message","id":str(message.public_id),"content":message.content,"sender":message.sender.display_name})
        await self.channel_layer.group_send(f"user.unread.{recipient_id}", {"type":"unread.update", "room_id":self.room_id})
    async def chat_message(self,event): await self.send_json({"id":event["id"],"content":event["content"],"sender":event["sender"]})
    async def send_json(self,data): await self.send(text_data=json.dumps(data))
    @database_sync_to_async
    def allowed(self):
        room=ChatRoom.objects.filter(public_id=self.room_id).first()
        return bool(room and room.room_type == ChatRoom.Type.DIRECT and self.scope["user"].can_transfer() and room.participants.filter(user=self.scope["user"]).exists())
    @database_sync_to_async
    def persist(self,content):
        room=ChatRoom.objects.get(public_id=self.room_id)
        message=send_message(sender=self.scope["user"],room=room,content=content)
        recipient=room.participants.exclude(user=self.scope["user"]).values_list("user_id",flat=True).first()
        return message, recipient
    @database_sync_to_async
    def mark_read(self):
        from .services import mark_room_read
        room=ChatRoom.objects.get(public_id=self.room_id)
        mark_room_read(room=room,user=self.scope["user"])

class UnreadConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        user=self.scope.get("user",AnonymousUser())
        if not user.is_authenticated: await self.close(code=4401); return
        self.group=f"user.unread.{user.pk}"; await self.channel_layer.group_add(self.group,self.channel_name); await self.accept()
        # A reconnect gets its authoritative count from persistent read state,
        # not from events that may have been missed while disconnected.
        await self.send_json(await self.summary())
    async def disconnect(self, code):
        if hasattr(self,"group"): await self.channel_layer.group_discard(self.group,self.channel_name)
    async def unread_update(self,event):
        payload=await self.summary()
        payload["room_id"]=event.get("room_id")
        await self.send_json(payload)
    async def send_json(self,data): await self.send(text_data=json.dumps(data))
    @database_sync_to_async
    def count_unread(self):
        from .services import unread_chat_count
        return unread_chat_count(self.scope["user"])
    @database_sync_to_async
    def summary(self):
        from .services import unread_chat_summary
        total, rooms=unread_chat_summary(self.scope["user"])
        return {"type":"unread_update", "unread_count":total, "total_unread":total, "unread_rooms":rooms}

class CommunityConsumer(AsyncWebsocketConsumer):
    group="community.global"
    async def connect(self):
        if not self.scope.get("user",AnonymousUser()).is_authenticated or not await self.allowed(): await self.close(code=4403); return
        await self.channel_layer.group_add(self.group,self.channel_name); await self.accept()
    async def disconnect(self,code): await self.channel_layer.group_discard(self.group,self.channel_name)
    async def receive(self,text_data=None,bytes_data=None):
        if bytes_data or not text_data or len(text_data)>4096: await self.close(code=4400); return
        try:
            message=await self.persist(json.loads(text_data).get("content",""))
        except Exception:
            await self.send(text_data=json.dumps({"error":"message_rejected"})); return
        await self.channel_layer.group_send(self.group,{"type":"community.message","id":str(message.public_id),"content":message.content,"sender":message.sender.display_name,"created_at":message.created_at.isoformat()})
    async def community_message(self,event): await self.send(text_data=json.dumps(event))
    @database_sync_to_async
    def allowed(self):
        from .models import User
        return self.scope["user"].status in {User.Status.ACTIVE,User.Status.RESTRICTED}
    @database_sync_to_async
    def persist(self,content):
        from .services import send_community_message
        return send_community_message(sender=self.scope["user"],content=content)
