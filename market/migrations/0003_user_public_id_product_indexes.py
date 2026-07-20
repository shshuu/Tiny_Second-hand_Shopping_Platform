import uuid
from django.db import migrations, models

def populate_public_ids(apps, schema_editor):
    User=apps.get_model("market","User")
    for user in User.objects.filter(public_id__isnull=True).iterator():
        user.public_id=uuid.uuid4(); user.save(update_fields=["public_id"])

class Migration(migrations.Migration):
    dependencies=[("market","0002_wallet_immutability_triggers")]
    operations=[
        migrations.AddField(model_name="user",name="public_id",field=models.UUIDField(null=True,editable=False)),
        migrations.RunPython(populate_public_ids,migrations.RunPython.noop),
        migrations.AlterField(model_name="user",name="public_id",field=models.UUIDField(default=uuid.uuid4,unique=True,editable=False)),
        migrations.AddIndex(model_name="product",index=models.Index(fields=["status","created_at"],name="market_prod_status_created_idx")),
        migrations.AddIndex(model_name="product",index=models.Index(fields=["category","price"],name="market_prod_category_price_idx")),
        migrations.AddIndex(model_name="product",index=models.Index(fields=["seller","status"],name="market_prod_seller_status_idx")),
    ]
