from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("market", "0008_automoderationcase_assignment")]

    operations = [
        migrations.AlterField(
            model_name="automoderationcase",
            name="review_status",
            field=models.CharField(choices=[("PENDING", "Pending"), ("REVIEWING", "Reviewing"), ("ACCEPTED", "Accepted"), ("REJECTED", "Rejected")], default="PENDING", max_length=12),
        ),
    ]
