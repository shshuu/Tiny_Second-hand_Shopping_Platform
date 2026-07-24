import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("market", "0005_report_assignment")]
    operations = [
        migrations.AddField(model_name="wallettransaction", name="product", field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="wallet_transactions", to="market.product")),
        migrations.CreateModel(name="ChatReadState", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("last_read_at", models.DateTimeField(blank=True, null=True)),
            ("room", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="read_states", to="market.chatroom")),
            ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="chat_read_states", to=settings.AUTH_USER_MODEL)),
        ], options={"constraints": [models.UniqueConstraint(fields=("room", "user"), name="unique_chat_read_state")]}),
        migrations.CreateModel(name="Purchase", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("public_id", models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
            ("amount", models.PositiveBigIntegerField()),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("completed_at", models.DateTimeField(auto_now_add=True)),
            ("buyer", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="purchases", to=settings.AUTH_USER_MODEL)),
            ("product", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="purchase", to="market.product")),
            ("seller", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="sales", to=settings.AUTH_USER_MODEL)),
            ("transaction", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="purchase", to="market.wallettransaction")),
        ]),
    ]
