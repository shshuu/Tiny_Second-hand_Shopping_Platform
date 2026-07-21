import json
import asyncio
from asgiref.sync import async_to_sync
from channels.testing import WebsocketCommunicator
from django.conf import settings
from django.test import Client
from django.test import TransactionTestCase
from django.test import override_settings
from config.asgi import application
from market.consumers import ChatConsumer
from market.models import Block, Category, ChatMessage, Product, User
from market.services import direct_room, register_user

class WebSocketChatTests(TransactionTestCase):
    def setUp(self):
        self.a=register_user(username="wsa",password="very-secure-password",display_name="A")
        self.b=register_user(username="wsb",password="very-secure-password",display_name="B")
        self.c=register_user(username="wsc",password="very-secure-password",display_name="C")
        self.category=Category.objects.create(name="Websocket",slug="websocket")
        self.product=Product.objects.create(seller=self.b,category=self.category,title="Websocket product",description="x",price=10,condition="USED",status=Product.Status.ACTIVE)
        self.room=direct_room(sender=self.a,recipient=self.b,product=self.product)
    def _communicator(self,user, room=None):
        """Exercise ProtocolTypeRouter + AuthMiddlewareStack, not a mocked user."""
        client=Client(); client.force_login(user)
        cookie=client.cookies[settings.SESSION_COOKIE_NAME].value
        return WebsocketCommunicator(application, f"/ws/chat/{(room or self.room).public_id}/", headers=[(b"cookie", f"{settings.SESSION_COOKIE_NAME}={cookie}".encode())])
    def test_direct_room_participants_exchange_persisted_message(self):
        first=self._communicator(self.a); second=self._communicator(self.b)
        async def run():
            self.assertTrue((await first.connect())[0]); self.assertTrue((await second.connect())[0])
            await first.send_to(text_data=json.dumps({"content":"hello"}))
            self.assertEqual((await first.receive_json_from())["content"],"hello")
            self.assertEqual((await second.receive_json_from())["content"],"hello")
            await first.disconnect(); await second.disconnect()
        async_to_sync(run)()
    def test_anonymous_and_non_participant_are_rejected(self):
        anonymous=WebsocketCommunicator(application,f"/ws/chat/{self.room.public_id}/")
        other=self._communicator(self.c)
        async def run():
            self.assertFalse((await anonymous.connect())[0])
            self.assertFalse((await other.connect())[0])
        async_to_sync(run)()
    def test_direct_block_and_restricted_messages_are_rejected_without_persisting(self):
        first=self._communicator(self.a); second=self._communicator(self.b)
        Block.objects.create(blocker=self.b, blocked=self.a)
        async def run():
            self.assertTrue((await first.connect())[0]); self.assertTrue((await second.connect())[0])
            await first.send_to(text_data=json.dumps({"content":"blocked"}))
            self.assertEqual((await first.receive_json_from())["error"], "message_rejected")
            await first.disconnect(); await second.disconnect()
        async_to_sync(run)()
        self.assertFalse(ChatMessage.objects.filter(content="blocked").exists())
        Block.objects.all().delete()
        for status in (User.Status.RESTRICTED, User.Status.SUSPENDED):
            self.a.status=status; self.a.save(update_fields=["status"])
            first=self._communicator(self.a)
            async def rejected(): self.assertFalse((await first.connect())[0])
            async_to_sync(rejected)()

    @override_settings(CHAT_RATE_LIMIT_PER_MINUTE=1, RATE_LIMIT_TTL_SECONDS=1)
    def test_redis_rate_limit_is_per_user_and_allows_after_ttl(self):
        room=self.room; first=self._communicator(self.a, room); second=self._communicator(self.b, room)
        async def run():
            self.assertTrue((await first.connect())[0]); self.assertTrue((await second.connect())[0])
            await first.send_to(text_data=json.dumps({"content":"one"})); await first.receive_json_from(); await second.receive_json_from()
            await first.send_to(text_data=json.dumps({"content":"two"})); self.assertEqual((await first.receive_json_from())["error"], "message_rejected")
            await second.send_to(text_data=json.dumps({"content":"other"})); self.assertEqual((await second.receive_json_from())["content"], "other"); await first.receive_json_from()
            await asyncio.sleep(1.2)
            await first.send_to(text_data=json.dumps({"content":"after-ttl"})); self.assertEqual((await first.receive_json_from())["content"], "after-ttl")
            await first.disconnect(); await second.disconnect()
        async_to_sync(run)()
        self.assertFalse(ChatMessage.objects.filter(content="two").exists())
